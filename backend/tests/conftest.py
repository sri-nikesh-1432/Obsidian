"""Shared test fixtures.

Tests run the real dispatch() pipeline against an in-process moto AWS.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("OBSIDIAN_LOCAL_AWS", "true")
os.environ.setdefault("OBSIDIAN_DEV_MODE", "true")
# Tests provision admin accounts generically, so allow any admin address here.
os.environ.setdefault("OBSIDIAN_ADMIN_EMAILS", "*")
os.environ["OBSIDIAN_TABLE_PREFIX"] = "obsidian-test"

from obsidian import aws            # noqa: E402
from obsidian.gateway import dispatch  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _aws():
    aws.ensure_resources()
    yield
    aws.stop_local_mock()


class Client:
    """Minimal HTTP client that speaks API Gateway events to dispatch()."""

    def __init__(self, ip: str | None = None) -> None:
        import random
        self.cookie = ""
        # unique source IP per simulated client (rate limits are per-IP)
        self.ip = ip or f"10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"

    def request(self, method: str, path: str, body: dict | None = None,
                *, raw: bytes | None = None, headers: dict | None = None,
                ip: str | None = None):
        ip = ip or self.ip
        hdrs = {"content-type": "application/json"}
        if self.cookie:
            hdrs["cookie"] = self.cookie
        if headers:
            hdrs.update(headers)
        payload = b""
        if raw is not None:
            payload = raw
        elif body is not None:
            payload = json.dumps(body).encode()
        # split any query string off the path (real clients send it separately)
        query: dict = {}
        if "?" in path:
            path, _, qs = path.partition("?")
            for pair in qs.split("&"):
                if not pair:
                    continue
                k, _, v = pair.partition("=")
                from urllib.parse import unquote
                query[unquote(k)] = unquote(v)
        event = {
            "version": "2.0",
            "rawPath": path,
            "headers": hdrs,
            "queryStringParameters": query or None,
            "requestContext": {"requestId": uuid.uuid4().hex,
                               "http": {"method": method, "path": path, "sourceIp": ip}},
            "body": base64.b64encode(payload).decode() if payload else "",
            "isBase64Encoded": True,
        }
        resp = dispatch(event, None)
        # capture cookie
        set_cookie = resp.get("headers", {}).get("set-cookie")
        if set_cookie:
            values = set_cookie if isinstance(set_cookie, list) else [set_cookie]
            for v in values:
                if v.startswith("obsidian_session="):
                    value = v.split(";", 1)[0].split("=", 1)[1]
                    self.cookie = f"obsidian_session={value}" if value else ""
        data = json.loads(resp["body"]) if resp.get("body") else {}
        return resp["statusCode"], data

    def get(self, path: str, **kw):
        return self.request("GET", path, **kw)

    def post(self, path: str, body: dict | None = None, **kw):
        return self.request("POST", path, body=body, **kw)

    def patch(self, path: str, body: dict | None = None, **kw):
        return self.request("PATCH", path, body=body, **kw)

    def put(self, path: str, body: dict | None = None, **kw):
        return self.request("PUT", path, body=body, **kw)

    def delete(self, path: str, **kw):
        return self.request("DELETE", path, **kw)


@pytest.fixture
def client() -> Client:
    return Client()


def register(client: Client, role: str = "student", email: str | None = None,
             password: str = "correct-horse-battery", name: str = "Test Student") -> str:
    """Register + verify OTP; returns the session cookie client."""
    email = email or f"{role}-{uuid.uuid4().hex[:8]}@obsidian.test"
    status, data = client.post("/api/v1/auth/register", {
        "role": role, "email": email, "password": password, "full_name": name,
    })
    assert status in (200, 201), data
    otp = data.get("dev_otp")
    assert otp, "dev_otp missing — dev mode required for tests"
    status, data = client.post("/api/v1/auth/otp/verify", {
        "challenge_id": data["challenge_id"], "code": otp,
    })
    assert status == 201, data
    return email
