"""Optional malware scanning for uploads via a ClamAV clamd daemon.

Design rules:
- Honesty first: if no scanner is configured we return ``not_scanned`` —
  we never claim a file is clean when nothing inspected it.
- Fail closed: when a scanner IS configured and cannot be reached or the
  scan errors, the upload is rejected if ``malware_fail_closed`` is on
  (the production default).
"""
from __future__ import annotations

import socket
import struct

from .config import settings

# scan results
CLEAN = "clean"
INFECTED = "infected"
NOT_SCANNED = "not_scanned"
ERROR = "error"

_TIMEOUT = 6.0  # seconds


def _clamd_available() -> bool:
    return bool(settings.clamd_host.strip())


def _instream_scan(payload: bytes) -> str:
    """Run a CLAMAV INSTREAM scan over one TCP connection to clamd.

    Returns ``clean`` or ``infected``; raises on transport/protocol errors.
    """
    host = settings.clamd_host.strip()
    port = settings.clamd_port
    chunks: list[bytes] = []
    # Stream the payload in <= 1024-byte chunks as the protocol requires.
    for i in range(0, len(payload), 1024):
        piece = payload[i:i + 1024]
        chunks.append(struct.pack(">I", len(piece)) + piece)
    command = b"zINSTREAM\x00" + b"".join(chunks)

    with socket.create_connection((host, port), timeout=_TIMEOUT) as sock:
        sock.settimeout(_TIMEOUT)
        sock.sendall(command)
        response = b""
        while not response.endswith(b"\x00"):
            data = sock.recv(4096)
            if not data:
                break
            response += data

    text = response.rstrip(b"\x00").decode("utf-8", errors="replace")
    if "FOUND" in text:
        return INFECTED
    if "OK" in text:
        return CLEAN
    raise RuntimeError(f"unexpected clamd response: {text[:120]!r}")


def scan(content: bytes) -> tuple[str, str]:
    """Scan upload content.

    Returns ``(status, detail)`` where status is one of
    ``clean`` / ``infected`` / ``not_scanned``.
    """
    if not _clamd_available():
        # No scanner configured: be honest, never claim "clean".
        return NOT_SCANNED, "no malware scanner configured"
    try:
        status = _instream_scan(content)
        if status == INFECTED:
            return INFECTED, "malware signature detected"
        return CLEAN, "scanned"
    except Exception as exc:  # noqa: BLE001 - report the failure, not internals
        return ERROR, f"{type(exc).__name__}: scan failed"


def enforce(content: bytes) -> str:
    """Scan and decide whether the upload may proceed.

    Returns the scan status to record on the document. Raises ``ApiError``
    (503 UPLOAD_REJECTED) when a configured scanner detects malware or when
    a configured scanner fails while ``malware_fail_closed`` is enabled.
    """
    from .errors import ApiError

    status, detail = scan(content)
    if status == INFECTED:
        raise ApiError("UPLOAD_REJECTED", "The file was rejected by malware scanning.", 413)
    if status == ERROR and settings.malware_fail_closed:
        raise ApiError("UPLOAD_REJECTED", "Malware scanning is unavailable. Please try again later.", 503)
    if status == ERROR and not settings.malware_fail_closed:
        # Explicitly opted out: record honestly that we could not scan.
        return NOT_SCANNED
    return status
