#!/usr/bin/env python
"""Local development runner for the OBSIDIAN API gateway.

This script sets up the in-memory DynamoDB tables (via moto), initializes
the client-side KMS/S3 wrappers to talk to localhost:5000, and hands
control off to the Cloudflare Workers-style `dispatch` entrypoint so
the development server mirrors production exactly.

Run it from the repo root with:

    uv run python backend/local/run.py

It reads environment from `.env` (if present) and from the OS environment.
Required for local dev: nothing — moto provides a free DynamoDB endpoint.

The server listens on http://localhost:5000 and exposes:

    GET  /health            → static health payload
    POST /api/users/*       → auth, profile, documents, sharing, activity…
    GET  /s/*              → public assets
    GET  /shared/*         → shared-link document endpoints

CORS origins allowed in this local mode (no auth token required):
    http://localhost:5173   (Vite dev server, React preview)
    http://localhost:3000   (alternative dev origin)
    http://localhost:8080   (alternative dev origin)

Rate limiting is enabled but relaxed for local development: only the
sign-in and sign-up endpoints hit the limiter; everything else is open
so you can poke at the API freely while building.
"""
from __future__ import annotations

import os
import sys
import uuid

# Make the backend package importable when run from the repo root.
_PACKAGE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, _PACKAGE_ROOT)

import uvicorn  # noqa: E402
from obsidian import audit, aws
from obsidian.config import settings

_lifespan_path = os.path.join(os.path.dirname(__file__), "lifespan.py")
if os.path.exists(_lifespan_path):
    import importlib.util as _ilum
    _sp = _ilum.spec_from_file_location("obsidian.local.lifespan", _lifespan_path)
    _mod = importlib.util.module_from_spec(_sp)
    _sp.loader.exec_module(_mod)
    lifespan = _mod
HOST = os.environ.get("API_HOST", "0.0.0.0")
PORT = int(os.environ.get("API_PORT", "5000"))


def build_app() -> uvicorn.Config:
    lifespan_ctx = None
    if lifespan is not None:
        lifespan_ctx = lifespan.LifespanContext()
        lifespan_ctx.setup()

    from obsidian.gateway import dispatch

    async def app(scope, receive, send):
        if lifespan_ctx is not None:
            await lifespan_ctx.run(scope, receive, send)

        if scope["type"] == "http":
            event = {
                "requestContext": {
                    "http": {"method": scope["method"], "sourceIp": scope.get("client", ["unknown"])[0]},
                    "requestId": str(uuid.uuid4()),
                },
                "httpMethod": scope["method"],
                "path": scope["path"],
                "rawPath": scope["path"],
                "queryStringParameters": dict((scope.get("query_string", b"").decode().split("=")) if b"=" in scope.get("query_string", b"") else []),
                "headers": dict((k.decode(), v.decode()) for k, v in scope.get("headers", [])),
                "isBase64Encoded": False,
                "body": "",
            }
            if scope.get("query_string"):
                from urllib.parse import parse_qs
                qs = parse_qs(scope["query_string"].decode(), keep_blank_values=True)
                event["queryStringParameters"] = {k: v[0] for k, v in qs.items()}

            # body
            body_chunks = []
            more = True
            while more:
                message = await receive()
                if message["type"] == "http.request":
                    body_chunks.append(message.get("body", b""))
                    more = message.get("more_body", False)
            raw = b"".join(body_chunks)
            event["body"] = raw.decode("utf-8", "replace") if raw else ""

            response = dispatch(event, (lifespan_ctx.scope.get("aws_context") if lifespan_ctx is not None else None))

            await send({
                "type": "http.response.start",
                "status": response["statusCode"],
                "headers": [(k.lower(), v) for k, v in response.get("headers", {}).items()],
            })
            await send({
                "type": "http.response.body",
                "body": response["body"].encode("utf-8") if isinstance(response["body"], str) else response["body"],
                "isBase64Encoded": response.get("isBase64Encoded", False),
            })

    settings.api_base_url = f"http://{HOST}:{PORT}"
    settings.is_prod = False
    settings.origins = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:8080",
    ]

    return uvicorn.Config(
        app,
        host=HOST,
        port=PORT,
        log_level="info",
        loop="asyncio",
        access_log=False,
        lifespan="auto",
    )


if __name__ == "__main__":
    print(f"Starting OBSIDIAN on http://{HOST}:{PORT}")
    print(f"Frontend preview: http://localhost:5173")
    print()
    uvicorn.run(build_app())
