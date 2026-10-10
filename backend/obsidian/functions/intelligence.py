"""OBSIDIAN Intelligence: consent, status, isolated query, sources, reindex.

The RAG identity is always derived from the authenticated session:
session -> user_id -> personal RAG partition. No endpoint accepts a
frontend-supplied RAG identifier.
"""
from __future__ import annotations

from .. import audit, aws, rag
from ..config import settings
from ..context import RequestContext, load_profile
from ..errors import ApiError, invalid_input
from ..router import route


@route("POST", "/intelligence/consent", rate=("ai_consent", 20, 300))
def set_consent(req: RequestContext) -> dict:
    user = req.require_auth()
    consent = req.body.get("consent")
    if not isinstance(consent, bool):
        raise invalid_input("Consent must be true or false.")
    user_id = user["user_id"]

    if consent:
        inst = rag.instance(user_id)
        if not inst:
            rag.create_instance(user_id)
        else:
            rag.set_enabled(user_id, True, "READY")
        profile = load_profile(user_id) or {}
        rag.upsert_profile_chunk(user_id, profile, user["role"])
        _ingest_eligible_documents(user_id)
        aws.table("users").update_item(
            Key={"pk": user["pk"], "sk": "META"},
            UpdateExpression="SET ai_enabled = :t, onboarding_complete = :o",
            ExpressionAttributeValues={":t": True, ":o": True},
        )
        audit.write_event(
            actor_id=user_id, actor_role=user["role"], event_type="ai_enabled",
            resource_type="rag", resource_id=user_id, request_id=req.request_id,
        )
        return {"ai_enabled": True, "status": "READY"}

    rag.wipe_user_rag(user_id)
    # wipe removed the instance item as well: recreate a disabled marker
    aws.table("rag").put_item(Item={
        "pk": f"RAG#{user_id}", "sk": "INSTANCE",
        "user_id": user_id, "enabled": False, "status": "DISABLED",
        "created_at": audit.now_iso(), "updated_at": audit.now_iso(), "chunk_count": 0,
    })
    aws.table("users").update_item(
        Key={"pk": user["pk"], "sk": "META"},
        UpdateExpression="SET ai_enabled = :f, onboarding_complete = :o",
        ExpressionAttributeValues={":f": False, ":o": True},
    )
    audit.write_event(
        actor_id=user_id, actor_role=user["role"], event_type="ai_disabled",
        resource_type="rag", resource_id=user_id, request_id=req.request_id,
    )
    return {"ai_enabled": False, "status": "DISABLED"}


def _ingest_eligible_documents(user_id: str, limit: int = 50) -> int:
    from .documents import decrypt_document
    from boto3.dynamodb.conditions import Key
    resp = aws.table("documents").query(
        IndexName="gsi1",
        KeyConditionExpression=Key("gsi1pk").eq(f"OWNER#{user_id}"),
        ScanIndexForward=False,
        Limit=200,
    )
    count = 0
    for doc in resp.get("Items", []):
        if doc.get("deleted_at") or not doc.get("rag_eligible"):
            continue
        if count >= limit:
            break
        try:
            payload = decrypt_document(doc, "", action="rag_index")
            import base64
            content = base64.b64decode(payload["content_base64"])
            status = rag.ingest_document(user_id, doc["document_id"], doc["filename"],
                                         doc.get("mime_type", ""), content)
            aws.table("documents").update_item(
                Key={"pk": doc["pk"], "sk": "META"},
                UpdateExpression="SET rag_status = :s",
                ExpressionAttributeValues={":s": status},
            )
            count += 1
        except Exception:
            continue
    return count


@route("GET", "/intelligence/status")
def status(req: RequestContext) -> dict:
    user = req.require_auth()
    if not user.get("ai_enabled"):
        return {"enabled": False, "status": "DISABLED", "reason": "consent_not_granted"}
    inst = rag.instance(user["user_id"]) or {}
    sources = rag.list_sources(user["user_id"])
    return {
        "enabled": bool(inst.get("enabled")),
        "status": inst.get("status", "NOT_CREATED"),
        "chunk_count": sources["chunk_count"],
        "document_count": len(sources["documents"]),
        "profile_indexed": sources["profile_indexed"],
        "created_at": inst.get("created_at", ""),
        "isolation": "personal-partition",
        "model_mode": "provider" if settings_llm() else "retrieval-only",
        "provider": settings.llm_provider,
        "model": settings.llm_model,
    }


def settings_llm() -> bool:
    from ..config import settings
    return settings.llm_configured


def _parse_history(raw) -> list[dict]:
    """Recent conversation turns supplied by the client.

    History is only ever used as prompt context for this authenticated user's
    own question — it is never treated as an authorization boundary and never
    reaches retrieval for anyone else.
    """
    if not isinstance(raw, list):
        return []
    turns: list[dict] = []
    for turn in raw[-12:]:
        if not isinstance(turn, dict):
            continue
        role = turn.get("role")
        if role not in ("user", "assistant"):
            continue
        content = str(turn.get("content", ""))[:2000]
        if content:
            turns.append({"role": role, "content": content})
    return turns


@route("POST", "/intelligence/query", rate=("ai_query", 20, 300))
def query(req: RequestContext) -> dict:
    user = req.require_auth()
    if not user.get("ai_enabled"):
        raise ApiError("AI_UNAVAILABLE",
                       "Personal intelligence is not enabled for your account.", 403)
    question = str(req.body.get("query", "")).strip()
    if not question:
        raise invalid_input("Please enter a question.")
    if len(question) > 2000:
        raise invalid_input("That question is too long.")

    profile = load_profile(user["user_id"]) or {}
    own_sid = profile.get("student_id", "")

    # Hard privacy guard: never retrieve or confirm anything about others.
    if rag.looks_like_cross_user_request(question, own_sid):
        audit.write_event(
            actor_id=user["user_id"], actor_role=user["role"], event_type="ai_query",
            resource_type="rag", resource_id=user["user_id"], request_id=req.request_id,
            metadata={"scope": "cross_user_blocked"},
        )
        return {"answer": rag.SCOPE_RESPONSE, "sources": [], "scope": "personal"}

    history = _parse_history(req.body.get("history"))
    chunks = rag.retrieve(user["user_id"], question)
    sources = []
    seen = set()
    for c in chunks:
        if not c.get("document_id"):
            continue  # the profile summary is not a citable document
        key = (c["document_id"], c.get("page", 0))
        if key in seen:
            continue
        seen.add(key)
        sources.append({
            "document_id": c["document_id"],
            "filename": c["filename"],
            "page": c.get("page", 0),
            "relevance": c["score"],
        })
    answer = rag.generate_answer(question, chunks, history)

    audit.write_event(
        actor_id=user["user_id"], actor_role=user["role"], event_type="ai_query",
        resource_type="rag", resource_id=user["user_id"], request_id=req.request_id,
        metadata={"had_context": bool(chunks), "sources": len(sources)},
    )
    return {"answer": answer, "sources": sources, "scope": "personal"}


@route("GET", "/intelligence/sources")
def sources(req: RequestContext) -> dict:
    user = req.require_auth()
    if not user.get("ai_enabled"):
        raise ApiError("AI_UNAVAILABLE",
                       "Personal intelligence is not enabled for your account.", 403)
    return rag.list_sources(user["user_id"])


@route("POST", "/intelligence/reindex", rate=("ai_reindex", 5, 300))
def reindex(req: RequestContext) -> dict:
    user = req.require_auth()
    if not user.get("ai_enabled"):
        raise ApiError("AI_UNAVAILABLE",
                       "Personal intelligence is not enabled for your account.", 403)
    user_id = user["user_id"]
    audit.write_event(
        actor_id=user_id, actor_role=user["role"], event_type="rag_index_started",
        resource_type="rag", resource_id=user_id, request_id=req.request_id,
    )
    profile = load_profile(user_id) or {}
    rag.upsert_profile_chunk(user_id, profile, user["role"])
    count = _ingest_eligible_documents(user_id)
    sources = rag.list_sources(user_id)
    audit.write_event(
        actor_id=user_id, actor_role=user["role"], event_type="rag_index_completed",
        resource_type="rag", resource_id=user_id, request_id=req.request_id,
        metadata={"documents": count, "chunks": sources["chunk_count"]},
    )
    return {"reindexed": count, "chunk_count": sources["chunk_count"]}
