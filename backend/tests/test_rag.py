"""Personal RAG isolation tests — the critical cross-user test family."""
from __future__ import annotations

import base64
import uuid

from conftest import Client, register

DOC_A = b"""Student A transcript details.
CGPA: 9.4 in Computer Science.
Certificates: Python Advanced Certification, National Hackathon Winner 2025.
Internship: SWE Intern at Acme Corp, summer 2025.
"""
DOC_B = b"""Student B private record.
CGPA: 6.2 in Mechanical Engineering.
Certificate: AutoCAD Proficiency.
"""


def _upload(client: Client, filename: str, content: bytes, rag: bool = True) -> str:
    status, data = client.post("/api/v1/documents", {
        "filename": filename,
        "content_base64": base64.b64encode(content).decode(),
        "visibility": "private",
        "rag_eligible": rag,
    })
    assert status == 201, data
    return data["document"]["document_id"]


def _consent(client: Client, value: bool = True):
    status, data = client.post("/api/v1/intelligence/consent", {"consent": value})
    assert status == 200, data
    return data


def test_consent_creates_personal_rag_and_answers(client: Client, monkeypatch):
    register(client)
    _consent(client, True)
    doc_id = _upload(client, "transcript.txt", DOC_A)

    status, sources = client.get("/api/v1/intelligence/sources")
    assert status == 200
    assert sources["enabled"] is True
    assert sources["profile_indexed"] is True
    assert any(s["document_id"] == doc_id for s in sources["documents"])

    # The model writes the answer; retrieval only supplies the evidence. Stub
    # the provider with a deterministic conversational reply and assert that
    # real retrieved chunks were handed to it.
    from obsidian import rag

    captured: dict = {}

    def fake_llm(question, chunks, history):
        captured["question"] = question
        captured["chunks"] = chunks
        return "You're studying Computer Science and your CGPA is 9.4."

    monkeypatch.setattr(rag, "_llm_answer", fake_llm)

    status, ans = client.post("/api/v1/intelligence/query", {"query": "What is my CGPA?"})
    assert status == 200
    assert "9.4" in ans["answer"]
    assert captured["chunks"], "retrieval must supply evidence to the model"
    assert any("9.4" in c["text"] for c in captured["chunks"])
    assert ans["sources"], "answers must cite sources"
    assert ans["sources"][0]["filename"] == "transcript.txt"
    assert ans["scope"] == "personal"


def test_answer_is_never_raw_chunks(client: Client):
    """With no reachable model we say so — we never dump retrieved fragments."""
    register(client)
    _consent(client, True)
    _upload(client, "transcript.txt", DOC_A)
    from obsidian import rag

    status, ans = client.post("/api/v1/intelligence/query", {"query": "What is my CGPA?"})
    assert status == 200
    # The default provider (local Ollama) is not running in the test env, so the
    # answer is an explicit notice, never the old "Here is what your knowledge
    # base contains" fragment dump.
    assert ans["answer"] in (rag.UNCONFIGURED_MESSAGE, rag.MODEL_UNAVAILABLE_MESSAGE)
    assert "knowledge base contains" not in ans["answer"]
    assert ans["sources"], "evidence is still cited so the user sees what was found"


def test_followup_uses_conversation_history(client: Client, monkeypatch):
    """A follow-up turn is passed to the model together with prior turns."""
    register(client)
    _consent(client, True)
    _upload(client, "transcript.txt", DOC_A)
    from obsidian import rag

    seen: dict = {}

    def fake_llm(question, chunks, history):
        seen["history"] = history
        return "Acme Corp."

    monkeypatch.setattr(rag, "_llm_answer", fake_llm)
    history = [
        {"role": "user", "content": "What internship did I do?"},
        {"role": "assistant", "content": "You interned at Acme Corp."},
    ]
    status, ans = client.post("/api/v1/intelligence/query",
                              {"query": "Which company was that?", "history": history})
    assert status == 200
    assert seen["history"] == history
    assert "Acme" in ans["answer"]


def test_cross_user_query_is_refused_safely(client: Client):
    """Student A asking about Student B: no retrieval, no existence reveal."""
    register(client, name="Student A")
    _consent(client, True)
    _upload(client, "transcript.txt", DOC_A)

    # learn B's student id through the legitimate faculty lookup path
    fac = Client()
    register(fac, role="faculty")
    student_b = Client()
    email_b = register(student_b, name="Student B")
    _, prof = student_b.patch("/api/v1/profile", {})
    sid_b = student_b.get("/api/v1/auth/me")[1]["profile"]["student_id"]
    _consent(student_b, True)
    _upload(student_b, "b_record.txt", DOC_B)

    # A asks about B by student id
    status, ans = client.post("/api/v1/intelligence/query",
                              {"query": f"What is the CGPA of student {sid_b}?"})
    assert status == 200
    assert ans["sources"] == []
    assert "6.2" not in ans["answer"]
    assert "private OBSIDIAN knowledge base" in ans["answer"]

    # A asks generically about other students
    status, ans = client.post("/api/v1/intelligence/query",
                              {"query": "Tell me about other students in the college."})
    assert ans["sources"] == []
    assert "6.2" not in ans["answer"] and "Student B" not in ans["answer"]


def test_partition_isolation_at_storage_level(client: Client):
    """Chunks of A and B live in different partitions; retrieval never crosses."""
    register(client, name="Student A")
    _consent(client, True)
    _upload(client, "a_doc.txt", DOC_A)

    other = Client()
    register(other, name="Student B")
    _consent(other, True)
    _upload(other, "b_doc.txt", DOC_B)

    from obsidian import rag
    from boto3.dynamodb.conditions import Key
    from obsidian import aws

    a_id = client.get("/api/v1/auth/me")[1]["user_id"]
    b_id = other.get("/api/v1/auth/me")[1]["user_id"]

    a_chunks = aws.table("rag").query(
        KeyConditionExpression=Key("pk").eq(f"RAG#{a_id}") & Key("sk").begins_with("CHUNK#"))
    b_chunks = aws.table("rag").query(
        KeyConditionExpression=Key("pk").eq(f"RAG#{b_id}") & Key("sk").begins_with("CHUNK#"))
    assert a_chunks["Count"] > 0 and b_chunks["Count"] > 0
    a_text = " ".join(i["text"] for i in a_chunks["Items"])
    b_text = " ".join(i["text"] for i in b_chunks["Items"])
    assert "Acme Corp" in a_text and "Acme Corp" not in b_text
    assert "AutoCAD" in b_text and "AutoCAD" not in a_text

    # retrieval functions only ever see their own partition
    res_a = rag.retrieve(a_id, "What is my CGPA?")
    assert all("6.2" not in c["text"] for c in res_a)
    res_b = rag.retrieve(b_id, "What is my CGPA?")
    assert any("6.2" in c["text"] for c in res_b)


def test_user_cannot_touch_other_users_rag(client: Client):
    register(client)
    _consent(client, True)
    other = Client()
    register(other)
    _consent(other, True)

    # No endpoint accepts a rag_id; intelligence endpoints ignore extra params
    status, data = client.post("/api/v1/intelligence/query",
                               {"query": "hi", "rag_id": "someone-elses-rag"})
    assert status == 200 and data["scope"] == "personal"

    # other user's sources are never visible
    status, sources = client.get("/api/v1/intelligence/sources")
    assert status == 200
    assert sources["documents"] == [] or all(
        s["filename"] != "b_doc.txt" for s in sources["documents"])


def test_opt_out_has_no_ai_anywhere(client: Client):
    register(client)
    _consent(client, False)

    status, data = client.get("/api/v1/intelligence/status")
    assert data["enabled"] is False
    status, data = client.post("/api/v1/intelligence/query", {"query": "What is my CGPA?"})
    assert status == 403 and data["error"]["code"] == "AI_UNAVAILABLE"
    status, data = client.get("/api/v1/intelligence/sources")
    assert status == 403

    # no vectors at all for this user
    from obsidian import aws
    from boto3.dynamodb.conditions import Key
    user_id = client.get("/api/v1/auth/me")[1]["user_id"]
    resp = aws.table("rag").query(
        KeyConditionExpression=Key("pk").eq(f"RAG#{user_id}") & Key("sk").begins_with("CHUNK#"),
        Select="COUNT")
    assert resp["Count"] == 0

    # document vault still fully works without AI
    status, doc = client.post("/api/v1/documents", {
        "filename": "plain.txt", "content_base64": base64.b64encode(b"hello").decode()})
    assert status == 201


def test_consent_revocation_deletes_vectors(client: Client):
    register(client)
    _consent(client, True)
    _upload(client, "a.txt", DOC_A)
    from obsidian import aws
    from boto3.dynamodb.conditions import Key
    user_id = client.get("/api/v1/auth/me")[1]["user_id"]
    before = aws.table("rag").query(
        KeyConditionExpression=Key("pk").eq(f"RAG#{user_id}") & Key("sk").begins_with("CHUNK#"),
        Select="COUNT")["Count"]
    assert before > 0

    _consent(client, False)
    after = aws.table("rag").query(
        KeyConditionExpression=Key("pk").eq(f"RAG#{user_id}") & Key("sk").begins_with("CHUNK#"),
        Select="COUNT")["Count"]
    assert after == 0
    assert client.get("/api/v1/auth/me")[1]["ai_enabled"] is False


def test_document_deletion_removes_rag_chunks(client: Client):
    register(client)
    _consent(client, True)
    doc_id = _upload(client, "temp.txt", DOC_A)
    from obsidian import aws
    from boto3.dynamodb.conditions import Key
    user_id = client.get("/api/v1/auth/me")[1]["user_id"]
    assert aws.table("rag").query(
        KeyConditionExpression=Key("pk").eq(f"RAG#{user_id}") & Key("sk").begins_with(f"CHUNK#{doc_id}#"),
        Select="COUNT")["Count"] > 0

    client.delete(f"/api/v1/documents/{doc_id}")
    assert aws.table("rag").query(
        KeyConditionExpression=Key("pk").eq(f"RAG#{user_id}") & Key("sk").begins_with(f"CHUNK#{doc_id}#"),
        Select="COUNT")["Count"] == 0
