"""Secure sharing handlers: restricted grants and expiring/revocable links.

Token rules:
- 256-bit cryptographically random token, returned to the owner exactly once
- only the SHA-256 hash is stored (never the raw token, never in audit logs)
- expiry and revocation are enforced server-side on every access
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from boto3.dynamodb.conditions import Key

from .. import audit, aws, security
from ..context import RequestContext
from ..errors import ApiError, access_denied, invalid_input, not_found, rate_limited
from ..ids import uuid_hex
from ..router import route
from ..validation import TEXT_EXTENSIONS, extension_of

PERMISSIONS = ("viewer", "editor")
EXPIRY_CHOICES = {3600, 86400, 604800, None}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _share_status(share: dict) -> str:
    if share.get("revoked_at"):
        return "revoked"
    if share.get("expires_at") and share["expires_at"] < _now():
        return "expired"
    return "active"


def _share_view(share: dict, doc_filename: str | None = None) -> dict:
    return {
        "share_id": share["share_id"],
        "document_id": share["document_id"],
        "filename": doc_filename if doc_filename is not None else share.get("filename", ""),
        "mode": share.get("mode", "link"),
        "permission": share.get("permission", "viewer"),
        "status": _share_status(share),
        "created_at": share.get("created_at", ""),
        "expires_at": share.get("expires_at", ""),
        "revoked_at": share.get("revoked_at", ""),
        "access_count": int(share.get("access_count", 0)),
        "last_accessed_at": share.get("last_accessed_at", ""),
        "grantee_email": share.get("grantee_email", ""),
    }


def _load_own_share(req: RequestContext, share_id: str) -> dict:
    user = req.require_auth()
    resp = aws.table("shares").get_item(Key={"pk": f"SHARE#{share_id}", "sk": "S"})
    share = resp.get("Item")
    if not share or share.get("owner_id") != user["user_id"]:
        # identical response whether the share is missing or someone else's:
        # no existence leak across owners
        if share:
            audit.write_event(
                actor_id=user["user_id"], actor_role=user["role"],
                event_type="authorization_denied", resource_type="share",
                resource_id=share_id, result="denied", request_id=req.request_id,
            )
        raise not_found()
    return share


def _resolve_expiry(body: dict) -> str:
    """Return ISO expiry timestamp or '' for never."""
    if "expires_in" in body:
        raw = body["expires_in"]
        if raw is None or raw == "" or raw == "never":
            return ""
        try:
            seconds = int(raw)
        except (TypeError, ValueError):
            raise invalid_input("Expiration must be a number of seconds.")
        if seconds < 60 or seconds > 365 * 86400:
            raise invalid_input("Expiration must be between 1 minute and 1 year.")
        return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
    return ""


# ------------------------------------------------------------------ create

@route("POST", "/documents/{document_id}/shares", roles=("student",))
def create_share(req: RequestContext) -> dict:
    user = req.require_auth()
    from .documents import load_document
    doc = load_document(req.path_params["document_id"])
    if not doc or doc.get("deleted_at") or doc.get("owner_id") != user["user_id"]:
        raise not_found()

    body = req.body
    mode = str(body.get("mode", "link")).lower()
    permission = str(body.get("permission", "viewer")).lower()
    if mode not in ("link", "restricted"):
        raise invalid_input("Share mode must be 'link' or 'restricted'.")
    if permission not in PERMISSIONS:
        raise invalid_input("Permission must be viewer or editor.")
    if permission == "editor" and extension_of(doc["filename"]) not in TEXT_EXTENSIONS:
        raise invalid_input("Editor access is only available for text documents.")

    expires_at = _resolve_expiry(body)
    share_id = uuid_hex()
    now = _now()
    share: dict = {
        "pk": f"SHARE#{share_id}", "sk": "S",
        "share_id": share_id,
        "document_id": doc["document_id"],
        "filename": doc["filename"],
        "owner_id": user["user_id"],
        "mode": mode,
        "permission": permission,
        "created_at": now,
        "expires_at": expires_at,
        "revoked_at": "",
        "access_count": 0,
        "last_accessed_at": "",
        "gsi1pk": f"OWNER#{user['user_id']}", "gsi1sk": f"TS#{now}#{share_id}",
        "gsi2pk": f"DOC#{doc['document_id']}", "gsi2sk": f"TS#{now}#{share_id}",
    }

    raw_token = None
    if mode == "link":
        raw_token = security.new_share_token()
        token_hash = security.hash_token(raw_token)
        share["token_hash"] = token_hash
    else:
        grantee_email = str(body.get("grantee_email", "")).strip().lower()
        grantee_student_id = str(body.get("grantee_student_id", "")).strip().upper()
        if grantee_student_id:
            # Share directly to a connected student by their code.
            presp = aws.table("profiles").query(
                IndexName="gsi1",
                KeyConditionExpression=Key("gsi1pk").eq(f"SID#{grantee_student_id}"),
                Limit=1,
            )
            items = presp.get("Items", [])
            grantee = None
            if items and items[0].get("user_id"):
                grantee = aws.table("users").get_item(
                    Key={"pk": f"USER#{items[0]['user_id']}", "sk": "META"}
                ).get("Item")
            if not grantee or grantee["user_id"] == user["user_id"] or grantee.get("status") != "active":
                raise ApiError("INVALID_INPUT", "We couldn't find an active OBSIDIAN account for that student.", 404)
        elif grantee_email:
            from .auth import find_user_by_email
            grantee = find_user_by_email(grantee_email)
            if not grantee or grantee["user_id"] == user["user_id"] or grantee.get("status") != "active":
                raise ApiError("INVALID_INPUT", "We couldn't find an active OBSIDIAN account for that recipient.", 404)
        else:
            raise invalid_input("Enter the recipient's email address or student code.")
        share["grantee_id"] = grantee["user_id"]
        share["grantee_email"] = grantee["email"]
        share["gsi3pk"] = f"GRANTEE#{grantee['user_id']}"
        share["gsi3sk"] = f"TS#{now}#{share_id}"

    aws.table("shares").put_item(Item=share)
    if mode == "link":
        aws.table("shares").put_item(Item={
            "pk": f"TOKEN#{security.hash_token(raw_token)}", "sk": "T",
            "share_id": share_id,
            "document_id": doc["document_id"],
            "created_at": now,
        })

    aws.table("documents").update_item(
        Key={"pk": doc["pk"], "sk": "META"},
        UpdateExpression="ADD share_count :one",
        ExpressionAttributeValues={":one": 1},
    )
    audit.write_event(
        actor_id=user["user_id"], actor_role=user["role"],
        event_type="share_created", resource_type="share",
        resource_id=share_id, request_id=req.request_id,
        metadata={"document_id": doc["document_id"], "mode": mode,
                  "permission": permission, "expires_at": expires_at or "never"},
    )
    view = _share_view(share)
    if raw_token:
        view["url"] = f"/s/{raw_token}"  # raw token returned exactly once
        view["token_preview"] = raw_token[:6] + "…"
    return 201, {"share": view}


# --------------------------------------------------------------------- read

@route("GET", "/documents/{document_id}/shares", roles=("student",))
def list_document_shares(req: RequestContext) -> dict:
    user = req.require_auth()
    from .documents import load_document
    doc = load_document(req.path_params["document_id"])
    if not doc or doc.get("deleted_at") or doc.get("owner_id") != user["user_id"]:
        raise not_found()
    resp = aws.table("shares").query(
        IndexName="gsi2",
        KeyConditionExpression=Key("gsi2pk").eq(f"DOC#{doc['document_id']}"),
        ScanIndexForward=False,
        Limit=100,
    )
    shares = [_share_view(s, doc["filename"]) for s in resp.get("Items", [])]
    return {"shares": shares}


@route("GET", "/shares", roles=("student",))
def list_my_shares(req: RequestContext) -> dict:
    user = req.require_auth()
    resp = aws.table("shares").query(
        IndexName="gsi1",
        KeyConditionExpression=Key("gsi1pk").eq(f"OWNER#{user['user_id']}"),
        ScanIndexForward=False,
        Limit=200,
    )
    shares = [_share_view(s) for s in resp.get("Items", [])]
    active = sum(1 for s in shares if s["status"] == "active")
    expired = sum(1 for s in shares if s["status"] == "expired")
    revoked = sum(1 for s in shares if s["status"] == "revoked")
    return {"shares": shares, "summary": {"active": active, "expired": expired, "revoked": revoked}}


@route("GET", "/documents/shared-with-me", roles=("student",))
def shared_with_me(req: RequestContext) -> dict:
    user = req.require_auth()
    resp = aws.table("shares").query(
        IndexName="gsi3",
        KeyConditionExpression=Key("gsi3pk").eq(f"GRANTEE#{user['user_id']}"),
        ScanIndexForward=False,
        Limit=100,
    )
    from .documents import load_document
    out = []
    for s in resp.get("Items", []):
        if _share_status(s) != "active":
            continue
        doc = load_document(s["document_id"])
        if not doc or doc.get("deleted_at"):
            continue
        view = _share_view(s, doc["filename"])
        view["mime_type"] = doc.get("mime_type", "")
        view["size_bytes"] = doc.get("size_bytes", 0)
        view["owner"] = "Owner"  # never leak more than policy allows
        out.append(view)
    return {"shares": out}


# ------------------------------------------------------------------ update

@route("PATCH", "/shares/{share_id}", roles=("student",))
def update_share(req: RequestContext) -> dict:
    share = _load_own_share(req, req.path_params["share_id"])
    if share.get("sk") != "S" or share.get("mode") != "link":
        raise not_found()
    body = req.body
    updates: dict = {}
    if "permission" in body:
        perm = str(body["permission"]).lower()
        if perm not in PERMISSIONS:
            raise invalid_input("Permission must be viewer or editor.")
        from .documents import load_document
        doc = load_document(share["document_id"])
        if perm == "editor" and (not doc or extension_of(doc["filename"]) not in TEXT_EXTENSIONS):
            raise invalid_input("Editor access is only available for text documents.")
        updates["permission"] = perm
    if "expires_in" in body:
        updates["expires_at"] = _resolve_expiry(body)
    if not updates:
        return {"share": _share_view(share)}
    expr = ", ".join(f"#f{i} = :f{i}" for i in range(len(updates)))
    names = {f"#f{i}": k for i, k in enumerate(updates)}
    values = {f":f{i}": v for i, v in enumerate(updates.values())}
    aws.table("shares").update_item(
        Key={"pk": share["pk"], "sk": "S"},
        UpdateExpression=f"SET {expr}",
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )
    user = req.require_auth()
    audit.write_event(
        actor_id=user["user_id"], actor_role=user["role"],
        event_type="share_created", resource_type="share",
        resource_id=share["share_id"], request_id=req.request_id,
        metadata={"updated_fields": sorted(updates.keys()), "action": "update"},
    )
    share.update(updates)
    return {"share": _share_view(share)}


@route("DELETE", "/shares/{share_id}", roles=("student",))
def revoke_share(req: RequestContext) -> dict:
    user = req.require_auth()
    share = _load_own_share(req, req.path_params["share_id"])
    if share.get("revoked_at"):
        return {"share": _share_view(share)}
    now = _now()
    aws.table("shares").update_item(
        Key={"pk": share["pk"], "sk": "S"},
        UpdateExpression="SET revoked_at = :r",
        ExpressionAttributeValues={":r": now},
    )
    if share.get("mode") == "link" and share.get("token_hash"):
        # remove the token index so resolution fails immediately (fail closed)
        try:
            aws.table("shares").delete_item(Key={"pk": f"TOKEN#{share['token_hash']}", "sk": "T"})
        except Exception:
            pass
    audit.write_event(
        actor_id=user["user_id"], actor_role=user["role"],
        event_type="share_revoked", resource_type="share",
        resource_id=share["share_id"], request_id=req.request_id,
        metadata={"document_id": share.get("document_id", "")},
    )
    share["revoked_at"] = now
    return {"share": _share_view(share)}


# ------------------------------------------------------ public link access

def _resolve_token(req: RequestContext, token: str) -> tuple[dict, dict]:
    """Validate token -> share -> document. Raises safe errors; audits denials."""
    if not token or len(token) < 20 or len(token) > 200:
        raise ApiError("SHARE_UNAVAILABLE", "This link is unavailable.", 404)
    token_hash = security.hash_token(token)
    resp = aws.table("shares").get_item(Key={"pk": f"TOKEN#{token_hash}", "sk": "T"})
    index_item = resp.get("Item")
    if not index_item:
        audit.write_event(
            actor_id=None, actor_role=None, event_type="share_access_denied",
            resource_type="share", resource_id="", result="denied",
            request_id=req.request_id, metadata={"reason": "unknown_token"},
        )
        raise ApiError("SHARE_UNAVAILABLE", "This link is unavailable.", 404)

    sresp = aws.table("shares").get_item(Key={"pk": f"SHARE#{index_item['share_id']}", "sk": "S"})
    share = sresp.get("Item")
    if not share:
        audit.write_event(
            actor_id=None, actor_role=None, event_type="share_access_denied",
            resource_type="share", resource_id=index_item["share_id"],
            result="denied", request_id=req.request_id,
            metadata={"reason": "missing_share"},
        )
        raise ApiError("SHARE_UNAVAILABLE", "This link is unavailable.", 404)
    if share.get("revoked_at"):
        audit.write_event(
            actor_id=None, actor_role=None, event_type="share_access_denied",
            resource_type="share", resource_id=share["share_id"], result="denied",
            request_id=req.request_id, metadata={"reason": "revoked"},
        )
        raise ApiError("SHARE_REVOKED", "This link is no longer active.", 410)
    if share.get("expires_at") and share["expires_at"] < _now():
        audit.write_event(
            actor_id=None, actor_role=None, event_type="share_access_denied",
            resource_type="share", resource_id=share["share_id"], result="denied",
            request_id=req.request_id, metadata={"reason": "expired"},
        )
        raise ApiError("SHARE_EXPIRED", "This link has expired.", 410)

    from .documents import load_document
    doc = load_document(share["document_id"])
    if not doc or doc.get("deleted_at"):
        audit.write_event(
            actor_id=None, actor_role=None, event_type="share_access_denied",
            resource_type="share", resource_id=share["share_id"], result="denied",
            request_id=req.request_id, metadata={"reason": "document_unavailable"},
        )
        raise ApiError("SHARE_UNAVAILABLE", "This link is unavailable.", 404)
    return share, doc


@route("GET", "/s/{token}", auth="public", rate=("share_access", 30, 60))
def resolve_share(req: RequestContext) -> dict:
    share, doc = _resolve_token(req, str(req.path_params["token"]))
    aws.table("shares").update_item(
        Key={"pk": share["pk"], "sk": "S"},
        UpdateExpression="SET last_accessed_at = :t ADD access_count :one",
        ExpressionAttributeValues={":one": 1, ":t": _now()},
    )
    audit.write_event(
        actor_id=None, actor_role=None, event_type="share_accessed",
        resource_type="document", resource_id=doc["document_id"],
        request_id=req.request_id,
        metadata={"share_id": share["share_id"], "permission": share["permission"], "via": "link"},
    )
    return {
        "document": {
            "document_id": doc["document_id"],
            "filename": doc["filename"],
            "mime_type": doc.get("mime_type", ""),
            "size_bytes": doc.get("size_bytes", 0),
            "created_at": doc.get("created_at", ""),
            "encryption": doc.get("encryption_algorithm", ""),
        },
        "permission": share.get("permission", "viewer"),
        "expires_at": share.get("expires_at", ""),
    }


@route("GET", "/s/{token}/content", auth="public", rate=("share_content", 30, 60))
def share_content(req: RequestContext) -> dict:
    share, doc = _resolve_token(req, str(req.path_params["token"]))
    from .documents import decrypt_document
    payload = decrypt_document(doc, req.request_id, action="share_access")
    aws.table("shares").update_item(
        Key={"pk": share["pk"], "sk": "S"},
        UpdateExpression="SET last_accessed_at = :t ADD access_count :one",
        ExpressionAttributeValues={":one": 1, ":t": _now()},
    )
    audit.write_event(
        actor_id=None, actor_role=None, event_type="share_accessed",
        resource_type="document", resource_id=doc["document_id"],
        request_id=req.request_id,
        metadata={"share_id": share["share_id"], "permission": share["permission"],
                  "via": "link", "action": "download"},
    )
    payload["permission"] = share.get("permission", "viewer")
    return payload


@route("PUT", "/s/{token}/content", auth="public", rate=("share_edit", 20, 60))
def share_edit(req: RequestContext) -> dict:
    share, doc = _resolve_token(req, str(req.path_params["token"]))
    if share.get("permission") != "editor":
        audit.write_event(
            actor_id=None, actor_role=None, event_type="share_access_denied",
            resource_type="share", resource_id=share["share_id"], result="denied",
            request_id=req.request_id, metadata={"reason": "permission"},
        )
        raise access_denied()
    if extension_of(doc["filename"]) not in TEXT_EXTENSIONS:
        raise ApiError("INVALID_INPUT", "This file type cannot be edited.", 400)

    import base64
    from .. import crypto
    try:
        content = base64.b64decode(str(req.body.get("content_base64", "")), validate=True)
    except Exception:
        raise invalid_input("The content could not be decoded.")
    max_bytes = aws.settings.max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise invalid_input("Content exceeds the size limit.")

    encrypted = crypto.encrypt_bytes(content, doc["document_id"])
    s3 = aws.storage_client()
    s3.put_object(
        Bucket=aws.settings.document_bucket,
        Key=doc["storage_key"],
        Body=encrypted.ciphertext,
        ContentType="application/octet-stream",
        **aws.object_store_sse(encrypted.key_id),
    )
    now = _now()
    aws.table("documents").update_item(
        Key={"pk": doc["pk"], "sk": "META"},
        UpdateExpression="SET wrapped_dek = :w, nonce = :n, ciphertext_sha256 = :c, "
                         "plaintext_sha256 = :p, size_bytes = :s, updated_at = :u, key_id = :k",
        ExpressionAttributeValues={
            ":w": encrypted.wrapped_dek.hex(), ":n": encrypted.nonce.hex(),
            ":c": encrypted.ciphertext_sha256, ":p": encrypted.plaintext_sha256,
            ":s": len(content), ":u": now, ":k": encrypted.key_id,
        },
    )
    audit.write_event(
        actor_id=share.get("owner_id"), actor_role=None,
        event_type="document_updated", resource_type="document",
        resource_id=doc["document_id"], request_id=req.request_id,
        metadata={"via": "shared_link_editor", "share_id": share["share_id"]},
    )
    return {"ok": True, "size_bytes": len(content)}
