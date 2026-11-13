"""Strict, read-only JSON input: no duplicate keys, no NaN or Infinity."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"duplicate key {key!r}")
        seen[key] = value
    return seen


def _no_constant(name: str) -> Any:
    raise ValueError(f"{name} is not JSON")


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f"{text} is too large for a number")
    return value


def parse_strict(text: str) -> Any:
    """Parse JSON text; a duplicate key (where the last would win silently), a NaN or
    Infinity, or a number too large for a float (``1e400``) raises ``ValueError``."""
    return json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_constant,
                      parse_float=_finite_float)


@dataclass(frozen=True)
class JsonFile:
    """A parsed JSON file: its label (the path as given), the SHA-256 of its bytes, and
    the document."""

    label: str
    sha256: str
    document: Any = field(repr=False)


def read_json(path: str | Path) -> JsonFile:
    """Read and parse one JSON file without changing it. ``OSError`` if unreadable;
    ``ValueError`` (with the file named) if it is not strict UTF-8 JSON."""
    path = Path(path)
    data = path.read_bytes()
    try:
        document = parse_strict(data.decode("utf-8"))
    except RecursionError:
        raise ValueError(f"{path}: not JSON: nested too deeply") from None
    except (UnicodeDecodeError, ValueError) as error:
        first = str(error).splitlines()[0] if str(error) else type(error).__name__
        raise ValueError(f"{path}: not JSON: {first}") from None
    return JsonFile(label=str(path), sha256=hashlib.sha256(data).hexdigest(), document=document)


def freeze(value: Any) -> Any:
    """A read-only deep copy of a JSON value: objects become read-only mappings and
    arrays become tuples."""
    if isinstance(value, dict):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze(item) for item in value)
    return value


def thaw(value: Any) -> Any:
    """The JSON value behind :func:`freeze` (plain dicts and lists), for serializing."""
    if isinstance(value, MappingProxyType | dict):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [thaw(item) for item in value]
    return value
