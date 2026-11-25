"""Photo upload bounds shared by the API and the MCP transport."""

import asyncio
import os
from dataclasses import dataclass

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
DEFAULT_BODY_SECONDS = 90
IDLE_SECONDS = 15
MAX_BODY_SECONDS = 300
TIMEOUT_CODE = "photo.upload_timeout"
TIMEOUT_MESSAGE = "The photo upload body did not arrive within the deadline"


class UploadBodyTimeout(Exception):
    pass


@dataclass(frozen=True)
class UploadBodyLimits:
    total_seconds: int = DEFAULT_BODY_SECONDS

    def __post_init__(self):
        if type(self.total_seconds) is not int or not IDLE_SECONDS <= self.total_seconds <= MAX_BODY_SECONDS:
            raise ValueError(f"STUDIO_UPLOAD_BODY_SECONDS must be an integer from {IDLE_SECONDS} to {MAX_BODY_SECONDS}")

    @classmethod
    def from_environment(cls):
        try:
            seconds = int(os.getenv("STUDIO_UPLOAD_BODY_SECONDS", str(DEFAULT_BODY_SECONDS)))
        except ValueError:
            raise ValueError("STUDIO_UPLOAD_BODY_SECONDS must be an integer") from None
        return cls(seconds)

    async def stream(self, request):
        """Yield each chunk within both the idle window and the original deadline."""
        clock = asyncio.get_running_loop().time
        deadline = clock() + self.total_seconds
        chunks = request.stream()
        while True:
            receive_by = min(deadline, clock() + IDLE_SECONDS)
            timeout = asyncio.timeout_at(receive_by)
            try:
                async with timeout:
                    chunk = await anext(chunks)
            except StopAsyncIteration:
                return
            except TimeoutError as error:
                if timeout.expired():
                    raise UploadBodyTimeout from error
                raise
            # A buffered receive may complete without yielding to the timeout callback.
            if clock() >= receive_by:
                raise UploadBodyTimeout
            yield chunk
