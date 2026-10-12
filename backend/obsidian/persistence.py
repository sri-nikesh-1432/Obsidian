"""Durable state for the in-process deployment.

Render runs the API with AWS emulated in-process (moto): DynamoDB, S3 and KMS
all live in memory and are wiped on every restart or redeploy. To keep accounts,
documents, groups and keys across restarts *without* an AWS account, this module
snapshots every DynamoDB table into the configured Cloudflare object store
(Workers KV or R2) and restores it on boot.

Document wrapping keys are a special case: the real KMS key material is not
exportable, so a small **software KMS** replaces it here. Its root key lives in
the object store, which keeps every already-wrapped data key usable after a
restart.

Everything is a no-op unless ``settings.state_persistence_enabled`` — i.e. the
deployment is running in-process AWS *and* a Cloudflare object store is
configured. Against real AWS (or plain S3/moto) nothing changes.
"""
from __future__ import annotations

import base64
import gzip
import json
import os
import sys
import threading
import uuid

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import ClientError

from .config import settings

# Reserved object-store keys. The ``system/`` prefix keeps them clear of any
# document ciphertext (documents use ``documents/...``).
_SNAPSHOT_KEY = "system/db-snapshot.json.gz"
_KMS_ROOT_KEY = "system/kms-root"
_KMS_ID_KEY = "system/kms-key-id"

_serializer = TypeSerializer()
_deserializer = TypeDeserializer()

_lock = threading.RLock()
_dirty = threading.Event()
_stop = threading.Event()
_thread: threading.Thread | None = None
_software_kms: "_SoftwareKMS | None" = None


def enabled() -> bool:
    """True when in-process AWS state should be mirrored to Cloudflare."""
    return settings.state_persistence_enabled


# ----------------------------------------------------------------- object store

def _client():
    from . import aws  # lazy: avoids an import cycle with aws.py

    return aws.storage_client()


def _read(key: str) -> bytes | None:
    try:
        return _client().get_object(Bucket=settings.document_bucket, Key=key)["Body"].read()
    except (KeyError, ClientError):
        return None
    except Exception as exc:  # noqa: BLE001 - fail open, just report the type
        print(f"[obsidian] persistence read {key!r} failed: {type(exc).__name__}", file=sys.stderr)
        return None


def _write(key: str, data: bytes) -> None:
    _client().put_object(Bucket=settings.document_bucket, Key=key, Body=data)


# ----------------------------------------------------------------- software KMS

class _SoftwareKMS:
    """Minimal KMS replacement whose key material is stable across restarts.

    Only the four operations the codebase issues are implemented: ``create_key``,
    ``enable_key_rotation``, ``encrypt`` and ``decrypt``. Ciphertexts are
    AES-256-GCM with a random 96-bit nonce and an ``OSK1`` magic prefix so a
    decrypt of unknown material fails loudly instead of silently.
    """

    def __init__(self, root: bytes, key_id: str) -> None:
        self._root = root
        self.key_id = key_id

    def create_key(self, **kwargs) -> dict:
        return {"KeyMetadata": {
            "KeyId": self.key_id,
            "Enabled": True,
            "KeyUsage": "ENCRYPT_DECRYPT",
            "KeyState": "Enabled",
            "Origin": "EXTERNAL",
        }}

    def enable_key_rotation(self, **kwargs) -> dict:
        return {}

    def encrypt(self, Plaintext: bytes = b"", **kwargs) -> dict:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        nonce = os.urandom(12)
        ct = AESGCM(self._root).encrypt(nonce, bytes(Plaintext), None)
        return {"CiphertextBlob": b"OSK1" + nonce + ct, "KeyId": self.key_id}

    def decrypt(self, CiphertextBlob: bytes = b"", **kwargs) -> dict:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        blob = bytes(CiphertextBlob)
        if blob[:4] != b"OSK1":
            raise ValueError("ciphertext was not produced by the software KMS")
        nonce, ct = blob[4:16], blob[16:]
        return {"Plaintext": AESGCM(self._root).decrypt(nonce, ct, None), "KeyId": self.key_id}


def software_kms() -> "_SoftwareKMS":
    """Load (or create once) the persistent software KMS root key."""
    global _software_kms
    with _lock:
        if _software_kms is not None:
            return _software_kms
        raw = _read(_KMS_ROOT_KEY)
        kid = _read(_KMS_ID_KEY)
        if raw and kid:
            root = base64.b64decode(raw)
            key_id = kid.decode("utf-8")
        else:
            root = os.urandom(32)
            key_id = "software/" + uuid.uuid4().hex
            _write(_KMS_ROOT_KEY, base64.b64encode(root))
            _write(_KMS_ID_KEY, key_id.encode("utf-8"))
            print(f"[obsidian] persistence: created software KMS key {key_id!r}", file=sys.stderr)
        _software_kms = _SoftwareKMS(root, key_id)
        return _software_kms


# ----------------------------------------------------------------- snapshot/restore

def _scan_all(tbl) -> list[dict]:
    items: list[dict] = []
    kwargs: dict = {}
    while True:
        resp = tbl.scan(**kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    return items


def snapshot() -> bool:
    """Write every DynamoDB table to the object store as one gzip blob."""
    if not enabled():
        return False
    from . import aws

    aws.ensure_resources()
    payload = {
        name: [_serializer.serialize(item) for item in _scan_all(aws.table(name))]
        for name in aws.TABLES
    }
    blob = gzip.compress(json.dumps(payload).encode("utf-8"))
    _write(_SNAPSHOT_KEY, blob)
    return True


def restore() -> bool:
    """Repopulate DynamoDB from the last snapshot. Returns True if one existed."""
    if not enabled():
        return False
    raw = _read(_SNAPSHOT_KEY)
    if not raw:
        return False
    from . import aws

    aws.ensure_resources()
    payload = json.loads(gzip.decompress(raw).decode("utf-8"))
    total = 0
    for name, items in payload.items():
        if name not in aws.TABLES:
            continue
        tbl = aws.table(name)
        with tbl.batch_writer() as batch:
            for item in items:
                batch.put_item(Item=_deserializer.deserialize(item))
                total += 1
    print(f"[obsidian] persistence: restored {total} items", file=sys.stderr)
    return True


# ----------------------------------------------------------------- autosave

def mark_dirty() -> None:
    """Flag that a mutation happened; the autosave thread persists it soon."""
    if enabled():
        _dirty.set()


def _loop() -> None:
    interval = max(5, int(settings.persist_interval))
    while not _stop.wait(interval):
        if not _dirty.is_set():
            continue
        try:
            if snapshot():
                _dirty.clear()
        except Exception as exc:  # noqa: BLE001 - keep the service alive, retry later
            print(f"[obsidian] persistence snapshot failed: {type(exc).__name__}: {exc}",
                  file=sys.stderr)


def start_autosave() -> None:
    global _thread
    if not enabled():
        return
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(target=_loop, name="obsidian-persist", daemon=True)
        _thread.start()


def flush() -> None:
    """Persist immediately if there are unsaved changes (used on shutdown)."""
    if not enabled() or not _dirty.is_set():
        return
    try:
        if snapshot():
            _dirty.clear()
    except Exception as exc:  # noqa: BLE001 - shutdown path must never raise
        print(f"[obsidian] persistence flush failed: {type(exc).__name__}: {exc}",
              file=sys.stderr)


def reset_cache() -> None:
    """Drop in-process caches (used by tests to emulate a fresh process)."""
    global _software_kms, _thread
    with _lock:
        _software_kms = None
        _thread = None
        _dirty.clear()
        _stop.clear()
