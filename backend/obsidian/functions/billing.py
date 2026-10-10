"""Storage billing: quotas and Razorpay payments.

Business rule (students only):

    free account          ->  5 GB
    first upgrade         -> 15 GB   INR 3,999
    second upgrade        -> 25 GB   INR 6,999
    every later upgrade   -> +10 GB  INR 6,999

Uploads are refused with HTTP 402 ``STORAGE_QUOTA_EXCEEDED`` once the account's
entitlement is full. A completed payment *adds* 10 GB to the entitlement
permanently — Razorpay is the source of truth for a successful charge:

    1. POST /billing/orders   -> server creates a Razorpay order (price is
                                 fixed server-side; the client cannot set it)
    2. Razorpay Checkout      -> returns payment_id + signature
    3. POST /billing/verify   -> server verifies HMAC(order_id|payment_id)
    4. POST /billing/webhook  -> optional, out-of-band confirmation

Only step 3/4 can credit storage, and only after a signature check passes.
The payment secret never leaves the backend.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone

from boto3.dynamodb.conditions import Key

from .. import audit, aws, plans
from ..config import settings
from ..context import RequestContext
from ..errors import ApiError, invalid_input
from ..ids import uuid_hex
from ..router import route

RAZORPAY_API = "https://api.razorpay.com/v1"


# ------------------------------------------------------------------ accounting

def entitlement_bytes(user: dict) -> int:
    """The account's storage ceiling in bytes (free tier when never upgraded)."""
    raw = user.get("storage_limit_bytes")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 0
    if value <= 0:
        return plans.free_bytes()
    return value


def used_bytes(user_id: str) -> int:
    """Authoritative storage usage: the sum of all live documents."""
    total = 0
    kwargs: dict = {
        "IndexName": "gsi1",
        "KeyConditionExpression": Key("gsi1pk").eq(f"OWNER#{user_id}"),
        "Limit": 500,
    }
    while True:
        resp = aws.table("documents").query(**kwargs)
        for d in resp.get("Items", []):
            if d.get("deleted_at"):
                continue
            total += int(d.get("size_bytes", 0))
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    return total


def storage_status(user: dict, used: int | None = None) -> dict:
    if used is None:
        used = used_bytes(user["user_id"])
    limit = entitlement_bytes(user)
    tier = plans.tier_from_entitlement_bytes(limit)
    percent = round(min(100.0, (used / limit) * 100), 2) if limit else 0.0
    return {
        "used_bytes": used,
        "limit_bytes": limit,
        "remaining_bytes": max(0, limit - used),
        "percent_used": percent,
        "tier": tier,
        "total_gb": plans.total_gb_for_tier(tier),
        "exceeded": used >= limit,
        "near_limit": used >= limit * 0.9,
        "next_plan": plans.next_plan(limit),
        "plans": plans.plan_catalog(),
    }


def check_quota(user: dict, incoming_bytes: int) -> None:
    """Raise 402 when a new document would push the account over its ceiling."""
    limit = entitlement_bytes(user)
    used = used_bytes(user["user_id"])
    if used + incoming_bytes > limit:
        nxt = plans.next_plan(limit)
        raise ApiError(
            "STORAGE_QUOTA_EXCEEDED",
            (
                f"Your {plans.total_gb_for_tier(plans.tier_from_entitlement_bytes(limit))} GB "
                f"of storage is full. Upgrade to {nxt['total_gb']} GB to keep uploading."
            ),
            402,
            details={
                "used_bytes": used,
                "limit_bytes": limit,
                "incoming_bytes": incoming_bytes,
                "next_plan": nxt,
            },
        )


def _set_entitlement(user_id: str, limit_bytes: int) -> None:
    aws.table("users").update_item(
        Key={"pk": f"USER#{user_id}", "sk": "META"},
        UpdateExpression="SET storage_limit_bytes = :l, storage_updated_at = :t",
        ExpressionAttributeValues={
            ":l": limit_bytes,
            ":t": datetime.now(timezone.utc).isoformat(),
        },
    )


# ---------------------------------------------------------------------- orders

def _order_key(order_id: str) -> dict:
    return {"pk": f"ORDER#{order_id}", "sk": "B"}


def _load_order(order_id: str) -> dict | None:
    if not order_id or len(order_id) > 128:
        return None
    resp = aws.table("billing").get_item(Key=_order_key(order_id))
    return resp.get("Item")


def _record_order(*, order_id: str, user: dict, plan: dict, provider: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    item = {
        "pk": f"ORDER#{order_id}", "sk": "B",
        "order_id": order_id,
        "user_id": user["user_id"],
        "email": user.get("email", ""),
        "tier": plan["tier"],
        "total_gb": plan["total_gb"],
        "added_bytes": plan["added_gb"] * plans.GB,
        "amount_paise": plan["price_paise"],
        "currency": "INR",
        "provider": provider,
        "status": "created",
        "created_at": now,
        "paid_at": "",
        "payment_id": "",
        # gsi1 lists a user's orders newest-first for the billing history view.
        "gsi1pk": f"USER#{user['user_id']}", "gsi1sk": f"{now}#{order_id}",
    }
    aws.table("billing").put_item(Item=item)
    return item


def _razorpay_post(path: str, payload: dict) -> dict:
    import httpx
    resp = httpx.post(
        f"{RAZORPAY_API}{path}",
        auth=(settings.razorpay_key_id, settings.razorpay_key_secret),
        json=payload,
        timeout=20.0,
    )
    if resp.status_code >= 300:
        raise ApiError("PAYMENT_PROVIDER_ERROR",
                       "The payment provider could not create this order. Please try again.", 502)
    return resp.json()


@route("GET", "/billing/plans", auth="public")
def list_plans(req: RequestContext) -> dict:
    return {
        "currency": "INR",
        "free_gb": plans.FREE_GB,
        "step_gb": plans.STEP_GB,
        "plans": plans.plan_catalog(),
        "payments_configured": bool(settings.razorpay_key_id and settings.razorpay_key_secret),
    }


@route("GET", "/billing/status", roles=("student",))
def billing_status(req: RequestContext) -> dict:
    user = req.require_auth()
    status = storage_status(user)
    status["payments"] = {
        "configured": bool(settings.razorpay_key_id and settings.razorpay_key_secret),
        "key_id": settings.razorpay_key_id,  # publishable id only
        "currency": "INR",
    }
    return status


@route("POST", "/billing/orders", roles=("student",), rate=("billing_order", 20, 300))
def create_order(req: RequestContext) -> dict:
    """Create an order for the account's next plan. Price is server-side only."""
    user = req.require_auth()
    limit = entitlement_bytes(user)
    plan = plans.next_plan(limit)

    requested_tier = req.body.get("tier")
    if requested_tier is not None:
        try:
            requested_tier = int(requested_tier)
        except (TypeError, ValueError):
            raise invalid_input("The requested plan is not valid.")
        # Only the next step may be bought: no skipping, no downgrades.
        if requested_tier != plan["tier"]:
            if requested_tier == plan["tier"] - 1:
                raise invalid_input("That plan is already active.")
            raise invalid_input("Please purchase the next plan in sequence.")

    configured = bool(settings.razorpay_key_id and settings.razorpay_key_secret)
    if configured:
        receipt = f"obs_{user['user_id'][:10]}_{uuid_hex()[:8]}"[:40]
        payload = {
            "amount": plan["price_paise"],
            "currency": "INR",
            "receipt": receipt,
            "notes": {
                "user_id": user["user_id"],
                "tier": str(plan["tier"]),
                "total_gb": str(plan["total_gb"]),
            },
        }
        data = _razorpay_post("/orders", payload)
        order_id = str(data.get("id", ""))
        item = _record_order(order_id=order_id, user=user, plan=plan, provider="razorpay")
        audit.write_event(
            actor_id=user["user_id"], actor_role=user["role"],
            event_type="storage_order_created", resource_type="billing",
            resource_id=order_id, request_id=req.request_id,
            metadata={"tier": plan["tier"], "amount_paise": plan["price_paise"]},
        )
        return 201, {
            "order_id": order_id,
            "amount": plan["price_paise"],
            "currency": "INR",
            "key_id": settings.razorpay_key_id,
            "plan": plan,
            "simulated": False,
            "order": {"id": item["order_id"], "status": item["status"]},
        }

    # No provider configured. Only ever reachable in explicit local dev mode —
    # production forces dev_mode off in Settings.__post_init__.
    if not settings.dev_mode:
        raise ApiError("PAYMENTS_NOT_CONFIGURED",
                       "Payments are not configured for this environment.", 501)
    order_id = f"dev_{uuid_hex()}"
    item = _record_order(order_id=order_id, user=user, plan=plan, provider="dev")
    return 201, {
        "order_id": order_id,
        "amount": plan["price_paise"],
        "currency": "INR",
        "key_id": "",
        "plan": plan,
        "simulated": True,
        "order": {"id": item["order_id"], "status": item["status"]},
    }


# ------------------------------------------------------------------ crediting

def _mark_paid(order: dict, payment_id: str, *, source: str, request_id: str | None) -> dict:
    """Idempotently credit the entitlement for a paid order."""
    if order.get("status") == "paid":
        user_resp = aws.table("users").get_item(
            Key={"pk": f"USER#{order['user_id']}", "sk": "META"})
        user = user_resp.get("Item") or {}
        return {"credited": False, "already_paid": True, "status": storage_status(user),
                "user_id": order["user_id"]}

    user_resp = aws.table("users").get_item(
        Key={"pk": f"USER#{order['user_id']}", "sk": "META"})
    user = user_resp.get("Item")
    if not user:
        raise ApiError("INVALID_INPUT", "This order could not be matched to an account.", 400)

    current = entitlement_bytes(user)
    target = max(current, plans.bytes_for_total_gb(order["total_gb"]))
    _set_entitlement(order["user_id"], target)

    now = datetime.now(timezone.utc).isoformat()
    aws.table("billing").update_item(
        Key=_order_key(order["order_id"]),
        UpdateExpression="SET #s = :s, paid_at = :p, payment_id = :pid, #src = :src",
        # `source` is a DynamoDB reserved word — alias it.
        ExpressionAttributeNames={"#s": "status", "#src": "source"},
        ExpressionAttributeValues={
            ":s": "paid", ":p": now, ":pid": payment_id, ":src": source,
        },
    )
    # A purchase also upgrades an expired/downgraded flag if any existed.
    audit.write_event(
        actor_id=order["user_id"], actor_role=user.get("role"),
        event_type="storage_purchased", resource_type="billing",
        resource_id=order["order_id"], request_id=request_id,
        metadata={
            "tier": order["tier"], "total_gb": order["total_gb"],
            "amount_paise": order["amount_paise"], "payment_id": payment_id,
            "source": source,
        },
    )
    refreshed = aws.table("users").get_item(
        Key={"pk": f"USER#{order['user_id']}", "sk": "META"}).get("Item") or user
    return {"credited": True, "already_paid": False, "status": storage_status(refreshed),
            "user_id": order["user_id"]}


def _verify_razorpay_signature(order_id: str, payment_id: str, signature: str) -> bool:
    if not settings.razorpay_key_secret:
        return False
    expected = hmac.new(
        settings.razorpay_key_secret.encode("utf-8"),
        f"{order_id}|{payment_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature or "")


@route("POST", "/billing/verify", roles=("student",), rate=("billing_verify", 30, 300))
def verify_payment(req: RequestContext) -> dict:
    """Client-side confirmation after Razorpay Checkout returns."""
    user = req.require_auth()
    order_id = str(req.body.get("razorpay_order_id", "")).strip()
    payment_id = str(req.body.get("razorpay_payment_id", "")).strip()
    signature = str(req.body.get("razorpay_signature", "")).strip()

    order = _load_order(order_id)
    if not order or order.get("user_id") != user["user_id"]:
        raise invalid_input("This payment could not be matched to your account.")
    if order.get("status") == "paid":
        return {"ok": True, "already_paid": True, "status": storage_status(user)}

    if order.get("provider") == "dev":
        if not settings.dev_mode:
            raise ApiError("PAYMENTS_NOT_CONFIGURED", "Payments are not configured.", 501)
        result = _mark_paid(order, f"devpay_{uuid_hex()[:12]}", source="dev",
                            request_id=req.request_id)
    else:
        if not _verify_razorpay_signature(order_id, payment_id, signature):
            audit.write_event(
                actor_id=user["user_id"], actor_role=user["role"],
                event_type="payment_verification_failed", resource_type="billing",
                resource_id=order_id, result="denied", request_id=req.request_id,
                metadata={"payment_id": payment_id[:64]},
            )
            raise ApiError("PAYMENT_VERIFICATION_FAILED",
                           "We could not verify this payment. You have not been charged twice.", 400)
        result = _mark_paid(order, payment_id, source="checkout",
                            request_id=req.request_id)

    return {
        "ok": True,
        "credited": result["credited"],
        "status": result["status"],
    }


@route("POST", "/billing/webhook", auth="public")
def razorpay_webhook(req: RequestContext) -> dict:
    """Out-of-band payment confirmation signed by Razorpay.

    Verifies ``X-Razorpay-Signature`` = HMAC-SHA256(raw body, webhook secret).
    """
    signature = str(req.headers.get("x-razorpay-signature", ""))
    if not settings.razorpay_webhook_secret:
        raise ApiError("PAYMENTS_NOT_CONFIGURED", "Payments are not configured.", 501)
    expected = hmac.new(
        settings.razorpay_webhook_secret.encode("utf-8"),
        req.raw_body or b"",
        hashlib.sha256,
    ).hexdigest()
    if not signature or not hmac.compare_digest(expected, signature):
        raise ApiError("ACCESS_DENIED", "Invalid webhook signature.", 403)

    try:
        payload = json.loads((req.raw_body or b"{}").decode("utf-8"))
    except Exception:
        raise invalid_input("The webhook payload is not valid JSON.")

    entity = (((payload.get("payload") or {}).get("payment") or {}).get("entity") or {})
    order_id = str(entity.get("order_id", ""))
    payment_id = str(entity.get("id", ""))
    event = str(payload.get("event", ""))

    if not order_id:
        return {"ok": True, "ignored": True}

    order = _load_order(order_id)
    if not order:
        return {"ok": True, "ignored": True}

    if event in ("payment.captured", "order.paid", "payment.authorized"):
        result = _mark_paid(order, payment_id, source="webhook", request_id=req.request_id)
        return {"ok": True, "credited": result["credited"]}
    if event in ("payment.failed",):
        aws.table("billing").update_item(
            Key=_order_key(order_id),
            UpdateExpression="SET #s = :s, failed_at = :t",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": "failed", ":t": datetime.now(timezone.utc).isoformat(),
            },
        )
    return {"ok": True, "ignored": True}


@route("GET", "/billing/history", roles=("student",))
def billing_history(req: RequestContext) -> dict:
    user = req.require_auth()
    resp = aws.table("billing").query(
        IndexName="gsi1",
        KeyConditionExpression=Key("gsi1pk").eq(f"USER#{user['user_id']}"),
        ScanIndexForward=False,
        Limit=50,
    )
    rows = []
    for it in resp.get("Items", []):
        rows.append({
            "order_id": it.get("order_id", ""),
            "plan": plans.label_for_tier(int(it.get("tier", 0))),
            "total_gb": int(it.get("total_gb", 0)),
            "amount_inr": int(it.get("amount_paise", 0)) // 100,
            "status": it.get("status", ""),
            "created_at": it.get("created_at", ""),
            "paid_at": it.get("paid_at", ""),
        })
    return {"orders": rows}
