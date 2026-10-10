"""Document vault tests: encryption at rest, validation, integrity, authz."""
from __future__ import annotations

import base64
import uuid

from conftest import Client, register

PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"
TXT_BYTES = b"My internship certificate notes.\nCGPA: 8.9\n"


def _upload(client: Client, filename: str, content: bytes, **opts) -> tuple[int, dict]:
    body = {
        "filename": filename,
        "content_base64": base64.b64encode(content).decode(),
        "visibility": opts.get("visibility", "private"),
        "profile_visible": opts.get("profile_visible", False),
        "rag_eligible": opts.get("rag_eligible", False),
    }
    return client.post("/api/v1/documents", body)


def test_upload_encrypts_and_roundtrips(client: Client):
    register(client)
    status, data = _upload(client, "Internship_Certificate.pdf", PDF_BYTES)
    assert status == 201, data
    doc = data["document"]
    assert doc["encryption"] == "AES-256-GCM" and doc["encrypted_at_rest"] is True

    # ciphertext at rest must NOT contain the plaintext
    from obsidian import aws
    meta = aws.table("documents").get_item(
        Key={"pk": f"DOC#{doc['document_id']}", "sk": "META"})["Item"]
    obj = aws.get_client("s3").get_object(
        Bucket=aws.settings.document_bucket, Key=meta["storage_key"])
    ciphertext = obj["Body"].read()
    assert PDF_BYTES not in ciphertext
    assert b"%PDF" not in ciphertext
    assert len(ciphertext) >= len(PDF_BYTES)  # GCM overhead, no truncation

    # download returns the exact original bytes after decryption
    status, data = client.get(f"/api/v1/documents/{doc['document_id']}/content")
    assert status == 200
    assert base64.b64decode(data["content_base64"]) == PDF_BYTES
    assert data["filename"] == "Internship_Certificate.pdf"


def test_integrity_tamper_detected(client: Client):
    register(client)
    _, data = _upload(client, "notes.txt", TXT_BYTES)
    doc_id = data["document"]["document_id"]

    from obsidian import aws
    meta = aws.table("documents").get_item(Key={"pk": f"DOC#{doc_id}", "sk": "META"})["Item"]
    s3 = aws.get_client("s3")
    obj = s3.get_object(Bucket=aws.settings.document_bucket, Key=meta["storage_key"])
    ciphertext = bytearray(obj["Body"].read())
    ciphertext[0] ^= 0xFF  # flip a bit
    s3.put_object(Bucket=aws.settings.document_bucket, Key=meta["storage_key"],
                  Body=bytes(ciphertext))

    status, data = client.get(f"/api/v1/documents/{doc_id}/content")
    assert status == 500 or data.get("error", {}).get("code") == "ENCRYPTION_ERROR"
    assert "Traceback" not in str(data)


def test_validation_rejects_dangerous_uploads(client: Client):
    register(client)
    # executable extension
    status, data = _upload(client, "malware.exe", b"MZ\x90\x00")
    assert status == 400 and data["error"]["code"] == "UPLOAD_REJECTED"
    # path traversal in filename is sanitized, then must still pass rules
    status, data = _upload(client, "../../etc/passwd.txt", b"hello")
    assert status == 201
    assert "/" not in data["document"]["filename"] and ".." not in data["document"]["filename"]
    # MIME spoof: .pdf with shell content
    status, data = _upload(client, "fake.pdf", b"#!/bin/sh\nrm -rf /\n")
    assert status == 400
    # oversized file
    big = b"A" * (9 * 1024 * 1024)
    status, data = _upload(client, "big.txt", big)
    assert status == 400


def test_private_document_is_private_between_students(client: Client):
    register(client)
    _, data = _upload(client, "private_resume.txt", TXT_BYTES, visibility="private")
    doc_id = data["document"]["document_id"]

    other = Client()
    register(other, name="Other Student")
    status, body = other.get(f"/api/v1/documents/{doc_id}")
    assert status == 403
    status, body = other.get(f"/api/v1/documents/{doc_id}/content")
    assert status == 403
    # and it never appears in the other student's listing
    status, listing = other.get("/api/v1/documents")
    assert status == 200 and listing["documents"] == []


def test_rename_delete_and_activity(client: Client):
    register(client)
    _, data = _upload(client, "old_name.txt", TXT_BYTES)
    doc_id = data["document"]["document_id"]

    status, data = client.patch(f"/api/v1/documents/{doc_id}", {"filename": "new_name.txt"})
    assert status == 200 and data["document"]["filename"] == "new_name.txt"

    status, data = client.get(f"/api/v1/documents/{doc_id}/activity")
    assert status == 200
    types = {e["event_type"] for e in data["events"]}
    assert "document_uploaded" in types and "document_renamed" in types

    status, _ = client.delete(f"/api/v1/documents/{doc_id}")
    assert status == 200
    status, _ = client.get(f"/api/v1/documents/{doc_id}/content")
    assert status == 404

    # object removed from storage
    from obsidian import aws
    from botocore.exceptions import ClientError
    meta = aws.table("documents").get_item(Key={"pk": f"DOC#{doc_id}", "sk": "META"})["Item"]
    try:
        aws.get_client("s3").get_object(
            Bucket=aws.settings.document_bucket, Key=meta["storage_key"])
        assert False, "object should be deleted"
    except ClientError:
        pass


def test_role_boundaries_on_document_api(client: Client):
    """Faculty cannot upload or list; recruiters cannot browse a vault."""
    fac = Client()
    register(fac, role="faculty")
    status, _ = fac.get("/api/v1/documents")
    assert status == 403
    status, _ = _upload(fac, "x.txt", b"hello")
    assert status == 403

    rec = Client()
    register(rec, role="recruiter")
    status, _ = rec.get("/api/v1/documents")
    assert status == 403
