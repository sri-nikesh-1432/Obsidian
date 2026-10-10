"""Sharing tests: link lifecycle, expiry, revocation, tokens, restricted grants."""
from __future__ import annotations

import base64
import uuid

from conftest import Client, register

TXT = b"Shared notes for the placement cell.\n"


def _setup(owner: Client) -> str:
    register(owner)
    status, data = owner.post("/api/v1/documents", {
        "filename": "notes.txt",
        "content_base64": base64.b64encode(TXT).decode(),
        "visibility": "private",
    })
    assert status == 201, data
    return data["document"]["document_id"]


def _make_link(owner: Client, doc_id: str, **opts) -> tuple[int, dict]:
    body = {"mode": "link", "permission": "viewer", **opts}
    return owner.post(f"/api/v1/documents/{doc_id}/shares", body)


def test_link_share_access_and_metadata():
    owner = Client()
    doc_id = _setup(owner)
    status, data = _make_link(owner, doc_id, expires_in=3600)
    assert status == 201, data
    share = data["share"]
    assert share["url"].startswith("/s/")
    token = share["url"].split("/s/")[1]
    assert len(token) >= 40  # high entropy

    guest = Client()
    status, meta = guest.get(f"/api/v1/s/{token}")
    assert status == 200
    assert meta["document"]["filename"] == "notes.txt"
    assert meta["permission"] == "viewer"

    status, content = guest.get(f"/api/v1/s/{token}/content")
    assert status == 200
    assert base64.b64decode(content["content_base64"]) == TXT

    # owner sees the link as active with access count
    status, listing = owner.get(f"/api/v1/documents/{doc_id}/shares")
    assert listing["shares"][0]["status"] == "active"
    assert listing["shares"][0]["access_count"] >= 1

    # access was audited without exposing the raw token
    from obsidian import audit
    events, _ = audit.list_for_actor("anonymous", limit=50)
    shared_events = [e for e in events if e["event_type"] == "share_accessed"]
    assert shared_events
    blob = str(shared_events)
    assert token not in blob


def test_expired_link_fails():
    owner = Client()
    doc_id = _setup(owner)
    status, data = _make_link(owner, doc_id, expires_in=3600)
    token = data["share"]["url"].split("/s/")[1]
    share_id = data["share"]["share_id"]

    # force expiry directly in the store (server-side truth)
    from obsidian import aws
    from datetime import datetime, timedelta, timezone
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    aws.table("shares").update_item(
        Key={"pk": f"SHARE#{share_id}", "sk": "S"},
        UpdateExpression="SET expires_at = :e",
        ExpressionAttributeValues={":e": past})

    guest = Client()
    status, body = guest.get(f"/api/v1/s/{token}")
    assert status == 410 and body["error"]["code"] == "SHARE_EXPIRED"
    status, body = guest.get(f"/api/v1/s/{token}/content")
    assert status == 410


def test_revoked_link_fails_immediately():
    owner = Client()
    doc_id = _setup(owner)
    _, data = _make_link(owner, doc_id, expires_in=604800)
    token = data["share"]["url"].split("/s/")[1]
    share_id = data["share"]["share_id"]

    guest = Client()
    assert guest.get(f"/api/v1/s/{token}")[0] == 200

    status, _ = owner.delete(f"/api/v1/shares/{share_id}")
    assert status == 200

    status, body = guest.get(f"/api/v1/s/{token}")
    assert status in (404, 410)  # token index removed or marked revoked
    status, body = guest.get(f"/api/v1/s/{token}/content")
    assert status in (404, 410)


def test_invalid_token_and_tampering():
    owner = Client()
    _setup(owner)
    guest = Client()
    status, body = guest.get("/api/v1/s/not-a-real-token-value-1234567890")
    assert status == 404 and body["error"]["code"] == "SHARE_UNAVAILABLE"
    # mutated token from a real share must fail too
    status, data = _make_link(owner, _setup(owner), expires_in=3600)
    token = data["share"]["url"].split("/s/")[1]
    mutated = token[:-2] + ("AA" if token[-2:] != "AA" else "BB")
    assert guest.get(f"/api/v1/s/{mutated}")[0] == 404


def test_only_owner_can_revoke():
    owner = Client()
    doc_id = _setup(owner)
    _, data = _make_link(owner, doc_id)
    share_id = data["share"]["share_id"]

    other = Client()
    register(other)
    status, _ = other.delete(f"/api/v1/shares/{share_id}")
    assert status == 404  # not found for non-owner (no existence leak)


def test_editor_denied_for_non_text_documents():
    owner = Client()
    register(owner)
    status, up = owner.post("/api/v1/documents", {
        "filename": "cert.pdf",
        "content_base64": base64.b64encode(b"%PDF-1.4 fake").decode(),
    })
    doc_id = up["document"]["document_id"]
    status, body = _make_link(owner, doc_id, permission="editor")
    assert status == 422


def test_restricted_share_grants_only_that_user():
    owner = Client()
    doc_id = _setup(owner)
    recipient = Client()
    recipient_email = register(recipient, name="Recipient Student")

    status, data = owner.post(f"/api/v1/documents/{doc_id}/shares", {
        "mode": "restricted", "permission": "viewer", "grantee_email": recipient_email,
    })
    assert status == 201

    # recipient sees it in shared-with-me and can read content
    status, shared = recipient.get("/api/v1/documents/shared-with-me")
    assert status == 200 and len(shared["shares"]) == 1
    status, content = recipient.get(f"/api/v1/documents/{doc_id}/content")
    assert status == 200 and base64.b64decode(content["content_base64"]) == TXT

    # a third student has no access
    stranger = Client()
    register(stranger)
    assert stranger.get(f"/api/v1/documents/{doc_id}/content")[0] == 403


def test_deleted_document_kills_links():
    owner = Client()
    doc_id = _setup(owner)
    _, data = _make_link(owner, doc_id, expires_in=604800)
    token = data["share"]["url"].split("/s/")[1]
    owner.delete(f"/api/v1/documents/{doc_id}")
    guest = Client()
    status, body = guest.get(f"/api/v1/s/{token}")
    assert status in (404, 410)
