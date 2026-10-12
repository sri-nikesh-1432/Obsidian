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


def test_admin_registration_is_allowlisted(monkeypatch):
    """Only allowlisted addresses may register the admin role."""
    from obsidian.config import settings
    allowed = f"owner-{uuid.uuid4().hex[:8]}@obsidian.test"
    monkeypatch.setattr(settings, "admin_emails", allowed)

    intruder = Client()
    status, _ = intruder.post("/api/v1/auth/register", {
        "role": "admin", "email": f"intruder-{uuid.uuid4().hex[:8]}@obsidian.test",
        "password": "correct-horse-battery", "full_name": "Intruder",
    })
    assert status == 403

    owner = Client()
    register(owner, role="admin", email=allowed, name="Owner")
    status, me = owner.get("/api/v1/auth/me")
    assert status == 200
    assert me["role"] == "admin"
    # admins never go through the end-user onboarding wizard
    assert me["onboarding_complete"] is True


def test_admin_insights_and_intelligence():
    admin = _admin()
    student = Client()
    register(student)

    status, data = admin.get("/api/v1/admin/insights")
    assert status == 200, data
    for key in ("users", "sessions", "documents", "shares", "groups", "payments",
                "series", "security", "health"):
        assert key in data, key
    assert len(data["series"]) == 14
    assert "revenue_inr" in data["payments"]

    status, ans = admin.post("/api/v1/admin/intelligence",
                             {"question": "What is our revenue and payments?"})
    assert status == 200, ans
    assert ans["model_mode"] == "grounded-analytics"
    assert "metrics" in ans and "answer" in ans
    assert "payment" in ans["answer"].lower() or "revenue" in ans["answer"].lower()

    # a non-admin can never reach the assistant
    other = Client()
    register(other)
    assert other.post("/api/v1/admin/intelligence", {"question": "hi"})[0] == 403
    assert other.post("/api/v1/admin/intelligence", {"question": ""})[0] == 403


def test_admin_intelligence_requires_question():
    admin = _admin()
    status, _ = admin.post("/api/v1/admin/intelligence", {"question": "  "})
    assert status in (400, 422)
