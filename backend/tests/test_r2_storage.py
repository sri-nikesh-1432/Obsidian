"""End-to-end proof that the Cloudflare R2 object-store path works.

R2 speaks the S3 protocol, so this test stands up a tiny in-process
S3-compatible server, points ``OBSIDIAN_R2_ENDPOINT`` at it, and runs the real
storage + decrypt code against it in a *fresh subprocess* (so moto is started
with the R2 passthrough from the outset). It asserts the bytes really land on —
and come back off — the endpoint, and that delete removes them.

No Cloudflare credentials or network access are needed.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve()


def test_r2_object_store_roundtrip():
    proc = subprocess.run(
        [sys.executable, str(HERE), "--probe"],
        cwd=str(BACKEND_DIR), capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    assert "R2_E2E_OK" in proc.stdout, proc.stdout + proc.stderr


# --------------------------------------------------------------------- probe
# Runs in a child process (see __main__ guard) so environment + moto bootstrap
# are clean; pytest only ever sees the subprocess result.

def _probe() -> int:
    import base64
    import os
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    store: dict[tuple[str, str], bytes] = {}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _split(self):
            parts = self.path.lstrip("/").split("/", 1)
            return parts[0], (parts[1] if len(parts) > 1 else "")

        def _read_body(self):
            if self.headers.get("Expect", "").lower() == "100-continue":
                self.send_response_only(100)
                self.end_headers()
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(n) if n else b""

        def do_PUT(self):
            bucket, key = self._split()
            store[(bucket, key)] = self._read_body()
            self.send_response(200)
            self.send_header("ETag", '"probe"')
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):
            bucket, key = self._split()
            body = store.get((bucket, key))
            if body is None:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("ETag", '"probe"')
            self.end_headers()
            self.wfile.write(body)

        def do_DELETE(self):
            bucket, key = self._split()
            store.pop((bucket, key), None)
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):  # keep the probe output clean
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    endpoint = f"http://127.0.0.1:{port}"

    os.environ.update({
        "OBSIDIAN_LOCAL_AWS": "true",
        "OBSIDIAN_DEV_MODE": "true",
        "OBSIDIAN_TABLE_PREFIX": "obsidian-r2probe",
        "OBSIDIAN_STORAGE_BACKEND": "r2",
        "OBSIDIAN_R2_ENDPOINT": endpoint,
        "OBSIDIAN_R2_ACCESS_KEY_ID": "probe-access-key",
        "OBSIDIAN_R2_SECRET_ACCESS_KEY": "probe-secret-key",
        "OBSIDIAN_R2_REGION": "auto",
        "OBSIDIAN_DOCUMENT_BUCKET": "probe-bucket",
    })
    sys.path.insert(0, str(BACKEND_DIR))

    from obsidian import aws, crypto
    from obsidian.functions import documents as docs

    aws.ensure_resources()
    assert aws.settings.r2_configured, "R2 not configured"
    client = aws.storage_client()
    assert client.meta.endpoint_url == endpoint, client.meta.endpoint_url

    # 1. raw round-trip through the R2 client
    payload = b"obsidian-r2-roundtrip\x00" + os.urandom(16)
    key = "documents/probe/content"
    client.put_object(Bucket="probe-bucket", Key=key, Body=payload)
    assert store.get(("probe-bucket", key)) == payload, "object not stored on endpoint"
    got = client.get_object(Bucket="probe-bucket", Key=key)["Body"].read()
    assert got == payload, "object did not round-trip"

    # 2. full crypto + handler path: encrypt -> store on R2 -> decrypt via handler
    doc_id = "probe-doc-0001"
    plaintext = b"the quick brown fox jumps over the lazy dog " * 10
    enc = crypto.encrypt_bytes(plaintext, doc_id)
    assert aws.object_store_sse(enc.key_id) == {}, "R2 must not send aws:kms SSE"
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
    assert ("probe-bucket", storage_key) not in store, "object not deleted"

    print(json.dumps({
        "result": "R2_E2E_OK",
        "endpoint": endpoint,
        "roundtrip_bytes": len(payload),
        "decrypted_bytes": len(plaintext),
        "stored_after_delete": ("probe-bucket", storage_key) in store,
    }))
    server.shutdown()
    return 0


if __name__ == "__main__" and "--probe" in sys.argv:
    raise SystemExit(_probe())
