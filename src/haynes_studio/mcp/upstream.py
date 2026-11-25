"""The bounded JSON transport to one configured Studio API origin."""

import json
import re
from dataclasses import dataclass
from http import HTTPStatus
from uuid import uuid4

import httpx

from haynes_studio.canonical.jsonvalues import too_deep
from haynes_studio.jsonio import parse_strict

MAX_API_BYTES = 8 * 1024 * 1024
MAX_ERROR_BYTES = 64 * 1024
STATUSES = {
    400: "invalid", 401: "unauthenticated", 403: "forbidden", 404: "not_found",
    409: "conflict", 413: "too_large", 422: "invalid", 500: "internal",
    503: "service_unavailable",
}
ERROR_STATUSES = frozenset(STATUSES.values()) | {"unavailable"}
_CODE = re.compile(r"[a-z][a-z0-9_.-]{0,95}")
_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,96}")


def json_text(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class Problem(Exception):
    def __init__(self, http_status: int, code: str, message: str, *,
                 request_id: str | None = None, path: str = "", **detail):
        super().__init__(code)
        self.error = {
            "http_status": http_status, "status": STATUSES.get(http_status, "internal"), "code": code,
            "request_id": request_id or f"mcp-{uuid4().hex}", "path": path,
            "message": message, **detail,
        }

    @classmethod
    def internal(cls, request_id: str | None = None):
        return cls(500, "internal", "The Studio operation could not be completed",
                   request_id=request_id)

    @classmethod
    def unavailable(cls, request_id: str | None = None):
        return cls(503, "service_unavailable", "The Studio API is unavailable",
                   request_id=request_id)


def auth_required():
    return Problem(401, "auth.required", "Present a valid Studio agent key")


def _checked(value, pattern):
    return value if isinstance(value, str) and pattern.fullmatch(value) else None


def _error(response: httpx.Response, document: object, request_id: str | None) -> Problem:
    detail = document.get("error") if isinstance(document, dict) else None
    if isinstance(detail, dict):
        request_id = _checked(detail.get("request_id"), _REQUEST_ID) or request_id
        status, http_status = detail.get("status"), detail.get("http_status")
        code, message, path = detail.get("code"), detail.get("message"), detail.get("path")
        if (isinstance(status, str) and status in ERROR_STATUSES
                and type(http_status) is int and 400 <= http_status < 600
                and _checked(code, _CODE) and isinstance(message, str) and message
                and isinstance(path, str)
                and ("request_id" not in detail or _checked(detail["request_id"], _REQUEST_ID))):
            problem = Problem(http_status, code, message, request_id=request_id, path=path)
            problem.error.update(detail)
            try:
                if len(json_text({"error": problem.error}).encode("utf-8")) <= MAX_ERROR_BYTES:
                    return problem
            except (ValueError, RecursionError):
                pass
            return Problem.internal(request_id)

    status = response.status_code
    if status in STATUSES:
        return Problem(status, STATUSES[status], HTTPStatus(status).phrase, request_id=request_id)
    if status in (502, 504):
        return Problem.unavailable(request_id)
    return Problem.internal(request_id)


async def _read_json(response: httpx.Response):
    media_type = response.headers.get("content-type", "").partition(";")[0].strip().lower()
    if media_type != "application/json" or response.headers.get("content-encoding", "identity") != "identity":
        raise ValueError("Expected uncompressed JSON")
    body = bytearray()
    # MockTransport and ASGITransport can return a response with content already read.
    async for chunk in response.aiter_bytes():
        if len(body) + len(chunk) > MAX_API_BYTES:
            raise ValueError("API response too large")
        body.extend(chunk)
    document = parse_strict(body.decode("utf-8"))
    if too_deep(document):
        raise ValueError("API response too deeply nested")
    return document


@dataclass(frozen=True)
class Reply:
    document: dict
    request_id: str | None


class StudioAPI:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def request(self, authorization: str, method: str, path: str, *,
                      query: dict | None = None, body: dict | None = None,
                      revision: int | None = None, expect: int | tuple[int, ...] = 200,
                      idempotency_key: str | None = None, binary: bytes | None = None,
                      media_type: str | None = None, provenance: str | None = None) -> Reply:
        headers = {"Authorization": authorization, "Accept": "application/json",
                   "Accept-Encoding": "identity"}
        if revision is not None:
            headers["If-Match"] = f'"{revision}"'
        expected = (expect,) if isinstance(expect, int) else expect
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        if binary is not None:
            headers.update({"Content-Type": media_type, "X-Studio-Photo-Provenance": provenance})
        # An explicit Request forwards only these headers. In particular, never
        # send inbound cookies or cookies from an earlier upstream response.
        request = httpx.Request(method, self.client.base_url.join(path), headers=headers,
                                params=query, json=body, content=binary)
        request_id = None
        try:
            response = await self.client.send(request, stream=True, follow_redirects=False)
            try:
                request_id = _checked(response.headers.get("x-request-id"), _REQUEST_ID)
                if response.status_code == 204 and 204 in expected:
                    return Reply({}, request_id)
                try:
                    document = await _read_json(response)
                except (ValueError, RecursionError):
                    document = None
                if response.status_code not in expected:
                    raise _error(response, document, request_id)
                if not isinstance(document, dict):
                    raise Problem.internal(request_id)
                return Reply(document, request_id)
            finally:
                await response.aclose()
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ProxyError, httpx.RemoteProtocolError):
            raise Problem.unavailable(request_id) from None
        except httpx.HTTPError:
            raise Problem.internal(request_id) from None
