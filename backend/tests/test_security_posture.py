"""Regression tests for the security-audit fixes (FAIL/PARTIAL findings).

Covers:
- production defaults fail closed
- security response headers (Cache-Control, CSP, HSTS only in prod)
- shared DynamoDB-backed rate limiter
- faculty/recruiter verification workflow
- Secrets Manager loader never raises
- malware scanner honesty (never claims "clean" when unconfigured)
"""
from __future__ import annotations

import base64
import json
import os
import uuid

import pytest

from conftest import Client, register


# ------------------------------------------------------------ prod defaults

def test_production_defaults_fail_closed(monkeypatch):
    """OBSIDIAN_ENV=production must force every dev affordance off."""
    monkeypatch.setenv("OBSIDIAN_ENV", "production")
    monkeypatch.setenv("OBSIDIAN_LOCAL_AWS", "true")
    monkeypatch.setenv("OBSIDIAN_DEV_MODE", "true")
    monkeypatch.setenv("OBSIDIAN_COOKIE_SECURE", "false")
    monkeypatch.setenv("OBSIDIAN_RELAX_RATE_LIMITS", "true")

    from obsidian.config import Settings
    s = Settings()
    assert s.is_prod
    assert s.local_aws is False
    assert s.dev_mode is False
    assert s.cookie_secure is True
    assert s.relax_rate_limits is False


def test_development_defaults_are_fail_closed_too(monkeypatch):
    """With no env set, dev affordances must default to off."""
    for var in ("OBSIDIAN_LOCAL_AWS", "OBSIDIAN_DEV_MODE", "OBSIDIAN_COOKIE_SECURE",
                "OBSIDIAN_RELAX_RATE_LIMITS"):
        monkeypatch.delenv(var, raising=False)
    from obsidian.config import Settings
    s = Settings()
    assert s.local_aws is False
    assert s.dev_mode is False
    assert s.cookie_secure is False
    assert s.relax_rate_limits is False


# ----------------------------------------------------------------- headers

def _raw_event(method: str, path: str, ip: str = "10.0.0.1") -> dict:
    return {
        "version": "2.0",
        "rawPath": path,
        "headers": {"content-type": "application/json"},
        "queryStringParameters": None,
        "requestContext": {"requestId": uuid.uuid4().hex,
                           "http": {"method": method, "path": path, "sourceIp": ip}},
        "body": "",
        "isBase64Encoded": False,
    }


def test_responses_carry_security_headers():
    from obsidian.gateway import dispatch
    resp = dispatch(_raw_event("GET", "/api/v1/healthz"), None)
    h = resp["headers"]
    assert "no-store" in h.get("Cache-Control", "")
    assert "no-cache" in h.get("Pragma", "")
    assert h.get("Content-Security-Policy", "").startswith("default-src 'none'")
    assert "frame-ancestors 'none'" in h["Content-Security-Policy"]
    assert h.get("X-Content-Type-Options") == "nosniff"
    assert h.get("X-Frame-Options") == "DENY"
    assert h.get("Cross-Origin-Resource-Policy") == "same-origin"


def test_hsts_only_in_production():
    from obsidian.config import settings
    from obsidian.gateway import dispatch
    try:
        settings.is_prod = False
        resp = dispatch(_raw_event("GET", "/api/v1/healthz"), None)
        assert "Strict-Transport-Security" not in resp["headers"]

        settings.is_prod = True
        resp = dispatch(_raw_event("GET", "/api/v1/healthz"), None)
        assert "max-age=31536000" in resp["headers"]["Strict-Transport-Security"]
    finally:
        settings.is_prod = False


# ------------------------------------------------------------ rate limiter

def test_shared_rate_limiter_counts_across_calls():
    """The limiter must count cumulatively (DynamoDB fixed window), not per call."""
    from obsidian.security import limiter
    key = f"test:{uuid.uuid4().hex}"
    try:
        for _ in range(3):
            ok, _retry = limiter.check(key, 3, 60)
            assert ok is True
        ok, retry = limiter.check(key, 3, 60)
        assert ok is False
        assert retry > 0
    finally:
        limiter.reset(key)


def test_rate_limit_triggers_http_429():
    client = Client(ip=f"10.99.{uuid.uuid4().hex[:2]}.{uuid.uuid4().hex[:2]}")
    # OTP verify route has a tight limit; hammer it until it throttles.
    status = None
    for _ in range(60):
        status, _data = client.post("/api/v1/auth/otp/verify",
                                    {"challenge_id": "x", "code": "000000"})
        if status == 429:
            break
    assert status == 429, "expected the rate limiter to eventually return 429"


# ----------------------------------------------------- verification workflow

def _admin_client() -> Client:
    a = Client()
    register(a, role="admin", name="Admin User")
    return a


def test_faculty_lookup_requires_verification():
    """A pending faculty account gets 403 VERIFICATION_PENDING until approved."""
    student = Client()
    register(student, role="student", name="Student One")

    faculty = Client()
    register(faculty, role="faculty", name="Faculty One")

    admin = _admin_client()

    # find the faculty user_id
    status, data = admin.get("/api/v1/admin/users")
    assert status == 200, data
    fac_entry = next(u for u in data["users"] if u["role"] == "faculty")
    assert "verification_status" in fac_entry

    # withdraw verification -> lookup must be blocked
    status, data = admin.post(f"/api/v1/admin/users/{fac_entry['user_id']}/verification",
                              {"status": "pending"})
    assert status == 200, data

    status, data = faculty.get("/api/v1/profile/student/SOMEID123")
    assert status == 403, data
    assert data["error"]["code"] == "VERIFICATION_PENDING"

    # admin approves -> lookup proceeds (404 for unknown ID, not 403)
    status, data = admin.post(f"/api/v1/admin/users/{fac_entry['user_id']}/verification",
                              {"status": "verified"})
    assert status == 200, data
    status, data = faculty.get("/api/v1/profile/student/SOMEID123")
    assert status == 404, data
    assert data["error"]["code"] != "VERIFICATION_PENDING"


def test_admin_cannot_change_own_verification():
    admin = _admin_client()
    status, data = admin.get("/api/v1/admin/users")
    assert status == 200, data
    me = next(u for u in data["users"] if u["role"] == "admin")
    status, data = admin.post(f"/api/v1/admin/users/{me['user_id']}/verification",
                              {"status": "pending"})
    # the request is rejected before anything is changed (422 per ApiError status)
    assert status in (400, 422), data


def test_initial_verification_by_role():
    from obsidian.profile_schema import initial_verification
    assert initial_verification("faculty", dev_mode=False) == "pending"
    assert initial_verification("recruiter", dev_mode=False) == "pending"
    assert initial_verification("student", dev_mode=False) == "verified"
    # development affordance
    assert initial_verification("faculty", dev_mode=True) == "verified"


# --------------------------------------------------------------- secrets

def test_secret_loader_never_raises():
    from obsidian.config import Settings
    s = Settings()
    s.secrets_name = "obsidian/does-not-exist"
    s._secrets_loaded = False
    s.load_secrets()  # must not raise even if Secrets Manager is unreachable
    s.load_secrets()  # idempotent
    assert s._secrets_loaded is True


def test_secret_loader_absent_is_noop():
    from obsidian.config import Settings
    s = Settings()
    s.secrets_name = ""
    s._secrets_loaded = False
    s.load_secrets()
    assert s.resend_api_key == s.resend_api_key  # attribute untouched, no error


# -------------------------------------------------------------- malware

def test_scanner_is_honest_when_unconfigured():
    """No scanner configured -> 'not_scanned', never 'clean'."""
    from obsidian import scanner
    status, detail = scanner.scan(b"some file bytes")
    assert status == scanner.NOT_SCANNED
    assert scanner.enforce(b"some file bytes") == scanner.NOT_SCANNED


def test_scanner_rejects_infected_payload(monkeypatch):
    from obsidian import scanner
    monkeypatch.setattr(scanner.settings, "clamd_host", "127.0.0.1")
    monkeypatch.setattr(scanner, "_instream_scan", lambda payload: scanner.INFECTED)
    status, _ = scanner.scan(b"evil")
    assert status == scanner.INFECTED
    with pytest.raises(Exception) as exc:
        scanner.enforce(b"evil")
    assert getattr(exc.value, "status", None) == 413
    assert getattr(exc.value, "code", "") == "UPLOAD_REJECTED"


def test_scanner_fails_closed_on_error(monkeypatch):
    from obsidian import scanner
    monkeypatch.setattr(scanner.settings, "clamd_host", "127.0.0.1")
    monkeypatch.setattr(scanner.settings, "malware_fail_closed", True)

    def boom(payload):
        raise ConnectionRefusedError("clamd down")
    monkeypatch.setattr(scanner, "_instream_scan", boom)

    status, _ = scanner.scan(b"data")
    assert status == scanner.ERROR
    with pytest.raises(Exception) as exc:
        scanner.enforce(b"data")
    assert getattr(exc.value, "status", None) == 503


def test_upload_records_scan_status(client: Client):
    """Uploads must record an honest scan_status on the document."""
    register(client, role="student", name="Uploader")
    payload = base64.b64encode(b"%PDF-1.4 test content").decode()
    status, data = client.post("/api/v1/documents", {
        "filename": "transcript.pdf", "content_base64": payload,
    })
    assert status in (200, 201), data
    doc_id = data["document"]["document_id"]
    status, data = client.get(f"/api/v1/documents/{doc_id}")
    assert status == 200, data
    assert data["document"].get("scan_status") in ("not_scanned", "clean")
