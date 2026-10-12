"""Document vault handlers: upload, read, rename, delete, activity.

Every persistent document body is encrypted with AES-256-GCM using a fresh
per-document DEK wrapped by KMS. Ciphertext lives in a private S3 bucket;
metadata lives in DynamoDB. Authorization is enforced before any decryption.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone

from boto3.dynamodb.conditions import Key

from .. import audit, aws, crypto, scanner
from ..context import RequestContext
from ..errors import ApiError, access_denied, invalid_input, not_found
from ..ids import uuid_hex
from ..router import route
from ..validation import validate_file, sanitize_folder, TEXT_EXTENSIONS, extension_of
from .billing import check_quota, storage_status

VISIBILITIES = ("public", "private")


def load_document(document_id: str) -> dict | None:
    if not document_id or len(document_id) > 64:
        return None
    resp = aws.table("documents").get_item(Key={"pk": f"DOC#{document_id}", "sk": "META"})
    return resp.get("Item")


def _require_owner_document(req: RequestContext, document_id: str) -> dict:
    user = req.require_auth()
    doc = load_document(document_id)
    if not doc or doc.get("deleted_at"):
        raise not_found()
    if doc.get("owner_id") != user["user_id"]:
        audit.write_event(
            actor_id=user["user_id"], actor_role=user["role"],
            event_type="authorization_denied", resource_type="document",
            resource_id=document_id, result="denied", request_id=req.request_id,
        )
        raise access_denied()
    return doc


def active_grant(req: RequestContext, document_id: str) -> dict | None:
    """An active restricted share granted to the current user, if any."""
    if not req.user:
        return None
    resp = aws.table("shares").query(
        IndexName="gsi3",
        KeyConditionExpression=Key("gsi3pk").eq(f"GRANTEE#{req.user_id}"),
        Limit=100,
    )
    now = datetime.now(timezone.utc).isoformat()
    for it in resp.get("Items", []):
        if it.get("document_id") != document_id:
            continue
        if it.get("revoked_at") or (it.get("expires_at") and it["expires_at"] < now):
            continue
        if it.get("mode") != "restricted":
            continue
        return it
    return None


def decrypt_document(doc: dict, request_id: str, *, action: str = "document_viewed") -> dict:
    """Fetch ciphertext from S3, verify integrity, decrypt. Fails closed."""
    try:
        s3 = aws.storage_client()
        obj = s3.get_object(Bucket=aws.settings.document_bucket, Key=doc["storage_key"])
        ciphertext = obj["Body"].read()
    except Exception:
        audit.write_event(
            actor_id=doc.get("owner_id"), actor_role=None,
            event_type="suspicious_activity", resource_type="document",
            resource_id=doc.get("document_id", ""), result="failure",
            request_id=request_id, metadata={"stage": "storage_read"},
        )
        raise ApiError("STORAGE_ERROR", "The document could not be retrieved right now.", 503)

    try:
        plaintext = crypto.decrypt_bytes(
            ciphertext=ciphertext,
            nonce=bytes.fromhex(doc["nonce"]),
            wrapped_dek=bytes.fromhex(doc["wrapped_dek"]),
            document_id=doc["document_id"],
            expected_ciphertext_sha256=doc.get("ciphertext_sha256", ""),
        )
    except Exception:
        # Integrity/authentication failure: never return partial plaintext.
        audit.write_event(
            actor_id=doc.get("owner_id"), actor_role=None,
            event_type="suspicious_activity", resource_type="document",
            resource_id=doc.get("document_id", ""), result="failure",
            request_id=request_id, metadata={"stage": "integrity_check", "action": action},
        )
        raise ApiError("ENCRYPTION_ERROR", "This document failed its integrity check and cannot be opened.", 500)

    return {
        "filename": doc["filename"],
        "mime_type": doc.get("mime_type", "application/octet-stream"),
        "size_bytes": len(plaintext),
        "content_base64": base64.b64encode(plaintext).decode("ascii"),
        "plaintext_sha256": doc.get("plaintext_sha256", ""),
    }


def doc_view(doc: dict) -> dict:
    return {
        "document_id": doc["document_id"],
        "filename": doc["filename"],
        "folder": doc.get("folder", ""),
        "mime_type": doc.get("mime_type", ""),
        "size_bytes": doc.get("size_bytes", 0),
        "visibility": doc.get("visibility", "private"),
        "profile_visible": bool(doc.get("profile_visible")),
        "rag_eligible": bool(doc.get("rag_eligible")),
        "rag_status": doc.get("rag_status", ""),
        "scan_status": doc.get("scan_status", "not_scanned"),
        "encryption": doc.get("encryption_algorithm", "AES-256-GCM"),
        "encrypted_at_rest": True,
        "integrity": "sha256-verified" if doc.get("ciphertext_sha256") else "",
        "created_at": doc.get("created_at", ""),
        "updated_at": doc.get("updated_at", ""),
        "owner_id": doc.get("owner_id", ""),
        "share_count": int(doc.get("share_count", 0)),
        "active_share_count": int(doc.get("active_share_count", 0)),
        "extension": extension_of(doc.get("filename", "")),
        "is_text": extension_of(doc.get("filename", "")) in TEXT_EXTENSIONS,
    }


# ------------------------------------------------------------------- upload

def _process_upload(
    user: dict,
    filename: str,
    content: bytes,
    *,
    visibility: str,
    profile_visible: bool,
    rag_eligible: bool,
    folder: str,
    request_id: str,
) -> dict:
    """Validate, scan, encrypt and store one document. Returns the stored item."""
    filename, mime = validate_file(filename, content)

    # Storage entitlement (5 GB free, +10 GB per paid plan). Checked before
    # anything is encrypted or written so a full account never touches S3.
    check_quota(user, len(content))

    # Malware scan before anything is encrypted or stored. Raises on
    # detection (and on scanner failure when fail-closed is enabled).
    try:
        scan_status = scanner.enforce(content)
    except ApiError:
        audit.write_event(
            actor_id=user["user_id"], actor_role=user["role"],
            event_type="suspicious_activity", resource_type="document",
            resource_id="upload", result="failure", request_id=request_id,
            metadata={"stage": "malware_scan"},
        )
        raise

    if visibility not in VISIBILITIES:
        raise invalid_input("Visibility must be public or private.")
    if profile_visible and visibility == "private":
        # Profile visibility is deliberate and cannot be implied by privacy.
        profile_visible = True  # allowed: a private-in-vault doc can still be profile-visible

    folder = sanitize_folder(folder)
    document_id = uuid_hex()
    now = datetime.now(timezone.utc).isoformat()
    storage_key = f"documents/{document_id}/content"

    encrypted = crypto.encrypt_bytes(content, document_id)

    s3 = aws.storage_client()
    try:
        s3.put_object(
            Bucket=aws.settings.document_bucket,
            Key=storage_key,
            Body=encrypted.ciphertext,
            ContentType="application/octet-stream",
            Metadata={
                "document-id": document_id,
                "algorithm": crypto.ALGORITHM,
                "ciphertext-sha256": encrypted.ciphertext_sha256,
            },
            **aws.object_store_sse(encrypted.key_id),
        )
    except Exception:
        audit.write_event(
            actor_id=user["user_id"], actor_role=user["role"],
            event_type="suspicious_activity", resource_type="document",
            resource_id=document_id, result="failure", request_id=request_id,
            metadata={"stage": "storage_write"},
        )
        raise ApiError("STORAGE_ERROR", "The document could not be stored. Please try again.", 503)

    ai_enabled = bool(user.get("ai_enabled"))
    rag_status = ""
    if ai_enabled and rag_eligible:
        rag_status = "indexing"
    elif not ai_enabled:
        rag_status = "disabled"

    item = {
        "pk": f"DOC#{document_id}", "sk": "META",
        "document_id": document_id,
        "owner_id": user["user_id"],
        "filename": filename,
        "folder": folder,
        "mime_type": mime,
        "size_bytes": len(content),
        "storage_key": storage_key,
        "encryption_algorithm": crypto.ALGORITHM,
        "wrapped_dek": encrypted.wrapped_dek.hex(),
        "nonce": encrypted.nonce.hex(),
        "key_id": encrypted.key_id,
        "ciphertext_sha256": encrypted.ciphertext_sha256,
        "plaintext_sha256": encrypted.plaintext_sha256,
        "visibility": visibility,
        "profile_visible": profile_visible,
        "rag_eligible": rag_eligible,
        "rag_status": rag_status,
        "scan_status": scan_status,
        "share_count": 0,
        "active_share_count": 0,
        "status": "active",
        "created_at": now,
        "updated_at": now,
        "deleted_at": "",
        "gsi1pk": f"OWNER#{user['user_id']}",
        "gsi1sk": f"DOC#{now}#{document_id}",
    }
    aws.table("documents").put_item(Item=item)
    audit.write_event(
        actor_id=user["user_id"], actor_role=user["role"],
        event_type="document_uploaded", resource_type="document",
        resource_id=document_id, request_id=request_id,
        metadata={"filename": filename, "size_bytes": len(content),
                  "visibility": visibility, "folder": folder},
    )

    if ai_enabled and rag_eligible:
        try:
            from ..rag import ingest_document
            status = ingest_document(user["user_id"], document_id, filename, mime, content)
            item["rag_status"] = status
            aws.table("documents").update_item(
                Key={"pk": item["pk"], "sk": "META"},
                UpdateExpression="SET rag_status = :s",
                ExpressionAttributeValues={":s": status},
            )
        except Exception:
            item["rag_status"] = "failed"

    return item


def _decode_content(content_b64: str) -> bytes:
    if not content_b64:
        raise ApiError("UPLOAD_REJECTED", "No file content was provided.", 400)
    try:
        return base64.b64decode(content_b64, validate=True)
    except Exception:
        raise ApiError("UPLOAD_REJECTED", "The file content could not be decoded.", 400)


def _upload_options(body: dict) -> tuple[str, bool, bool]:
    visibility = str(body.get("visibility", "private")).lower()
    if visibility not in VISIBILITIES:
        raise invalid_input("Visibility must be public or private.")
    return visibility, bool(body.get("profile_visible", False)), bool(body.get("rag_eligible", False))


@route("POST", "/documents", roles=("student",), rate=("upload", 120, 60))
def upload_document(req: RequestContext) -> dict:
    user = req.require_auth()
    body = req.body
    content = _decode_content(str(body.get("content_base64", "")))
    visibility, profile_visible, rag_eligible = _upload_options(body)
    item = _process_upload(
        user, str(body.get("filename", "")), content,
        visibility=visibility, profile_visible=profile_visible,
        rag_eligible=rag_eligible, folder=str(body.get("folder", "")),
        request_id=req.request_id,
    )
    return 201, {"document": doc_view(item)}


@route("POST", "/documents/batch", roles=("student",), rate=("upload", 120, 60))
def upload_batch(req: RequestContext) -> dict:
    """Folder / multi-file upload. Each file is validated independently; a bad
    file is reported without failing the whole batch."""
    user = req.require_auth()
    body = req.body
    files = body.get("files")
    if not isinstance(files, list) or not files:
        raise invalid_input("Provide a list of files to upload.")
    if len(files) > 200:
        raise invalid_input("A single batch is limited to 200 files.")
    default_visibility, default_profile_visible, default_rag = _upload_options(body)
    default_folder = str(body.get("folder", ""))

    uploaded: list[dict] = []
    errors: list[dict] = []
    for entry in files:
        if not isinstance(entry, dict):
            errors.append({"filename": "", "error": "invalid entry"})
            continue
        name = str(entry.get("filename", ""))
        try:
            content = _decode_content(str(entry.get("content_base64", "")))
            visibility = str(entry.get("visibility", default_visibility)).lower()
            if visibility not in VISIBILITIES:
                visibility = default_visibility
            item = _process_upload(
                user, name, content,
                visibility=visibility,
                profile_visible=bool(entry.get("profile_visible", default_profile_visible)),
                rag_eligible=bool(entry.get("rag_eligible", default_rag)),
                folder=str(entry.get("folder", default_folder)),
                request_id=req.request_id,
            )
            uploaded.append(doc_view(item))
        except ApiError as exc:
            errors.append({"filename": name, "error": exc.message})
        except Exception:
            errors.append({"filename": name, "error": "upload failed"})

    return 201, {
        "uploaded": uploaded,
        "errors": errors,
        "count": len(uploaded),
        "failed": len(errors),
    }


# --------------------------------------------------------------------- read

@route("GET", "/documents", roles=("student",))
def list_documents(req: RequestContext) -> dict:
    user = req.require_auth()
    query = str(req.query.get("query", "")).strip().lower()
    folder = str(req.query.get("folder", "")).strip()
    sort = str(req.query.get("sort", "newest"))
    try:
        limit = min(int(req.query.get("limit", 100)), 200)
    except ValueError:
        limit = 100

    resp = aws.table("documents").query(
        IndexName="gsi1",
        KeyConditionExpression=Key("gsi1pk").eq(f"OWNER#{user['user_id']}"),
        ScanIndexForward=False,
        Limit=500,
    )
    docs = [d for d in resp.get("Items", []) if not d.get("deleted_at")]
    folders = sorted({d.get("folder", "") for d in docs if d.get("folder")})
    if folder:
        docs = [d for d in docs if d.get("folder", "") == folder]
    if query:
        docs = [d for d in docs if query in d["filename"].lower()
                or query in d.get("mime_type", "").lower()
                or query in d.get("folder", "").lower()]
    if sort == "name":
        docs.sort(key=lambda d: d["filename"].lower())
    elif sort == "oldest":
        docs.reverse()
    elif sort == "size":
        docs.sort(key=lambda d: d.get("size_bytes", 0), reverse=True)

    views = []
    for d in docs[:limit]:
        view = doc_view(d)
        view["active_share_count"] = _active_share_count(d)
        views.append(view)
    total_bytes = sum(d.get("size_bytes", 0) for d in docs)
    return {
        "documents": views,
        "folders": folders,
        "total": len(docs),
        "total_bytes": total_bytes,
        "storage": storage_status(user, used=total_bytes),
    }


def _active_share_count(doc: dict) -> int:
    resp = aws.table("shares").query(
        IndexName="gsi2",
        KeyConditionExpression=Key("gsi2pk").eq(f"DOC#{doc['document_id']}"),
        Limit=100,
    )
    now = datetime.now(timezone.utc).isoformat()
    count = 0
    for s in resp.get("Items", []):
        if s.get("revoked_at"):
            continue
        if s.get("expires_at") and s["expires_at"] < now:
            continue
        count += 1
    return count


@route("GET", "/documents/{document_id}", roles=("student",))
def get_document(req: RequestContext) -> dict:
    user = req.require_auth()
    doc = load_document(req.path_params["document_id"])
    if not doc or doc.get("deleted_at"):
        raise not_found()
    if doc.get("owner_id") != user["user_id"]:
        grant = active_grant(req, doc["document_id"])
        if not grant:
            audit.write_event(
                actor_id=user["user_id"], actor_role=user["role"],
                event_type="authorization_denied", resource_type="document",
                resource_id=doc["document_id"], result="denied",
                request_id=req.request_id,
            )
            raise access_denied()
        view = doc_view(doc)
        view["shared_with_me"] = {"permission": grant.get("permission", "viewer")}
        return {"document": view, "is_owner": False}
    view = doc_view(doc)
    view["active_share_count"] = _active_share_count(doc)
    return {"document": view, "is_owner": True}


@route("GET", "/documents/{document_id}/content", roles=("student",))
def get_document_content(req: RequestContext) -> dict:
    user = req.require_auth()
    doc = load_document(req.path_params["document_id"])
    if not doc or doc.get("deleted_at"):
        raise not_found()
    is_owner = doc.get("owner_id") == user["user_id"]
    if not is_owner:
        grant = active_grant(req, doc["document_id"])
        if not grant:
            audit.write_event(
                actor_id=user["user_id"], actor_role=user["role"],
                event_type="authorization_denied", resource_type="document",
                resource_id=doc["document_id"], result="denied",
                request_id=req.request_id, metadata={"route": "content"},
            )
            raise access_denied()

    payload = decrypt_document(doc, req.request_id, action="document_downloaded")
    audit.write_event(
        actor_id=user["user_id"], actor_role=user["role"],
        event_type="document_downloaded" if req.query.get("download") == "1" else "document_viewed",
        resource_type="document", resource_id=doc["document_id"],
        request_id=req.request_id, metadata={"via": "owner" if is_owner else "restricted_share"},
    )
    payload["document"] = doc_view(doc)
    return payload


@route("PUT", "/documents/{document_id}/content", roles=("student",))
def replace_document_content(req: RequestContext) -> dict:
    """Owner edit for text-format documents (re-encrypts the object)."""
    user = req.require_auth()
    doc = _require_owner_document(req, req.path_params["document_id"])
    if extension_of(doc["filename"]) not in TEXT_EXTENSIONS:
        raise ApiError("INVALID_INPUT", "This file type cannot be edited in OBSIDIAN.", 400)
    try:
        content = base64.b64decode(str(req.body.get("content_base64", "")), validate=True)
    except Exception:
        raise invalid_input("The content could not be decoded.")
    max_bytes = aws.settings.max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise invalid_input("Content exceeds the size limit.")
    # Only the *growth* counts against the entitlement.
    growth = len(content) - int(doc.get("size_bytes", 0))
    if growth > 0:
        check_quota(user, growth)

    encrypted = crypto.encrypt_bytes(content, doc["document_id"])
    s3 = aws.storage_client()
    s3.put_object(
        Bucket=aws.settings.document_bucket,
        Key=doc["storage_key"],
        Body=encrypted.ciphertext,
        ContentType="application/octet-stream",
        **aws.object_store_sse(encrypted.key_id),
    )
    now = datetime.now(timezone.utc).isoformat()
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
        actor_id=user["user_id"], actor_role=user["role"],
        event_type="document_updated", resource_type="document",
        resource_id=doc["document_id"], request_id=req.request_id,
        metadata={"size_bytes": len(content)},
    )
    return {"ok": True, "size_bytes": len(content)}


# ------------------------------------------------------------------- update

@route("PATCH", "/documents/{document_id}", roles=("student",))
def update_document(req: RequestContext) -> dict:
    user = req.require_auth()
    doc = _require_owner_document(req, req.path_params["document_id"])
    body = req.body
    updates: dict = {}
    events: list[tuple[str, dict]] = []

    if "filename" in body:
        from ..validation import sanitize_filename, extension_of as ext_of
        new_name = sanitize_filename(str(body["filename"]))
        if ext_of(new_name) != ext_of(doc["filename"]):
            raise invalid_input("The file extension cannot be changed.")
        if new_name != doc["filename"]:
            updates["filename"] = new_name
            events.append(("document_renamed", {"from": doc["filename"][:80], "to": new_name[:80]}))

    if "visibility" in body:
        vis = str(body["visibility"]).lower()
        if vis not in VISIBILITIES:
            raise invalid_input("Visibility must be public or private.")
        if vis != doc.get("visibility"):
            updates["visibility"] = vis
            events.append(("visibility_changed", {"scope": "document", "visibility": vis}))

    if "profile_visible" in body:
        pv = bool(body["profile_visible"])
        if pv != bool(doc.get("profile_visible")):
            updates["profile_visible"] = pv
            events.append(("visibility_changed", {"scope": "document", "profile_visible": pv}))

    if "folder" in body:
        new_folder = sanitize_folder(str(body["folder"]))
        if new_folder != doc.get("folder", ""):
            updates["folder"] = new_folder
            events.append(("document_updated", {"scope": "folder", "folder": new_folder}))

    if "rag_eligible" in body:
        updates["rag_eligible"] = bool(body["rag_eligible"])

    if not updates:
        return {"document": doc_view(doc)}

    now = datetime.now(timezone.utc).isoformat()
    updates["updated_at"] = now
    names = {f"#f{i}": k for i, k in enumerate(updates)}
    expr = ", ".join(f"#f{i} = :f{i}" for i in range(len(updates)))
    values = {f":f{i}": v for i, v in enumerate(updates.values())}
    aws.table("documents").update_item(
        Key={"pk": doc["pk"], "sk": "META"},
        UpdateExpression=f"SET {expr}",
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )
    for event_type, meta in events:
        audit.write_event(
            actor_id=user["user_id"], actor_role=user["role"],
            event_type=event_type, resource_type="document",
            resource_id=doc["document_id"], request_id=req.request_id,
            metadata=meta,
        )

    # AI indexing preference changes trigger ingestion / removal.
    if user.get("ai_enabled") and ("rag_eligible" in updates or "visibility" in updates):
        try:
            from ..rag import ingest_document, remove_document_chunks
            if updates.get("rag_eligible", doc.get("rag_eligible")):
                s3 = aws.storage_client()
                obj = s3.get_object(Bucket=aws.settings.document_bucket, Key=doc["storage_key"])
                # controlled decryption for indexing inside trusted backend
                from ..functions.documents import decrypt_document as _dec  # noqa
                payload = decrypt_document(doc, req.request_id, action="rag_index")
                raw = base64.b64decode(payload["content_base64"])
                status = ingest_document(user["user_id"], doc["document_id"],
                                         updates.get("filename", doc["filename"]),
                                         doc.get("mime_type", ""), raw)
            else:
                remove_document_chunks(user["user_id"], doc["document_id"])
                status = "removed"
        except Exception:
            status = "failed"
        aws.table("documents").update_item(
            Key={"pk": doc["pk"], "sk": "META"},
            UpdateExpression="SET rag_status = :s",
            ExpressionAttributeValues={":s": status},
        )
        updates["rag_status"] = status

    refreshed = load_document(doc["document_id"])
    return {"document": doc_view(refreshed or doc)}


# ------------------------------------------------------------------- delete

@route("DELETE", "/documents/{document_id}", roles=("student",))
def delete_document(req: RequestContext) -> dict:
    user = req.require_auth()
    doc = _require_owner_document(req, req.path_params["document_id"])
    now = datetime.now(timezone.utc).isoformat()

    # 1. revoke all share links immediately
    shares = aws.table("shares").query(
        IndexName="gsi2",
        KeyConditionExpression=Key("gsi2pk").eq(f"DOC#{doc['document_id']}"),
        Limit=100,
    ).get("Items", [])
    for s in shares:
        if not s.get("revoked_at"):
            aws.table("shares").update_item(
                Key={"pk": s["pk"], "sk": "S"},
                UpdateExpression="SET revoked_at = :r",
                ExpressionAttributeValues={":r": now},
            )

    # 2. remove personal RAG references (no orphaned vectors)
    try:
        from ..rag import remove_document_chunks
        remove_document_chunks(user["user_id"], doc["document_id"])
    except Exception:
        pass

    # 3. delete encrypted object
    try:
        aws.storage_client().delete_object(
            Bucket=aws.settings.document_bucket, Key=doc["storage_key"]
        )
    except Exception:
        audit.write_event(
            actor_id=user["user_id"], actor_role=user["role"],
            event_type="suspicious_activity", resource_type="document",
            resource_id=doc["document_id"], result="failure",
            request_id=req.request_id, metadata={"stage": "storage_delete"},
        )

    # 4. tombstone metadata (retained for auditability)
    aws.table("documents").update_item(
        Key={"pk": doc["pk"], "sk": "META"},
        UpdateExpression="SET deleted_at = :d, #st = :s, active_share_count = :z",
        ExpressionAttributeNames={"#st": "status"},
        ExpressionAttributeValues={":d": now, ":s": "deleted", ":z": 0},
    )
    audit.write_event(
        actor_id=user["user_id"], actor_role=user["role"],
        event_type="document_deleted", resource_type="document",
        resource_id=doc["document_id"], request_id=req.request_id,
        metadata={"filename": doc["filename"][:80], "shares_revoked": len(shares)},
    )
    return {"ok": True, "document_id": doc["document_id"]}


# ----------------------------------------------------------------- activity

@route("GET", "/documents/{document_id}/activity", roles=("student",))
def document_activity(req: RequestContext) -> dict:
    doc = _require_owner_document(req, req.path_params["document_id"])
    events, _ = audit.list_for_actor(doc["owner_id"], limit=200)
    scoped = [e for e in events if e.get("resource_id") == doc["document_id"]]
    return {"events": [_safe_event(e) for e in scoped[:50]]}


def _safe_event(e: dict) -> dict:
    return {
        "event_id": e.get("event_id", ""),
        "event_type": e.get("event_type", ""),
        "timestamp": e.get("timestamp", ""),
        "result": e.get("result", ""),
        "actor_role": e.get("actor_role", ""),
        "metadata": e.get("metadata", {}),
    }
