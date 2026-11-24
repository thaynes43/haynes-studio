"""Stateless Streamable HTTP server for the scoped Studio tools."""

import logging
import re
import ssl
from contextlib import asynccontextmanager
from http.cookiejar import CookieJar, DefaultCookiePolicy
from ipaddress import ip_address
from pathlib import Path

import httpx
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecurityMiddleware, TransportSecuritySettings
from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from haynes_studio.agent_tokens import AGENT_TOKEN_PATTERN
from haynes_studio.canonical.jsonvalues import too_deep
from haynes_studio.errors import pointer

from .tools import OPERATIONS
from .upstream import Problem, StudioAPI, auth_required, json_text

VERSION = "1.0.0"
MAX_ARGUMENT_BYTES = 64 * 1024
MAX_RESULT_BYTES = 128 * 1024
MAX_REQUEST_BYTES = 256 * 1024
LOCAL_HOSTS = ("127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*", "[::1]", "[::1]:*")
_BEARER = re.compile(rf"(?i:Bearer) {AGENT_TOKEN_PATTERN}")
_DNS_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_CLUSTER_SERVICE = re.compile(rf"{_DNS_LABEL}\.{_DNS_LABEL}\.svc(?:\.cluster\.local\.?)?")
logger = logging.getLogger(__name__)


def _tool_result(document: dict, *, error: bool = False) -> CallToolResult:
    return CallToolResult(
        isError=error, structuredContent=document,
        content=[TextContent(type="text", text=json_text(document))],
    )


def _validate_arguments(model, values):
    if too_deep(values):
        raise Problem(422, "schema.invalid", "Tool arguments may nest to 64 levels")
    try:
        size = len(json_text(values).encode("utf-8"))
    except (UnicodeError, ValueError, OverflowError):
        raise Problem(422, "schema.invalid", "Expected strict UTF-8 JSON arguments") from None
    if size > MAX_ARGUMENT_BYTES:
        raise Problem(413, "request.too_large", "Tool arguments are limited to 64 KiB")
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
    def __init__(self, manager, api, security):
        self.manager = manager
        self.api = api
        self.security = TransportSecurityMiddleware(security)

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

        await self.manager.handle_request(scope, receive, send_response)


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
               api_transport: httpx.AsyncBaseTransport | None = None) -> Starlette:
    """Configure the API origin and the streamable HTTP transport."""
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
    schemas = [operation.schema(name) for name, operation in OPERATIONS.items()]

    @server.list_tools()
    async def list_tools():
        return schemas

    @server.call_tool(validate_input=False)
    async def call_tool(name, raw):
        reply = None
        try:
            operation = OPERATIONS.get(name)
            if operation is None:
                raise Problem(404, "tool.not_found", "This Studio tool is unavailable")
            arguments = _validate_arguments(operation.arguments, raw)
            request = server.request_context.request
            reply = await operation.call(api, request.headers["authorization"], arguments)
            document = operation.project(reply, arguments)
            if len(json_text(document).encode("utf-8")) > MAX_RESULT_BYTES:
                raise Problem(413, "result.too_large",
                              "Result exceeds 128 KiB. Read fewer fields or a smaller page",
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

    @asynccontextmanager
    async def lifespan(_):
        async with client, manager.run():
            yield

    app = Starlette(routes=[Route("/mcp", Endpoint(manager, api, security))], lifespan=lifespan)
    app.router.redirect_slashes = False
    return app
