"""Password hashing, session tokens, OTP codes, and rate limiting."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque

from .config import settings

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

    _ph = PasswordHasher(time_cost=2, memory_cost=64 * 1024, parallelism=2)
    _HAS_ARGON2 = True
except Exception:  # pragma: no cover - fallback keeps the system usable
    _HAS_ARGON2 = False


# ---------------------------------------------------------------- passwords

def hash_password(password: str) -> str:
    if _HAS_ARGON2:
        return _ph.hash(password)
    import base64
    import os
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return "scrypt$%s$%s" % (salt.hex(), dk.hex())


def verify_password(password: str, stored: str) -> bool:
    if stored.startswith("scrypt$"):
        try:
            _, salt_hex, dk_hex = stored.split("$")
            dk = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
            return hmac.compare_digest(dk.hex(), dk_hex)
        except Exception:
            return False
    if _HAS_ARGON2:
        try:
            return _ph.verify(stored, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False
        except Exception:
            return False
    return False


def needs_rehash(stored: str) -> bool:
    if not _HAS_ARGON2 or stored.startswith("scrypt$"):
        return False
    try:
        return _ph.check_needs_rehash(stored)
    except Exception:
        return False


# ------------------------------------------------------------- opaque tokens

def new_token(num_bytes: int = 32) -> str:
    """Cryptographically secure high-entropy token (URL-safe)."""
    return secrets.token_urlsafe(num_bytes)


def new_share_token() -> str:
    return secrets.token_urlsafe(32)  # 256 bits of entropy


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_token(token: str) -> str:
    return sha256_hex(token)


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


# ----------------------------------------------------------------------- OTP

def generate_otp(length: int = 6) -> str:
    return "".join(str(secrets.randbelow(10)) for _ in range(length))


# ---------------------------------------------------------------- rate limits

class RateLimiter:
    """Fixed-window rate limiter shared across instances via DynamoDB.

    Concurrent Lambda executions must see the same counters, so window
    counts live in a dedicated table. If the table is unavailable the
    limiter degrades to the in-process window rather than failing open.
    """

    _FALLBACK_WARNED = False

    def __init__(self) -> None:
        self._events: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        try:
            return self._check_shared(key, limit, window_seconds)
        except Exception:
            self._warn_fallback()
            return self._check_local(key, limit, window_seconds)

    def _check_shared(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        from . import aws
        now = time.time()
        bucket = int(now // window_seconds)
        window_start = bucket * window_seconds
        resp = aws.table("ratelimits").update_item(
            Key={"pk": f"RL#{key}#{bucket}", "sk": "C"},
            UpdateExpression="ADD #c :one SET #t = if_not_exists(#t, :ttl)",
            ExpressionAttributeNames={"#c": "count", "#t": "ttl"},
            ExpressionAttributeValues={":one": 1, ":ttl": int(window_start + window_seconds + 60)},
            ReturnValues="ALL_NEW",
        )
        count = int(resp.get("Attributes", {}).get("count", 1))
        if count > limit:
            return False, max(1, int(window_start + window_seconds - now))
        return True, 0

    def _check_local(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        now = time.time()
        with self._lock:
            q = self._events[key]
            cutoff = now - window_seconds
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= limit:
                return False, int(window_seconds - (now - q[0])) if q else window_seconds
            q.append(now)
            return True, 0

    @classmethod
    def _warn_fallback(cls) -> None:
        if cls._FALLBACK_WARNED:
            return
        cls._FALLBACK_WARNED = True
        import sys
        print("[obsidian] rate limiter: shared store unavailable, using per-process fallback",
              file=sys.stderr)

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._events.clear()
            else:
                self._events.pop(key, None)


limiter = RateLimiter()


# -------------------------------------------------------------------- cookies

def build_session_cookie(token: str) -> str:
    parts = [f"{settings.cookie_name}={token}", "Path=/", "HttpOnly", "SameSite=Lax"]
    if settings.cookie_secure:
        parts.append("Secure")
    return "; ".join(parts)


def clear_session_cookie() -> str:
    parts = [f"{settings.cookie_name}=", "Path=/", "HttpOnly", "SameSite=Lax", "Max-Age=0"]
    if settings.cookie_secure:
        parts.append("Secure")
    return "; ".join(parts)
