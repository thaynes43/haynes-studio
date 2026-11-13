"""JSON values as the canonical code reads them, without recursion.

- :func:`normalize` copies a JSON value into plain dicts and lists and turns every
  integral float (``1900.0``) into an int. JSON Schema and JavaScript treat ``1900.0``
  as the integer 1900, and story 378's legacy loader does the same, so validators,
  models and derived values all see one number. ``1900.5`` stays a float (and fails
  ``time.not_integer_ms`` where an integer is required); booleans are never numbers.
- :func:`too_deep` tells whether a value nests deeper than :data:`MAX_DEPTH` levels.
  Every canonical document is far shallower; a deeper one is refused before any
  recursive code (JSON Schema, read-only copies) sees it.

Both walk the value with an explicit stack, so a deeply nested input cannot exhaust
Python's recursion limit here.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

MAX_DEPTH = 64
"""Containers (objects and arrays) inside one another; a story is about 7 deep."""

_CONTAINERS = (Mapping, list, tuple)


def integral(value: Any) -> Any:
    """``value`` with an integral, finite float turned into an int; anything else as is."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _empty(value: Any) -> dict | list:
    return {} if isinstance(value, Mapping) else []


def normalize(value: Any) -> Any:
    """A plain-JSON copy of ``value`` (mappings become dicts, tuples become lists) with
    integral floats as ints (see :func:`integral`)."""
    if not isinstance(value, _CONTAINERS):
        return integral(value)
    root = _empty(value)
    stack = [(value, root)]
    while stack:
        source, target = stack.pop()
        items = source.items() if isinstance(source, Mapping) else enumerate(source)
        for key, item in items:
            if isinstance(item, _CONTAINERS):
                copy = _empty(item)
                stack.append((item, copy))
            else:
                copy = integral(item)
            if isinstance(target, dict):
                target[key] = copy
            else:
                target.append(copy)
    return root


def too_deep(value: Any, limit: int = MAX_DEPTH) -> bool:
    """True when ``value`` nests more than ``limit`` containers deep."""
    stack = [(value, 1)] if isinstance(value, _CONTAINERS) else []
    while stack:
        item, depth = stack.pop()
        if depth > limit:
            return True
        children = item.values() if isinstance(item, Mapping) else item
        stack.extend((child, depth + 1) for child in children
                     if isinstance(child, _CONTAINERS))
    return False
