"""Audit / activity logging.

Every security-sensitive operation writes an event. Logs never contain
passwords, OTPs, encryption keys, raw share tokens, or document plaintext.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from . import aws

EVENT_TYPES = {
    # authentication
    "registration_requested", "registration_completed", "login_success", "login_failure",
    "logout", "otp_requested", "otp_success", "otp_failure", "password_reset",
    # documents
    "document_uploaded", "document_viewed", "document_downloaded", "document_renamed",
    "document_deleted", "document_updated",
    # sharing
    "share_created", "share_accessed", "share_access_denied", "share_revoked",
    # connections (student social graph)
    "connection_requested", "connection_accepted", "connection_declined",
    "connection_removed",
    # profile
    "profile_updated", "visibility_changed",
    # AI
    "ai_enabled", "ai_disabled", "ai_query", "rag_index_started", "rag_index_completed",
    "rag_index_failed",
    # security
    "authorization_denied", "suspicious_activity", "rate_limit_triggered",
    # faculty/recruiter lookups
    "student_lookup",
}

SECURITY_EVENTS = {
    "login_failure", "otp_failure", "authorization_denied", "suspicious_activity",
    "rate_limit_triggered", "share_access_denied", "registration_requested",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_event(
    *,
    actor_id: str | None,
    actor_role: str | None,
    event_type: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    result: str = "success",
    request_id: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """Persist an audit event (append-oriented)."""
    if event_type not in EVENT_TYPES:
        event_type = "suspicious_activity"
    ts = now_iso()
    event_id = uuid.uuid4().hex
    actor = actor_id or "anonymous"
    item = {
        "pk": f"ACTOR#{actor}",
        "sk": f"TS#{ts}#{event_id}",
        "event_id": event_id,
        "timestamp": ts,
        "actor_id": actor_id or "",
        "actor_role": actor_role or "",
        "event_type": event_type,
        "resource_type": resource_type or "",
        "resource_id": resource_id or "",
        "result": result,
        "request_id": request_id or "",
        "metadata": _safe_metadata(metadata or {}),
        "is_security": event_type in SECURITY_EVENTS,
        "gsi1pk": f"TYPE#{event_type}",
        "gsi1sk": ts,
    }
    try:
        aws.table("audit").put_item(Item=item)
    except Exception:
        # Audit failure must never break the user action, but it is logged
        # structurally for operators (no secrets involved).
        import sys
        print(f"[audit] failed to persist event type={event_type}", file=sys.stderr)
    return item


def _safe_metadata(metadata: dict) -> dict:
    """Strip anything that could become a secondary data leak."""
    banned = {"password", "otp", "code", "token", "secret", "key", "content", "plaintext"}
    safe: dict = {}
    for k, v in metadata.items():
        if any(b in k.lower() for b in banned):
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            safe[k] = v
        elif isinstance(v, (list, tuple)):
            safe[k] = [x for x in v if isinstance(x, (str, int, float, bool))][:50]
        elif isinstance(v, dict):
            safe[k] = _safe_metadata(v)
        else:
            safe[k] = str(v)[:200]
    return safe


def list_for_actor(actor_id: str, limit: int = 100, next_token: str | None = None) -> tuple[list[dict], str | None]:
    from boto3.dynamodb.conditions import Key
    tbl = aws.table("audit")
    kwargs: dict = {
        "KeyConditionExpression": Key("pk").eq(f"ACTOR#{actor_id}"),
        "ScanIndexForward": False,
        "Limit": limit,
    }
    if next_token:
        kwargs["ExclusiveStartKey"] = {"pk": f"ACTOR#{actor_id}", "sk": next_token}
    resp = tbl.query(**kwargs)
    items = resp.get("Items", [])
    token = None
    if resp.get("LastEvaluatedKey"):
        token = resp["LastEvaluatedKey"]["sk"]
    return items, token


def list_security_events(limit: int = 100) -> list[dict]:
    from boto3.dynamodb.conditions import Key
    tbl = aws.table("audit")
    items: list[dict] = []
    for et in sorted(SECURITY_EVENTS):
        resp = tbl.query(
            IndexName="gsi1",
            KeyConditionExpression=Key("gsi1pk").eq(f"TYPE#{et}"),
            ScanIndexForward=False,
            Limit=min(limit, 25),
        )
        items.extend(resp.get("Items", []))
    items.sort(key=lambda i: i.get("timestamp", ""), reverse=True)
    return items[:limit]
