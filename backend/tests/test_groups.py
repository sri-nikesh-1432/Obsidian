"""Faculty groups + group chat: RBAC, membership, and messaging."""
from __future__ import annotations

from conftest import Client, register


def _me(client: Client) -> dict:
    status, data = client.get("/api/v1/auth/me")
    assert status == 200, data
    return data


def _make_faculty() -> Client:
    c = Client()
    register(c, role="faculty", name="Dr. Rao")
    return c


def _make_student(name: str) -> Client:
    c = Client()
    register(c, role="student", name=name)
    return c


def _student_id(client: Client) -> str:
    return _me(client)["profile"]["student_id"]


def test_group_lifecycle_and_rbac():
    faculty = _make_faculty()
    s1 = _make_student("Alice Student")
    s2 = _make_student("Bob Student")

    # only faculty can create groups
    status, _ = s1.post("/api/v1/groups", {"name": "Nope"})
    assert status == 403

    status, data = faculty.post("/api/v1/groups", {"name": "CS-301", "description": "Security"})
    assert status == 200, data
    gid = data["group"]["group_id"]
    assert data["group"]["role"] == "owner"
    assert data["group"]["member_count"] == 0

    # students see nothing until added
    status, data = s1.get("/api/v1/groups")
    assert status == 200 and data["total"] == 0

    # add by student code
    status, data = faculty.post(f"/api/v1/groups/{gid}/members",
                                {"student_id": _student_id(s1)})
    assert status == 200 and data["added"] is True, data

    # idempotent re-add
    status, data = faculty.post(f"/api/v1/groups/{gid}/members",
                                {"student_id": _student_id(s1)})
    assert status == 200 and data["added"] is False

    # unknown code -> generic 404
    status, _ = faculty.post(f"/api/v1/groups/{gid}/members", {"student_id": "OBS-ZZZZ-ZZZZZZ"})
    assert status == 404

    # member sees the group; non-member does not
    status, data = s1.get("/api/v1/groups")
    assert status == 200 and data["total"] == 1
    assert data["groups"][0]["role"] == "member"

    assert s2.get(f"/api/v1/groups/{gid}")[0] == 404

    # only the owner may add members
    assert s1.post(f"/api/v1/groups/{gid}/members",
                   {"student_id": _student_id(s2)})[0] == 403

    # member count reflects the roster
    status, data = faculty.get(f"/api/v1/groups/{gid}")
    assert status == 200 and data["group"]["member_count"] == 1
    assert len(data["members"]) == 1


def test_group_chat_and_rename_delete():
    faculty = _make_faculty()
    s1 = _make_student("Alice Student")
    s2 = _make_student("Bob Student")

    gid = faculty.post("/api/v1/groups", {"name": "Group A"})[1]["group"]["group_id"]
    faculty.post(f"/api/v1/groups/{gid}/members", {"student_id": _student_id(s1)})

    # both members can talk; outsiders cannot
    assert s1.post(f"/api/v1/groups/{gid}/messages", {"body": "hello"})[0] == 200
    assert faculty.post(f"/api/v1/groups/{gid}/messages", {"body": "welcome"})[0] == 200
    assert s2.post(f"/api/v1/groups/{gid}/messages", {"body": "intrude"})[0] == 404

    # empty message rejected
    assert s1.post(f"/api/v1/groups/{gid}/messages", {"body": "   "})[0] == 422

    status, data = s1.get(f"/api/v1/groups/{gid}/messages")
    assert status == 200
    bodies = [m["body"] for m in data["messages"]]
    assert bodies == ["hello", "welcome"], bodies

    # rename: owner only
    assert s1.patch(f"/api/v1/groups/{gid}", {"name": "Hacked"})[0] == 403
    status, data = faculty.patch(f"/api/v1/groups/{gid}", {"name": "Group B"})
    assert status == 200 and data["group"]["name"] == "Group B"

    # remove member then they lose access
    status, data = faculty.delete(f"/api/v1/groups/{gid}/members/{_student_id(s1)}")
    assert status == 200 and data["removed"] is True
    assert s1.get(f"/api/v1/groups/{gid}")[0] == 404

    # delete the group
    assert faculty.delete(f"/api/v1/groups/{gid}")[0] == 200
    assert faculty.get(f"/api/v1/groups/{gid}")[0] == 404


def test_group_activity_is_audited():
    faculty = _make_faculty()
    s1 = _make_student("Alice Student")
    gid = faculty.post("/api/v1/groups", {"name": "Audited"})[1]["group"]["group_id"]
    faculty.post(f"/api/v1/groups/{gid}/members", {"student_id": _student_id(s1)})
    s1.post(f"/api/v1/groups/{gid}/messages", {"body": "hi"})

    status, data = faculty.get("/api/v1/activity?limit=50")
    assert status == 200
    types = {e["event_type"] for e in data["events"]}
    assert {"group_created", "group_member_added"} <= types, types

    status, data = s1.get("/api/v1/activity?limit=50")
    assert status == 200
    assert "group_message_sent" in {e["event_type"] for e in data["events"]}
