"""Role-based onboarding: each role has its own fields and validation."""
from __future__ import annotations

from conftest import Client, register


def test_student_onboarding(client: Client):
    register(client)
    status, data = client.patch("/api/v1/profile", {
        "full_name": "Arjun Mehta", "institution": "State University",
        "course": "B.Tech CS", "education_level": "Bachelor's",
        "department": "CSE", "year": "3rd year", "graduation_year": "2027",
        "cgpa": "9.1", "skills": ["Python"],
    })
    assert status == 200, data
    assert data["profile"]["cgpa"] == "9.1"
    assert data["profile"]["skills"] == ["Python"]
    _, me = client.get("/api/v1/auth/me")
    assert me["profile"]["student_id"].startswith("OBS-")


def test_student_cannot_set_faculty_fields(client: Client):
    register(client)
    status, _ = client.patch("/api/v1/profile", {"faculty_id": "FAC-1"})
    assert status == 422


def test_faculty_onboarding(client: Client):
    register(client, role="faculty")
    status, data = client.patch("/api/v1/profile", {
        "full_name": "Dr. Rao", "institution": "State University", "faculty_id": "FAC-1",
        "department": "CSE", "designation": "Professor", "expertise": ["Databases", "Security"],
        "office_contact": "Block C",
    })
    assert status == 200, data
    assert data["profile"]["expertise"] == ["Databases", "Security"]
    # no student academic fields are exposed to (or settable by) faculty
    assert "cgpa" not in data["profile"]
    assert "year" not in data["profile"]
    assert client.patch("/api/v1/profile", {"cgpa": "9"})[0] == 422
    # designations are validated
    assert client.patch("/api/v1/profile", {"designation": "Wizard"})[0] == 422


def test_recruiter_onboarding(client: Client):
    register(client, role="recruiter")
    status, data = client.patch("/api/v1/profile", {
        "full_name": "Dana Cole", "company": "Northwind", "job_title": "Talent Partner",
        "industry": "Software", "hiring_domains": ["Backend", "Data"],
    })
    assert status == 200, data
    assert data["profile"]["company"] == "Northwind"
    assert data["profile"]["hiring_domains"] == ["Backend", "Data"]
    assert "course" not in data["profile"]
    assert client.patch("/api/v1/profile", {"institution": "State University"})[0] == 422


def test_admin_onboarding(client: Client):
    register(client, role="admin")
    status, data = client.patch("/api/v1/profile", {
        "full_name": "Sys Admin", "admin_designation": "Platform Administrator",
        "organization": "State University",
    })
    assert status == 200, data
    assert data["profile"]["organization"] == "State University"
    assert "student_id" not in data["profile"]


def test_role_is_never_client_settable(client: Client):
    register(client)
    status, _ = client.patch("/api/v1/profile", {"role": "admin"})
    assert status in (200, 422)
    _, me = client.get("/api/v1/auth/me")
    assert me["role"] == "student"


def test_onboarding_status_reports_missing_fields(client: Client):
    register(client)  # profile not completed yet
    status, data = client.get("/api/v1/profile")
    assert status == 200
    assert data["onboarding"]["role"] == "student"
    assert data["onboarding"]["complete"] is False
    assert "institution" in data["onboarding"]["missing"]

    client.patch("/api/v1/profile", {
        "institution": "State University", "course": "B.Tech CS",
        "education_level": "Bachelor's", "department": "CSE", "year": "3rd year",
        "graduation_year": "2027",
    })
    _, data = client.get("/api/v1/profile")
    assert data["onboarding"]["complete"] is True
    assert data["onboarding"]["missing"] == []
