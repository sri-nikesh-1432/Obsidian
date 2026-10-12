"""End-to-end proof that the Cloudflare Workers KV object-store path works.

Workers KV is *not* S3-compatible, so this test stands up a tiny in-process
HTTP server that mimics the `/accounts/{id}/storage/kv/namespaces/{ns}/values`
REST endpoints, points ``OBSIDIAN_CF_API_BASE`` at it, and runs the real storage
+ decrypt code against it in a *fresh subprocess*. It asserts the bytes really
land on — and come back off — the endpoint, and that delete removes them.

No Cloudflare credentials or network access are needed.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve()


def test_kv_object_store_roundtrip():
    proc = subprocess.run(
        [sys.executable, str(HERE), "--probe"],
        cwd=str(BACKEND_DIR), capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    assert "KV_E2E_OK" in proc.stdout, proc.stdout + proc.stderr


# --------------------------------------------------------------------- probe
# Runs in a child process (see __main__ guard) so environment + moto bootstrap
# are clean; pytest only ever sees the subprocess result.

def _probe() -> int:
    import base64
    import os
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import unquote

    store: dict[str, bytes] = {}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _key(self):
            # .../storage/kv/namespaces/{ns}/values/{urlencoded-key}
            marker = "/values/"
            tail = self.path.split(marker, 1)[1] if marker in self.path else ""
            return unquote(tail.split("?", 1)[0])

        def _body(self):
            if self.headers.get("Expect", "").lower() == "100-continue":
                self.send_response_only(100)
                self.end_headers()
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(n) if n else b""

        def _reply(self, status: int, body: bytes = b"") -> None:
            payload = json.dumps({"success": 200 <= status < 300, "result": None}).encode()
            payload = payload if not body else body
            self.send_response(status)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_PUT(self):
            store[self._key()] = self._body()
            self._reply(200)

        def do_GET(self):
            body = store.get(self._key())
            if body is None:
                self._reply(404)
                return
            self._reply(200, body)

        def do_DELETE(self):
            store.pop(self._key(), None)
            self._reply(200)

        def log_message(self, *args):  # keep the probe output clean
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    endpoint = f"http://127.0.0.1:{port}"

    os.environ.update({
        "OBSIDIAN_LOCAL_AWS": "true",
        "OBSIDIAN_DEV_MODE": "true",
        "OBSIDIAN_TABLE_PREFIX": "obsidian-kvprobe",
        "OBSIDIAN_STORAGE_BACKEND": "kv",
        "OBSIDIAN_CF_API_BASE": endpoint,
        "OBSIDIAN_CF_ACCOUNT_ID": "probe-account",
        "OBSIDIAN_CF_API_TOKEN": "probe-token",
        "OBSIDIAN_KV_NAMESPACE_ID": "probe-namespace",
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
    })
    sys.path.insert(0, str(BACKEND_DIR))

    from obsidian import aws, crypto
    from obsidian.functions import documents as docs

    aws.ensure_resources()
    assert aws.settings.kv_configured, "Workers KV not configured"

    # 1. raw round-trip through the KV shim
    client = aws.storage_client()
    payload = b"obsidian-kv-roundtrip\x00" + os.urandom(16)
    key = "documents/probe/content"
    client.put_object(Bucket="probe-bucket", Key=key, Body=payload)
    assert store.get(key) == payload, "object not stored on endpoint"
    got = client.get_object(Bucket="probe-bucket", Key=key)["Body"].read()
    assert got == payload, "object did not round-trip"

    # 2. full crypto + handler path: encrypt -> store on KV -> decrypt via handler
    doc_id = "probe-doc-0001"
    plaintext = b"the quick brown fox jumps over the lazy dog " * 10
    enc = crypto.encrypt_bytes(plaintext, doc_id)
    assert aws.object_store_sse(enc.key_id) == {}, "Workers KV must not send aws:kms SSE"
    storage_key = f"documents/{doc_id}/content"
    client.put_object(Bucket="probe-bucket", Key=storage_key, Body=enc.ciphertext,
                      **aws.object_store_sse(enc.key_id))
    doc = {
        "document_id": doc_id,
        "filename": "probe.txt",
        "mime_type": "text/plain",
        "storage_key": storage_key,
        "nonce": enc.nonce.hex(),
        "wrapped_dek": enc.wrapped_dek.hex(),
        "key_id": enc.key_id,
        "ciphertext_sha256": enc.ciphertext_sha256,
        "plaintext_sha256": enc.plaintext_sha256,
        "owner_id": "probe-user",
    }
    out = docs.decrypt_document(doc, "probe-request")
    assert base64.b64decode(out["content_base64"]) == plaintext, "decrypt mismatch"

    # 3. delete removes the object from the endpoint
    client.delete_object(Bucket="probe-bucket", Key=storage_key)
    assert storage_key not in store, "object not deleted"

    print(json.dumps({
        "result": "KV_E2E_OK",
        "endpoint": endpoint,
        "roundtrip_bytes": len(payload),
        "decrypted_bytes": len(plaintext),
        "stored_after_delete": storage_key in store,
    }))
    server.shutdown()
    return 0


if __name__ == "__main__" and "--probe" in sys.argv:
    raise SystemExit(_probe())
