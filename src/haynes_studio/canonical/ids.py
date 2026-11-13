"""Prefixed ULID identifiers (contract section 2, P-01): ``<prefix>_<ULID>``.

A ULID here is 26 upper-case Crockford base32 characters: a 48-bit millisecond
timestamp and 80 random bits, first character ``0`` to ``7``. Minted with the
standard library only. Pure functions plus one small stateful minter.
"""

from __future__ import annotations

import re
import secrets
import time
from collections.abc import Callable

PREFIXES = {
    "prd": "production", "sty": "story", "brd": "board", "lin": "line", "cue": "cue",
    "nte": "note", "ast": "asset", "asv": "asset version", "job": "job", "run": "run",
    "dlv": "delivery", "apr": "go-live approval", "key": "agent key",
    "fmv": "format version", "pub": "publication", "fbk": "feedback",
}
ULID_PATTERN = "[0-7][0-9A-HJKMNP-TV-Z]{25}"
ID_PATTERN = rf"^({'|'.join(PREFIXES)})_{ULID_PATTERN}$"
_ID = re.compile(ID_PATTERN)
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_RANDOM_BITS = 80
_TIME_BITS = 48


def is_id(value: object, prefix: str | None = None) -> bool:
    """True when ``value`` is a well-formed ID (of ``prefix``, when given)."""
    if not isinstance(value, str) or not _ID.match(value):
        return False
    return prefix is None or value.startswith(prefix + "_")


def _encode(number: int) -> str:
    chars = []
    for _ in range(26):
        chars.append(_ALPHABET[number & 31])
        number >>= 5
    return "".join(reversed(chars))


def ulid(timestamp_ms: int, randomness: int) -> str:
    """The 26-character ULID for a 48-bit ms timestamp and 80 random bits."""
    if not 0 <= timestamp_ms < 1 << _TIME_BITS:
        raise ValueError("timestamp_ms out of range for a ULID")
    if not 0 <= randomness < 1 << _RANDOM_BITS:
        raise ValueError("randomness out of range for a ULID")
    return _encode((timestamp_ms << _RANDOM_BITS) | randomness)


class Minter:
    """Mints prefixed ULIDs, monotonic within one minter: an ID minted later sorts
    after every earlier one, even within the same millisecond (the random part is
    incremented). ``clock`` returns ms since the epoch; ``random_bits`` returns 80
    random bits. Both are injectable for deterministic tests."""

    def __init__(self, clock: Callable[[], int] | None = None,
                 random_bits: Callable[[], int] | None = None):
        self._clock = clock or (lambda: time.time_ns() // 1_000_000)
        self._random = random_bits or (lambda: secrets.randbits(_RANDOM_BITS))
        self._last: tuple[int, int] | None = None

    def mint(self, prefix: str) -> str:
        if prefix not in PREFIXES:
            raise ValueError(f"unknown ID prefix {prefix!r}")
        now = self._clock()
        if self._last is not None and now <= self._last[0]:
            now, rand = self._last[0], self._last[1] + 1
            if rand >= 1 << _RANDOM_BITS:
                now, rand = now + 1, self._random()
        else:
            rand = self._random()
        self._last = (now, rand)
        return f"{prefix}_{ulid(now, rand)}"
