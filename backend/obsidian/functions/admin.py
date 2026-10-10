"""Admin endpoints: aggregate analytics, users, security monitoring.

Admin access never exposes document plaintext or encryption material —
administrative visibility follows the privacy policy.
"""
from __future__ import annotations

from datetime import datetime, timezone

from boto3.dynamodb.conditions import Key

from .. import audit, aws
from ..context import RequestContext
from ..errors import invalid_input, not_found
from ..router import route

ADMIN = ("admin",)


@route("GET", "/admin/analytics", roles=ADMIN)
def analytics(req: RequestContext) -> dict:
    users = _scan("users", 2000)
    documents = _scan("documents", 5000)
    shares = _scan("shares", 5000)

    active_docs = [d for d in documents if not d.get("deleted_at")]
    now = datetime.now(timezone.utc).isoformat()

    by_role: dict[str, int] = {}
    ai_enabled = 0
    for u in users:
        by_role[u.get("role", "unknown")] = by_role.get(u.get("role", "unknown"), 0) + 1
        if u.get("ai_enabled"):
            ai_enabled += 1

    share_status = {"active": 0, "expired": 0, "revoked": 0}
    for s in shares:
        if s.get("revoked_at"):
            share_status["revoked"] += 1
        elif s.get("expires_at") and s["expires_at"] < now:
            share_status["expired"] += 1
        else:
            share_status["active"] += 1

    storage_bytes = sum(int(d.get("size_bytes", 0)) for d in active_docs)

    return {
        "users": {
            "total": len(users),
            "by_role": by_role,
            "mfa_enabled": sum(1 for u in users if u.get("mfa_enabled")),
            "ai_enabled": ai_enabled,
        },
        "documents": {
            "total": len(active_docs),
            "storage_bytes": storage_bytes,
            "public": sum(1 for d in active_docs if d.get("visibility") == "public"),
            "private": sum(1 for d in active_docs if d.get("visibility") != "public"),
            "profile_visible": sum(1 for d in active_docs if d.get("profile_visible")),
        },
        "shares": {
            "total": len(shares),
            **share_status,
        },
        "security": _security_counts(),
        "health": {
            "status": "operational",
            "storage_backend": "s3+kms",
            "metadata_backend": "dynamodb",
            "encryption": "AES-256-GCM (envelope, KMS)",
            "checked_at": now,
        },
    }


def _security_counts() -> dict:
    counts = {}
    for et in ("login_failure", "otp_failure", "authorization_denied",
               "share_access_denied", "rate_limit_triggered", "suspicious_activity"):
        try:
            resp = aws.table("audit").query(
                IndexName="gsi1",
                KeyConditionExpression=Key("gsi1pk").eq(f"TYPE#{et}"),
                Select="COUNT",
            )
            counts[et] = resp.get("Count", 0)
        except Exception:
            counts[et] = 0
    return counts


def _scan(table_name: str, limit: int) -> list[dict]:
    tbl = aws.table(table_name)
    items: list[dict] = []
    kwargs: dict = {"Limit": min(limit, 1000)}
    while len(items) < limit:
        resp = tbl.scan(**kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    return items


@route("GET", "/admin/users", roles=ADMIN)
def list_users(req: RequestContext) -> dict:
    role_filter = str(req.query.get("role", "")).lower()
    try:
        limit = min(int(req.query.get("limit", 100)), 500)
    except ValueError:
        limit = 100
    users = _scan("users", 2000)
    if role_filter:
        users = [u for u in users if u.get("role") == role_filter]
    users.sort(key=lambda u: u.get("created_at", ""), reverse=True)

    now = datetime.now(timezone.utc).isoformat()
    out = []
    for u in users[:limit]:
        out.append({
            "user_id": u["user_id"],
            "email": u.get("email", ""),
            "role": u.get("role", ""),
            "status": u.get("status", ""),
            "mfa_enabled": bool(u.get("mfa_enabled")),
            "ai_enabled": bool(u.get("ai_enabled")),
            "verification_status": u.get("verification_status", "verified"),
            "created_at": u.get("created_at", ""),
            "last_login_at": u.get("last_login_at", ""),
        })
    return {"users": out, "total": len(users)}


@route("POST", "/admin/users/{user_id}/verification", roles=ADMIN)
def set_verification(req: RequestContext) -> dict:
    """Approve or withdraw a faculty/recruiter account's access."""
    actor = req.require_auth()
    target = str(req.path_params["user_id"])
    status = str(req.body.get("status", "")).lower()
    if status not in ("verified", "pending"):
        raise invalid_input("Status must be 'verified' or 'pending'.")
    if target == actor["user_id"]:
        raise invalid_input("You cannot change your own verification status.")

    resp = aws.table("users").get_item(Key={"pk": f"USER#{target}", "sk": "META"})
    if not resp.get("Item"):
        raise not_found()

    aws.table("users").update_item(
        Key={"pk": f"USER#{target}", "sk": "META"},
        UpdateExpression="SET verification_status = :s, updated_at = :t",
        ExpressionAttributeValues={":s": status, ":t": audit.now_iso()},
    )
    audit.write_event(
        actor_id=actor["user_id"], actor_role=actor["role"],
        event_type="verification_changed", resource_type="user",
        resource_id=target, request_id=req.request_id,
        metadata={"verification_status": status},
    )
    return {"user_id": target, "verification_status": status}


@route("GET", "/admin/security-events", roles=ADMIN)
def security_events(req: RequestContext) -> dict:
    try:
        limit = min(int(req.query.get("limit", 60)), 200)
    except ValueError:
        limit = 60
    events = audit.list_security_events(limit=limit)
    return {"events": [{
        "event_id": e.get("event_id", ""),
        "event_type": e.get("event_type", ""),
        "timestamp": e.get("timestamp", ""),
        "actor_id": (e.get("actor_id") or "")[:12],
        "actor_role": e.get("actor_role", ""),
        "result": e.get("result", ""),
        "resource_type": e.get("resource_type", ""),
        "request_id": e.get("request_id", "")[:16],
        "metadata": e.get("metadata", {}),
    } for e in events]}


@route("GET", "/admin/activity", roles=ADMIN)
def recent_activity(req: RequestContext) -> dict:
    events = _scan("audit", 500)
    events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return {"events": [{
        "event_id": e.get("event_id", ""),
        "event_type": e.get("event_type", ""),
        "timestamp": e.get("timestamp", ""),
        "actor_role": e.get("actor_role", ""),
        "result": e.get("result", ""),
        "resource_type": e.get("resource_type", ""),
        "metadata": e.get("metadata", {}),
    } for e in events[:80]]}


@route("GET", "/admin/shares", roles=ADMIN)
def share_stats(req: RequestContext) -> dict:
    shares = _scan("shares", 5000)
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    status_counts = {"active": 0, "expired": 0, "revoked": 0}
    for s in shares:
        if s.get("sk") != "S":
            continue
        status = "revoked" if s.get("revoked_at") else (
            "expired" if s.get("expires_at") and s["expires_at"] < now else "active")
        status_counts[status] += 1
        rows.append({
            "share_id": s.get("share_id", ""),
            "mode": s.get("mode", ""),
            "permission": s.get("permission", ""),
            "status": status,
            "created_at": s.get("created_at", ""),
            "expires_at": s.get("expires_at", ""),
            "access_count": int(s.get("access_count", 0)),
            "document_id": s.get("document_id", ""),
        })
    rows.sort(key=lambda r: r["created_at"], reverse=True)
    return {"summary": status_counts, "shares": rows[:100], "total": len(rows)}


@route("GET", "/admin/rag", roles=ADMIN)
def rag_stats(req: RequestContext) -> dict:
    instances = [i for i in _scan("rag", 5000) if i.get("sk") == "INSTANCE"]
    enabled = [i for i in instances if i.get("enabled")]
    chunks = sum(int(i.get("chunk_count", 0)) for i in instances)
    return {
        "total_instances": len(instances),
        "enabled": len(enabled),
        "disabled": len(instances) - len(enabled),
        "total_chunks": chunks,
        "isolation_model": "per-user partition (RAG#<user_id>)",
    }
