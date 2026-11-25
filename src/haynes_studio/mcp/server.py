"""Stateless Streamable HTTP server for the scoped Studio tools."""

import logging
import re
import ssl
from contextlib import asynccontextmanager
from http.cookiejar import CookieJar, DefaultCookiePolicy
from ipaddress import ip_address
from io import BytesIO
from pathlib import Path
from threading import Lock

import httpx
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecurityMiddleware, TransportSecuritySettings
from mcp.shared import session as sdk_session
from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.datastructures import MutableHeaders
from starlette.requests import ClientDisconnect, Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

from haynes_studio.agent_tokens import AGENT_TOKEN_PATTERN
from haynes_studio.canonical.jsonvalues import too_deep
from haynes_studio.errors import pointer
from haynes_studio.photo_limits import TIMEOUT_CODE, TIMEOUT_MESSAGE, UploadBodyLimits, UploadBodyTimeout

from .arguments import MAX_UPLOAD_BASE64, UploadPhoto
from .tools import OPERATIONS
from .upstream import Problem, StudioAPI, auth_required, json_text

VERSION = "1.0.0"
MAX_ARGUMENT_BYTES = 64 * 1024
MAX_RESULT_BYTES = 128 * 1024
MAX_REQUEST_BYTES = 2 * 1024 * 1024  # Also carries a 256 KiB archive text value after JSON escaping.
MAX_UPLOAD_METADATA_BYTES = 256 * 1024
MAX_UPLOAD_REQUEST_BYTES = MAX_UPLOAD_BASE64 + MAX_UPLOAD_METADATA_BYTES
UPLOAD_TOOL = "studio_upload_photo"
_upload_slot = Lock()
LOCAL_HOSTS = ("127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*", "[::1]", "[::1]:*")
_BEARER = re.compile(rf"(?i:Bearer) {AGENT_TOKEN_PATTERN}")
_DNS_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_CLUSTER_SERVICE = re.compile(rf"{_DNS_LABEL}\.{_DNS_LABEL}\.svc\.cluster\.local\.?")
logger = logging.getLogger(__name__)

_SDK_VALIDATION_LOGS = (
    "Failed to validate request:", "Message that failed validation:", "Failed to validate notification:",
)
_SDK_MESSAGE_LOGS = ("Received message:", "Received exception from stream:")


def _hide_sdk_payloads(record: logging.LogRecord) -> bool:
    # The pinned SDK includes invalid inputs in root logging and message values in
    # its low-level logger. Keep the events without rendering any wire content.
    prefixes = (_SDK_VALIDATION_LOGS if record.pathname == sdk_session.__file__
                else _SDK_MESSAGE_LOGS if record.name == Server.__module__ else ())
    if isinstance(record.msg, str) and record.msg.startswith(prefixes):
        record.msg, record.args = record.msg.partition(":")[0], ()
    return True


def _tool_result(document: dict, *, error: bool = False) -> CallToolResult:
    return CallToolResult(
        isError=error, structuredContent=document,
        content=[TextContent(type="text", text=json_text(document))],
    )


def _validate_arguments(model, values, limit=MAX_ARGUMENT_BYTES):
    if too_deep(values):
        raise Problem(422, "schema.invalid", "Tool arguments may nest to 64 levels")
    # The raw media field is independently bounded by the upload schema. The
    # regular metadata budget still applies to the rest of the request.
    metadata = ({key: value for key, value in values.items() if key != "data_base64"}
                if model is UploadPhoto and isinstance(values, dict) else values)
    try:
        size = len(json_text(metadata).encode("utf-8"))
    except (UnicodeError, ValueError, OverflowError):
        raise Problem(422, "schema.invalid", "Expected strict UTF-8 JSON arguments") from None
    if size > limit:
        raise Problem(413, "request.too_large", f"Tool arguments are limited to {limit // 1024} KiB")
    try:
        return model.model_validate(values)
    except ValidationError as error:
        # Pydantic's messages and context can contain input values.
        violations = [{"path": pointer(*item["loc"]), "rule": item["type"]}
                      for item in error.errors(include_url=False, include_context=False, include_input=False)]
        problem = Problem(422, "schema.invalid", "Arguments do not match the tool input schema",
                          path=violations[0]["path"], violations=violations)
        if len(json_text({"error": problem.error}).encode("utf-8")) > MAX_RESULT_BYTES:
            raise Problem(413, "result.too_large", "Too many argument violations to report within 128 KiB") from None
        raise problem from None


class Endpoint:
    def __init__(self, manager, api, security, *, upload=False):
        self.manager = manager
        self.api = api
        self.security = TransportSecurityMiddleware(security)
        self.upload = upload

    async def __call__(self, scope, receive, send):
        request = Request(scope, receive)
        denied = await self.security.validate_request(request, request.method == "POST")
        if denied is not None:
            return await denied(scope, receive, send)
        credentials = request.headers.getlist("authorization")
        try:
            if len(credentials) != 1 or not _BEARER.fullmatch(credentials[0]):
                raise auth_required()
            # Authenticate discovery and protocol requests too. The actual operation
            # rechecks the key and its current production scopes at the API.
            reply = await self.api.request(credentials[0], "GET", "/v1/me")
            principal = reply.document.get("principal")
            if not isinstance(principal, dict) or principal.get("kind") != "agent":
                raise auth_required()
            if self.upload and request.method == "POST":
                grants = reply.document.get("production_scopes")
                if not isinstance(grants, dict) or not any(
                    isinstance(scopes, list) and "assets:upload" in scopes for scopes in grants.values()
                ):
                    raise Problem(403, "auth.forbidden", "A production upload grant is required")
        except Problem as problem:
            status = problem.error["http_status"]
            headers = {"Cache-Control": "no-store"}
            if status == 401:
                headers["WWW-Authenticate"] = "Bearer"
            response = JSONResponse({"error": problem.error}, status_code=status, headers=headers)
            return await response(scope, receive, send)
        async def send_response(message):
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Cache-Control"] = "no-store"
            await send(message)

        request.state.upload_endpoint = self.upload
        if not self.upload or request.method != "POST":
            return await self.manager.handle_request(scope, receive, send_response)
        if not _upload_slot.acquire(blocking=False):
            problem = Problem(503, "photo.upload_busy", "Another photo upload is in progress. Retry shortly")
            response = JSONResponse({"error": problem.error}, status_code=503, headers={"Retry-After": "1"})
            return await response(scope, receive, send_response)
        try:
            await self.manager.handle_request(scope, receive, send_response)
        finally:
            _upload_slot.release()


class UploadSessionManager(StreamableHTTPSessionManager):
    """Give the SDK one bounded body, without retaining a second encoded copy."""

    def __init__(self, *args, body_limits: UploadBodyLimits, **kwargs):
        super().__init__(*args, **kwargs)
        self.body_limits = body_limits

    async def handle_request(self, scope, receive, send):
        request = Request(scope, receive)
        too_large = PlainTextResponse("Request body too large", status_code=413)
        try:
            declared = int(request.headers.get("content-length", "0"))
        except ValueError:
            declared = 0
        limit = self.max_request_body_size if request.method == "POST" else MAX_UPLOAD_METADATA_BYTES
        if declared > limit:
            return await too_large(scope, receive, send)

        try:
            with BytesIO() as buffer:
                async for chunk in self.body_limits.stream(request):
                    if buffer.tell() + len(chunk) > limit:
                        return await too_large(scope, receive, send)
                    buffer.write(chunk)
                body = buffer.getvalue()
        except ClientDisconnect:
            return
        except UploadBodyTimeout:
            problem = Problem(408, TIMEOUT_CODE, TIMEOUT_MESSAGE)
            response = JSONResponse({"error": problem.error}, status_code=408)
            return await response(scope, receive, send)

        async def replay():
            nonlocal body
            if body is None:
                return await receive()
            message = {"type": "http.request", "body": body, "more_body": False}
            body = None
            return message

        # The SDK's bounded ASGI wrapper collects a bytearray and retains it
        # throughout dispatch. This route supplies its own bounded body instead.
        await self._handle_request(scope, replay, send)


def _loopback(host: str) -> bool:
    if host in {"localhost", "localhost."}:
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def _api_origin(url: str) -> httpx.URL:
    origin = httpx.URL(url)
    if (origin.scheme not in {"http", "https"} or not origin.host or origin.userinfo
            or origin.raw_path != b"/" or origin.fragment):
        raise ValueError("STUDIO_API_URL must be an HTTP(S) origin")
    if origin.scheme == "http" and not (_loopback(origin.host) or _CLUSTER_SERVICE.fullmatch(origin.host)):
        raise ValueError("STUDIO_API_URL requires HTTPS outside loopback and Kubernetes Service DNS")
    return origin


def create_app(api_url: str, *, allowed_hosts: tuple[str, ...] = LOCAL_HOSTS,
               allowed_origins: tuple[str, ...] = (),
               api_ca_file: str | Path | None = None,
               upload_body_limits: UploadBodyLimits = UploadBodyLimits(),
               api_transport: httpx.AsyncBaseTransport | None = None) -> Starlette:
    """Configure the API origin and the streamable HTTP transport."""
    logging.getLogger().addFilter(_hide_sdk_payloads)
    logging.getLogger(Server.__module__).addFilter(_hide_sdk_payloads)
    # Share connections, with no upstream cookie persistence or environment proxies.
    origin = _api_origin(api_url)
    verify = ssl.create_default_context(cafile=str(api_ca_file)) if api_ca_file is not None else True
    client = httpx.AsyncClient(
        base_url=origin, transport=api_transport, trust_env=False, verify=verify,
        cookies=CookieJar(policy=DefaultCookiePolicy(allowed_domains=())),
        timeout=httpx.Timeout(30, connect=5),
    )
    api = StudioAPI(client)
    server = Server("studio-mcp", version=VERSION)
    schemas = [operation.schema(name) for name, operation in OPERATIONS.items() if name != UPLOAD_TOOL]
    upload_schema = OPERATIONS[UPLOAD_TOOL].schema(UPLOAD_TOOL)

    @server.list_tools()
    async def list_tools():
        return [upload_schema] if server.request_context.request.state.upload_endpoint else schemas

    @server.call_tool(validate_input=False)
    async def call_tool(name, raw):
        reply = None
        try:
            request = server.request_context.request
            operation = OPERATIONS.get(name)
            if operation is None or (name == UPLOAD_TOOL) != request.state.upload_endpoint:
                raise Problem(404, "tool.not_found", "This Studio tool is unavailable on this endpoint")
            arguments = _validate_arguments(operation.arguments, raw, operation.argument_limit or MAX_ARGUMENT_BYTES)
            reply = await operation.call(api, request.headers["authorization"], arguments)
            document = operation.project(reply, arguments)
            limit = operation.result_limit or MAX_RESULT_BYTES
            if len(json_text(document).encode("utf-8")) > limit:
                raise Problem(413, "result.too_large",
                              f"Result exceeds {limit // 1024} KiB. Read fewer fields or a smaller page",
                              request_id=reply.request_id)
            return _tool_result(document)
        except Problem as problem:
            return _tool_result({"error": problem.error}, error=True)
        except Exception as error:
            request_id = reply.request_id if reply else None
            problem = Problem.internal(request_id)
            logger.error("Studio tool failed (%s) request_id=%s",
                         type(error).__name__, problem.error["request_id"])
            return _tool_result({"error": problem.error}, error=True)

    security = TransportSecuritySettings(
        allowed_hosts=list(allowed_hosts), allowed_origins=list(allowed_origins),
    )
    manager = StreamableHTTPSessionManager(
        server, json_response=True, stateless=True, security_settings=security,
        max_request_body_size=MAX_REQUEST_BYTES,
    )
    upload_manager = UploadSessionManager(
        server, json_response=True, stateless=True, security_settings=security,
        max_request_body_size=MAX_UPLOAD_REQUEST_BYTES, body_limits=upload_body_limits,
    )

    @asynccontextmanager
    async def lifespan(_):
        async with client, manager.run(), upload_manager.run():
            yield

    app = Starlette(routes=[
        Route("/mcp", Endpoint(manager, api, security)),
        Route("/mcp/upload", Endpoint(upload_manager, api, security, upload=True)),
    ], lifespan=lifespan)
    app.router.redirect_slashes = False
    return app
