"""Student connection graph: follow requests, followers/following, and peer
profile viewing.

Privacy model ("explicit share to a connection"):
- A connection sees only a student's *public* (profile-visible) documents, or
  documents the owner has explicitly shared with them.
- Private vault documents never become visible through a connection.

The graph is a set of directed edges. Accepting a request makes the edge
mutual (both students follow each other), matching a LinkedIn-style
connection rather than a one-way follow.
"""
from __future__ import annotations

from datetime import datetime, timezone

from boto3.dynamodb.conditions import Key

from .. import audit, aws
from ..context import RequestContext, load_profile
from ..errors import ApiError, invalid_input, not_found, rate_limited
from ..router import route

STATUSES = ("pending", "accepted")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _edge_key(me: str, other: str) -> dict:
    return {"pk": f"USER#{me}", "sk": f"CONN#{other}"}


def _get_edge(me: str, other: str) -> dict | None:
    return aws.table("connections").get_item(Key=_edge_key(me, other)).get("Item")


def _put_edge(me: str, other: str, status: str, *, created_at: str | None = None,
              responded_at: str = "") -> dict:
    now = _now()
    item = {
        **_edge_key(me, other),
        "user_id": me,
        "other_id": other,
        "status": status,
        "created_at": created_at or now,
        "updated_at": now,
        "responded_at": responded_at,
        "gsi1pk": f"TARGET#{other}",
        "gsi1sk": f"STATUS#{status}#{created_at or now}#{me}",
    }
    aws.table("connections").put_item(Item=item)
    return item


def _delete_edge(me: str, other: str) -> None:
    aws.table("connections").delete_item(Key=_edge_key(me, other))


def _profile_by_student_id(student_id: str) -> dict | None:
    if not student_id:
        return None
    resp = aws.table("profiles").query(
        IndexName="gsi1",
        KeyConditionExpression=Key("gsi1pk").eq(f"SID#{student_id.strip().upper()}"),
        Limit=1,
    )
    items = resp.get("Items", [])
    return items[0] if items else None


def _require_active_target(student_id: str, me: str) -> dict:
    """Resolve a student code to an active student account (not the caller)."""
    profile = _profile_by_student_id(student_id)
    if not profile or profile.get("role") not in (None, "student"):
        raise not_found()
    target_id = profile.get("user_id")
    if not target_id or target_id == me:
        raise invalid_input("You cannot connect with your own account.")
    user = aws.table("users").get_item(Key={"pk": f"USER#{target_id}", "sk": "META"}).get("Item")
    if not user or user.get("status") != "active" or user.get("role") != "student":
        raise not_found()
    return profile


def _public_student_view(profile: dict) -> dict:
    return {
        "student_id": profile.get("student_id", ""),
        "full_name": profile.get("full_name", ""),
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
        "profile_visibility": profile.get("profile_visibility", "private"),
        "avatar_seed": profile.get("avatar_seed", ""),
    }


def _relationship(me: str, other: str) -> str:
    mine = _get_edge(me, other)
    theirs = _get_edge(other, me)
    if mine and mine.get("status") == "accepted" and theirs and theirs.get("status") == "accepted":
        return "connected"
    if mine and mine.get("status") == "pending":
        return "requested"
    if theirs and theirs.get("status") == "pending":
        return "incoming"
    return "none"


def _summary(me: str, other_id: str, status: str, *, created_at: str = "") -> dict:
    profile = load_profile(other_id) or {}
    return {
        "user_id": other_id,
        "student_id": profile.get("student_id", ""),
        "full_name": profile.get("full_name", ""),
        "course": profile.get("course", ""),
        "institution": profile.get("institution", ""),
        "year": profile.get("year", ""),
        "avatar_seed": profile.get("avatar_seed", ""),
        "status": status,
        "created_at": created_at,
    }


# -------------------------------------------------------------------- search

@route("GET", "/connections/search", roles=("student",), rate=("student_search", 30, 300))
def search_student(req: RequestContext) -> dict:
    """Exact student-code lookup. There is no browsable directory."""
    user = req.require_auth()
    student_id = str(req.query.get("student_id", "")).strip()
    if not student_id:
        raise invalid_input("Enter a student code to search.")
    profile = _profile_by_student_id(student_id)
    audit.write_event(
        actor_id=user["user_id"], actor_role=user["role"],
        event_type="student_lookup", resource_type="profile",
        resource_id=student_id.upper(),
        result="success" if profile else "failure", request_id=req.request_id,
        metadata={"found": bool(profile), "via": "connections"},
    )
    if not profile:
        raise not_found()
    target_id = profile.get("user_id", "")
    if target_id == user["user_id"]:
        raise invalid_input("That is your own student code.")
    relationship = _relationship(user["user_id"], target_id)
    return {
        "student": _public_student_view(profile),
        "relationship": relationship,
    }


# ------------------------------------------------------------------ listing

@route("GET", "/connections", roles=("student",))
def list_connections(req: RequestContext) -> dict:
    user = req.require_auth()
    me = user["user_id"]

    out = aws.table("connections").query(
        KeyConditionExpression=Key("pk").eq(f"USER#{me}") & Key("sk").begins_with("CONN#"),
        Limit=500,
    ).get("Items", [])
    inc = aws.table("connections").query(
        IndexName="gsi1",
        KeyConditionExpression=Key("gsi1pk").eq(f"TARGET#{me}"),
        Limit=500,
    ).get("Items", [])

    following = [_summary(me, e["other_id"], "accepted", created_at=e.get("created_at", ""))
                 for e in out if e.get("status") == "accepted"]
    followers = [_summary(me, e["user_id"], "accepted", created_at=e.get("created_at", ""))
                 for e in inc if e.get("status") == "accepted"]
    pending_outgoing = [_summary(me, e["other_id"], "requested", created_at=e.get("created_at", ""))
                        for e in out if e.get("status") == "pending"]
    pending_incoming = [_summary(me, e["user_id"], "incoming", created_at=e.get("created_at", ""))
                        for e in inc if e.get("status") == "pending"]

    return {
        "following": following,
        "followers": followers,
        "pending_incoming": pending_incoming,
        "pending_outgoing": pending_outgoing,
        "counts": {
            "following": len(following),
            "followers": len(followers),
            "pending_incoming": len(pending_incoming),
            "pending_outgoing": len(pending_outgoing),
        },
    }


# ------------------------------------------------------------------ requests

@route("POST", "/connections/requests", roles=("student",), rate=("connection", 60, 60))
def send_request(req: RequestContext) -> dict:
    user = req.require_auth()
    me = user["user_id"]
    student_id = str(req.body.get("student_id", "")).strip()
    profile = _require_active_target(student_id, me)
    target_id = profile["user_id"]

    existing = _get_edge(me, target_id)
    if existing and existing.get("status") == "accepted":
        return {"relationship": "connected", "student": _public_student_view(profile)}

    # If they already asked us, requesting back completes the connection.
    reverse = _get_edge(target_id, me)
    if reverse and reverse.get("status") == "pending":
        now = _now()
        _put_edge(target_id, me, "accepted", created_at=reverse.get("created_at"), responded_at=now)
        _put_edge(me, target_id, "accepted", responded_at=now)
        audit.write_event(
            actor_id=me, actor_role=user["role"], event_type="connection_accepted",
            resource_type="connection", resource_id=target_id, request_id=req.request_id,
            metadata={"mutual": True},
        )
        return {"relationship": "connected", "student": _public_student_view(profile)}

    if not existing:
        _put_edge(me, target_id, "pending")
        audit.write_event(
            actor_id=me, actor_role=user["role"], event_type="connection_requested",
            resource_type="connection", resource_id=target_id, request_id=req.request_id,
            metadata={"student_id": profile.get("student_id", "")},
        )
    return {"relationship": "requested", "student": _public_student_view(profile)}


def _requester_of(me: str, student_id: str) -> dict:
    profile = _require_active_target(student_id, me)
    requester_id = profile["user_id"]
    edge = _get_edge(requester_id, me)
    if not edge or edge.get("status") != "pending":
        raise not_found()
    return {"profile": profile, "requester_id": requester_id, "edge": edge}


@route("POST", "/connections/requests/{student_id}/accept", roles=("student",), rate=("connection", 60, 60))
def accept_request(req: RequestContext) -> dict:
    user = req.require_auth()
    me = user["user_id"]
    found = _requester_of(me, str(req.path_params["student_id"]))
    requester_id = found["requester_id"]
    now = _now()
    _put_edge(requester_id, me, "accepted",
              created_at=found["edge"].get("created_at"), responded_at=now)
    _put_edge(me, requester_id, "accepted", responded_at=now)
    audit.write_event(
        actor_id=me, actor_role=user["role"], event_type="connection_accepted",
        resource_type="connection", resource_id=requester_id, request_id=req.request_id,
        metadata={"student_id": found["profile"].get("student_id", "")},
    )
    return {"relationship": "connected", "student": _public_student_view(found["profile"])}


@route("POST", "/connections/requests/{student_id}/decline", roles=("student",), rate=("connection", 60, 60))
def decline_request(req: RequestContext) -> dict:
    user = req.require_auth()
    me = user["user_id"]
    found = _requester_of(me, str(req.path_params["student_id"]))
    _delete_edge(found["requester_id"], me)
    audit.write_event(
        actor_id=me, actor_role=user["role"], event_type="connection_declined",
        resource_type="connection", resource_id=found["requester_id"], request_id=req.request_id,
        metadata={},
    )
    return {"relationship": "none", "student": _public_student_view(found["profile"])}


@route("DELETE", "/connections/{student_id}", roles=("student",), rate=("connection", 60, 60))
def remove_connection(req: RequestContext) -> dict:
    user = req.require_auth()
    me = user["user_id"]
    profile = _require_active_target(str(req.path_params["student_id"]), me)
    other = profile["user_id"]
    _delete_edge(me, other)
    _delete_edge(other, me)
    audit.write_event(
        actor_id=me, actor_role=user["role"], event_type="connection_removed",
        resource_type="connection", resource_id=other, request_id=req.request_id,
        metadata={"student_id": profile.get("student_id", "")},
    )
    return {"relationship": "none", "student": _public_student_view(profile)}


# ------------------------------------------------------- peer profile view

@route("GET", "/connections/{student_id}", roles=("student",))
def view_connection(req: RequestContext) -> dict:
    """A peer student's profile and their *public* (profile-visible) documents.

    Explicitly shared documents appear through the existing share grant flow.
    """
    user = req.require_auth()
    me = user["user_id"]
    profile = _require_active_target(str(req.path_params["student_id"]), me)
    owner_id = profile["user_id"]

    from .profile import _profile_visible_documents
    relationship = _relationship(me, owner_id)
    docs = _profile_visible_documents(owner_id) if profile.get("profile_visibility") == "public" else []
    return {
        "student": _public_student_view(profile),
        "relationship": relationship,
        "documents": docs,
    }


@route("GET", "/connections/{student_id}/documents/{document_id}/content",
       roles=("student",), rate=("profile_doc", 60, 300))
def connection_document_content(req: RequestContext) -> dict:
    """Serve a profile-visible document to a connected peer.

    A private document is only reachable through an explicit share grant (see
    ``/documents/{id}/content``); it is never reachable here.
    """
    user = req.require_auth()
    me = user["user_id"]
    profile = _require_active_target(str(req.path_params["student_id"]), me)
    if profile.get("profile_visibility") != "public":
        raise not_found()
    owner_id = profile["user_id"]
    document_id = str(req.path_params["document_id"])

    from .documents import load_document, decrypt_document
    doc = load_document(document_id)
    if not doc or doc.get("owner_id") != owner_id or doc.get("deleted_at") or not doc.get("profile_visible"):
        raise not_found()

    payload = decrypt_document(doc, req.request_id, action="connection_document_viewed")
    audit.write_event(
        actor_id=me, actor_role=user["role"], event_type="document_viewed",
        resource_type="document", resource_id=document_id, request_id=req.request_id,
        metadata={"via": "connection", "student_id": profile.get("student_id", "")},
    )
    payload["document"] = {
        "document_id": doc["document_id"],
        "filename": doc["filename"],
        "folder": doc.get("folder", ""),
        "mime_type": doc.get("mime_type", ""),
        "size_bytes": doc.get("size_bytes", 0),
        "created_at": doc.get("created_at", ""),
        "visibility": doc.get("visibility", ""),
    }
    return payload
