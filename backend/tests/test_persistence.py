"""End-to-end proof that in-memory AWS state survives a restart.

The deployment runs AWS in-process (moto), so DynamoDB/KMS vanish on restart.
This probe stands up a tiny in-process Workers KV REST server, points the app at
it, writes a user and an encrypted payload, snapshots to "Cloudflare", then
simulates a *restart* (moto torn down and rebuilt) and asserts the user row and
the wrapped document key both come back intact.

No Cloudflare credentials or network access are needed.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve()


def test_state_survives_restart():
    proc = subprocess.run(
        [sys.executable, str(HERE), "--probe"],
        cwd=str(BACKEND_DIR), capture_output=True, text=True, timeout=240,
    )
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    assert "PERSIST_E2E_OK" in proc.stdout, proc.stdout + proc.stderr


# --------------------------------------------------------------------- probe

def _probe() -> int:
    import base64
    import json
    import os
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import unquote

    store: dict[str, bytes] = {}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _key(self):
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

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    endpoint = f"http://127.0.0.1:{port}"

    os.environ.update({
        "OBSIDIAN_LOCAL_AWS": "true",
        "OBSIDIAN_DEV_MODE": "true",
        "OBSIDIAN_TABLE_PREFIX": "obsidian-persistprobe",
        "OBSIDIAN_STORAGE_BACKEND": "kv",
        "OBSIDIAN_CF_API_BASE": endpoint,
        "OBSIDIAN_CF_ACCOUNT_ID": "probe-account",
        "OBSIDIAN_CF_API_TOKEN": "probe-token",
        "OBSIDIAN_KV_NAMESPACE_ID": "probe-namespace",
        "OBSIDIAN_PERSIST_STATE": "true",
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
    })
    sys.path.insert(0, str(BACKEND_DIR))

    from obsidian import aws, crypto, persistence

    assert persistence.enabled(), "durable state should be enabled"

    aws.ensure_resources()

    # a user row and an encrypted document wrapped by the (software) KMS
    aws.table("users").put_item(Item={
        "pk": "USER#probe", "sk": "META", "email": "probe@obsidian.test",
        "role": "student", "status": "active",
    })
    enc = crypto.encrypt_bytes(b"durable payload", "probe-doc")
    assert enc.key_id.startswith("software/"), enc.key_id

    assert persistence.snapshot(), "snapshot() should report success"
    assert "system/db-snapshot.json.gz" in store, "snapshot not written to endpoint"

    # the server persists via mark_dirty() + flush() on the way down; exercise it
    store.pop("system/db-snapshot.json.gz", None)
    persistence.mark_dirty()
    persistence.flush()
    assert "system/db-snapshot.json.gz" in store, "flush() did not write the snapshot"

    # ---- simulate a process restart --------------------------------
    aws.stop_local_mock()          # tear down the in-memory AWS
    persistence.reset_cache()      # forget in-process caches

    aws.ensure_resources()         # fresh, empty in-memory AWS
    assert aws.table("users").get_item(
        Key={"pk": "USER#probe", "sk": "META"}).get("Item") is None, \
        "precondition: restart should start empty"

    assert persistence.restore(), "restore() should find the snapshot"

    # ---- assert everything came back -------------------------------
    user = aws.table("users").get_item(Key={"pk": "USER#probe", "sk": "META"}).get("Item")
    assert user and user["email"] == "probe@obsidian.test", "user row did not survive restart"

    plaintext = crypto.decrypt_bytes(
        ciphertext=enc.ciphertext, nonce=enc.nonce, wrapped_dek=enc.wrapped_dek,
        document_id="probe-doc", expected_ciphertext_sha256=enc.ciphertext_sha256,
    )
    assert plaintext == b"durable payload", "wrapped key did not survive restart"

    print(json.dumps({
        "result": "PERSIST_E2E_OK",
        "endpoint": endpoint,
        "snapshot_bytes": len(store["system/db-snapshot.json.gz"]),
        "kms_key_id": enc.key_id,
    }))
    server.shutdown()
    return 0


if __name__ == "__main__" and "--probe" in sys.argv:
    raise SystemExit(_probe())
