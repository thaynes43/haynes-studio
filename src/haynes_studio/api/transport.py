"""Strict query text and bounded JSON decoding at the transport boundary."""

import json
import logging
from urllib.parse import parse_qsl
from uuid import uuid4

from fastapi import Request
from fastapi.routing import APIRoute
from starlette.datastructures import MutableHeaders

from haynes_studio.canonical.jsonvalues import too_deep
from haynes_studio.jsonio import parse_strict

from .errors import APIError, error_response

WRITE_LIMIT = 2 * 1024 * 1024
REQUEST_ID_HEADER = "X-Request-ID"
access_log = logging.getLogger("uvicorn.studio.access")
logger = logging.getLogger(__name__)


class RequestContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        request = Request(scope)
        request_id = request.state.request_id = f"req-{uuid4().hex}"
        response_status = None

        async def send_response(message):
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = message["status"]
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "private, no-store"
                headers["Referrer-Policy"] = "no-referrer"
                headers[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_response)
        except Exception as error:
            logger.error("Studio request failed (%s) request_id=%s", type(error).__name__, request_id)
            if response_status is not None:
                # Headers are committed. Let the server terminate the partial response.
                raise RuntimeError("Studio response interrupted") from None
            problem = APIError(500, "request.failed", "The request could not be completed")
            await error_response(request, problem)(scope, receive, send_response)
        finally:
            principal = getattr(request.state, "principal", None)
            access_log.info("%s", json.dumps({
                "method": request.method, "path": scope["path"], "status": response_status,
                "principal_kind": principal.kind if principal else "anonymous",
                "principal_id": (principal.sub or principal.key_id or principal.worker_id)
                if principal else None,
                "request_id": request_id,
            }))


def _check_text(value: str) -> None:
    # Postgres JSONB and UTF-8 cannot represent NUL or lone surrogates.
    if "\x00" in value:
        raise ValueError("Text contains a NUL character")
    value.encode("utf-8")


class StrictRequest(Request):
    async def json(self):
        try:
            doc = parse_strict((await self.body()).decode("utf-8"))
            if too_deep(doc):
                raise ValueError("JSON too deeply nested")
            stack = [doc]
            while stack:
                value = stack.pop()
                if isinstance(value, dict):
                    stack.extend(value)
                    stack.extend(value.values())
                elif isinstance(value, list):
                    stack.extend(value)
                elif isinstance(value, str):
                    _check_text(value)
            return doc
        except (ValueError, RecursionError) as error:
            raise APIError(422, "schema.invalid", "Expected strict UTF-8 JSON within 64 levels") from error


class MetadataRoute(APIRoute):
    body_limit = WRITE_LIMIT

    def too_large(self):
        return APIError(413, "request.too_large", "Metadata requests are limited to 2 MiB")

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def checked(request):
            try:
                query = request.scope["query_string"].decode("ascii")
                for name, value in parse_qsl(query, keep_blank_values=True, errors="strict"):
                    _check_text(name)
                    _check_text(value)
            except ValueError as error:
                raise APIError(422, "schema.invalid", "Expected UTF-8 query text without NUL",
                               path="/query") from error
            size = 0

            async def receive():
                nonlocal size
                message = await request.receive()
                size += len(message.get("body", b""))
                if size > self.body_limit:
                    raise self.too_large()
                return message

            return await handler(StrictRequest(request.scope, receive))

        return checked
