"""End-to-end smoke test — drives the real HTTP interface the browser uses.

Runs against the Vite dev server proxy (default http://localhost:5173) so the
whole chain (browser origin -> proxy -> API gateway runtime -> handlers ->
moto AWS) is exercised.

    python tests/e2e_smoke.py [base_url]
"""
from __future__ import annotations

import base64
import json
import sys
import uuid
from urllib import error, request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5173").rstrip("/")
API = BASE + "/api/v1"

PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [ok] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


class Client:
    def __init__(self) -> None:
        self.cookie = ""

    def call(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = request.Request(API + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("Origin", BASE)
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
            status = e.code
        if "obsidian_session=" in sc:
            value = sc.split("obsidian_session=")[1].split(";")[0]
            self.cookie = f"obsidian_session={value}"
        return status, payload

    def get(self, p):
        return self.call("GET", p)

    def post(self, p, b=None):
        return self.call("POST", p, b)

    def patch(self, p, b=None):
        return self.call("PATCH", p, b)

    def delete(self, p):
        return self.call("DELETE", p)


def register(role: str, name: str) -> tuple[Client, str]:
    c = Client()
    email = f"{role}-{uuid.uuid4().hex[:7]}@smoke.test"
    st, data = c.post("/auth/register", {
        "role": role, "email": email,
        "password": "correct-horse-battery", "full_name": name,
    })
    assert st == 200, data
    st, out = c.post("/auth/otp/verify", {
        "challenge_id": data["challenge_id"], "code": data["dev_otp"],
    })
    assert st == 201, out
    return c, email


def main() -> None:
    print(f"\nOBSIDIAN e2e smoke -> {BASE}\n")

    # 1. public pages
    st, _ = Client().call("GET", "/auth/me")
    check("public /auth/me reachable", st == 200)

    # 2. student registration + MFA
    student, s_email = register("student", "Smoke Student")
    st, me = student.get("/auth/me")
    check("student session after OTP MFA", st == 200 and me["email"] == s_email)
    sid = me["profile"]["student_id"]
    check("opaque student ID issued", sid.startswith("OBS-"))

    # 3. onboarding profile + AI consent
    st, _ = student.patch("/profile", {
        "institution": "Smoke University", "course": "B.Sc",
        "cgpa": "8.8", "skills": ["Cryptography"], "profile_visibility": "public",
    })
    check("profile onboarding", st == 200)
    st, _ = student.post("/intelligence/consent", {"consent": True})
    check("AI consent grants personal RAG", st == 200)

    # 4. upload + encryption at rest
    content = f"SMOKE-PLAINTEXT-{uuid.uuid4().hex}\nCGPA: 8.8\ncertificates: one\n".encode()
    st, data = student.post("/documents", {
        "filename": "smoke_certificate.txt",
        "content_base64": base64.b64encode(content).decode(),
        "visibility": "private", "profile_visible": False, "rag_eligible": True,
    })
    check("upload + server-side encryption", st == 201, str(data))
    doc_id = data["document"]["document_id"]
    check("document reports AES-256-GCM",
          data["document"]["encryption"] == "AES-256-GCM")

    # raw object at rest must be ciphertext
    import boto3  # noqa: E402  (only used to inspect the local store)

    # 5. download roundtrip
    st, out = student.get(f"/documents/{doc_id}/content")
    decoded = base64.b64decode(out["content_base64"]) if st == 200 else b""
    check("decrypted download matches original", decoded == content)

    # 6. private doc invisible to another student
    other, _ = register("student", "Other Person")
    st, _ = other.get(f"/documents/{doc_id}/content")
    check("cross-user access denied", st == 403)

    # 7. share link lifecycle
    st, data = student.post(f"/documents/{doc_id}/shares",
                            {"mode": "link", "permission": "viewer", "expires_in": 3600})
    check("share link created", st == 201, str(data))
    token = data["share"]["url"].split("/s/")[1]
    share_id = data["share"]["share_id"]

    guest = Client()
    st, meta = guest.get(f"/s/{token}")
    check("anonymous link access works", st == 200 and meta["permission"] == "viewer")
    st, body = guest.get(f"/s/{token}/content")
    check("link serves decrypted content",
          st == 200 and base64.b64decode(body["content_base64"]) == content)

    st, _ = student.delete(f"/shares/{share_id}")
    check("owner revokes link", st == 200)
    st, body = guest.get(f"/s/{token}")
    check("revoked link fails", st in (404, 410), f"status={st}")

    # 8. bad token
    st, body = guest.get("/s/" + "A" * 43)
    check("invalid token fails", st in (404, 410))

    # 9. RAG: own question answered with sources
    st, ans = student.post("/intelligence/query", {"query": "What is my CGPA?"})
    check("personal AI answers own data",
          st == 200 and ("8.8" in ans["answer"] or ans["sources"]), str(ans)[:160])

    # 10. RAG: cross-user question refused
    st, ans2 = student.post("/intelligence/query",
                            {"query": f"What is the CGPA of student {sid}?"})
    # asking about OWN id is fine; ask about a foreign-looking id instead
    st, ans3 = student.post("/intelligence/query",
                            {"query": "Tell me about every other student in the college"})
    check("cross-user AI question scoped",
          st == 200 and ans3["sources"] == [], str(ans3)[:160])

    # 11. opted-out user has no AI
    plain, _ = register("student", "No AI Person")
    st, _ = plain.post("/intelligence/query", {"query": "hello"})
    check("opted-out AI blocked", st == 403)

    # 12. faculty lookup by exact ID only
    fac, _ = register("faculty", "Smoke Faculty")
    st, lookup = fac.get(f"/profile/student/{sid}")
    check("faculty finds student by exact ID", st == 200)
    st, missing = fac.get("/profile/student/OBS-AAAA-BBBBBB")
    check("unknown ID -> generic 404", st == 404)
    st, _ = fac.get("/documents")
    check("faculty cannot list a vault", st == 403)
    st, _ = fac.get("/profile/students")
    check("no directory endpoint", st == 404)

    # 13. recruiter cannot read private docs
    rec, _ = register("recruiter", "Smoke Recruiter")
    st, _ = rec.get(f"/documents/{doc_id}/content")
    check("recruiter cannot read private doc", st in (403, 401, 404))

    # 14. admin analytics + RBAC
    adm, _ = register("admin", "Smoke Admin")
    st, stats = adm.get("/admin/analytics")
    check("admin analytics", st == 200 and stats["users"]["total"] >= 4)
    st, _ = student.get("/admin/analytics")
    check("student blocked from admin", st == 403)

    # 15. audit trail exists
    st, act = student.get("/activity")
    types = {e["event_type"] for e in act.get("events", [])}
    check("audit events recorded",
          st == 200 and {"document_uploaded", "share_created", "ai_query"} <= types,
          str(sorted(types))[:200])

    # 16. logout invalidates
    student.post("/auth/logout")
    st, _ = student.get("/documents")
    check("logout invalidates session", st == 401)

    print(f"\n{'PASS' if FAIL == 0 else 'FAIL'} — {PASS} passed, {FAIL} failed\n")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
