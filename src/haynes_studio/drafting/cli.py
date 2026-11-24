"""The studio draft apply command and its private, create-only receipt."""

import argparse
import asyncio
import json
import os
import ssl
from datetime import timedelta
from pathlib import Path
from typing import TextIO

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import McpError

from haynes_studio.agent_tokens import MAX_AGENT_TOKEN_LENGTH, valid_agent_token
from haynes_studio.errors import ContractError
from haynes_studio.jsonio import parse_strict

from .apply import Result, apply_into, read_baseline
from .document import MAX_DOCUMENT_BYTES, Draft


def add_command(commands) -> None:
    draft = commands.add_parser("draft", help="apply an agent draft through the scoped Studio MCP")
    actions = draft.add_subparsers(dest="action", required=True)
    apply = actions.add_parser("apply", help="validate and apply boards to one prepared story")
    apply.add_argument("draft_file", type=Path)
    apply.add_argument("--story", required=True, metavar="STORY_ID")
    apply.add_argument("--previous", type=Path, metavar="RECEIPT", help="the previous apply receipt")
    apply.add_argument("--out", required=True, type=Path, metavar="NEW_RECEIPT",
                       help="a new private JSON receipt path")
    apply.add_argument("--key-file", type=Path, help="a mounted agent-key file (or set STUDIO_AGENT_KEY)")
    apply.set_defaults(handler=_command)


def _read(path: Path) -> bytes:
    with path.open("rb") as source:
        return source.read(MAX_DOCUMENT_BYTES + 1)


def _endpoint() -> str:
    try:
        url = httpx.URL(os.environ.get("STUDIO_MCP_URL", ""))
    except httpx.InvalidURL:
        raise ValueError("STUDIO_MCP_URL is invalid") from None
    local_http = url.scheme == "http" and url.host in {"localhost", "127.0.0.1", "::1"}
    if ((url.scheme != "https" and not local_http) or not url.host or url.userinfo
            or url.query or url.fragment or url.path == "/"):
        raise ValueError("STUDIO_MCP_URL must name an HTTPS MCP endpoint or a loopback HTTP endpoint")
    return str(url)


def _key(path: Path | None) -> str:
    secret = os.environ.get("STUDIO_AGENT_KEY")
    if path is not None:
        if secret is not None:
            raise ValueError("Choose either STUDIO_AGENT_KEY or --key-file")
        try:
            with path.open("rb") as source:
                secret = source.read(MAX_AGENT_TOKEN_LENGTH + 3).decode("ascii").removesuffix("\n").removesuffix("\r")
        except UnicodeError:
            raise ValueError("Invalid Studio agent key") from None
    if not valid_agent_token(secret):
        raise ValueError("A valid Studio agent key is required")
    return secret


def _apply_failure(error: BaseException) -> dict:
    if isinstance(error, BaseExceptionGroup):
        faults = [_apply_failure(item) for item in error.exceptions]
        return next((item for item in faults if item["http_status"] is not None), faults[0])
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        code = {401: "auth.required", 403: "auth.forbidden"}.get(status, "draft.transport_failed")
        return {"code": code, "http_status": status}
    if isinstance(error, KeyboardInterrupt):
        return {"code": "draft.interrupted", "http_status": None}
    if isinstance(error, (asyncio.CancelledError, httpx.HTTPError, McpError, OSError)):
        return {"code": "draft.transport_failed", "http_status": None}
    return {"code": "draft.unexpected_failure", "http_status": None}


async def _apply(endpoint: str, key: str, verify: ssl.SSLContext | bool, result: Result,
                 *, first_apply: bool) -> None:
    async with httpx.AsyncClient(headers={"Authorization": "Bearer " + key}, verify=verify,
                                 trust_env=False, follow_redirects=False, timeout=30) as http:
        async with streamable_http_client(endpoint, http_client=http) as (read, write, _):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=30)) as session:
                await session.initialize()
                await apply_into(session, result, first_apply=first_apply)


def _command(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    try:
        draft = Draft.parse(_read(args.draft_file))
        if args.story != draft.story_id:
            raise ValueError("--story must match the story_id in the draft")
        previous = None
        if args.previous is not None:
            raw = _read(args.previous)
            if len(raw) > MAX_DOCUMENT_BYTES:
                raise ValueError("Previous receipt exceeds the 4 MiB file limit")
            try:
                previous = read_baseline(parse_strict(raw.decode("utf-8")), draft)
            except (UnicodeError, RecursionError, ValueError):
                raise ValueError("Expected a valid previous receipt for this story and production") from None
        endpoint, key = _endpoint(), _key(args.key_file)
        ca_file = os.environ.get("STUDIO_MCP_CA_FILE")
        verify = ssl.create_default_context(cafile=ca_file) if ca_file else True
        fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except ContractError as error:
        for violation in error.violations:
            print(f"studio draft: {violation.rule} at {violation.path or '/'}", file=err)
        return 2
    except (OSError, ValueError) as error:
        text = (error.strerror or type(error).__name__) if isinstance(error, OSError) else str(error)
        print(f"studio draft: {text}", file=err)
        return 2
    with os.fdopen(fd, "w", encoding="utf-8") as receipt:
        result = Result(draft, dict(previous or {}))
        try:
            asyncio.run(_apply(endpoint, key, verify, result, first_apply=previous is None))
        except (Exception, BaseExceptionGroup, asyncio.CancelledError, KeyboardInterrupt) as error:
            if result.error is None:
                result.abort(_apply_failure(error))
        payload = json.dumps(result.document(), indent=2)
        try:
            receipt.write(payload + "\n")
            receipt.flush()
        except OSError:
            print("studio draft: receipt write failed", file=err)
            print(payload, file=out)
            return 1
    print(f"studio draft: receipt saved to {args.out}", file=out)
    return 0 if result.ok else 1
