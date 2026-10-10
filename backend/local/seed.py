"""Demo seeder — creates realistic accounts THROUGH THE REAL API.

Nothing is written directly to the database: every record below passes the
same authentication, MFA, validation, encryption and consent paths a real
user would hit. Run with the local API server up:

    python backend/local/seed.py [http://127.0.0.1:8080]
"""
from __future__ import annotations

import base64
import json
import sys
import uuid
from urllib import error, request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080") + "/api/v1"
PASSWORD = "correct-horse-battery"


class Client:
    def __init__(self) -> None:
        self.cookie = ""

    def call(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = request.Request(BASE + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.cookie:
            req.add_header("Cookie", self.cookie)
        try:
            with request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read() or b"{}")
                sc = resp.headers.get("Set-Cookie", "")
                status = resp.status
        except error.HTTPError as e:
            payload = json.loads(e.read() or b"{}")
            sc = e.headers.get("Set-Cookie", "") if e.headers else ""
            return e.code, payload
        if "obsidian_session=" in sc:
            self.cookie = sc.split("obsidian_session=")[1].split(";")[0]
            self.cookie = f"obsidian_session={self.cookie}"
        return status, payload


def register(role: str, email: str, name: str) -> Client:
    c = Client()
    code, data = c.call("POST", "/auth/register", {
        "role": role, "email": email, "password": PASSWORD, "full_name": name,
    })
    if code not in (200, 201):
        print(f"  ! register failed for {email}: {data}")
        return c
    code, data = c.call("POST", "/auth/otp/verify", {
        "challenge_id": data["challenge_id"], "code": data["dev_otp"],
    })
    if code not in (200, 201):
        print(f"  ! otp verify failed for {email}: {data}")
    return c


def upload(c: Client, filename: str, content: bytes, **opts) -> str:
    code, data = c.call("POST", "/documents", {
        "filename": filename,
        "content_base64": base64.b64encode(content).decode(),
        "visibility": opts.get("visibility", "private"),
        "profile_visible": opts.get("profile_visible", False),
        "rag_eligible": opts.get("rag_eligible", True),
    })
    if code != 201:
        print(f"  ! upload failed {filename}: {data}")
        return ""
    return data["document"]["document_id"]


RESUME = """ARJUN MEHTA — Resume
CGPA: 9.1 / 10  · B.Tech Computer Science · State University · Graduating 2027

EDUCATION
  State University — B.Tech Computer Science (2023–2027)
  City Senior Secondary School — 94.2% (2022–2023)

INTERNSHIPS
  SWE Intern, Nimbus Cloud (May 2025 – Jul 2025)
    Built an encrypted document pipeline using AES-256-GCM and S3.
  Research Intern, University Security Lab (Jan 2025 – Apr 2025)
    Studied access-control models for student data platforms.

PROJECTS
  OBSIDIAN — secure student document vault (encryption, RBAC, audit)
  Vantage — lightweight network monitor in Go

SKILLS
  Python, TypeScript, AWS, Docker, PostgreSQL, cryptography
"""

TRANSCRIPT = """OFFICIAL TRANSCRIPT — ARJUN MEHTA
Student ID: see profile   · Program: B.Tech Computer Science

Semester 1: CGPA 8.9    Semester 2: CGPA 9.0
Semester 3: CGPA 9.2    Semester 4: CGPA 9.3
Cumulative CGPA: 9.1

Course highlights: Operating Systems 9.5, Computer Networks 9.0,
Database Systems 9.2, Information Security 9.6.
"""

CERT = """CERTIFICATE OF ACHIEVEMENT
This is to certify that ARJUN MEHTA has completed the
"Advanced Python Engineering" professional certification
with distinction. Issued June 2025.
"""


def main() -> None:
    print("Seeding OBSIDIAN demo data through the public API …")

    # ---------------- student ----------------
    student = register("student", "arjun@obsidian.dev", "Arjun Mehta")
    student.call("PATCH", "/profile", {
        "institution": "State University",
        "course": "B.Tech Computer Science",
        "education_level": "Bachelor's",
        "department": "Computer Science",
        "year": "3rd year",
        "graduation_year": "2027",
        "cgpa": "9.1",
        "bio": "Security-minded computer science student focused on applied cryptography and privacy-preserving systems.",
        "skills": ["Python", "TypeScript", "AWS", "Cryptography", "Docker"],
        "profile_visibility": "public",
        "show_phone": False,
    })
    student.call("POST", "/intelligence/consent", {"consent": True})

    upload(student, "Resume_Arjun_Mehta.pdf",
           ("%PDF-1.4\n" + RESUME).encode(),
           visibility="public", profile_visible=True, rag_eligible=True)
    upload(student, "Transcript_Sem4.txt", TRANSCRIPT.encode(),
           visibility="private", profile_visible=False, rag_eligible=True)
    upload(student, "Python_Certification.txt", CERT.encode(),
           visibility="public", profile_visible=True, rag_eligible=True)

    # an active share link + a revoked one
    code, docs = student.call("GET", "/documents")
    doc_ids = [d["document_id"] for d in docs.get("documents", [])]
    if doc_ids:
        student.call("POST", f"/documents/{doc_ids[0]}/shares",
                     {"mode": "link", "permission": "viewer", "expires_in": 604800})
        code, tmp = student.call("POST", f"/documents/{doc_ids[-1]}/shares",
                                 {"mode": "link", "permission": "viewer", "expires_in": 3600})
        if code == 201:
            student.call("DELETE", f"/shares/{tmp['share']['share_id']}")

    # ---------------- second student (for lookup demos) ----------------
    student2 = register("student", "meera@obsidian.dev", "Meera Iyer")
    student2.call("PATCH", "/profile", {
        "institution": "State University",
        "course": "B.Tech Electronics",
        "education_level": "Bachelor's",
        "department": "Electronics",
        "year": "3rd year",
        "graduation_year": "2027",
        "cgpa": "8.4",
        "bio": "Electronics student exploring embedded security.",
        "skills": ["Embedded C", "PCB design", "Python"],
        "profile_visibility": "public",
    })
    upload(student2, "Meera_CV.pdf", ("%PDF-1.4\nEmbedded security CV").encode(),
           visibility="public", profile_visible=True, rag_eligible=True)

    # ---------------- faculty / recruiter / admin ----------------
    faculty = register("faculty", "prof.rao@obsidian.dev", "Prof. Rao")
    recruiter = register("recruiter", "talent@northwind.io", "Dana Cole")
    admin = register("admin", "admin@obsidian.dev", "System Admin")

    # ---------------- report ----------------
    code, me = student.call("GET", "/auth/me")
    sid = me.get("profile", {}).get("student_id", "?")
    print("\n  Demo accounts (password for all: correct-horse-battery)")
    print("  " + "-" * 64)
    print(f"  Student   arjun@obsidian.dev     student ID: {sid}")
    print("  Student   meera@obsidian.dev")
    print("  Faculty   prof.rao@obsidian.dev")
    print("  Recruiter talent@northwind.io")
    print("  Admin     admin@obsidian.dev")
    print("  " + "-" * 64)
    print("  Sign-in needs an email OTP — in dev mode it is shown in the UI.")


if __name__ == "__main__":
    main()
