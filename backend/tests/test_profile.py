"""Profile + faculty/recruiter lookup tests (no global directory)."""
from __future__ import annotations

import base64
import uuid

from conftest import Client, register


def _make_student() -> tuple[Client, str]:
    c = Client()
    email = register(c, name="Lookup Target")
    status, data = c.patch("/api/v1/profile", {
        "institution": "State University",
        "course": "B.Tech Computer Science",
        "cgpa": "8.7",
        "skills": ["Python", "Security"],
        "bio": "Security-minded student.",
    })
    assert status == 200, data
    sid = c.get("/api/v1/auth/me")[1]["profile"]["student_id"]
    return c, sid


def test_faculty_lookup_requires_exact_student_id():
    _, sid = _make_student()
    fac = Client()
    register(fac, role="faculty")

    status, data = fac.get(f"/api/v1/profile/student/{sid}")
    assert status == 200
    assert data["student"]["institution"] == "State University"
    assert data["student"]["cgpa"] == "8.7"

    # wrong id -> generic 404 (no existence leak)
    status, body = fac.get("/api/v1/profile/student/OBS-XXXX-XXXXXX")
    assert status == 404
    assert body["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_no_browsing_students():
    """Students cannot look up other students; there is no directory endpoint."""
    a = Client()
    register(a)
    _, sid = _make_student()
    status, body = a.get(f"/api/v1/profile/student/{sid}")
    assert status == 403  # role policy blocks it

    # a list-style endpoint does not exist at all
    status, body = a.get("/api/v1/profile/students")
    assert status == 404
    fac = Client()
    register(fac, role="faculty")
    assert fac.get("/api/v1/profile/students")[0] == 404


def test_private_profile_is_not_revealed():
    student, sid = _make_student()
    student.patch("/api/v1/profile", {"profile_visibility": "private"})
    fac = Client()
    register(fac, role="faculty")
    status, body = fac.get(f"/api/v1/profile/student/{sid}")
    assert status == 404  # identical to a nonexistent ID


def test_recruiter_sees_only_profile_visible_documents():
    student, sid = _make_student()
    student.post("/api/v1/documents", {
        "filename": "public_cert.pdf",
        "content_base64": base64.b64encode(b"%PDF-1.4 public").decode(),
        "visibility": "public", "profile_visible": True,
    })
    student.post("/api/v1/documents", {
        "filename": "private_grades.pdf",
        "content_base64": base64.b64encode(b"%PDF-1.4 secret").decode(),
        "visibility": "private", "profile_visible": False,
    })

    rec = Client()
    register(rec, role="recruiter")
    status, data = rec.get(f"/api/v1/profile/student/{sid}")
    assert status == 200
    names = [d["filename"] for d in data["documents"]]
    assert "public_cert.pdf" in names
    assert "private_grades.pdf" not in names

    # cannot fetch the private document through the profile content route
    docs = student.get("/api/v1/documents")[1]["documents"]
    private = next(d for d in docs if d["filename"] == "private_grades.pdf")
    status, body = rec.get(
        f"/api/v1/profile/student/{sid}/documents/{private['document_id']}/content")
    assert status == 404

    # profile-visible document is readable
    public = next(d for d in docs if d["filename"] == "public_cert.pdf")
    status, content = rec.get(
        f"/api/v1/profile/student/{sid}/documents/{public['document_id']}/content")
    assert status == 200
    assert base64.b64decode(content["content_base64"]).startswith(b"%PDF-1.4 public")


def test_profile_updates_are_audited_and_scoped():
    c = Client()
    register(c)
    status, data = c.patch("/api/v1/profile", {"institution": "Tech Univ"})
    assert status == 200 and data["profile"]["institution"] == "Tech Univ"

    from obsidian import audit
    user_id = c.get("/api/v1/auth/me")[1]["user_id"]
    events, _ = audit.list_for_actor(user_id, limit=50)
    assert any(e["event_type"] == "profile_updated" for e in events)

    # invalid values rejected
    status, body = c.patch("/api/v1/profile", {"cgpa": "42"})
    assert status == 422
    status, body = c.patch("/api/v1/profile", {"profile_visibility": "everyone"})
    assert status == 422
