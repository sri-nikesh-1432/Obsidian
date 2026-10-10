"""Admin analytics + RBAC tests."""
from __future__ import annotations

import uuid

from conftest import Client, register


def _admin() -> Client:
    a = Client()
    register(a, role="admin", name="Admin User")
    return a


def test_admin_endpoints_require_admin_role():
    s = Client()
    register(s)
    for path in ("/api/v1/admin/analytics", "/api/v1/admin/users",
                 "/api/v1/admin/security-events", "/api/v1/admin/shares",
                 "/api/v1/admin/activity", "/api/v1/admin/rag"):
        status, _ = s.get(path)
        assert status == 403, path
    # unauthenticated
    anon = Client()
    assert anon.get("/api/v1/admin/analytics")[0] == 401


def test_admin_analytics_aggregates():
    admin = _admin()
    student = Client()
    register(student)
    student.post("/api/v1/documents", {
        "filename": "x.pdf",
        "content_base64": "JVBERi0xLjQK",
        "visibility": "private",
    })

    status, data = admin.get("/api/v1/admin/analytics")
    assert status == 200
    assert data["users"]["total"] >= 2
    assert data["users"]["by_role"].get("student", 0) >= 1
    assert data["documents"]["total"] >= 1
    assert data["documents"]["storage_bytes"] > 0
    assert "security" in data and "health" in data
    # no plaintext content or secrets anywhere in admin payloads
    blob = str(data)
    assert "password_hash" not in blob and "wrapped_dek" not in blob


def test_security_events_capture_failures():
    admin = _admin()
    victim = Client()
    email = register(victim)
    victim.post("/api/v1/auth/logout")

    # failed login
    anon = Client()
    anon.post("/api/v1/auth/login", {"email": email, "password": "wrong-password-1"})
    # failed OTP attempt
    status, login = anon.post("/api/v1/auth/login",
                              {"email": email, "password": "correct-horse-battery"})
    anon.post("/api/v1/auth/otp/verify",
              {"challenge_id": login["challenge_id"], "code": "999999"})

    status, data = admin.get("/api/v1/admin/security-events")
    assert status == 200
    types = {e["event_type"] for e in data["events"]}
    assert "login_failure" in types
    assert "otp_failure" in types
    blob = str(data)
    assert "correct-horse-battery" not in blob  # no passwords in logs


def test_admin_can_list_users_but_not_documents():
    admin = _admin()
    status, data = admin.get("/api/v1/admin/users")
    assert status == 200 and len(data["users"]) >= 2
    assert all("password_hash" not in u for u in data["users"])
    # there is deliberately no admin endpoint that returns document contents
    anon = Client()
    assert anon.get("/api/v1/admin/documents")[0] == 404
