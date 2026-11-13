"""The ``studio.delivery/v1`` validator (contract section 8), with story 404's contexts
and conventions: it refuses a document nested deeper than 64 levels, reads a
normalized copy, never raises for a malformed document, and returns violations sorted
by path.

The schema file carries the field rules: identifiers, the timestamp, the codecs and
24 fps, the locator grammar (``store.locator_invalid``), and the shape of each store
adapter (a legacy delivery is read-only, has no proxy, and names a legacy path and
its evidence file; a studio delivery is writable, has a proxy and locators only).
The code here runs only on a document the schema accepted and checks what one field
cannot:

- each locator names its own file: the file name is the ``sha256``, the folder its
  first two digits, the extension ``.mp4``; master and proxy are in one production's
  folder, never the library (``store.locator_invalid``);
- the master is a media kind's delivery size, and the proxy that kind's proxy size;
- TIME-11: the master's frames, the decoded frames and the expected frames agree,
  and the proxy has as many frames as the master;
- the proxy is under ``proxy_under_bytes``, which is the limit for its frame count;
- a legacy block's URL names its own ledger.

Contexts ``read``, ``write`` and ``queue_run`` check the same rules; a delivery has
no ``derived`` block, so ``derived`` is an unknown field everywhere.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from haynes_studio.canonical.validate import (
    READ,
    SCHEMA_INVALID,
    _blocking,
    _check_context,
    _prepare,
    _sorted,
)
from haynes_studio.delivery.model import (
    DELIVERY_FILE,
    DELIVERY_SCHEMA,
    LEGACY_WAN_LEDGER,
    MASTER_SIZES,
    PROXY_SIZES,
    media_kind_of,
    proxy_byte_limit,
)
from haynes_studio.errors import Violation
from haynes_studio.library.validate import LOCATOR_INVALID, locator_problems
from haynes_studio.schemas import schema_violations
from haynes_studio.store.layout import LIBRARY


def validate_delivery(document: Any, *, context: str = READ) -> list[Violation]:
    """Every rule a ``studio.delivery/v1`` document breaks, sorted by path."""
    _check_context(context)
    document, stop = _prepare(document, DELIVERY_SCHEMA)
    if stop is not None:
        return stop
    found = schema_violations(DELIVERY_FILE, document, default_rule=SCHEMA_INVALID)
    if not _blocking(found):
        found += _rules(document)
    return _sorted(found)


def _rules(doc: Mapping[str, Any]) -> list[Violation]:
    master, proxy = doc["master"], doc["proxy"]
    verification = doc["verification"]
    found = _locators(master, proxy)
    kind = media_kind_of(master["width"], master["height"])
    if kind is None:
        sizes = ", ".join(f"{w}x{h} ({k})" for k, (w, h) in MASTER_SIZES.items())
        found.append(Violation(SCHEMA_INVALID, "/master/width",
                               f"a master is a media kind's delivery size: {sizes}"))
    elif proxy is not None and (proxy["width"], proxy["height"]) != PROXY_SIZES[kind]:
        width, height = PROXY_SIZES[kind]
        found.append(Violation(SCHEMA_INVALID, "/proxy/width",
                               f"the proxy of a {kind} is {width}x{height} (P-10)"))
    frames = master["frames"]
    for at, value, what in [("/verification/decoded_frames", verification["decoded_frames"],
                             "the decoded frames"),
                            ("/verification/expected_frames", verification["expected_frames"],
                             "the expected frames")]:
        if value != frames:
            found.append(Violation(SCHEMA_INVALID, at,
                                   f"{what} must equal the master's {frames} frames (TIME-11)"))
    if proxy is not None:
        if proxy["frames"] != frames:
            found.append(Violation(SCHEMA_INVALID, "/proxy/frames",
                                   f"the proxy must have the master's {frames} frames (TIME-11)"))
        limit = verification["proxy_under_bytes"]
        if limit != proxy_byte_limit(frames):
            found.append(Violation(SCHEMA_INVALID, "/verification/proxy_under_bytes",
                                   f"the proxy limit of {frames} frames is "
                                   f"{proxy_byte_limit(frames)} bytes (P-10)"))
        elif proxy["bytes"] >= limit:
            found.append(Violation(SCHEMA_INVALID, "/proxy/bytes",
                                   f"the proxy must be under {limit} bytes (P-10)"))
    legacy = doc["legacy"]
    if legacy is not None and legacy["url"].split("/")[-2] != legacy["ledger_id"]:
        found.append(Violation(SCHEMA_INVALID, "/legacy/url", "the URL must name this ledger"))
    return found


def _locators(master: Mapping[str, Any], proxy: Mapping[str, Any] | None) -> list[Violation]:
    """``store.locator_invalid`` for a locator that does not name its own file, or that
    puts the master and proxy outside one production's folder (proposal)."""
    found = []
    production = None
    for name, media in (("master", master), ("proxy", proxy)):
        if media is None or media["locator"] is None:
            continue
        folder = media["locator"].partition("/sha256/")[0]
        at = f"/{name}/locator"
        if folder == LIBRARY:
            found.append(Violation(LOCATOR_INVALID, at,
                                   "a delivered file is in its production's folder, not the library"))
            continue
        if production is not None and folder != f"productions/{production}":
            found.append(Violation(LOCATOR_INVALID, at,
                                   "the master and the proxy are in one production's folder"))
            continue
        production = folder.removeprefix("productions/")
        found += locator_problems(media, production, f"/{name}")
    return found


__all__ = ["validate_delivery"]
