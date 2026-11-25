"""Stable HTTP error envelopes."""

from typing import Literal

from fastapi import HTTPException, Request
from starlette.responses import JSONResponse, Response

from .models import JsonObject, TransportModel

ErrorStatus = Literal["invalid", "unavailable", "conflict", "forbidden", "unauthenticated",
                      "not_found", "too_large", "service_unavailable", "internal"]
STATUS = {
    400: "invalid", 401: "unauthenticated", 403: "forbidden", 404: "not_found",
    405: "invalid", 408: "invalid", 409: "conflict", 413: "too_large", 416: "invalid",
    422: "invalid", 500: "internal", 503: "service_unavailable",
}


class ErrorDetail(TransportModel):
    code: str
    status: ErrorStatus
    http_status: int
    path: str
    message: str
    request_id: str
    current_revision: int | None = None
    board_id: str | None = None
    person_edit: Literal["content", "reordered", "removed"] | None = None
    person_edit_revision: int | None = None
    existing_entity_id: str | None = None
    evidence: JsonObject | None = None


class ErrorEnvelope(TransportModel):
    error: ErrorDetail


class APIError(HTTPException):
    def __init__(self, http_status: int, code: str, message: str, *, path: str = "",
                 headers: dict | None = None, status: ErrorStatus | None = None,
                 current_revision: int | None = None, board_id: str | None = None,
                 person_edit: str | None = None, person_edit_revision: int | None = None,
                 existing_entity_id: str | None = None,
                 evidence: JsonObject | None = None):
        self.details = {"code": code, "status": status or STATUS[http_status],
                        "http_status": http_status, "path": path, "message": message}
        if current_revision is not None:
            self.details["current_revision"] = current_revision
        if board_id is not None:
            self.details["board_id"] = board_id
        if person_edit is not None:
            self.details.update(person_edit=person_edit, person_edit_revision=person_edit_revision)
        if existing_entity_id is not None:
            self.details["existing_entity_id"] = existing_entity_id
        if evidence is not None:
            self.details["evidence"] = evidence
        super().__init__(http_status, detail=message, headers=headers)


def error_response(request: Request, error: APIError) -> Response:
    if request.method == "HEAD":
        return Response(status_code=error.status_code, headers=error.headers)
    details = {**error.details, "request_id": request.state.request_id}
    return JSONResponse({"error": details}, status_code=error.status_code, headers=error.headers)


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
        (404, "Resource unavailable"), (409, "The revision differs or the board is protected"),
        (413, "Request exceeds its size limit"), (422, "The request is invalid or the method is not buildable"),
        (500, "Unexpected internal failure"), (503, "A service dependency is unavailable"),
    ]
}
