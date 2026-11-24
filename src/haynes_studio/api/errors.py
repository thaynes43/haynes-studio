"""Stable HTTP error envelopes."""

from typing import Literal

from fastapi import HTTPException

from .models import TransportModel

ErrorStatus = Literal["invalid", "unavailable", "conflict", "forbidden", "unauthenticated",
                      "not_found", "too_large", "internal"]
STATUS = {
    400: "invalid", 401: "unauthenticated", 403: "forbidden", 404: "not_found",
    405: "invalid", 409: "conflict", 413: "too_large", 416: "invalid",
    422: "invalid", 500: "internal", 503: "unavailable",
}


class ErrorDetail(TransportModel):
    code: str
    status: ErrorStatus
    http_status: int
    path: str
    message: str
    current_revision: int | None = None


class ErrorEnvelope(TransportModel):
    error: ErrorDetail


class APIError(HTTPException):
    def __init__(self, http_status: int, code: str, message: str, *, path: str = "",
                 headers: dict | None = None, status: ErrorStatus | None = None,
                 current_revision: int | None = None):
        self.details = ErrorDetail(code=code, status=status or STATUS[http_status],
                                   http_status=http_status, path=path, message=message,
                                   current_revision=current_revision)
        super().__init__(http_status, detail=message, headers=headers)


def unauthenticated():
    return APIError(401, "auth.required", "Sign in or present a valid credential",
                    headers={"WWW-Authenticate": "Bearer"})


def forbidden(code: str = "auth.forbidden", message: str = "This credential cannot perform the operation"):
    return APIError(403, code, message)


def missing():
    return APIError(404, "not_found", "The requested resource is unavailable")


ERROR_RESPONSES = {
    code: {"model": ErrorEnvelope, "description": description}
    for code, description in [
        (401, "Authentication required"), (403, "Credential, production or CSRF check failed"),
        (404, "Resource unavailable"), (409, "The current revision differs"),
        (413, "Request exceeds its size limit"), (422, "The request violates the contract"),
        (500, "Internal error"), (503, "A service dependency is unavailable"),
    ]
}
