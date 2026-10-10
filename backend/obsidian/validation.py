"""Server-side upload validation.

The client is never trusted: extension allowlist, MIME sniffing via magic
bytes, size limits, and filename sanitization are enforced here.
"""
from __future__ import annotations

import os
import re
import unicodedata

from .config import settings
from .errors import ApiError

# Extension allowlist (deployment policy). Executables are never accepted.
ALLOWED_EXTENSIONS = {
    "pdf", "png", "jpg", "jpeg", "webp", "gif", "txt", "md", "csv",
    "docx", "xlsx", "pptx", "rtf", "json", "log",
}

DANGEROUS_PATTERNS = re.compile(r"(\.exe|\.dll|\.bat|\.cmd|\.sh|\.msi|\.scr|\.js|\.vbs|\.jar|\.py)$", re.I)

MAX_FILENAME_LEN = 180

# Text formats safe for editor-permitted shares
TEXT_EXTENSIONS = {"txt", "md", "csv", "json", "log"}


def sanitize_filename(name: str) -> str:
    """Strip path components, traversal, control characters, and bound length."""
    if not name:
        raise ApiError("UPLOAD_REJECTED", "A filename is required.", 400)
    name = unicodedata.normalize("NFKC", name)
    # Never allow path components or traversal
    name = name.replace("\\", "/").split("/")[-1]
    name = name.replace("\x00", "")
    name = "".join(c for c in name if c.isprintable())
    name = name.strip().lstrip(".")
    # collapse whitespace
    name = re.sub(r"\s+", " ", name)
    if not name:
        raise ApiError("UPLOAD_REJECTED", "The filename is not valid.", 400)
    if DANGEROUS_PATTERNS.search(name):
        raise ApiError("UPLOAD_REJECTED", "This file type is not allowed.", 400)
    if len(name) > MAX_FILENAME_LEN:
        stem, ext = os.path.splitext(name)
        name = stem[: MAX_FILENAME_LEN - len(ext)] + ext
    return name


def extension_of(filename: str) -> str:
    return os.path.splitext(filename)[1].lstrip(".").lower()


def validate_file(filename: str, content: bytes) -> tuple[str, str]:
    """Validate size, extension and magic bytes. Returns (filename, mime)."""
    if not content:
        raise ApiError("UPLOAD_REJECTED", "The file is empty.", 400)
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise ApiError(
            "UPLOAD_REJECTED",
            f"File exceeds the {settings.max_upload_mb} MB upload limit.",
            400,
        )
    filename = sanitize_filename(filename)
    ext = extension_of(filename)
    if not ext or ext not in ALLOWED_EXTENSIONS:
        raise ApiError(
            "UPLOAD_REJECTED",
            "This file type is not allowed. Allowed: " + ", ".join(sorted(ALLOWED_EXTENSIONS)),
            400,
        )
    mime = _sniff(content, ext)
    if mime is None:
        raise ApiError(
            "UPLOAD_REJECTED",
            "The file content does not match its extension.",
            400,
        )
    return filename, mime


def _sniff(content: bytes, ext: str) -> str | None:
    """Verify magic bytes for known binary types; sanity-check text types."""
    head = content[:16]
    binary_signatures: dict[str, list[tuple[bytes, str]]] = {
        "pdf": [(b"%PDF-", "application/pdf")],
        "png": [(b"\x89PNG\r\n\x1a\n", "image/png")],
        "jpg": [(b"\xff\xd8\xff", "image/jpeg")],
        "jpeg": [(b"\xff\xd8\xff", "image/jpeg")],
        "gif": [(b"GIF87a", "image/gif"), (b"GIF89a", "image/gif")],
        "webp": [(b"RIFF", "image/webp")],  # refined below
        "zip_container": [(b"PK\x03\x04", "application/zip")],
    }
    if ext in ("pdf", "png", "jpg", "jpeg", "gif"):
        for sig, mime in binary_signatures[ext]:
            if content.startswith(sig):
                return mime
        return None
    if ext == "webp":
        if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
            return "image/webp"
        return None
    if ext in ("docx", "xlsx", "pptx"):
        if content.startswith(b"PK\x03\x04"):
            return "application/zip"
        return None
    if ext in ("txt", "md", "csv", "json", "log", "rtf"):
        if ext == "rtf":
            return "application/rtf" if content.startswith(b"{\\rtf") else None
        sample = content[:4096]
        if b"\x00" in sample:
            return None
        # Reject content that looks executable/binary
        suspicious = sum(1 for b in sample if b < 9 or (13 < b < 32))
        if suspicious / max(len(sample), 1) > 0.15:
            return None
        try:
            sample.decode("utf-8")
        except UnicodeDecodeError:
            try:
                sample.decode("latin-1")
            except Exception:
                return None
        return {
            "txt": "text/plain", "md": "text/markdown", "csv": "text/csv",
            "json": "application/json", "log": "text/plain",
        }.get(ext, "text/plain")
    return None
