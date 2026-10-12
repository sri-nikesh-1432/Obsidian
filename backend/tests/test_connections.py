"""Tests for the student connection graph and folder/multi-file uploads."""
from __future__ import annotations

import base64
import uuid

from conftest import Client, register

PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"
TXT_BYTES = b"Shared study notes.\nCGPA: 9.1\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 32


def _student_id(client: Client) -> str:
    status, data = client.get("/api/v1/profile")
    assert status == 200, data
    return data["profile"]["student_id"]


def _two_students() -> tuple[Client, str, Client, str]:
    a = Client()
    register(a, email=f"a-{uuid.uuid4().hex[:8]}@obsidian.test", name="Alice")
    b = Client()
    register(b, email=f"b-{uuid.uuid4().hex[:8]}@obsidian.test", name="Bob")
    return a, _student_id(a), b, _student_id(b)


def _upload(client: Client, filename: str, content: bytes, **opts) -> tuple[int, dict]:
    return client.post("/api/v1/documents", {
        "filename": filename,
        "content_base64": base64.b64encode(content).decode(),
        "visibility": opts.get("visibility", "private"),
        "profile_visible": opts.get("profile_visible", False),
        "rag_eligible": False,
    })


# ------------------------------------------------------------- connection flow

def test_connection_request_accept_and_lists(client: Client):
    a, a_sid, b, b_sid = _two_students()

    # exact-code search
    status, data = a.get(f"/api/v1/connections/search?student_id={b_sid}")
    assert status == 200 and data["relationship"] == "none"
    assert data["student"]["full_name"] == "Bob"

    # unknown code -> 404 (no enumeration)
    status, _ = a.get("/api/v1/connections/search?student_id=OBS-0000-000000")
    assert status == 404
    # own code -> 422 (invalid input)
    status, _ = a.get(f"/api/v1/connections/search?student_id={a_sid}")
    assert status == 422

    # send request
    status, data = a.post("/api/v1/connections/requests", {"student_id": b_sid})
    assert status == 200 and data["relationship"] == "requested"

    # B sees it incoming
    status, listing = b.get("/api/v1/connections")
    assert status == 200
    assert listing["counts"]["pending_incoming"] == 1
    assert listing["pending_incoming"][0]["student_id"] == a_sid

    # B accepts -> mutual
    status, data = b.post(f"/api/v1/connections/requests/{a_sid}/accept")
    assert status == 200 and data["relationship"] == "connected"

    _, la = a.get("/api/v1/connections")
    _, lb = b.get("/api/v1/connections")
    assert la["counts"]["following"] == 1 and la["counts"]["followers"] == 1
    assert lb["counts"]["following"] == 1 and lb["counts"]["followers"] == 1
    assert la["following"][0]["student_id"] == b_sid

    # remove
    status, data = a.delete(f"/api/v1/connections/{b_sid}")
    assert status == 200 and data["relationship"] == "none"
    _, la = a.get("/api/v1/connections")
    assert la["counts"]["following"] == 0 and la["counts"]["followers"] == 0


def test_mutual_request_auto_accepts(client: Client):
    a, a_sid, b, b_sid = _two_students()
    a.post("/api/v1/connections/requests", {"student_id": b_sid})
    # B requests back before accepting -> auto-connect
    status, data = b.post("/api/v1/connections/requests", {"student_id": a_sid})
    assert status == 200 and data["relationship"] == "connected"
    _, la = a.get("/api/v1/connections")
    assert la["counts"]["following"] == 1


def test_decline_request(client: Client):
    a, a_sid, b, b_sid = _two_students()
    a.post("/api/v1/connections/requests", {"student_id": b_sid})
    status, data = b.post(f"/api/v1/connections/requests/{a_sid}/decline")
    assert status == 200 and data["relationship"] == "none"
    _, listing = b.get("/api/v1/connections")
    assert listing["counts"]["pending_incoming"] == 0
    # A can request again
    status, data = a.post("/api/v1/connections/requests", {"student_id": b_sid})
    assert status == 200 and data["relationship"] == "requested"


# ------------------------------------------------------------- privacy model

def test_connection_sees_only_profile_visible_documents(client: Client):
    a, a_sid, b, b_sid = _two_students()

    _, pub = _upload(b, "public_cv.pdf", PDF_BYTES, visibility="public", profile_visible=True)
    pub_id = pub["document"]["document_id"]
    _, priv = _upload(b, "private_diary.txt", TXT_BYTES, visibility="private")
    priv_id = priv["document"]["document_id"]

    # connect
    a.post("/api/v1/connections/requests", {"student_id": b_sid})
    b.post(f"/api/v1/connections/requests/{a_sid}/accept")

    status, data = a.get(f"/api/v1/connections/{b_sid}")
    assert status == 200 and data["relationship"] == "connected"
    ids = {d["document_id"] for d in data["documents"]}
    assert pub_id in ids and priv_id not in ids

    # profile-visible doc is readable
    status, data = a.get(f"/api/v1/connections/{b_sid}/documents/{pub_id}/content")
    assert status == 200
    assert base64.b64decode(data["content_base64"]) == PDF_BYTES

    # private doc is NOT readable through the connection route
    status, _ = a.get(f"/api/v1/connections/{b_sid}/documents/{priv_id}/content")
    assert status == 404


def test_explicit_share_to_connection_by_student_code(client: Client):
    a, a_sid, b, b_sid = _two_students()
    _, doc = _upload(b, "private_resume.txt", TXT_BYTES, visibility="private")
    doc_id = doc["document"]["document_id"]

    # B explicitly shares the private file with A using A's student code
    status, data = b.post(f"/api/v1/documents/{doc_id}/shares", {
        "mode": "restricted", "permission": "viewer", "grantee_student_id": a_sid,
    })
    assert status == 201, data

    # A now has an active grant (private doc reachable via the standard route)
    status, content = a.get(f"/api/v1/documents/{doc_id}/content")
    assert status == 200
    assert base64.b64decode(content["content_base64"]) == TXT_BYTES
    status, listing = a.get("/api/v1/documents/shared-with-me")
    assert status == 200 and any(s["document_id"] == doc_id for s in listing["shares"])


def test_connection_routes_are_student_only(client: Client):
    fac = Client()
    register(fac, role="faculty")
    status, _ = fac.get("/api/v1/connections")
    assert status == 403


# ------------------------------------------------------------- folder uploads

def test_batch_folder_upload_and_listing(client: Client):
    register(client)
    files = [
        {"filename": "syllabus.pdf", "folder": "Semester 2/Notes",
         "content_base64": base64.b64encode(PDF_BYTES).decode()},
        {"filename": "scan.png", "folder": "Semester 2/Notes",
         "content_base64": base64.b64encode(PNG_BYTES).decode()},
    ]
    status, data = client.post("/api/v1/documents/batch", {
        "files": files, "visibility": "private",
    })
    assert status == 201, data
    assert data["count"] == 2 and data["failed"] == 0
    for d in data["uploaded"]:
        assert d["folder"] == "Semester 2/Notes"

    # folder surfacing + filtering
    status, listing = client.get("/api/v1/documents")
    assert status == 200
    assert "Semester 2/Notes" in listing["folders"]

    status, listing = client.get("/api/v1/documents?folder=Semester%202/Notes")
    assert listing["total"] == 2

    # a bad file in the batch is reported, the rest succeed
    status, data = client.post("/api/v1/documents/batch", {
        "files": [
            {"filename": "good.txt", "content_base64": base64.b64encode(TXT_BYTES).decode()},
            {"filename": "bad.exe", "content_base64": base64.b64encode(b"MZ").decode()},
        ],
    })
    assert status == 201 and data["count"] == 1 and data["failed"] == 1
    assert data["errors"][0]["filename"] == "bad.exe"


def test_folder_path_traversal_is_sanitized(client: Client):
    register(client)
    status, data = client.post("/api/v1/documents", {
        "filename": "notes.txt",
        "content_base64": base64.b64encode(TXT_BYTES).decode(),
        "folder": "../../../etc/secret",
    })
    assert status == 201
    assert ".." not in data["document"]["folder"]


def test_widened_types_accept_images_but_reject_executables(client: Client):
    register(client)
    status, data = _upload(client, "photo.png", PNG_BYTES)
    assert status == 201, data
    status, data = _upload(client, "photo.svg", b"<svg></svg>")
    assert status == 400  # svg remains disallowed (script-capable)
    status, data = _upload(client, "script.exe", b"MZ\x90\x00")
    assert status == 400
