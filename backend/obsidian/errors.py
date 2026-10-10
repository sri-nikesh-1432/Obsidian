"""Stable, non-leaky API errors.

Public responses never contain stack traces, SQL, encryption internals, or
the existence of hidden resources.
"""
from __future__ import annotations


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, *, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details or {}


def auth_required(message: str = "You must be signed in to perform this action.") -> ApiError:
    return ApiError("AUTH_REQUIRED", message, 401)


def access_denied() -> ApiError:
    # Deliberately generic: never reveal whether a resource exists.
    return ApiError("ACCESS_DENIED", "You do not have permission to perform this action.", 403)


def not_found() -> ApiError:
    return ApiError("RESOURCE_NOT_FOUND", "The requested resource could not be accessed.", 404)


def invalid_input(message: str = "The provided input is invalid.") -> ApiError:
    return ApiError("INVALID_INPUT", message, 422)


def rate_limited(retry: int = 60) -> ApiError:
    return ApiError(
        "RATE_LIMITED",
        f"Too many attempts. Please try again in {retry} seconds.",
        429,
        details={"retry_after": retry},
    )


def server_error(code: str = "INTERNAL_ERROR", message: str = "Something went wrong. Please try again.") -> ApiError:
    return ApiError(code, message, 500)


def error_payload(code: str, message: str, request_id: str, details: dict | None = None) -> dict:
    body: dict = {"error": {"code": code, "message": message, "request_id": request_id}}
    if details:
        body["error"]["details"] = details
    return body
