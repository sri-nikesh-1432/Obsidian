"""Authentication tests: registration, OTP MFA, login, sessions."""
from __future__ import annotations

import uuid

from conftest import Client, register


def test_register_and_verify(client: Client):
    email = f"s-{uuid.uuid4().hex[:8]}@obsidian.test"
    status, data = client.post("/api/v1/auth/register", {
        "role": "student", "email": email, "password": "correct-horse-battery",
        "full_name": "Ada Student",
    })
    assert status == 200
    assert "dev_otp" in data and "challenge_id" in data

    # wrong OTP fails
    status, data2 = client.post("/api/v1/auth/otp/verify", {
        "challenge_id": data["challenge_id"], "code": "000000" if data["dev_otp"] != "000000" else "111111",
    })
    assert status == 400

    # correct OTP completes registration and sets a session cookie
    status, data3 = client.post("/api/v1/auth/otp/verify", {
        "challenge_id": data["challenge_id"], "code": data["dev_otp"],
    })
    assert status == 201
    assert data3["role"] == "student"
    assert data3["authenticated"] is not False

    status, me = client.get("/api/v1/auth/me")
    assert status == 200 and me["email"] == email
    assert me["profile"]["student_id"].startswith("OBS-")


def test_otp_is_single_use(client: Client):
    email = f"s-{uuid.uuid4().hex[:8]}@obsidian.test"
    _, data = client.post("/api/v1/auth/register", {
        "role": "student", "email": email, "password": "correct-horse-battery",
    })
    code = data["dev_otp"]
    status, _ = client.post("/api/v1/auth/otp/verify",
                            {"challenge_id": data["challenge_id"], "code": code})
    assert status == 201
    status, again = client.post("/api/v1/auth/otp/verify",
                                {"challenge_id": data["challenge_id"], "code": code})
    assert status == 400  # replay rejected


def test_wrong_password_is_generic(client: Client):
    email = f"s-{uuid.uuid4().hex[:8]}@obsidian.test"
    fresh = Client()
    register(fresh, email=email)
    login_client = Client()
    status, data = login_client.post("/api/v1/auth/login",
                                     {"email": email, "password": "wrong-password-x"})
    assert status == 401
    assert data["error"]["code"] == "INVALID_CREDENTIALS"
    # unknown account returns the identical error (no enumeration)
    status2, data2 = login_client.post("/api/v1/auth/login",
                                       {"email": f"ghost-{uuid.uuid4().hex[:6]}@obsidian.test",
                                        "password": "wrong-password-x"})
    assert status2 == 401 and data2["error"]["code"] == data["error"]["code"]


def test_login_requires_otp(client: Client):
    email = f"s-{uuid.uuid4().hex[:8]}@obsidian.test"
    fresh = Client()
    register(fresh, email=email)
    fresh.post("/api/v1/auth/logout")

    status, data = client.post("/api/v1/auth/login",
                               {"email": email, "password": "correct-horse-battery"})
    assert status == 200 and "challenge_id" in data
    status, session_body = client.get("/api/v1/auth/me")
    assert session_body.get("authenticated") is False  # OTP not yet completed

    status, verified = client.post("/api/v1/auth/otp/verify", {
        "challenge_id": data["challenge_id"], "code": data["dev_otp"]})
    assert status == 200
    status, me = client.get("/api/v1/auth/me")
    assert me["email"] == email


def test_logout_invalidates_session(client: Client):
    email = f"s-{uuid.uuid4().hex[:8]}@obsidian.test"
    register(client, email=email)
    status, _ = client.get("/api/v1/auth/me")
    assert status == 200
    client.post("/api/v1/auth/logout")
    status, data = client.get("/api/v1/documents")
    assert status == 401


def test_duplicate_registration_rejected(client: Client):
    email = f"s-{uuid.uuid4().hex[:8]}@obsidian.test"
    register(client, email=email)
    client.post("/api/v1/auth/logout")
    status, data = client.post("/api/v1/auth/register", {
        "role": "student", "email": email, "password": "correct-horse-battery"})
    assert status == 409


def test_role_comes_from_server_not_client(client: Client):
    """A client cannot claim a role it does not have."""
    email = f"s-{uuid.uuid4().hex[:8]}@obsidian.test"
    register(client, email=email)
    # admin endpoints must reject a student even with forged params
    status, data = client.get("/api/v1/admin/analytics")
    assert status == 403
    status, data = client.patch("/api/v1/profile", {"role": "admin"})
    assert status in (200, 422)  # profile update never elevates role
    _, me = client.get("/api/v1/auth/me")
    assert me["role"] == "student"


def test_rate_limits_block_brute_force():
    """OTP request endpoint is rate-limited per IP."""
    fixed_ip = "172.16.9.9"
    hammer = Client(ip=fixed_ip)
    email = f"victim-{uuid.uuid4().hex[:6]}@obsidian.test"
    register(Client(ip=fixed_ip), email=email)

    statuses = []
    for _ in range(8):
        status, _ = hammer.post("/api/v1/auth/otp/request",
                                {"email": email, "purpose": "login"})
        statuses.append(status)
    assert 429 in statuses, f"expected rate limiting, got {statuses}"
    last_status, data = hammer.post("/api/v1/auth/otp/request",
                                    {"email": email, "purpose": "login"})
    assert last_status == 429
    assert data["error"]["code"] == "RATE_LIMITED"
