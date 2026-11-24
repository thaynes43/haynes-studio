"""Authorize a content hash from PostgreSQL before opening a private store blob."""

import os
import re
from collections.abc import Iterator
from typing import Annotated, BinaryIO

from fastapi import APIRouter, Header, Request
from starlette.responses import Response, StreamingResponse

from haynes_studio.db.catalog import media_for_hash
from haynes_studio.db.engine import snapshot
from haynes_studio.store.errors import BLOB_MISSING, LOCATOR_INVALID, StoreError
from haynes_studio.store.layout import is_sha256, parse_locator

from .errors import APIError, ERROR_RESPONSES, ErrorEnvelope, missing

_CHUNK_SIZE = 256 * 1024
_SINGLE_RANGE = re.compile(r"bytes=([0-9]*)-([0-9]*)", re.IGNORECASE|re.ASCII)


def byte_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Return a single inclusive byte range; ignore unsupported or malformed ranges."""
    if header is None:
        return None
    match = _SINGLE_RANGE.fullmatch(header.strip())
    if match is None or not any(match.groups()):
        return None
    first, last = match.groups()

    def bounded(value: str) -> int:
        text = value.lstrip("0")
        # Give arbitrarily large numbers their range semantics without int overflow.
        return max(size, 1) if len(text) > len(str(size)) else int(text or "0")

    if not first:
        suffix = bounded(last)
        if suffix and size:
            return max(0, size - suffix), size - 1
    else:
        start_digits = first.lstrip("0")
        end_digits = last.lstrip("0")
        if last and (len(end_digits), end_digits) < (len(start_digits), start_digits):
            return None
        start = bounded(first)
        end = bounded(last) if last else size - 1
        if start < size:
            return start, min(size - 1, end)
    raise APIError(416, "media.range_unsatisfied", "The requested byte range is unavailable",
                   headers={"Accept-Ranges": "bytes", "Content-Range": f"bytes */{size}"})


class BlobStream(StreamingResponse):
    def __init__(self, handle: BinaryIO, start: int, size: int, **kwargs):
        self.handle = handle
        super().__init__(self._read(start, size), **kwargs)

    def _read(self, start: int, remaining: int) -> Iterator[bytes]:
        self.handle.seek(start)
        while remaining:
            chunk = self.handle.read(min(remaining, _CHUNK_SIZE))
            if not chunk:
                raise OSError("The media stream ended early")
            remaining -= len(chunk)
            yield chunk

    async def __call__(self, scope, receive, send):
        with self.handle:
            await super().__call__(scope, receive, send)


RangeHeader = Annotated[str | None, Header(alias="Range")]
IfRange = Annotated[str | None, Header(alias="If-Range")]
RANGE_RESPONSES = {
    200: {"description": "Complete media file",
          "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}},
    206: {"description": "Single byte range",
          "headers": {"Content-Range": {"schema": {"type": "string"}},
                      "Accept-Ranges": {"schema": {"type": "string"}}},
          "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}},
    416: {"description": "Range cannot be satisfied", "model": ErrorEnvelope,
          "headers": {"Content-Range": {"schema": {"type": "string"}}}},
}


def build_router(CurrentActor, authenticated_route):
    router = APIRouter(prefix="/v1", tags=["media"], responses=ERROR_RESPONSES,
                       route_class=authenticated_route)

    @router.get("/media/{sha256}", operation_id="get_media", response_class=Response,
                responses=RANGE_RESPONSES)
    @router.head("/media/{sha256}", operation_id="head_media", response_class=Response,
                 responses={code: {k: v for k, v in description.items() if k not in ("content", "model")}
                            for code, description in RANGE_RESPONSES.items()})
    def get_media(request: Request, sha256: str, actor: CurrentActor,
                  range_header: RangeHeader = None, if_range: IfRange = None):
        if not is_sha256(sha256):
            raise missing()
        with snapshot(request.app.state.engine) as conn:
            refs = media_for_hash(conn, sha256, actor.productions("read"))
        store_failed = False
        for ref in refs:
            handle = None
            try:
                loc = parse_locator(ref.locator)
                if loc.sha256 != sha256:
                    continue
                handle = request.app.state.store.open(loc.text)
                size = os.fstat(handle.fileno()).st_size
                if ref.size is not None and ref.size != size:
                    continue
                etag = f'"{sha256}"'
                selected = byte_range(range_header if if_range in (None, etag) else None, size)
                status, start, count = 200, 0, size
                headers = {"Accept-Ranges": "bytes", "ETag": etag,
                           "Content-Type": loc.media_type, "X-Content-Type-Options": "nosniff"}
                if selected is not None:
                    start, end = selected
                    count, status = end - start + 1, 206
                    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
                headers["Content-Length"] = str(count)
                if request.method == "HEAD":
                    return Response(status_code=status, headers=headers)
                response = BlobStream(handle, start, count, status_code=status, headers=headers)
                handle = None  # BlobStream now closes the open descriptor.
                return response
            except StoreError as error:
                if error.code not in (BLOB_MISSING, LOCATOR_INVALID):
                    raise
            except OSError:
                store_failed = True
            finally:
                if handle is not None:
                    handle.close()
        if store_failed:
            raise APIError(503, "store.failed", "The media store could not complete the request")
        raise missing()

    return router
