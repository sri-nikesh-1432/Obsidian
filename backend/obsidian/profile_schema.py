"""Role profile field definitions — the single source of truth.

Every role completes a different onboarding form. Both the profile handlers
and account creation read these tables, so the stored shape and the settable
shape can never drift apart.
"""
from __future__ import annotations

COMMON_FIELDS: dict[str, int] = {"full_name": 120, "phone": 30}

ROLE_FIELDS: dict[str, dict[str, int]] = {
    "student": {
        "institution": 160, "course": 160, "education_level": 80,
        "graduation_year": 10, "department": 120, "year": 20,
        "bio": 1200, "cgpa": 12,
    },
    "faculty": {
        "institution": 160, "faculty_id": 60, "department": 120,
        "designation": 80, "office_contact": 120, "bio": 1200,
    },
    "recruiter": {
        "company": 160, "job_title": 80, "industry": 80,
        "company_website": 200, "contact_number": 30,
    },
    "admin": {
        "admin_designation": 80, "organization": 160,
    },
}

ROLE_LIST_FIELDS: dict[str, tuple[str, ...]] = {
    "student": ("skills", "achievements"),
    "faculty": ("expertise",),
    "recruiter": ("hiring_domains",),
    "admin": (),
}

FACULTY_DESIGNATIONS = {
    "assistant professor", "associate professor", "professor", "lecturer",
    "visiting faculty", "research scholar", "teaching assistant",
    "head of department", "dean", "other",
}


# Fields that must be present for a role's onboarding to be considered done.
REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "student": ("full_name", "institution", "course", "education_level",
                "department", "year", "graduation_year"),
    "faculty": ("full_name", "institution", "faculty_id", "department", "designation"),
    "recruiter": ("full_name", "company", "job_title", "industry"),
    "admin": ("full_name", "admin_designation", "organization"),
}


def fields_for(role: str) -> dict[str, int]:
    """Settable scalar fields for a role (common + role-specific)."""
    return {**COMMON_FIELDS, **ROLE_FIELDS.get(role, {})}


def missing_required(role: str, profile: dict) -> list[str]:
    """Required fields still empty for this role (drives completion status)."""
    return [f for f in REQUIRED_FIELDS.get(role, ("full_name",))
            if not str(profile.get(f, "")).strip()]


def initial_verification(role: str, dev_mode: bool) -> str:
    """Faculty and recruiter accounts require approval before protected access.

    Development mode auto-verifies so local flows and tests stay usable; in
    production a new faculty/recruiter account starts ``pending`` and is
    approved by an administrator.
    """
    if role in ("faculty", "recruiter") and not dev_mode:
        return "pending"
    return "verified"


def empty_profile_fields(role: str) -> dict:
    """Empty scalar/list values for a freshly created profile of this role."""
    out: dict = {}
    for field in ROLE_FIELDS.get(role, {}):
        out[field] = ""
    for field in ROLE_LIST_FIELDS.get(role, ()):
        out[field] = []
    return out
