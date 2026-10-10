"""Minimal ASGI lifespan context for `backend/local/run.py`.

`backend/local/run.py` no longer depends on a real FastAPI application; it
builds its own ASGI app around the Lambda-style `dispatch()` entrypoint.
ASGI/UVICorn still requires a lifespan handler when `lifespan="auto"`, so this
tiny context manager owns startup/shutdown for the local dev server.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any


class LifespanContext:
    """Synchronous lifespan manager with a `.setup()` for `run.py`."""

    def __init__(self) -> None:
        self.scope: dict[str, Any] = {}

    async def __aenter__(self) -> "LifespanContext":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        pass

    def setup(self) -> None:
        """Called synchronously by `backend/local/run.py` before `serve_forever`."""
        self.scope = {"type": "lifespan", "app": "obsidian.local.run"}

    @asynccontextmanager
    async def run(self, scope, receive, send):
        self.scope = scope
        try:
            await receive()
            await send({"type": "lifespan.startup", "message": {"type": "lifespan.startup.complete"}})
            while True:
                message = await receive()
                if message.get("type") == "shutdown":
                    break
        except asyncio.CancelledError:
            pass
        finally:
            await send({"type": "lifespan.shutdown", "message": {"type": "lifespan.shutdown.complete"}})
