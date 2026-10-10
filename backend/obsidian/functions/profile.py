"""Profile handlers.

Includes the controlled student-ID lookup used by faculty and recruiters.
There is no global student directory endpoint anywhere in the API.
"""
from __future__ import annotations

from datetime import datetime, timezone

from boto3.dynamodb.conditions import Key

from .. import audit, aws
from ..context import RequestContext, load_profile
from ..errors import ApiError, invalid_input, not_found, rate_limited
from ..profile_schema import (
    COMMON_FIELDS, FACULTY_DESIGNATIONS, ROLE_FIELDS, ROLE_LIST_FIELDS, fields_for,
    missing_required,
)
from ..router import route


@route("GET", "/profile")
def get_profile(req: RequestContext) -> dict:
    user = req.require_auth()
    profile = load_profile(user["user_id"]) or {}
    role = user["role"]
    missing = missing_required(role, profile)
    return {
        "profile": _own_view(profile, role),
        "user": {"email": user["email"], "role": role},
        "onboarding": {"role": role, "complete": not missing, "missing": missing},
    }


@route("PATCH", "/profile")
def update_profile(req: RequestContext) -> dict:
    user = req.require_auth()
    profile = load_profile(user["user_id"]) or {}
    role = user["role"]
    body = req.body
    updates: dict = {}
    visibility_before = profile.get("profile_visibility", "public")

    # A role may only set the fields belonging to its own onboarding form.
    for field, max_len in fields_for(role).items():
        if field in body:
            value = str(body[field]).strip()[:max_len]
            if field == "cgpa" and value and not _valid_cgpa(value):
                raise invalid_input("CGPA must be a number between 0 and 10.")
            if field == "graduation_year" and value and not value.isdigit():
                raise invalid_input("Graduation year must be a four-digit year.")
            if field == "designation" and value and value.lower() not in FACULTY_DESIGNATIONS:
                raise invalid_input("Choose a valid academic designation.")
            updates[field] = value
    for field in ROLE_LIST_FIELDS.get(role, ()):
        if field in body:
            raw = body[field]
            if not isinstance(raw, list) or len(raw) > 60:
                raise invalid_input(f"{field} must be a list with at most 60 entries.")
            updates[field] = [str(v).strip()[:120] for v in raw if str(v).strip()][:60]
    # Student-only presentation controls.
    if role == "student":
        if "profile_visibility" in body:
            vis = str(body["profile_visibility"]).lower()
            if vis not in ("public", "private"):
                raise invalid_input("Profile visibility must be public or private.")
            updates["profile_visibility"] = vis
        if "show_phone" in body:
            updates["show_phone"] = bool(body["show_phone"])

    if not updates:
        raise invalid_input("No changes were provided.")

    now = datetime.now(timezone.utc).isoformat()
    updates["updated_at"] = now
    # alias every attribute name: several field names (e.g. "year") are
    # DynamoDB reserved words
    names = {f"#f{i}": k for i, k in enumerate(updates)}
    expr = ", ".join(f"#f{i} = :f{i}" for i in range(len(updates)))
    values = {f":f{i}": v for i, v in enumerate(updates.values())}
    aws.table("profiles").update_item(
        Key={"pk": f"PROFILE#{user['user_id']}", "sk": "META"},
        UpdateExpression=f"SET {expr}",
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )
    audit.write_event(
        actor_id=user["user_id"], actor_role=user["role"],
        event_type="profile_updated", resource_type="profile",
        resource_id=user["user_id"], request_id=req.request_id,
        metadata={"fields": sorted(updates.keys())},
    )
    if "profile_visibility" in updates and updates["profile_visibility"] != visibility_before:
        audit.write_event(
            actor_id=user["user_id"], actor_role=user["role"],
            event_type="visibility_changed", resource_type="profile",
            resource_id=user["user_id"], request_id=req.request_id,
            metadata={"profile_visibility": updates["profile_visibility"]},
        )
    profile = load_profile(user["user_id"]) or {}
    # Keep the personal knowledge base in sync when AI consent is granted.
    tracked = (set(COMMON_FIELDS)
               | {f for rf in ROLE_FIELDS.values() for f in rf}
               | {f for lf in ROLE_LIST_FIELDS.values() for f in lf})
    if user.get("ai_enabled") and (set(updates) & tracked):
        try:
            from ..rag import upsert_profile_chunk
            upsert_profile_chunk(user["user_id"], profile, role)
        except Exception:
            pass
    return {"profile": _own_view(profile, role)}


def _valid_cgpa(value: str) -> bool:
    try:
        num = float(value)
        return 0 <= num <= 10
    except ValueError:
        return False


def _own_view(profile: dict, role: str = "student") -> dict:
    """The caller's own profile, shaped for their role."""
    view: dict = {}
    for field in fields_for(role):
        view[field] = profile.get(field, "")
    for field in ROLE_LIST_FIELDS.get(role, ()):
        view[field] = profile.get(field, [])
    if role == "student":
        view["student_id"] = profile.get("student_id", "")
        view["profile_visibility"] = profile.get("profile_visibility", "public")
        view["show_phone"] = bool(profile.get("show_phone", False))
    view["created_at"] = profile.get("created_at", "")
    view["updated_at"] = profile.get("updated_at", "")
    return view


# ------------------------------------------------------- student ID lookup

def _require_verified_rep(req: RequestContext, user: dict) -> None:
    """Faculty/recruiter protected access requires administrator verification.

    Accounts created outside development start as ``pending`` and gain access
    only after an admin approves them.
    """
    if user.get("verification_status") == "verified":
        return
    audit.write_event(
        actor_id=user["user_id"], actor_role=user["role"],
        event_type="authorization_denied", result="denied",
        request_id=req.request_id, metadata={"reason": "verification_pending"},
    )
    raise ApiError(
        "VERIFICATION_PENDING",
        "Your account must be verified by an administrator before you can look up student records.",
        403,
    )


@route("GET", "/profile/student/{student_id}", roles=("faculty", "recruiter"),
       rate=("student_lookup", 30, 300))
def lookup_student(req: RequestContext) -> dict:
    """Faculty/recruiter lookup requires the student's exact opaque ID."""
    user = req.require_auth()
    _require_verified_rep(req, user)
    student_id = str(req.path_params["student_id"]).strip().upper()

    resp = aws.table("profiles").query(
        IndexName="gsi1",
        KeyConditionExpression=Key("gsi1pk").eq(f"SID#{student_id}"),
        Limit=1,
    )
    items = resp.get("Items", [])
    audit.write_event(
        actor_id=user["user_id"], actor_role=user["role"],
        event_type="student_lookup",
        resource_type="profile", resource_id=student_id,
        result="success" if items else "failure",
        request_id=req.request_id,
        metadata={"found": bool(items)},
    )
    if not items:
        # Identical response whether the ID is wrong or hidden: no enumeration.
        raise not_found()
    profile = items[0]
    if profile.get("profile_visibility") != "public":
        raise not_found()

    docs = _profile_visible_documents(profile["user_id"])
    return {
        "student": _visible_view(profile, user["role"]),
        "documents": docs,
    }


def _visible_view(profile: dict, role: str) -> dict:
    base = {
        "student_id": profile.get("student_id", ""),
        "institution": profile.get("institution", ""),
        "course": profile.get("course", ""),
        "education_level": profile.get("education_level", ""),
        "graduation_year": profile.get("graduation_year", ""),
        "department": profile.get("department", ""),
        "year": profile.get("year", ""),
        "bio": profile.get("bio", ""),
        "skills": profile.get("skills", []),
        "achievements": profile.get("achievements", []),
        "cgpa": profile.get("cgpa", ""),
        "profile_visibility": profile.get("profile_visibility", ""),
    }
    # Recruiters only receive fields the student deliberately exposed.
    if role == "recruiter":
        base["full_name"] = profile.get("full_name", "")
        base["show_phone"] = False
        base["phone"] = profile.get("phone", "") if profile.get("show_phone") else ""
        return base
    # Faculty receive academic contact information as well.
    base["full_name"] = profile.get("full_name", "")
    base["phone"] = profile.get("phone", "") if profile.get("show_phone") else ""
    base["show_phone"] = bool(profile.get("show_phone"))
    return base


def _profile_visible_documents(owner_id: str, limit: int = 50) -> list[dict]:
    resp = aws.table("documents").query(
        IndexName="gsi1",
        KeyConditionExpression=Key("gsi1pk").eq(f"OWNER#{owner_id}"),
        ScanIndexForward=False,
        Limit=200,
    )
    docs = []
    for it in resp.get("Items", []):
        if it.get("deleted_at") or not it.get("profile_visible"):
            continue
        docs.append({
            "document_id": it["document_id"],
            "filename": it["filename"],
            "mime_type": it.get("mime_type", ""),
            "size_bytes": it.get("size_bytes", 0),
            "created_at": it.get("created_at", ""),
            "visibility": it.get("visibility", "private"),
        })
        if len(docs) >= limit:
            break
    return docs


@route("GET", "/profile/student/{student_id}/documents/{document_id}/content",
       roles=("faculty", "recruiter"), rate=("profile_doc", 60, 300))
def profile_document_content(req: RequestContext) -> dict:
    """Serve a profile-visible document to faculty/recruiters under policy."""
    user = req.require_auth()
    _require_verified_rep(req, user)
    student_id = str(req.path_params["student_id"]).strip().upper()
    document_id = str(req.path_params["document_id"])

    resp = aws.table("profiles").query(
        IndexName="gsi1",
        KeyConditionExpression=Key("gsi1pk").eq(f"SID#{student_id}"),
        Limit=1,
    )
    items = resp.get("Items", [])
    if not items or items[0].get("profile_visibility") != "public":
        raise not_found()
    owner_id = items[0]["user_id"]

    from .documents import load_document, decrypt_document
    doc = load_document(document_id)
    if not doc or doc.get("owner_id") != owner_id or doc.get("deleted_at") or not doc.get("profile_visible"):
        raise not_found()

    payload = decrypt_document(doc, req.request_id)
    audit.write_event(
        actor_id=user["user_id"], actor_role=user["role"],
        event_type="document_viewed", resource_type="document",
        resource_id=document_id, request_id=req.request_id,
        metadata={"via": "profile", "student_id": student_id},
    )
    payload["document"] = _public_doc_view(doc)
    return payload


def _public_doc_view(doc: dict) -> dict:
    return {
        "document_id": doc["document_id"],
        "filename": doc["filename"],
        "mime_type": doc.get("mime_type", ""),
        "size_bytes": doc.get("size_bytes", 0),
        "created_at": doc.get("created_at", ""),
        "visibility": doc.get("visibility", ""),
    }
