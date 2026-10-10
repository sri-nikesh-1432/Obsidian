"""Identifier generation.

All internal identifiers are opaque UUIDs. The student lookup ID is a
non-guessable opaque token because it doubles as a lookup credential.
"""
from __future__ import annotations

import secrets
import uuid

# Crockford-style alphabet (no I, L, O, U) — easy to read aloud
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def uuid_hex() -> str:
    return uuid.uuid4().hex


def new_student_id() -> str:
    """Opaque, non-guessable student lookup identifier (not a sequence)."""
    body = "".join(_ALPHABET[secrets.randbelow(len(_ALPHABET))] for _ in range(10))
    return f"OBS-{body[:4]}-{body[4:]}"
