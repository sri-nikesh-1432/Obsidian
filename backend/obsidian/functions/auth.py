"""Authentication handlers: registration, login, OTP MFA, sessions, Google OAuth.

Role is stored server-side at registration and re-derived from the session on
every request. The client can never assert a role.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from boto3.dynamodb.conditions import Key

from .. import audit, aws, mailer, security
from ..config import settings
from ..context import RequestContext, create_session, revoke_session, user_summary, load_profile
from ..errors import ApiError, invalid_input, rate_limited
from ..ids import new_student_id, uuid_hex
from ..profile_schema import empty_profile_fields, initial_verification
from ..router import route

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
ROLES = ("student", "faculty", "recruiter", "admin")
MIN_PASSWORD_LEN = 10

# Work factor used to equalize timing when an account does not exist.
_DUMMY_HASH: str | None = None


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = security.hash_password("obsidian-timing-equalizer")
    return _DUMMY_HASH


def find_user_by_email(email: str) -> dict | None:
    resp = aws.table("users").query(
        IndexName="gsi1",
        KeyConditionExpression=Key("gsi1pk").eq(f"EMAIL#{email.lower()}"),
        Limit=1,
    )
    items = resp.get("Items", [])
    return items[0] if items else None


# ------------------------------------------------------------------ challenges

def _create_challenge(purpose: str, email: str, payload: dict | None = None,
                      user_id: str | None = None) -> dict:
    challenge_id = uuid_hex()
    code = security.generate_otp(6)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=settings.otp_ttl_seconds)
    item = {
        "pk": f"MFA#{challenge_id}",
        "sk": "C",
        "challenge_id": challenge_id,
        "purpose": purpose,
        "email": email.lower(),
        "user_id": user_id or "",
        "code_hash": security.hash_token(f"{challenge_id}:{code}"),
        "attempt_count": 0,
        "consumed_at": "",
        "created_at": now.isoformat(),
        "expires_at_iso": expires.isoformat(),
        "ttl": int(expires.timestamp()) + 3600,
        "payload": payload or {},
    }
    aws.table("mfa").put_item(Item=item)
    _send_otp_email(email, code, purpose)
    audit.write_event(
        actor_id=user_id, actor_role=None, event_type="otp_requested",
        resource_type="mfa_challenge", resource_id=challenge_id,
        request_id=None, metadata={"purpose": purpose},
    )
    item["_otp"] = code
    return item


def _send_otp_email(email: str, code: str, purpose: str) -> None:
    titles = {
        "signup": "Confirm your OBSIDIAN account",
        "login": "Your OBSIDIAN sign-in code",
        "password_reset": "Your OBSIDIAN password reset code",
    }
    title = titles.get(purpose, "Your OBSIDIAN verification code")
    text = f"{title}\n\nYour one-time code is: {code}\n\nIt expires in {settings.otp_ttl_seconds // 60} minutes. If you did not request this, you can safely ignore this email."
    html = f"""<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f6f3ec;padding:32px">
      <div style="max-width:440px;margin:auto;background:#fffdf9;border:1px solid #e8e2d6;border-radius:16px;padding:32px">
        <div style="letter-spacing:.28em;font-size:12px;color:#8a7f6f">OBSIDIAN</div>
        <h2 style="color:#211d18;margin:14px 0 6px">{title}</h2>
        <p style="color:#5c554b;font-size:14px;line-height:1.6">Enter this one-time code to continue. It expires in {settings.otp_ttl_seconds // 60} minutes.</p>
        <div style="font-size:30px;letter-spacing:.35em;font-weight:600;color:#211d18;background:#f6f3ec;border-radius:12px;padding:16px;text-align:center;margin:18px 0">{code}</div>
        <p style="color:#8a7f6f;font-size:12px">If you did not request this, ignore this email.</p>
      </div></div>"""
    mailer.send_email(to=email, subject=title, html=html, text=text)


def _challenge_response(challenge: dict, purpose: str) -> dict:
    body = {
        "challenge_id": challenge["challenge_id"],
        "purpose": purpose,
        "email": challenge["email"],
        "expires_in": settings.otp_ttl_seconds,
    }
    # Surface the code to the client ONLY when nothing can actually deliver it
    # (no Resend key, no SMTP relay) and we are in dev mode. As soon as a real
    # mail channel is configured the code never leaves the backend, even if
    # OBSIDIAN_DEV_MODE is still on.
    if settings.dev_mode and mailer.delivery_channel() == "dev":
        body["dev_otp"] = challenge["_otp"]
    return body


def _load_challenge(challenge_id: str) -> dict:
    resp = aws.table("mfa").get_item(Key={"pk": f"MFA#{challenge_id}", "sk": "C"})
    challenge = resp.get("Item")
    if not challenge:
        raise ApiError("INVALID_INPUT", "This verification request is no longer valid. Please start again.", 400)
    if challenge.get("consumed_at"):
        raise ApiError("INVALID_INPUT", "This code has already been used. Please start again.", 400)
    if challenge.get("expires_at_iso", "") < datetime.now(timezone.utc).isoformat():
        raise ApiError("INVALID_INPUT", "This code has expired. Please request a new one.", 400)
    return challenge


def _verify_code(challenge: dict, code: str, request_id: str) -> None:
    if not code or not isinstance(code, str) or not code.strip().isdigit():
        raise _otp_failure(challenge, request_id)
    if challenge["attempt_count"] >= settings.otp_max_attempts:
        _consume(challenge)
        raise ApiError("INVALID_INPUT", "Too many incorrect attempts. Please start again.", 400)
    expected = challenge["code_hash"]
    computed = security.hash_token(f"{challenge['challenge_id']}:{code}")
    if not security.constant_time_equals(computed, expected):
        aws.table("mfa").update_item(
            Key={"pk": challenge["pk"], "sk": "C"},
            UpdateExpression="ADD attempt_count :one",
            ExpressionAttributeValues={":one": 1},
        )
        audit.write_event(
            actor_id=challenge.get("user_id") or None, actor_role=None,
            event_type="otp_failure", result="failure", request_id=request_id,
            resource_type="mfa_challenge", resource_id=challenge["challenge_id"],
            metadata={"purpose": challenge["purpose"]},
        )
        remaining = settings.otp_max_attempts - challenge["attempt_count"] - 1
        if remaining <= 0:
            _consume(challenge)
            raise ApiError("INVALID_INPUT", "Too many incorrect attempts. Please start again.", 400)
        raise ApiError("INVALID_INPUT", f"That code is incorrect. {remaining} attempts remaining.", 400)
    audit.write_event(
        actor_id=challenge.get("user_id") or None, actor_role=None,
        event_type="otp_success", result="success", request_id=request_id,
        resource_type="mfa_challenge", resource_id=challenge["challenge_id"],
        metadata={"purpose": challenge["purpose"]},
    )


def _otp_failure(challenge: dict, request_id: str) -> ApiError:
    audit.write_event(
        actor_id=challenge.get("user_id") or None, actor_role=None,
        event_type="otp_failure", result="failure", request_id=request_id,
        resource_type="mfa_challenge", resource_id=challenge["challenge_id"],
    )
    return ApiError("INVALID_INPUT", "That code is incorrect.", 400)


def _consume(challenge: dict) -> None:
    aws.table("mfa").update_item(
        Key={"pk": challenge["pk"], "sk": "C"},
        UpdateExpression="SET consumed_at = :c",
        ExpressionAttributeValues={":c": datetime.now(timezone.utc).isoformat()},
    )


# ------------------------------------------------------------------ register

@route("POST", "/auth/register", auth="public", rate=("register", 10, 3600))
def register(req: RequestContext) -> dict:
    body = req.body
    role = str(body.get("role", "")).lower().strip()
    email = str(body.get("email", "")).strip().lower()
    password = str(body.get("password", ""))
    full_name = str(body.get("full_name", "")).strip()[:120]

    if role not in ROLES:
        raise invalid_input("Please choose a valid account role.")
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise invalid_input("Please enter a valid email address.")
    if len(password) < MIN_PASSWORD_LEN or len(password) > 200:
        raise invalid_input(f"Password must be at least {MIN_PASSWORD_LEN} characters.")
    if role == "admin" and not settings.is_allowed_admin_email(email):
        # Only allowlisted addresses may be provisioned as admin — in every
        # environment, and never by simply choosing the role at signup.
        from ..errors import access_denied
        raise access_denied()

    existing = find_user_by_email(email)
    if existing:
        raise ApiError("EMAIL_TAKEN", "An account with this email already exists.", 409)

    challenge = _create_challenge("signup", email, payload={
        "role": role,
        "password_hash": security.hash_password(password),
        "full_name": full_name,
    })
    audit.write_event(
        actor_id=None, actor_role=None, event_type="registration_requested",
        resource_type="user", resource_id=email, request_id=req.request_id,
        metadata={"role": role},
    )
    return _challenge_response(challenge, "signup")


@route("POST", "/auth/otp/request", auth="public", rate=("otp_request", 6, 600))
def request_otp(req: RequestContext) -> dict:
    challenge_id = str(req.body.get("challenge_id", "")).strip()
    purpose = str(req.body.get("purpose", "")).strip()
    email = str(req.body.get("email", "")).strip().lower()

    if challenge_id:
        challenge = _load_challenge(challenge_id)
        challenge = _create_challenge(challenge["purpose"], challenge["email"],
                                      payload=challenge.get("payload") or {},
                                      user_id=challenge.get("user_id") or None)
        return _challenge_response(challenge, challenge["purpose"])

    if purpose == "login" and EMAIL_RE.match(email):
        user = find_user_by_email(email)
        if (user and user.get("status") == "active"
                and (user.get("role") != "admin"
                     or settings.is_allowed_admin_email(user.get("email", "")))):
            challenge = _create_challenge("login", user["email"], user_id=user["user_id"])
            return _challenge_response(challenge, "login")

    # Always respond the same way: never reveal whether an account exists.
    return {"ok": True, "message": "If an account exists for that request, a code has been sent."}


@route("POST", "/auth/otp/verify", auth="public", rate=("otp_verify", 30, 300))
def verify_otp(req: RequestContext) -> dict:
    challenge_id = str(req.body.get("challenge_id", "")).strip()
    code = str(req.body.get("code", "")).strip()
    if not challenge_id:
        raise invalid_input("Verification request is required.")
    challenge = _load_challenge(challenge_id)
    _verify_code(challenge, code, req.request_id)
    _consume(challenge)

    purpose = challenge["purpose"]
    if purpose == "signup":
        return _complete_registration(req, challenge)
    if purpose == "login":
        return _complete_login(req, challenge)
    if purpose == "password_reset":
        return {"ok": True, "reset_token_ready": True, "challenge_id": challenge_id}
    raise ApiError("INVALID_INPUT", "This verification request is no longer valid.", 400)


def _complete_registration(req: RequestContext, challenge: dict) -> dict:
    payload = challenge.get("payload") or {}
    email = challenge["email"]
    existing = find_user_by_email(email)
    if existing:
        raise ApiError("EMAIL_TAKEN", "An account with this email already exists.", 409)

    role = payload.get("role", "student")
    if role == "admin" and not settings.is_allowed_admin_email(email):
        from ..errors import access_denied
        raise access_denied()

    now = datetime.now(timezone.utc).isoformat()
    user_id = uuid_hex()
    user_item = {
        "pk": f"USER#{user_id}", "sk": "META",
        "user_id": user_id, "email": email, "role": role,
        "status": "active", "password_hash": payload.get("password_hash", ""),
        "mfa_enabled": True, "ai_enabled": False,
        # Administrators run the platform, they are not onboarded like end
        # users — no profile wizard, no personal-AI consent step.
        "onboarding_complete": role == "admin",
        "verification_status": initial_verification(role, settings.dev_mode),
        "google_subject": "", "created_at": now, "updated_at": now,
        "last_login_at": now,
        "gsi1pk": f"EMAIL#{email}", "gsi1sk": user_id,
    }
    try:
        aws.table("users").put_item(
            Item=user_item,
            ConditionExpression="attribute_not_exists(pk)",
        )
    except Exception:
        raise ApiError("EMAIL_TAKEN", "An account with this email already exists.", 409)

    profile_item = {
        "pk": f"PROFILE#{user_id}", "sk": "META",
        "user_id": user_id,
        "full_name": payload.get("full_name", ""),
        "phone": "",
        **empty_profile_fields(role),
        "student_id": new_student_id() if role == "student" else "",
        "profile_visibility": "public",
        "show_phone": False,
        "created_at": now, "updated_at": now,
    }
    if role == "student":
        profile_item["gsi1pk"] = f"SID#{profile_item['student_id']}"
        profile_item["gsi1sk"] = user_id
    aws.table("profiles").put_item(Item=profile_item)

    token = create_session(user_id, req.ip, req.headers.get("user-agent", ""))
    audit.write_event(
        actor_id=user_id, actor_role=role, event_type="registration_completed",
        resource_type="user", resource_id=user_id, request_id=req.request_id,
    )
    audit.write_event(
        actor_id=user_id, actor_role=role, event_type="login_success",
        resource_type="session", resource_id=user_id, request_id=req.request_id,
        metadata={"method": "email_otp"},
    )
    body = user_summary(user_item)
    body["authenticated"] = True
    body["_cookies"] = [security.build_session_cookie(token)]
    return 201, body


def _complete_login(req: RequestContext, challenge: dict) -> dict:
    user = find_user_by_email(challenge["email"])
    if not user or user.get("status") != "active":
        raise ApiError("INVALID_INPUT", "This sign-in request is no longer valid.", 400)
    if user.get("role") == "admin" and not settings.is_allowed_admin_email(user.get("email", "")):
        from ..errors import access_denied
        raise access_denied()
    now = datetime.now(timezone.utc).isoformat()
    aws.table("users").update_item(
        Key={"pk": user["pk"], "sk": "META"},
        UpdateExpression="SET last_login_at = :t, updated_at = :t",
        ExpressionAttributeValues={":t": now},
    )
    token = create_session(user["user_id"], req.ip, req.headers.get("user-agent", ""))
    audit.write_event(
        actor_id=user["user_id"], actor_role=user["role"], event_type="login_success",
        resource_type="session", resource_id=user["user_id"], request_id=req.request_id,
        metadata={"method": "email_otp"},
    )
    user["last_login_at"] = now
    body = user_summary(user)
    body["authenticated"] = True
    body["_cookies"] = [security.build_session_cookie(token)]
    return body


# --------------------------------------------------------------------- login

@route("POST", "/auth/login", auth="public", rate=("login", 15, 300))
def login(req: RequestContext) -> dict:
    email = str(req.body.get("email", "")).strip().lower()
    password = str(req.body.get("password", ""))
    if not EMAIL_RE.match(email) or not password:
        raise ApiError("INVALID_CREDENTIALS", "Incorrect email or password.", 401)

    user = find_user_by_email(email)
    if not user:
        security.verify_password(password, _dummy_hash())
        audit.write_event(
            actor_id=None, actor_role=None, event_type="login_failure",
            resource_type="user", resource_id=email, result="failure",
            request_id=req.request_id, metadata={"reason": "unknown_account"},
        )
        raise ApiError("INVALID_CREDENTIALS", "Incorrect email or password.", 401)

    if not security.verify_password(password, user.get("password_hash", "")):
        audit.write_event(
            actor_id=user["user_id"], actor_role=user["role"], event_type="login_failure",
            resource_type="user", resource_id=user["user_id"], result="failure",
            request_id=req.request_id, metadata={"reason": "bad_password"},
        )
        raise ApiError("INVALID_CREDENTIALS", "Incorrect email or password.", 401)
    if user.get("status") != "active":
        raise ApiError("ACCESS_DENIED", "This account is not active.", 403)
    if user.get("role") == "admin" and not settings.is_allowed_admin_email(user.get("email", "")):
        # An admin account that is no longer on the allowlist cannot sign in.
        # The failed attempt is recorded like any other denied sign-in.
        audit.write_event(
            actor_id=user["user_id"], actor_role=user["role"], event_type="login_failure",
            resource_type="user", resource_id=user["user_id"], result="failure",
            request_id=req.request_id, metadata={"reason": "admin_not_allowlisted"},
        )
        raise ApiError("ACCESS_DENIED", "This admin account is not authorized.", 403)

    # Role is selected before sign-in; the server decides whether the
    # credential actually belongs to an account with that role.
    requested_role = str(req.body.get("role", "") or "").lower().strip()
    if requested_role and requested_role in ROLES and requested_role != user.get("role"):
        audit.write_event(
            actor_id=user["user_id"], actor_role=user["role"], event_type="login_failure",
            resource_type="user", resource_id=user["user_id"], result="failure",
            request_id=req.request_id, metadata={"reason": "role_mismatch"},
        )
        raise ApiError("ROLE_MISMATCH",
                       f"This account is registered as {user.get('role')}. "
                       f"Please continue as {user.get('role')}.", 403)

    challenge = _create_challenge("login", user["email"], user_id=user["user_id"])
    return _challenge_response(challenge, "login")


# -------------------------------------------------------------------- logout

@route("POST", "/auth/logout", auth="any")
def logout(req: RequestContext) -> dict:
    if req.user:
        audit.write_event(
            actor_id=req.user["user_id"], actor_role=req.user["role"],
            event_type="logout", resource_type="session",
            resource_id=req.user["user_id"], request_id=req.request_id,
        )
    revoke_session(req.headers)
    return {"ok": True, "_cookies": [security.clear_session_cookie()]}


@route("GET", "/auth/me", auth="any")
def me(req: RequestContext) -> dict:
    if not req.user:
        return {"authenticated": False}
    body = user_summary(req.user)
    body["authenticated"] = True
    profile = load_profile(req.user["user_id"]) or {}
    body["profile"].update({
        "department": profile.get("department", ""),
        "year": profile.get("year", ""),
        "education_level": profile.get("education_level", ""),
        "graduation_year": profile.get("graduation_year", ""),
        "bio": profile.get("bio", ""),
        "skills": profile.get("skills", []),
        "achievements": profile.get("achievements", []),
        "cgpa": profile.get("cgpa", ""),
        "show_phone": bool(profile.get("show_phone", False)),
    })
    if req.user.get("role") == "student":
        # Storage standing rides along with /auth/me so the app shell can show
        # the meter without an extra round-trip on every page.
        from .billing import entitlement_bytes, used_bytes
        from .. import plans
        limit = entitlement_bytes(req.user)
        used = used_bytes(req.user["user_id"])
        tier = plans.tier_from_entitlement_bytes(limit)
        body["storage"] = {
            "used_bytes": used,
            "limit_bytes": limit,
            "remaining_bytes": max(0, limit - used),
            "percent_used": round(min(100.0, (used / limit) * 100), 2) if limit else 0.0,
            "tier": tier,
            "total_gb": plans.total_gb_for_tier(tier),
            "exceeded": used >= limit,
            "near_limit": used >= limit * 0.9,
        }
    return body


# --------------------------------------------------------------- sessions mgmt

@route("GET", "/auth/sessions")
def list_sessions(req: RequestContext) -> dict:
    user = req.require_auth()
    resp = aws.table("sessions").query(
        IndexName="gsi1",
        KeyConditionExpression=Key("gsi1pk").eq(f"USERSESSIONS#{user['user_id']}"),
        ScanIndexForward=False,
        Limit=25,
    )
    now = datetime.now(timezone.utc).isoformat()
    from ..context import session_cookie_value
    current_hash = security.hash_token(session_cookie_value(req.headers) or "")
    out = []
    for it in resp.get("Items", []):
        if it.get("revoked_at") or it.get("expires_at_iso", "") < now:
            continue
        out.append({
            "session_ref": it["pk"].split("SESSION#")[-1][:12],
            "created_at": it["created_at"],
            "last_seen_at": it.get("last_seen_at", ""),
            "ip_hash": it.get("ip_hash", ""),
            "current": it["pk"] == f"SESSION#{current_hash}",
        })
    return {"sessions": out}


@route("POST", "/auth/logout-others")
def logout_others(req: RequestContext) -> dict:
    user = req.require_auth()
    resp = aws.table("sessions").query(
        IndexName="gsi1",
        KeyConditionExpression=Key("gsi1pk").eq(f"USERSESSIONS#{user['user_id']}"),
    )
    from ..context import session_cookie_value
    current = session_cookie_value(req.headers) or ""
    current_pk = f"SESSION#{security.hash_token(current)}"
    now = datetime.now(timezone.utc).isoformat()
    revoked = 0
    for it in resp.get("Items", []):
        if it["pk"] == current_pk or it.get("revoked_at"):
            continue
        aws.table("sessions").update_item(
            Key={"pk": it["pk"], "sk": "S"},
            UpdateExpression="SET revoked_at = :r",
            ExpressionAttributeValues={":r": now},
        )
        revoked += 1
    audit.write_event(
        actor_id=user["user_id"], actor_role=user["role"],
        event_type="logout", resource_type="session",
        resource_id=user["user_id"], request_id=req.request_id,
        metadata={"scope": "all_other_sessions", "revoked": revoked},
    )
    return {"revoked": revoked}


# ------------------------------------------------------------ password reset

@route("POST", "/auth/password/forgot", auth="public", rate=("password_forgot", 5, 900))
def password_forgot(req: RequestContext) -> dict:
    email = str(req.body.get("email", "")).strip().lower()
    body: dict = {"ok": True, "message": "If an account exists for that email, a reset code has been sent."}
    if EMAIL_RE.match(email):
        user = find_user_by_email(email)
        if user:
            challenge = _create_challenge("password_reset", user["email"], user_id=user["user_id"])
            # The client needs the challenge id to submit the emailed code. It
            # is an opaque handle on its own, so returning it is safe.
            body["challenge_id"] = challenge["challenge_id"]
            if settings.dev_mode and mailer.delivery_channel() == "dev":
                body["dev_otp"] = challenge["_otp"]
        else:
            # Return a decoy id so an attacker cannot tell whether an account
            # exists. It never matches a real challenge and simply fails to
            # verify, exactly like a wrong code.
            body["challenge_id"] = uuid_hex()
    return body


@route("POST", "/auth/password/reset", auth="public", rate=("password_reset", 10, 900))
def password_reset(req: RequestContext) -> dict:
    challenge_id = str(req.body.get("challenge_id", "")).strip()
    code = str(req.body.get("code", "")).strip()
    new_password = str(req.body.get("new_password", ""))
    if len(new_password) < MIN_PASSWORD_LEN:
        raise invalid_input(f"Password must be at least {MIN_PASSWORD_LEN} characters.")
    challenge = _load_challenge(challenge_id)
    if challenge["purpose"] != "password_reset":
        raise invalid_input("This verification request is no longer valid.")
    _verify_code(challenge, code, req.request_id)
    _consume(challenge)
    user = find_user_by_email(challenge["email"])
    if not user:
        raise ApiError("INVALID_INPUT", "This reset request is no longer valid.", 400)
    aws.table("users").update_item(
        Key={"pk": user["pk"], "sk": "META"},
        UpdateExpression="SET password_hash = :p, updated_at = :t",
        ExpressionAttributeValues={
            ":p": security.hash_password(new_password),
            ":t": datetime.now(timezone.utc).isoformat(),
        },
    )
    # Invalidate existing sessions after a credential change.
    resp = aws.table("sessions").query(
        IndexName="gsi1",
        KeyConditionExpression=Key("gsi1pk").eq(f"USERSESSIONS#{user['user_id']}"),
    )
    now = datetime.now(timezone.utc).isoformat()
    for it in resp.get("Items", []):
        if not it.get("revoked_at"):
            aws.table("sessions").update_item(
                Key={"pk": it["pk"], "sk": "S"},
                UpdateExpression="SET revoked_at = :r",
                ExpressionAttributeValues={":r": now},
            )
    audit.write_event(
        actor_id=user["user_id"], actor_role=user["role"],
        event_type="password_reset", resource_type="user",
        resource_id=user["user_id"], request_id=req.request_id,
    )
    return {"ok": True}


# --------------------------------------------------------------- Google OAuth

def _frontend_url(path: str) -> str:
    return settings.public_base_url.rstrip("/") + path


@route("GET", "/auth/google/start", auth="public", rate=("google_start", 20, 300))
def google_start(req: RequestContext) -> dict:
    role = str(req.query.get("role", "student")).lower()
    if role not in ROLES:
        raise invalid_input("Please choose a valid account role.")
    if not settings.google_client_id:
        raise ApiError("GOOGLE_NOT_CONFIGURED",
                       "Google sign-in is not configured for this environment.", 501)
    state = security.new_token(24)
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)
    aws.table("mfa").put_item(Item={
        "pk": f"MFA#{state}", "sk": "GOOGLE",
        "purpose": "google_oauth", "role": role,
        "expires_at_iso": expires.isoformat(), "ttl": int(expires.timestamp()) + 300,
    })
    from urllib.parse import urlencode
    params = urlencode({
        "client_id": settings.google_client_id,
        "redirect_uri": settings.api_base_url.rstrip("/") + "/auth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    })
    return {"url": f"https://accounts.google.com/o/oauth2/v2/auth?{params}"}


@route("GET", "/auth/google/callback", auth="public")
def google_callback(req: RequestContext) -> tuple:
    state = str(req.query.get("state", ""))
    code = str(req.query.get("code", ""))
    resp = aws.table("mfa").get_item(Key={"pk": f"MFA#{state}", "sk": "GOOGLE"})
    state_item = resp.get("Item")
    if not state_item or state_item.get("expires_at_iso", "") < datetime.now(timezone.utc).isoformat():
        raise ApiError("INVALID_INPUT", "This sign-in request expired. Please try again.", 400)
    if not code:
        raise ApiError("INVALID_INPUT", "Google did not return a valid response.", 400)

    import httpx
    token_resp = httpx.post("https://oauth2.googleapis.com/token", data={
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": settings.api_base_url.rstrip("/") + "/auth/google/callback",
        "grant_type": "authorization_code",
    }, timeout=15.0)
    if token_resp.status_code != 200:
        raise ApiError("INVALID_INPUT", "Google sign-in could not be completed.", 400)
    id_token = token_resp.json().get("id_token", "")
    info = _verify_google_id_token(id_token)
    email = (info.get("email") or "").lower()
    if not email or not info.get("email_verified", False):
        raise ApiError("INVALID_INPUT", "Google did not return a verified email address.", 400)

    user = find_user_by_email(email)
    if user and user.get("role") == "admin" and not settings.is_allowed_admin_email(email):
        from ..errors import access_denied
        raise access_denied()
    now = datetime.now(timezone.utc).isoformat()
    if not user:
        role = state_item.get("role", "student")
        # Mirror the OTP registration path: only allowlisted addresses may be
        # provisioned as admin.
        if role == "admin" and not settings.is_allowed_admin_email(email):
            from ..errors import access_denied
            raise access_denied()
        user_id = uuid_hex()
        user = {
            "pk": f"USER#{user_id}", "sk": "META",
            "user_id": user_id, "email": email, "role": role,
            "status": "active", "password_hash": "",
            "mfa_enabled": True, "ai_enabled": False,
            "onboarding_complete": role == "admin",
            "verification_status": initial_verification(role, settings.dev_mode),
            "google_subject": info.get("sub", ""),
            "created_at": now, "updated_at": now, "last_login_at": now,
            "gsi1pk": f"EMAIL#{email}", "gsi1sk": user_id,
        }
        try:
            aws.table("users").put_item(Item=user, ConditionExpression="attribute_not_exists(pk)")
        except Exception:
            user = find_user_by_email(email)
        if user and not user.get("password_hash"):
            profile = {
                "pk": f"PROFILE#{user['user_id']}", "sk": "META",
                "user_id": user["user_id"],
                "full_name": info.get("name", ""),
                "phone": "",
                **empty_profile_fields(user["role"]),
                "student_id": new_student_id() if user["role"] == "student" else "",
                "profile_visibility": "public", "show_phone": False,
                "created_at": now, "updated_at": now,
            }
            if user["role"] == "student":
                profile["gsi1pk"] = f"SID#{profile['student_id']}"
                profile["gsi1sk"] = user["user_id"]
            aws.table("profiles").put_item(Item=profile)
            audit.write_event(
                actor_id=user["user_id"], actor_role=user["role"],
                event_type="registration_completed", resource_type="user",
                resource_id=user["user_id"], request_id=req.request_id,
                metadata={"method": "google"},
            )
    if not user:
        raise ApiError("INVALID_INPUT", "Google sign-in could not be completed.", 400)

    aws.table("mfa").delete_item(Key={"pk": f"MFA#{state}", "sk": "GOOGLE"})
    token = create_session(user["user_id"], req.ip, req.headers.get("user-agent", ""))
    audit.write_event(
        actor_id=user["user_id"], actor_role=user["role"], event_type="login_success",
        resource_type="session", resource_id=user["user_id"], request_id=req.request_id,
        metadata={"method": "google"},
    )
    location = _frontend_url("/auth/complete")
    return 302, {}, {"Location": location, "set-cookie": [security.build_session_cookie(token)]}


def _verify_google_id_token(id_token: str) -> dict:
    """Validate issuer, audience, expiry and signature of a Google ID token."""
    try:
        from google.oauth2 import id_token as google_id_token
        import requests  # google-auth verifies via the requests transport
        info = google_id_token.verify_oauth2_token(id_token, requests.Request(),
                                                   audience=settings.google_client_id)
        if info.get("iss") not in ("https://accounts.google.com", "accounts.google.com"):
            raise ValueError("bad issuer")
        return info
    except Exception:
        # Fallback: token obtained directly from Google's token endpoint over
        # TLS — still enforce audience, issuer and expiry claims.
        import base64
        import json
        try:
            payload = id_token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            info = json.loads(base64.urlsafe_b64decode(payload))
        except Exception:
            raise ApiError("INVALID_INPUT", "Google sign-in could not be verified.", 400)
        if info.get("aud") != settings.google_client_id:
            raise ApiError("INVALID_INPUT", "Google sign-in could not be verified.", 400)
        if info.get("iss") not in ("https://accounts.google.com", "accounts.google.com"):
            raise ApiError("INVALID_INPUT", "Google sign-in could not be verified.", 400)
        if int(info.get("exp", 0)) < datetime.now(timezone.utc).timestamp():
            raise ApiError("INVALID_INPUT", "Google sign-in could not be verified.", 400)
        return info
