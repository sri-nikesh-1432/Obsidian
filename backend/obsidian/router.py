"""Route registry (kept separate to avoid circular imports)."""
from __future__ import annotations

import re

# (method, path_pattern, handler, auth_mode, roles, rate_limit)
ROUTES: list[tuple] = []


def route(method: str, path: str, *, auth: str = "authenticated", roles: tuple = (),
          rate: tuple | None = None):
    """Register an API route.

    auth: "authenticated" | "any" | "public"
    roles: tuple of allowed roles (enforced server-side after session auth)
    rate: (route_key, limit, window_seconds)
    """
    def deco(fn):
        rate_cfg = {"key": rate[0], "limit": rate[1], "window": rate[2]} if rate else None
        ROUTES.append((method, path, fn, auth, roles, rate_cfg))
        return fn
    return deco


def compile_pattern(pattern: str) -> re.Pattern:
    parts: list[str] = []
    last_wildcard: str | None = None
    i = 0
    while i < len(pattern):
        if pattern[i] == '{':
            j = pattern.find('}', i)
            if j == -1:
                raise ValueError(f"Unclosed parameter in route {pattern!r}")
            name = pattern[i + 1:j].strip()
            if not name:
                raise ValueError(f"Empty parameter name in route {pattern!r}")
            if name in parts:
                pass
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
                raise ValueError(f"Invalid parameter name {name!r} in route {pattern!r}")
            parts.append(f"(?P<{name}>[^/]+)")
            i = j + 1
        elif pattern[i] == '*':
            if i + 1 < len(pattern) and pattern[i + 1] == '*':
                # catch-all trailing segment — only valid at end
                if i != len(pattern) - 2:
                    raise ValueError(f"Catch-all '{{*}}' must be at end of route {pattern!r}")
                last_wildcard = "(?P<wildcard>.+)"
                i += 2
            else:
                raise ValueError(f"Single '*' is not a valid route token in {pattern!r}")
        else:
            parts.append(re.escape(pattern[i]))
            i += 1
    if last_wildcard:
        parts.append(last_wildcard)
    regex = ''.join(parts)
    return re.compile(f"^{regex}$")
