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
# "Everything" a student is likely to archive, minus anything runnable.
ALLOWED_EXTENSIONS = {
    # documents & structured text
    "pdf", "txt", "md", "csv", "rtf", "json", "xml", "yaml", "yml", "toml",
    "ini", "cfg", "log", "srt", "vtt",
    "docx", "xlsx", "pptx", "odt", "ods", "odp", "odg", "odf", "epub",
    # images
    "png", "jpg", "jpeg", "webp", "gif", "bmp", "tif", "tiff", "ico",
    "heic", "heif", "avif",
    # audio
    "mp3", "wav", "m4a", "aac", "ogg", "oga", "opus", "flac", "wma", "amr",
    # video
    "mp4", "m4v", "mov", "webm", "avi", "mkv", "wmv", "flv", "mpg", "mpeg",
    "3gp", "3g2",
    # archives
    "zip", "tar", "gz", "tgz", "rar", "7z", "bz2", "xz", "zst",
    # design / other binary
    "psd", "ai", "dwg",
}

DANGEROUS_PATTERNS = re.compile(r"(\.exe|\.dll|\.bat|\.cmd|\.sh|\.msi|\.scr|\.js|\.vbs|\.jar|\.py)$", re.I)

MAX_FILENAME_LEN = 180
MAX_FOLDER_LEN = 400

# Text formats safe for editor-permitted shares
TEXT_EXTENSIONS = {
    "txt", "md", "csv", "json", "log", "xml", "yaml", "yml", "toml",
    "ini", "cfg", "srt", "vtt",
}

# Magic-byte constants
_ASF = b"\x30\x26\xb2\x75\x8e\x66\xcf\x11"
_MACHO = (b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf",
          b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe")
_TEXT_MIME = {
    "txt": "text/plain", "md": "text/markdown", "csv": "text/csv",
    "json": "application/json", "log": "text/plain", "xml": "application/xml",
    "yaml": "application/yaml", "yml": "application/yaml",
    "toml": "application/toml", "ini": "text/plain", "cfg": "text/plain",
    "srt": "application/x-subrip", "vtt": "text/vtt",
}
_IMAGE_MIME = {"heic": "image/heic", "heif": "image/heif", "avif": "image/avif"}
_VIDEO_MIME = {
    "mp4": "video/mp4", "m4v": "video/x-m4v", "mov": "video/quicktime",
    "webm": "video/webm", "mkv": "video/x-matroska", "3gp": "video/3gpp",
    "3g2": "video/3gpp2",
}
_ZIP_BASED = {"docx", "xlsx", "pptx", "odt", "ods", "odp", "odg", "odf", "epub", "zip"}


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


def sanitize_folder(folder: str) -> str:
    """Normalize an optional relative folder path.

    Keeps the nested structure (``a/b/c``) while removing traversal, path
    components, control characters, and unsafe filename characters. An empty
    or invalid value becomes ``""`` (root). Folder names are display-only and
    never used to build storage keys.
    """
    if not folder:
        return ""
    raw = unicodedata.normalize("NFKC", str(folder)).replace("\\", "/")
    parts: list[str] = []
    for segment in raw.split("/"):
        segment = segment.replace("\x00", "")
        segment = "".join(c for c in segment if c.isprintable() and c not in '<>:"|?*')
        segment = re.sub(r"\s+", " ", segment).strip().strip(".")
        if not segment or segment in (".", ".."):
            continue
        parts.append(segment[:120])
    out = "/".join(parts)
    if len(out) > MAX_FOLDER_LEN:
        out = out[:MAX_FOLDER_LEN].rsplit("/", 1)[0]
    return out


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


def _looks_executable(head: bytes) -> bool:
    """Reject runnable payloads regardless of the claimed extension."""
    return (
        head.startswith(b"MZ")
        or head.startswith(b"\x7fELF")
        or head.startswith(b"#!")
        or head[:4] in _MACHO
    )


def _sniff(content: bytes, ext: str) -> str | None:
    """Verify magic bytes for known binary types; sanity-check text types."""
    head = content[:64]
    if ext not in TEXT_EXTENSIONS and ext != "rtf" and _looks_executable(head):
        return None

    # ---- text-like formats ------------------------------------------------
    if ext in TEXT_EXTENSIONS:
        return _sniff_text(content, ext)
    if ext == "rtf":
        return "application/rtf" if content.startswith(b"{\\rtf") else None

    # ---- documents --------------------------------------------------------
    if ext == "pdf":
        return "application/pdf" if content.startswith(b"%PDF-") else None
    if ext in _ZIP_BASED:
        return "application/zip" if head[:2] == b"PK" else None

    # ---- images -----------------------------------------------------------
    if ext == "png":
        return "image/png" if content.startswith(b"\x89PNG\r\n\x1a\n") else None
    if ext in ("jpg", "jpeg"):
        return "image/jpeg" if content.startswith(b"\xff\xd8\xff") else None
    if ext == "gif":
        return "image/gif" if content.startswith((b"GIF87a", b"GIF89a")) else None
    if ext == "webp":
        return "image/webp" if content.startswith(b"RIFF") and content[8:12] == b"WEBP" else None
    if ext == "bmp":
        return "image/bmp" if content.startswith(b"BM") else None
    if ext in ("tif", "tiff"):
        return "image/tiff" if content.startswith((b"II*\x00", b"MM\x00*")) else None
    if ext == "ico":
        return "image/x-icon" if content.startswith(b"\x00\x00\x01\x00") else None
    if ext in _IMAGE_MIME:
        return _IMAGE_MIME[ext] if content[4:8] == b"ftyp" else None

    # ---- audio ------------------------------------------------------------
    if ext == "wav":
        return "audio/wav" if content.startswith(b"RIFF") and content[8:12] == b"WAVE" else None
    if ext == "mp3":
        if content.startswith(b"ID3") or (len(content) > 1 and content[0] == 0xFF and (content[1] & 0xE0) == 0xE0):
            return "audio/mpeg"
        return None
    if ext == "m4a":
        return "audio/mp4" if content[4:8] == b"ftyp" else None
    if ext == "aac":
        return "audio/aac" if (len(content) > 1 and content[0] == 0xFF and (content[1] & 0xF6) == 0xF0) else None
    if ext in ("ogg", "oga", "opus"):
        return "audio/ogg" if content.startswith(b"OggS") else None
    if ext == "flac":
        return "audio/flac" if content.startswith(b"fLaC") else None
    if ext == "wma":
        return "audio/x-ms-wma" if content.startswith(_ASF) else None
    if ext == "amr":
        return "audio/amr" if content.startswith(b"#!AMR") else None

    # ---- video ------------------------------------------------------------
    if ext in ("mp4", "m4v", "mov", "3gp", "3g2"):
        if content[4:8] in (b"ftyp", b"moov", b"mdat", b"free", b"wide", b"skip"):
            return _VIDEO_MIME[ext]
        return None
    if ext in ("webm", "mkv"):
        return _VIDEO_MIME[ext] if content.startswith(b"\x1a\x45\xdf\xa3") else None
    if ext == "avi":
        return "video/x-msvideo" if content.startswith(b"RIFF") and content[8:12] == b"AVI " else None
    if ext == "wmv":
        return "video/x-ms-wmv" if content.startswith(_ASF) else None
    if ext == "flv":
        return "video/x-flv" if content.startswith(b"FLV") else None
    if ext in ("mpg", "mpeg"):
        return "video/mpeg" if content.startswith((b"\x00\x00\x01\xba", b"\x00\x00\x01\xb3")) else None

    # ---- archives ---------------------------------------------------------
    if ext in ("gz", "tgz"):
        return "application/gzip" if head[:2] == b"\x1f\x8b" else None
    if ext == "bz2":
        return "application/x-bzip2" if head[:3] == b"BZh" else None
    if ext == "xz":
        return "application/x-xz" if head[:6] == b"\xfd7zXZ\x00" else None
    if ext == "zst":
        return "application/zstd" if head[:4] == b"\x28\xb5\x2f\xfd" else None
    if ext == "rar":
        return "application/vnd.rar" if head[:4] == b"Rar!" else None
    if ext == "7z":
        return "application/x-7z-compressed" if head[:6] == b"7z\xbc\xaf\x27\x1c" else None
    if ext == "tar":
        return "application/x-tar" if len(content) > 262 and content[257:262] == b"ustar" else None

    # ---- design -----------------------------------------------------------
    if ext == "psd":
        return "image/vnd.adobe.photoshop" if content.startswith(b"8BPS") else None

    # Allowed extension without a specific signature (e.g. ai, dwg): accept a
    # generic binary blob, having already rejected executables above.
    return "application/octet-stream"


def _sniff_text(content: bytes, ext: str) -> str | None:
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
    return _TEXT_MIME.get(ext, "text/plain")
