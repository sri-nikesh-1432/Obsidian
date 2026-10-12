"""Request context: authentication, role resolution, and safe helpers.

Every protected handler receives a RequestContext whose ``user``/``role``
are derived exclusively from the server-side session — never from any
value supplied by the frontend.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import aws, audit
from .config import settings
from .errors import ApiError, auth_required
from .profile_schema import ROLE_FIELDS, ROLE_LIST_FIELDS


@dataclass
class RequestContext:
    method: str
    path: str
    path_params: dict = field(default_factory=dict)
    query: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)
    body: dict = field(default_factory=dict)
    raw_body: bytes = b""
    ip: str = "unknown"
    request_id: str = ""
    user: dict | None = None          # authenticated user item (server-side truth)
    session: dict | None = None       # session item

    @property
    def user_id(self) -> str | None:
        return self.user["user_id"] if self.user else None

    @property
    def role(self) -> str | None:
        return self.user["role"] if self.user else None

    @property
    def email(self) -> str | None:
        return self.user["email"] if self.user else None

    def require_auth(self) -> dict:
        if not self.user:
            raise auth_required()
        return self.user

    def require_role(self, *roles: str) -> dict:
        user = self.require_auth()
        if user["role"] not in roles:
            from .errors import access_denied
            audit.write_event(
                actor_id=user["user_id"], actor_role=user["role"],
                event_type="authorization_denied", result="denied",
                request_id=self.request_id,
                metadata={"path": self.path, "method": self.method, "required_roles": list(roles)},
            )
            raise access_denied()
        return user


# --------------------------------------------------------------- session store

def session_cookie_value(headers: dict) -> str | None:
    cookie = headers.get("cookie") or headers.get("Cookie") or ""
    for part in cookie.split(";"):
        name, _, value = part.strip().partition("=")
        if name == settings.cookie_name:
            return value or None
    return None


def resolve_session(headers: dict) -> tuple[dict | None, dict | None]:
    """Return (user, session) for a valid, unexpired, unrevoked session."""
    from .security import hash_token
    token = session_cookie_value(headers)
    if not token:
        return None, None
    key = {"pk": f"SESSION#{hash_token(token)}", "sk": "S"}
    resp = aws.table("sessions").get_item(Key=key)
    session = resp.get("Item")
    if not session:
        return None, None
    if session.get("revoked_at"):
        return None, None
    expires = session.get("expires_at_iso", "")
    if expires and expires < datetime.now(timezone.utc).isoformat():
        return None, None
    user_resp = aws.table("users").get_item(Key={"pk": f"USER#{session['user_id']}", "sk": "META"})
    user = user_resp.get("Item")
    if not user or user.get("status") != "active":
        return None, None
    return user, session


def create_session(user_id: str, ip: str = "", user_agent: str = "") -> str:
    """Create a server-side session; returns the raw token (goes into cookie)."""
    import hashlib
    from .security import new_token, hash_token
    from .audit import now_iso
    token = new_token(32)
    now = datetime.now(timezone.utc)
    expires = datetime.fromtimestamp(now.timestamp() + settings.session_ttl_seconds, tz=timezone.utc)
    item = {
        "pk": f"SESSION#{hash_token(token)}",
        "sk": "S",
        "user_id": user_id,
        "created_at": now.isoformat(),
        "expires_at_iso": expires.isoformat(),
        "last_seen_at": now.isoformat(),
        "ip_hash": hashlib.sha256(ip.encode()).hexdigest()[:16] if ip else "",
        "ua_hash": hashlib.sha256(user_agent.encode()).hexdigest()[:16] if user_agent else "",
        "revoked_at": "",
        "ttl": int(expires.timestamp()) + 3600,
        "gsi1pk": f"USERSESSIONS#{user_id}",
        "gsi1sk": now.isoformat(),
    }
    aws.table("sessions").put_item(Item=item)
    return token


def revoke_session(headers: dict) -> None:
    from .audit import now_iso
    from .security import hash_token
    token = session_cookie_value(headers)
    if not token:
        return
    try:
        aws.table("sessions").update_item(
            Key={"pk": f"SESSION#{hash_token(token)}", "sk": "S"},
            UpdateExpression="SET revoked_at = :r",
            ConditionExpression="attribute_exists(pk)",
            ExpressionAttributeValues={":r": now_iso()},
        )
    except Exception:
        pass


def load_profile(user_id: str) -> dict | None:
    resp = aws.table("profiles").get_item(Key={"pk": f"PROFILE#{user_id}", "sk": "META"})
    return resp.get("Item")


def user_summary(user: dict) -> dict:
    profile = load_profile(user["user_id"]) or {}
    role = user.get("role", "student")
    # The profile returned to the caller is shaped for their role: a student
    # never receives faculty fields and vice versa.
    view: dict = {
        "full_name": profile.get("full_name", ""),
        "phone": profile.get("phone", ""),
    }
    for field in ROLE_FIELDS.get(role, {}):
        view[field] = profile.get(field, "")
    for field in ROLE_LIST_FIELDS.get(role, ()):
        view[field] = profile.get(field, [])
    if role == "student":
        view["student_id"] = profile.get("student_id", "")
        view["profile_visibility"] = profile.get("profile_visibility", "private")
    view["avatar_seed"] = profile.get("avatar_seed", "")
    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "role": role,
        "status": user.get("status", "active"),
        "mfa_enabled": bool(user.get("mfa_enabled", True)),
        "ai_enabled": bool(user.get("ai_enabled", False)),
        # Administrators never go through the end-user onboarding wizard, even
        # if an older account predates that rule.
        "onboarding_complete": bool(user.get("onboarding_complete", False)) or role == "admin",
        "verification_status": user.get("verification_status", "verified"),
        "created_at": user.get("created_at", ""),
        "last_login_at": user.get("last_login_at", ""),
        "profile": view,
    }
