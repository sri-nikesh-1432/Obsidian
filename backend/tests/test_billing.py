"""Storage plans, quotas and Razorpay billing tests."""
from __future__ import annotations

import base64

from conftest import Client, register

GB = 1024 * 1024 * 1024
TXT_BYTES = b"Internship certificate notes.\nCGPA: 8.9\n"


def _me(client: Client) -> dict:
    status, data = client.get("/api/v1/auth/me")
    assert status == 200
    return data


def _set_limit(user_id: str, limit_bytes: int) -> None:
    from obsidian import aws
    aws.table("users").update_item(
        Key={"pk": f"USER#{user_id}", "sk": "META"},
        UpdateExpression="SET storage_limit_bytes = :l",
        ExpressionAttributeValues={":l": limit_bytes},
    )


def _upload(client: Client, content: bytes, filename: str = "notes.txt"):
    return client.post("/api/v1/documents", {
        "filename": filename,
        "content_base64": base64.b64encode(content).decode(),
        "visibility": "private",
    })


# --------------------------------------------------------------------- plans

def test_plan_ladder_matches_the_pricing_rules():
    from obsidian import plans
    assert plans.free_bytes() == 5 * GB
    first = plans.next_plan(plans.free_bytes())
    assert first["tier"] == 1 and first["total_gb"] == 15
    assert first["price_inr"] == 3999 and first["price_paise"] == 399900
    second = plans.next_plan(15 * GB)
    assert second["tier"] == 2 and second["total_gb"] == 25
    assert second["price_inr"] == 6999 and second["price_paise"] == 699900
    third = plans.next_plan(25 * GB)
    assert third["tier"] == 3 and third["total_gb"] == 35
    # free -> 5, then +10 per tier
    assert plans.total_gb_for_tier(0) == 5
    assert plans.total_gb_for_tier(1) == 15
    assert plans.total_gb_for_tier(4) == 45


def test_plan_catalog_is_public(client: Client):
    status, data = client.get("/api/v1/billing/plans")
    assert status == 200, data
    tiers = {p["tier"]: p for p in data["plans"]}
    assert tiers[0]["total_gb"] == 5 and tiers[0]["price_inr"] == 0
    assert tiers[1]["total_gb"] == 15 and tiers[1]["price_inr"] == 3999
    assert tiers[2]["total_gb"] == 25 and tiers[2]["price_inr"] == 6999


def test_new_student_starts_on_five_gb(client: Client):
    register(client, "student")
    status, data = client.get("/api/v1/billing/status")
    assert status == 200, data
    assert data["limit_bytes"] == 5 * GB
    assert data["tier"] == 0 and data["total_gb"] == 5
    assert data["used_bytes"] == 0
    assert data["next_plan"]["total_gb"] == 15
    assert data["next_plan"]["price_inr"] == 3999


def test_storage_summary_is_in_auth_me(client: Client):
    register(client, "student")
    me = _me(client)
    assert me["storage"]["limit_bytes"] == 5 * GB
    assert me["storage"]["total_gb"] == 5


def test_non_students_cannot_read_billing_status(client: Client):
    register(client, "faculty")
    status, _ = client.get("/api/v1/billing/status")
    assert status == 403


# --------------------------------------------------------------------- quota

def test_upload_is_refused_when_entitlement_is_full(client: Client):
    register(client, "student")
    user_id = _me(client)["user_id"]
    _set_limit(user_id, 10)  # 10 bytes of space

    status, data = _upload(client, TXT_BYTES)
    assert status == 402, data
    assert data["error"]["code"] == "STORAGE_QUOTA_EXCEEDED"
    assert data["error"]["details"]["limit_bytes"] == 10
    assert data["error"]["details"]["next_plan"]["total_gb"] == 15

    # nothing was stored
    status, listed = client.get("/api/v1/documents")
    assert listed["total"] == 0


def test_upload_is_allowed_after_a_purchase(client: Client):
    register(client, "student")
    user_id = _me(client)["user_id"]
    _set_limit(user_id, 10)

    status, _ = _upload(client, TXT_BYTES)
    assert status == 402

    # buy the first plan (dev-mode simulated checkout)
    status, order = client.post("/api/v1/billing/orders", {})
    assert status == 201, order
    assert order["simulated"] is True
    assert order["amount"] == 399900

    status, verified = client.post("/api/v1/billing/verify", {
        "razorpay_order_id": order["order_id"],
        "razorpay_payment_id": "pay_test",
        "razorpay_signature": "dev",
    })
    assert status == 200, verified
    assert verified["credited"] is True
    assert verified["status"]["limit_bytes"] == 15 * GB

    # now the same upload succeeds
    status, data = _upload(client, TXT_BYTES)
    assert status == 201, data


# ------------------------------------------------------------------- payments

def test_orders_advance_the_ladder_and_are_sequential(client: Client):
    register(client, "student")

    status, first = client.post("/api/v1/billing/orders", {})
    assert status == 201 and first["plan"]["total_gb"] == 15
    client.post("/api/v1/billing/verify", {
        "razorpay_order_id": first["order_id"], "razorpay_payment_id": "p1", "razorpay_signature": "dev"})

    status, second = client.post("/api/v1/billing/orders", {})
    assert status == 201 and second["plan"]["total_gb"] == 25
    assert second["amount"] == 699900
    client.post("/api/v1/billing/verify", {
        "razorpay_order_id": second["order_id"], "razorpay_payment_id": "p2", "razorpay_signature": "dev"})

    status, third = client.post("/api/v1/billing/orders", {})
    assert status == 201 and third["plan"]["total_gb"] == 35
    assert third["amount"] == 699900

    status, info = client.get("/api/v1/billing/status")
    assert info["limit_bytes"] == 25 * GB and info["tier"] == 2


def test_verification_is_idempotent(client: Client):
    register(client, "student")
    _, order = client.post("/api/v1/billing/orders", {})
    body = {"razorpay_order_id": order["order_id"], "razorpay_payment_id": "p", "razorpay_signature": "dev"}
    status, first = client.post("/api/v1/billing/verify", body)
    assert status == 200 and first["credited"] is True
    status, second = client.post("/api/v1/billing/verify", body)
    assert status == 200 and second["already_paid"] is True
    status, info = client.get("/api/v1/billing/status")
    assert info["limit_bytes"] == 15 * GB  # credited exactly once


def test_cannot_pay_for_someone_elses_order(client: Client):
    register(client, "student")
    _, order = client.post("/api/v1/billing/orders", {})
    client.cookie = ""            # a second, unrelated student
    register(client, "student")
    status, data = client.post("/api/v1/billing/verify", {
        "razorpay_order_id": order["order_id"], "razorpay_payment_id": "x", "razorpay_signature": "dev"})
    assert status == 422, data


def test_cannot_skip_a_plan(client: Client):
    register(client, "student")
    status, data = client.post("/api/v1/billing/orders", {"tier": 3})
    assert status == 422, data


def test_real_signature_path_requires_a_configured_provider(client: Client):
    """Without a Razorpay key the server must not pretend a payment succeeded."""
    register(client, "student")
    from obsidian.config import settings
    # Simulate a real (non-dev) order that must be signature-verified.
    from obsidian import aws
    from obsidian.functions import billing
    user = _me(client)
    plan = billing.plans.next_plan(billing.entitlement_bytes({"storage_limit_bytes": 0}))
    billing._record_order(order_id="order_real_1", user=user, plan=plan, provider="razorpay")
    settings.razorpay_key_secret = "test_secret"
    try:
        status, data = client.post("/api/v1/billing/verify", {
            "razorpay_order_id": "order_real_1",
            "razorpay_payment_id": "pay_1",
            "razorpay_signature": "not-a-real-signature",
        })
        assert status == 400, data
        assert data["error"]["code"] == "PAYMENT_VERIFICATION_FAILED"
        # entitlement untouched
        status, info = client.get("/api/v1/billing/status")
        assert info["limit_bytes"] == 5 * GB

        # A correct signature from the same secret does credit.
        import hashlib
        import hmac
        sig = hmac.new(b"test_secret", b"order_real_1|pay_1", hashlib.sha256).hexdigest()
        status, ok = client.post("/api/v1/billing/verify", {
            "razorpay_order_id": "order_real_1", "razorpay_payment_id": "pay_1",
            "razorpay_signature": sig})
        assert status == 200 and ok["credited"] is True
        status, info = client.get("/api/v1/billing/status")
        assert info["limit_bytes"] == 15 * GB
    finally:
        settings.razorpay_key_secret = ""
        aws.table("billing").delete_item(Key={"pk": "ORDER#order_real_1", "sk": "B"})


def test_billing_history_lists_orders(client: Client):
    register(client, "student")
    _, order = client.post("/api/v1/billing/orders", {})
    client.post("/api/v1/billing/verify", {
        "razorpay_order_id": order["order_id"], "razorpay_payment_id": "p", "razorpay_signature": "dev"})
    status, data = client.get("/api/v1/billing/history")
    assert status == 200, data
    assert len(data["orders"]) == 1
    row = data["orders"][0]
    assert row["status"] == "paid" and row["total_gb"] == 15 and row["amount_inr"] == 3999


def test_webhook_requires_configuration(client: Client):
    status, data = client.post("/api/v1/billing/webhook", {"event": "payment.captured"})
    assert status == 501, data
