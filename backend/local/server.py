"""Local API Gateway-compatible dev server.

Runs the exact Lambda handlers that deploy to AWS API Gateway + Lambda.
AWS services (DynamoDB, S3, KMS) are served in-process by moto so the
boto3 code path is identical to production.

Usage:  python backend/local/server.py  (default port 5000)
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import sys
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qsl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("OBSIDIAN_LOCAL_AWS", "true")
os.environ.setdefault("OBSIDIAN_DEV_MODE", "true")
os.environ.setdefault("OBSIDIAN_DEMO_SHOW_ERRORS", "1")
os.environ.setdefault("OBSIDIAN_RELAX_RATE_LIMITS", "1")
print("[server] env OBSIDIAN_DEMO_SHOW_ERRORS =", os.environ.get("OBSIDIAN_DEMO_SHOW_ERRORS"), file=sys.stderr)

from obsidian import aws                      # noqa: E402
from obsidian.config import settings          # noqa: E402
from obsidian.security import limiter         # noqa: E402
print("[server] importing gateway…", file=sys.stderr)
from obsidian.gateway import dispatch          # noqa: E402
print("[server] imported gateway:", dispatch, file=sys.stderr)

HOST = os.environ.get("OBSIDIAN_API_HOST", "127.0.0.1")
PORT = int(os.environ.get("OBSIDIAN_API_PORT", "5000"))
# Optional single-container mode: serve the built SPA from the same origin as
# the API, so a Docker/VM deploy needs no separate static host or CORS setup.
STATIC_DIR = os.environ.get("OBSIDIAN_STATIC_DIR", "")

ALLOWED_ORIGINS = set(settings.origins)

HEALTH_BODY = json.dumps({
    "status": "ok",
    "service": "obsidian-api",
    "version": "0.1.0",
    "environment": settings.env,
    "port": PORT,
}).encode("utf-8")

HEALTH_HTML = b"""<!doctype html>
<html>
<head><title>OBSIDIAN Local Dev</title></head>
<body>
<h1>OBSIDIAN API is running</h1>
<p>Frontend preview: <a href="http://localhost:5173">http://localhost:5173</a></p>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "OBSIDIAN/dev"

    # ------------------------------------------------------------ debug
    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ------------------------------------------------------------ CORS
    def _cors_headers(self) -> list[tuple[str, str]]:
        origin = self.headers.get("Origin", "")
        out = []
        if origin and (origin in ALLOWED_ORIGINS or settings.is_prod is False
                       and origin.rsplit(":", 1)[0] in {o.rsplit(":", 1)[0] for o in ALLOWED_ORIGINS}):
            out.append(("Access-Control-Allow-Origin", origin))
            out.append(("Access-Control-Allow-Credentials", "true"))
            out.append(("Vary", "Origin"))
        return out

    # ---------------------------------------------------------- health
    def do_GET(self) -> None:  # noqa: N802
        print(f"[server] do_GET path={self.path!r}", file=sys.stderr)
        if self.path == "/health":
            print("[server] -> health 200", file=sys.stderr)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "http://localhost:5173")
            self.send_header("Content-Length", str(len(HEALTH_BODY)))
            self.end_headers()
            self.wfile.write(HEALTH_BODY)
            return
        if self.path == "/" and not STATIC_DIR:
            print("[server] -> index 200", file=sys.stderr)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "http://localhost:5173")
            self.send_header("Content-Length", str(len(HEALTH_HTML)))
            self.end_headers()
            self.wfile.write(HEALTH_HTML)
            return
        if not urlparse(self.path).path.startswith("/api/"):
            if self._serve_static(urlparse(self.path).path):
                return
        print("[server] -> _handle", file=sys.stderr)
        self._handle("GET")

    # ---------------------------------------------------------- static SPA
    def _serve_static(self, path: str) -> bool:
        """Serve the built frontend; fall back to index.html for SPA routes."""
        if not STATIC_DIR:
            return False
        root = Path(STATIC_DIR).resolve()
        rel = path.lstrip("/") or "index.html"
        target = (root / rel).resolve()
        if target != root and root not in target.parents:
            return False  # path traversal — never serve outside the root
        if not target.is_file():
            if "." in rel.split("/")[-1]:
                return False  # a missing asset (has an extension) is a real 404
            target = root / "index.html"
            if not target.is_file():
                return False
        ctype, _ = mimetypes.guess_type(str(target))
        payload = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype or "application/octet-stream")
        # Hashed assets are immutable; the HTML shell must never be cached.
        if target.name == "index.html":
            self.send_header("Cache-Control", "no-store")
        else:
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        return True

    def do_POST(self) -> None:  # noqa: N802
        print(f"[server] do_POST path={self.path!r}", file=sys.stderr)
        self._handle("POST")

    def do_PUT(self) -> None:  # noqa: N802
        print(f"[server] do_PUT path={self.path!r}", file=sys.stderr)
        self._handle("PUT")

    def do_PATCH(self) -> None:  # noqa: N802
        self._handle("PATCH")

    def do_DELETE(self) -> None:  # noqa: N802
        print(f"[server] do_DELETE path={self.path!r}", file=sys.stderr)
        self._handle("DELETE")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        for k, v in self._cors_headers():
            self.send_header(k, v)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ---------------------------------------------------------- routes
    def _handle(self, method: str) -> None:
        print(f"[server] _handle method={method} path={self.path!r}", file=sys.stderr)
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""

        event = {
            "version": "2.0",
            "rawPath": parsed.path,
            "headers": {k: v for k, v in self.headers.items()},
            "queryStringParameters": dict(parse_qsl(parsed.query)) or None,
            "requestContext": {
                "requestId": uuid.uuid4().hex,
                "http": {
                    "method": method,
                    "path": parsed.path,
                    "sourceIp": self.client_address[0],
                },
            },
            "body": base64.b64encode(body).decode("ascii") if body else "",
            "isBase64Encoded": True,
        }
        print(f"[server] dispatching event path={event['rawPath']!r}", file=sys.stderr)
        resp = dispatch(event, None)
        print(f"[server] dispatch returned status={resp.get('statusCode')}", file=sys.stderr)
        status = resp.get("statusCode", 200)
        headers = resp.get("headers", {})
        raw = resp.get("body", "")
        payload = raw.encode("utf-8") if isinstance(raw, str) else raw
        if resp.get("isBase64Encoded"):
            payload = base64.b64decode(payload)

        self.send_response(status)
        for key, value in headers.items():
            if key.lower() == "set-cookie":
                values = value if isinstance(value, list) else [value]
                for v in values:
                    self.send_header("Set-Cookie", v)
            else:
                self.send_header(key, value)
        for k, v in self._cors_headers():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if method != "HEAD":
            self.wfile.write(payload)

    def log_message(self, fmt: str, *args) -> None:  # quieter default logging
        if os.environ.get("OBSIDIAN_QUIET") != "1":
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def main() -> None:
    print("[server] main() called", file=sys.stderr)
    # Local dev: the browser talks to the Vite dev server (5173), which proxies
    # ^/api/ to this backend. Point the OAuth redirect and the post-login
    # redirect at that origin so Google's callback lands on a reachable,
    # same-origin URL. Register this exact redirect URI in the Google Cloud
    # Console OAuth client's "Authorized redirect URIs":
    #     http://localhost:5173/api/v1/auth/google/callback
    # and add http://localhost:5173 as an Authorized JavaScript origin.
    settings.api_base_url = os.environ.get(
        "OBSIDIAN_API_BASE_URL", "http://localhost:5173/api/v1")
    settings.public_base_url = os.environ.get(
        "OBSIDIAN_PUBLIC_BASE_URL", "http://localhost:5173")
    aws.ensure_resources()
    print("[server] aws.ensure_resources() done", file=sys.stderr)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print("[server] server created on", HOST, PORT, file=sys.stderr)
    print("=" * 68)
    print("  OBSIDIAN API  ·  local API Gateway + Lambda runtime")
    print(f"  http://{HOST}:{PORT}/api/v1")
    print(f"  Frontend preview: http://localhost:5173")
    print(f"  AWS backend : {'moto (in-process DynamoDB/S3/KMS)' if settings.local_aws else 'real AWS'}")
    print(f"  Dev mode    : {settings.dev_mode} (OTP surfaced in API responses)")
    print("=" * 68)
    try:
        print("[server] about to serve_forever…", file=sys.stderr)
        server.serve_forever()
        print("[server] serve_forever returned (unexpected)", file=sys.stderr)
    except KeyboardInterrupt:
        print("\nstopping.", file=sys.stderr)
        server.server_close()


if __name__ == "__main__":
    print("[server] __name__ =", __name__, file=sys.stderr)
    main()
    print("[server] main() returned", file=sys.stderr)
