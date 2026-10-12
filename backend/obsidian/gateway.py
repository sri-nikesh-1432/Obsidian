"""API Gateway router.

Maps (method, path) to Lambda-style handlers, enforces authentication,
role checks, CSRF/origin validation for mutations, and per-route rate
limits — the request pipeline required by the security model:

    Authenticate -> Identify -> Validate role -> Authorize resource -> Audit
"""
from __future__ import annotations

import base64
import json
import os
import re
import uuid

from . import audit, aws
from .config import settings
from .context import RequestContext, resolve_session
from .errors import ApiError, access_denied, error_payload, rate_limited
from .security import limiter

from .router import ROUTES, compile_pattern

_COMPILED: list | None = None


def _routes():
    global _COMPILED
    if _COMPILED is None:
        # import handlers to trigger @route registration
        from .functions import auth as _auth            # noqa
        from .functions import profile as _profile      # noqa
        from .functions import documents as _documents  # noqa
        from .functions import sharing as _sharing      # noqa
        from .functions import connections as _connections  # noqa
        from .functions import activity as _activity    # noqa
        from .functions import admin as _admin          # noqa
        from .functions import intelligence as _intel   # noqa
        from .functions import billing as _billing      # noqa
        # static paths win over parametric ones (/documents/shared-with-me
        # must not be swallowed by /documents/{document_id})
        ordered = sorted(ROUTES, key=lambda r: 1 if "{" in r[1] else 0)
        _COMPILED = [(m, compile_pattern(p), fn, auth, roles, rate)
                     for (m, p, fn, auth, roles, rate) in ordered]
    return _COMPILED


def dispatch(event: dict, context: dict | None = None) -> dict:
    """API Gateway HTTP API (v2) style entry point."""
    settings.load_secrets()
    ctx_http = event.get("requestContext", {}).get("http", {})
    method = ctx_http.get("method") or event.get("httpMethod", "GET")
    path = event.get("rawPath") or event.get("path", "/")
    if path.startswith("/api/v1"):
        path = path[len("/api/v1"):]
    if not path.startswith("/"):
        path = "/" + path
    query = event.get("queryStringParameters") or {}
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    request_id = event.get("requestContext", {}).get("requestId") or uuid.uuid4().hex
    ip = ctx_http.get("sourceIp") or headers.get("x-forwarded-for", "unknown")

    body, raw_body = _decode_body(event)
    req = RequestContext(
        method=method, path=path, query=query, headers=headers,
        body=body, raw_body=raw_body, ip=ip, request_id=request_id,
    )

    try:
        matched = None
        for m, pattern, fn, auth, roles, rate in _routes():
            if m != method:
                continue
            match = pattern.match(path)
            if match:
                matched = (fn, auth, roles, rate, match)
                break
        if matched is None:
            raise ApiError("RESOURCE_NOT_FOUND", "The requested endpoint does not exist.", 404)
        fn, auth, roles, rate, match = matched
        req.path_params = match.groupdict()

        # ---- origin check for state-changing requests (CSRF defence)
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            _check_origin(headers)

        # ---- rate limiting (applied before any work)
        if rate and rate.get("limit"):
            key = f"{rate['key']}:{ip}"
            # Local dev server relaxes limits so seeding and smoke tests are
            # not blocked by in-process counters. Off by default elsewhere.
            effective_limit = rate["limit"] * 100 if settings.relax_rate_limits else rate["limit"]
            if settings.is_prod and settings.relax_rate_limits:
                # Belt and braces: __post_init__ already cleared this, but a
                # mutated settings object must never disable throttling in prod.
                effective_limit = rate["limit"]
                raise access_denied()
            ok, retry = limiter.check(key, effective_limit, rate["window"])
            if not ok:
                audit.write_event(
                    actor_id=None, actor_role=None, event_type="rate_limit_triggered",
                    result="denied", request_id=request_id,
                    metadata={"path": path, "route_key": rate["key"]},
                )
                raise rate_limited(retry)

        # ---- authentication comes from the server-side session only
        if auth in ("authenticated", "any"):
            user, session = resolve_session(headers)
            req.user, req.session = user, session
        if auth == "authenticated" and req.user is None:
            raise ApiError("AUTH_REQUIRED", "You must be signed in to perform this action.", 401)
        if roles:
            req.require_role(*roles)

        result = fn(req)
        status, resp_body = 200, result
        headers_out: dict = {}
        cookies: list[str] = []
        if isinstance(result, tuple):
            if len(result) == 3:
                status, resp_body, headers_out = result
            elif len(result) == 2:
                status, resp_body = result
        if isinstance(resp_body, dict) and "_cookies" in resp_body:
            cookies = resp_body.pop("_cookies")
        if isinstance(resp_body, dict) and "_headers" in resp_body:
            headers_out.update(resp_body.pop("_headers"))
        return _ok(status, resp_body, headers_out, cookies, request_id)

    except ApiError as e:
        return _err(e.status, e.code, e.message, request_id, e.details)
    except Exception as e:  # pragma: no cover - defensive
        import traceback
        if os.environ.get("OBSIDIAN_DEMO_SHOW_ERRORS") == "1":
            print(f"[error] {request_id} {method} {path}: {e}\n{traceback.format_exc()}")
        else:
            print(f"[error] {request_id} {method} {path}: {e}")
        return _err(500, "INTERNAL_ERROR", "Something went wrong. Please try again.", request_id)


def _decode_body(event: dict) -> tuple[dict, bytes]:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(body) if body else b""
    else:
        raw = body.encode("utf-8") if isinstance(body, str) else (body or b"")
    if not raw:
        return {}, b""
    ctype = ""
    for k, v in (event.get("headers") or {}).items():
        if k.lower() == "content-type":
            ctype = v.lower()
    if "application/json" in ctype:
        try:
            parsed = json.loads(raw.decode("utf-8"))
            return (parsed if isinstance(parsed, dict) else {"data": parsed}), raw
        except Exception:
            raise ApiError("INVALID_INPUT", "Request body is not valid JSON.", 400)
    return {}, raw


def _check_origin(headers: dict) -> None:
    origin = headers.get("origin")
    if not origin:
        return  # non-browser clients (curl/tests) without Origin header
    allowed = set(settings.origins) | {settings.api_base_url}
    if origin not in allowed and not settings.is_prod:
        allowed_hosts = {o.split("//")[-1] for o in allowed}
        if origin.split("//")[-1] in allowed_hosts:
            return
    if origin not in allowed:
        raise ApiError("ACCESS_DENIED", "Request origin is not allowed.", 403)


def _json_default(o):
    from decimal import Decimal
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    if isinstance(o, (set, frozenset, tuple)):
        return list(o)
    if isinstance(o, bytes):
        return o.decode("utf-8", "ignore")
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


def _ok(status: int, body, headers_out: dict, cookies: list[str], request_id: str) -> dict:
    resp = {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json; charset=utf-8",
            "X-Request-Id": request_id,
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "same-origin",
            "X-Frame-Options": "DENY",
            # Authenticated JSON must never be cached by a shared cache.
            "Cache-Control": "no-store, no-cache, must-revalidate, private",
            "Pragma": "no-cache",
            # API responses are data, not documents: no origin, no framing.
            "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
            "Cross-Origin-Resource-Policy": "same-origin",
            "Cross-Origin-Opener-Policy": "same-origin",
            **headers_out,
        },
        "isBase64Encoded": False,
        "body": json.dumps(body if body is not None else {}, default=_json_default),
    }
    if settings.is_prod:
        resp["headers"]["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if cookies:
        resp["headers"]["set-cookie"] = cookies
    return resp


def _err(status: int, code: str, message: str, request_id: str, details: dict | None = None) -> dict:
    return _ok(status, error_payload(code, message, request_id, details), {}, [], request_id)
