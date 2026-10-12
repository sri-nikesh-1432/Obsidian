"""User-facing activity and security event endpoints (safe subsets of audit)."""
from __future__ import annotations

from .. import audit
from ..context import RequestContext
from ..router import route

USER_SAFE_EVENTS = {
    "login_success", "login_failure", "logout", "otp_requested", "otp_success",
    "otp_failure", "password_reset", "document_uploaded", "document_viewed",
    "document_downloaded", "document_renamed", "document_deleted",
    "document_updated", "share_created", "share_accessed", "share_revoked",
    "share_access_denied", "profile_updated", "visibility_changed",
    "ai_enabled", "ai_disabled", "ai_query", "registration_completed",
    "student_lookup", "rate_limit_triggered", "authorization_denied",
    "group_created", "group_updated", "group_deleted", "group_viewed",
    "group_member_added", "group_member_removed", "group_message_sent",
}

SECURITY_FOR_USER = {
    "login_success", "login_failure", "otp_failure", "password_reset",
    "authorization_denied", "rate_limit_triggered", "suspicious_activity",
}


def _view(event: dict) -> dict:
    return {
        "event_id": event.get("event_id", ""),
        "event_type": event.get("event_type", ""),
        "timestamp": event.get("timestamp", ""),
        "result": event.get("result", ""),
        "resource_type": event.get("resource_type", ""),
        "resource_id": event.get("resource_id", "")[:12],
        "metadata": event.get("metadata", {}),
    }


@route("GET", "/activity")
def list_activity(req: RequestContext) -> dict:
    user = req.require_auth()
    try:
        limit = min(int(req.query.get("limit", 50)), 200)
    except ValueError:
        limit = 50
    events, next_token = audit.list_for_actor(user["user_id"], limit=200)
    filtered = [e for e in events if e.get("event_type") in USER_SAFE_EVENTS]
    return {
        "events": [_view(e) for e in filtered[:limit]],
        "next_token": next_token or "",
    }


@route("GET", "/security/events")
def security_events(req: RequestContext) -> dict:
    user = req.require_auth()
    events, _ = audit.list_for_actor(user["user_id"], limit=200)
    filtered = [e for e in events if e.get("event_type") in SECURITY_FOR_USER]
    return {"events": [_view(e) for e in filtered[:80]]}
