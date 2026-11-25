"""Receipt interface for a sanctioned transport. Studio ships no implementation."""

from typing import Protocol


class Transport(Protocol):
    def request(self, contract: bytes, *, sha256: str, deduplication_id: str) -> str:
        """Return the external request ID. Reuse it for the same deduplication ID."""
        ...
