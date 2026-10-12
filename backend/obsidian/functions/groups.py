"""Faculty-led groups and group chat.

A *teacher* (faculty account) creates a group, adds students to it by their
opaque student code, and posts messages that every member sees — a small
cohort/classroom feed. Students can read the groups they belong to and reply.

Privacy model:
- Only the group owner (the faculty who created it) and its members can read a
  group, its roster, or its messages. Anyone else receives a generic 404 so the
  existence of a group is never leaked.
- Only the owner can add/remove members, rename, or delete the group.
- Any member (owner included) can post to the group chat.
- Message bodies are the only free text stored here and are never logged in
  audit metadata.
"""
from __future__ import annotations

from boto3.dynamodb.conditions import Key

from .. import audit, aws
from ..context import RequestContext
from ..errors import invalid_input, not_found
from ..ids import uuid_hex
from ..router import route

NAME_MAX = 80
DESCRIPTION_MAX = 400
MESSAGE_MAX = 2000
SCHOOL = ("faculty", "student")


def _now() -> str:
    return audit.now_iso()


def _group_pk(group_id: str) -> str:
    return f"GROUP#{group_id}"


# ------------------------------------------------------------- resolution

def _resolve_student(student_id: str) -> dict:
    """Resolve a student code to an active student profile, else generic 404."""
    sid = str(student_id or "").strip().upper()
    if not sid:
        raise invalid_input("Enter the student's code.")
    resp = aws.table("profiles").query(
        IndexName="gsi1",
        KeyConditionExpression=Key("gsi1pk").eq(f"SID#{sid}"),
        Limit=1,
    )
    items = resp.get("Items", [])
    if not items:
        raise not_found()
    profile = items[0]
    if profile.get("role") not in (None, "student"):
        raise not_found()
    uid = profile.get("user_id")
    user = aws.table("users").get_item(Key={"pk": f"USER#{uid}", "sk": "META"}).get("Item")
    if not user or user.get("status") != "active" or user.get("role") != "student":
        raise not_found()
    return profile


def _load_meta(group_id: str) -> dict:
    item = aws.table("groups").get_item(
        Key={"pk": _group_pk(group_id), "sk": "META"}
    ).get("Item")
    if not item:
        raise not_found()
    return item


def _membership(group_id: str, user_id: str) -> dict | None:
    return aws.table("groups").get_item(
        Key={"pk": _group_pk(group_id), "sk": f"MEMBER#{user_id}"}
    ).get("Item")


def _authorize(group_id: str, actor: dict) -> tuple[dict, bool]:
    """Return (meta, is_owner); raise 404 unless the actor owns or is a member."""
    meta = _load_meta(group_id)
    if meta.get("owner_id") == actor["user_id"]:
        return meta, True
    if _membership(group_id, actor["user_id"]):
        return meta, False
    raise not_found()


def _require_owner(group_id: str, actor: dict) -> dict:
    meta = _load_meta(group_id)
    if meta.get("owner_id") != actor["user_id"]:
        raise not_found()
    return meta


def _member_count(group_id: str) -> int:
    return aws.table("groups").query(
        KeyConditionExpression=Key("pk").eq(_group_pk(group_id)) & Key("sk").begins_with("MEMBER#"),
        Select="COUNT",
    ).get("Count", 0)


def _summary(meta: dict, is_owner: bool) -> dict:
    return {
        "group_id": meta.get("group_id", ""),
        "name": meta.get("name", ""),
        "description": meta.get("description", ""),
        "owner_id": meta.get("owner_id", ""),
        "owner_name": meta.get("owner_name", ""),
        "member_count": _member_count(meta.get("group_id", "")),
        "created_at": meta.get("created_at", ""),
        "updated_at": meta.get("updated_at", ""),
        "role": "owner" if is_owner else "member",
    }


def _member_view(item: dict) -> dict:
    return {
        "user_id": item.get("user_id", ""),
        "student_id": item.get("student_id", ""),
        "full_name": item.get("full_name", ""),
        "institution": item.get("institution", ""),
        "avatar_seed": item.get("avatar_seed", ""),
        "joined_at": item.get("joined_at", ""),
    }


def _message_view(item: dict) -> dict:
    return {
        "message_id": item.get("message_id", ""),
        "sender_id": item.get("sender_id", ""),
        "sender_name": item.get("sender_name", ""),
        "sender_role": item.get("sender_role", ""),
        "body": item.get("body", ""),
        "created_at": item.get("created_at", ""),
    }


def _list_members(group_id: str) -> list[dict]:
    items = aws.table("groups").query(
        KeyConditionExpression=Key("pk").eq(_group_pk(group_id)) & Key("sk").begins_with("MEMBER#"),
        Limit=1000,
    ).get("Items", [])
    items.sort(key=lambda i: i.get("joined_at", ""))
    return [_member_view(i) for i in items]


def _list_messages(group_id: str, limit: int) -> list[dict]:
    items = aws.table("groups").query(
        KeyConditionExpression=Key("pk").eq(_group_pk(group_id)) & Key("sk").begins_with("MSG#"),
        ScanIndexForward=False,
        Limit=limit,
    ).get("Items", [])
    items.reverse()
    return [_message_view(i) for i in items]


def _clean_text(value, *, field: str, max_len: int, required: bool) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise invalid_input(f"{field} is required.")
    if len(text) > max_len:
        raise invalid_input(f"{field} is too long (max {max_len} characters).")
    return text


# ------------------------------------------------------------------ groups

@route("POST", "/groups", roles=("faculty",), rate=("group_write", 60, 300))
def create_group(req: RequestContext) -> dict:
    user = req.require_auth()
    name = _clean_text(req.body.get("name"), field="Group name", max_len=NAME_MAX, required=True)
    description = _clean_text(req.body.get("description"), field="Description",
                              max_len=DESCRIPTION_MAX, required=False)

    from ..context import load_profile
    owner_profile = load_profile(user["user_id"]) or {}
    group_id = uuid_hex()
    now = _now()
    meta = {
        "pk": _group_pk(group_id),
        "sk": "META",
        "group_id": group_id,
        "name": name,
        "description": description,
        "owner_id": user["user_id"],
        "owner_name": owner_profile.get("full_name", "") or user.get("email", ""),
        "owner_role": user["role"],
        "created_at": now,
        "updated_at": now,
        "gsi1pk": f"OWNER#{user['user_id']}",
        "gsi1sk": f"GROUP#{now}#{group_id}",
    }
    aws.table("groups").put_item(Item=meta)
    audit.write_event(
        actor_id=user["user_id"], actor_role=user["role"], event_type="group_created",
        resource_type="group", resource_id=group_id, request_id=req.request_id,
        metadata={"name": name},
    )
    return {"group": _summary(meta, True)}


@route("GET", "/groups", roles=SCHOOL)
def list_groups(req: RequestContext) -> dict:
    user = req.require_auth()
    groups: list[dict] = []
    if user["role"] == "faculty":
        metas = aws.table("groups").query(
            IndexName="gsi1",
            KeyConditionExpression=Key("gsi1pk").eq(f"OWNER#{user['user_id']}"),
            ScanIndexForward=False,
            Limit=200,
        ).get("Items", [])
        groups = [_summary(m, True) for m in metas]
    else:
        edges = aws.table("groups").query(
            IndexName="gsi2",
            KeyConditionExpression=Key("gsi2pk").eq(f"MEMBER#{user['user_id']}"),
            Limit=200,
        ).get("Items", [])
        for edge in edges:
            try:
                meta = _load_meta(edge.get("group_id", ""))
            except Exception:
                continue
            groups.append(_summary(meta, meta.get("owner_id") == user["user_id"]))
        groups.sort(key=lambda g: g.get("created_at", ""), reverse=True)
    return {"groups": groups, "total": len(groups)}


@route("GET", "/groups/{group_id}", roles=SCHOOL)
def group_detail(req: RequestContext) -> dict:
    user = req.require_auth()
    group_id = str(req.path_params["group_id"])
    meta, is_owner = _authorize(group_id, user)
    audit.write_event(
        actor_id=user["user_id"], actor_role=user["role"], event_type="group_viewed",
        resource_type="group", resource_id=group_id, request_id=req.request_id, metadata={},
    )
    return {
        "group": _summary(meta, is_owner),
        "members": _list_members(group_id),
        "messages": _list_messages(group_id, 50),
    }


@route("PATCH", "/groups/{group_id}", roles=("faculty",), rate=("group_write", 60, 300))
def update_group(req: RequestContext) -> dict:
    user = req.require_auth()
    group_id = str(req.path_params["group_id"])
    meta = _require_owner(group_id, user)

    updates: dict = {}
    if "name" in req.body:
        updates["name"] = _clean_text(req.body.get("name"), field="Group name",
                                      max_len=NAME_MAX, required=True)
    if "description" in req.body:
        updates["description"] = _clean_text(req.body.get("description"), field="Description",
                                             max_len=DESCRIPTION_MAX, required=False)
    if not updates:
        raise invalid_input("Nothing to update.")
    updates["updated_at"] = _now()

    expr = "SET " + ", ".join(f"#f{i} = :v{i}" for i in range(len(updates)))
    names = {f"#f{i}": k for i, k in enumerate(updates)}
    values = {f":v{i}": v for i, v in enumerate(updates.values())}
    aws.table("groups").update_item(
        Key={"pk": _group_pk(group_id), "sk": "META"},
        UpdateExpression=expr,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )
    meta.update(updates)
    audit.write_event(
        actor_id=user["user_id"], actor_role=user["role"], event_type="group_updated",
        resource_type="group", resource_id=group_id, request_id=req.request_id,
        metadata={"fields": list(updates.keys())},
    )
    return {"group": _summary(meta, True)}


@route("DELETE", "/groups/{group_id}", roles=("faculty",), rate=("group_write", 60, 300))
def delete_group(req: RequestContext) -> dict:
    user = req.require_auth()
    group_id = str(req.path_params["group_id"])
    _require_owner(group_id, user)

    tbl = aws.table("groups")
    kwargs: dict = {"KeyConditionExpression": Key("pk").eq(_group_pk(group_id))}
    with tbl.batch_writer() as batch:
        while True:
            resp = tbl.query(**kwargs)
            for item in resp.get("Items", []):
                batch.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last
    audit.write_event(
        actor_id=user["user_id"], actor_role=user["role"], event_type="group_deleted",
        resource_type="group", resource_id=group_id, request_id=req.request_id, metadata={},
    )
    return {"deleted": True, "group_id": group_id}


# ----------------------------------------------------------------- members

@route("POST", "/groups/{group_id}/members", roles=("faculty",), rate=("group_write", 60, 300))
def add_member(req: RequestContext) -> dict:
    user = req.require_auth()
    group_id = str(req.path_params["group_id"])
    _require_owner(group_id, user)
    profile = _resolve_student(req.body.get("student_id", ""))
    member_uid = profile["user_id"]

    if _membership(group_id, member_uid):
        return {"added": False, "member": _member_view({
            "user_id": member_uid, "student_id": profile.get("student_id", ""),
            "full_name": profile.get("full_name", ""),
            "institution": profile.get("institution", ""),
            "avatar_seed": profile.get("avatar_seed", ""),
        })}

    now = _now()
    item = {
        "pk": _group_pk(group_id),
        "sk": f"MEMBER#{member_uid}",
        "group_id": group_id,
        "user_id": member_uid,
        "student_id": profile.get("student_id", ""),
        "full_name": profile.get("full_name", ""),
        "institution": profile.get("institution", ""),
        "avatar_seed": profile.get("avatar_seed", ""),
        "added_by": user["user_id"],
        "joined_at": now,
        "gsi2pk": f"MEMBER#{member_uid}",
        "gsi2sk": f"GROUP#{group_id}",
    }
    aws.table("groups").put_item(Item=item)
    audit.write_event(
        actor_id=user["user_id"], actor_role=user["role"], event_type="group_member_added",
        resource_type="group", resource_id=group_id, request_id=req.request_id,
        metadata={"student_id": profile.get("student_id", "")},
    )
    return {"added": True, "member": _member_view(item)}


@route("DELETE", "/groups/{group_id}/members/{student_id}", roles=("faculty",),
       rate=("group_write", 60, 300))
def remove_member(req: RequestContext) -> dict:
    user = req.require_auth()
    group_id = str(req.path_params["group_id"])
    _require_owner(group_id, user)
    profile = _resolve_student(req.path_params["student_id"])
    member_uid = profile["user_id"]
    if not _membership(group_id, member_uid):
        raise not_found()

    aws.table("groups").delete_item(Key={"pk": _group_pk(group_id), "sk": f"MEMBER#{member_uid}"})
    audit.write_event(
        actor_id=user["user_id"], actor_role=user["role"], event_type="group_member_removed",
        resource_type="group", resource_id=group_id, request_id=req.request_id,
        metadata={"student_id": profile.get("student_id", "")},
    )
    return {"removed": True, "student_id": profile.get("student_id", "")}


# ----------------------------------------------------------------- messages

@route("POST", "/groups/{group_id}/messages", roles=SCHOOL, rate=("group_message", 120, 60))
def post_message(req: RequestContext) -> dict:
    user = req.require_auth()
    group_id = str(req.path_params["group_id"])
    meta, is_owner = _authorize(group_id, user)
    body = _clean_text(req.body.get("body"), field="Message", max_len=MESSAGE_MAX, required=True)

    from ..context import load_profile
    sender_profile = load_profile(user["user_id"]) or {}
    now = _now()
    message_id = uuid_hex()
    item = {
        "pk": _group_pk(group_id),
        "sk": f"MSG#{now}#{message_id}",
        "group_id": group_id,
        "message_id": message_id,
        "sender_id": user["user_id"],
        "sender_name": sender_profile.get("full_name", "") or user.get("email", ""),
        "sender_role": user["role"],
        "body": body,
        "created_at": now,
    }
    aws.table("groups").put_item(Item=item)
    audit.write_event(
        actor_id=user["user_id"], actor_role=user["role"], event_type="group_message_sent",
        resource_type="group", resource_id=group_id, request_id=req.request_id,
        metadata={"length": len(body)},
    )
    return {"message": _message_view(item)}


@route("GET", "/groups/{group_id}/messages", roles=SCHOOL)
def get_messages(req: RequestContext) -> dict:
    user = req.require_auth()
    group_id = str(req.path_params["group_id"])
    _authorize(group_id, user)
    try:
        limit = min(max(int(req.query.get("limit", 50)), 1), 100)
    except ValueError:
        limit = 50
    return {"messages": _list_messages(group_id, limit)}
