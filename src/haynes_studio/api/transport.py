"""Strict and bounded JSON decoding at the metadata transport boundary."""

from fastapi import Request
from fastapi.routing import APIRoute

from haynes_studio.canonical.jsonvalues import too_deep
from haynes_studio.jsonio import parse_strict

from .errors import APIError

WRITE_LIMIT = 2 * 1024 * 1024


class StrictRequest(Request):
    async def json(self):
        try:
            doc = parse_strict((await self.body()).decode("utf-8"))
            if too_deep(doc):
                raise ValueError("JSON too deeply nested")
            # Postgres JSONB and UTF-8 cannot represent NUL or lone surrogates.
            stack = [doc]
            while stack:
                value = stack.pop()
                if isinstance(value, dict):
                    stack.extend(value)
                    stack.extend(value.values())
                elif isinstance(value, list):
                    stack.extend(value)
                elif isinstance(value, str):
                    if "\x00" in value:
                        raise ValueError("JSON contains a NUL character")
                    value.encode("utf-8")
            return doc
        except (ValueError, RecursionError) as error:
            raise APIError(422, "schema.invalid", "Expected strict UTF-8 JSON within 64 levels") from error


class MetadataRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def checked(request):
            size = 0

            async def receive():
                nonlocal size
                message = await request.receive()
                size += len(message.get("body", b""))
                if size > WRITE_LIMIT:
                    raise APIError(413, "request.too_large", "Metadata requests are limited to 2 MiB")
                return message

            return await handler(StrictRequest(request.scope, receive))

        return checked
