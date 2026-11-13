"""Validators for ``studio.asset/v1`` and ``studio.asset-version/v1`` (contract sections
2, 7, 8, 9 and 10), with story 404's contexts and conventions.

Each validator refuses a document nested deeper than 64 levels, reads a normalized
copy (integral floats are ints), never raises for a malformed document, and returns
violations sorted by path. The JSON Schema files carry the field rules through their
``x-studio`` annotations: identifiers, the D42 external marker
(``prov.external_incomplete``), the licence object (``prov.licence_missing``), the
locator grammar of section 8 (``store.locator_invalid``), a voice's ``stock: true``
and its missing bytes (``voice.not_stock``), and each kind's and state's shape. The
code here runs only on a document the schema accepted and checks what one field
cannot: a stock voice ID, a locator that names the content's own hash and production,
capabilities that fit the kind and the media type, and a board voice's take offsets.

Contexts: ``read`` and ``write`` check the same rules (neither type has a ``derived``
block, so ``derived`` is an unknown field everywhere); ``queue_run`` adds nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from haynes_studio.canonical.validate import (
    READ,
    REF_DUPLICATE,
    SCHEMA_INVALID,
    _blocking,
    _check_context,
    _duplicates,
    _prepare,
    _sorted,
)
from haynes_studio.errors import Violation, pointer
from haynes_studio.library.model import (
    ASSET_SCHEMA,
    ASSET_VERSION_SCHEMA,
    CAPABILITY_MEDIA,
    KIND_CAPABILITIES,
    LAYER_CAPABILITIES,
    MEDIA_EXTENSIONS,
    OPAQUE_CAPABILITIES,
    is_stock_voice,
    measured_ms,
    stock_voice_id,
    take_offsets,
)
from haynes_studio.schemas import schema_violations

ASSET_FILE = "studio.asset.v1.schema.json"
ASSET_VERSION_FILE = "studio.asset-version.v1.schema.json"

CAPABILITY_MISMATCH = "asset.capability_mismatch"
LOCATOR_INVALID = "store.locator_invalid"
NOT_STOCK = "voice.not_stock"


def _v(rule: str, path: str, message: str) -> Violation:
    return Violation(rule, path, message)


def validate_asset(document: Any, *, context: str = READ) -> list[Violation]:
    """Every rule a ``studio.asset/v1`` document breaks, sorted by path."""
    _check_context(context)
    document, stop = _prepare(document, ASSET_SCHEMA)
    if stop is not None:
        return stop
    found = schema_violations(ASSET_FILE, document, default_rule=SCHEMA_INVALID)
    if not _blocking(found):
        found += _asset_rules(document)
    return _sorted(found)


def validate_asset_version(document: Any, *, context: str = READ) -> list[Violation]:
    """Every rule a ``studio.asset-version/v1`` document breaks, sorted by path."""
    _check_context(context)
    document, stop = _prepare(document, ASSET_VERSION_SCHEMA)
    if stop is not None:
        return stop
    found = schema_violations(ASSET_VERSION_FILE, document, default_rule=SCHEMA_INVALID)
    if not _blocking(found):
        found += _asset_rules(document) + _version_rules(document)
    return _sorted(found)


# Asset fields (shared by both documents) ---------------------------------------------------


def _asset_rules(doc: Mapping[str, Any]) -> list[Violation]:
    found = _duplicates(((pointer("labels", i), label) for i, label in enumerate(doc["labels"])),
                        "label")
    if doc["kind"] == "voice" and not stock_voice_id(doc["attributes"]["voice_id"]):
        found.append(_v(NOT_STOCK, "/attributes/voice_id",
                        f"{doc['attributes']['voice_id']!r} is not a recorded stock TTS voice "
                        "(VOICE-1, P-22)"))
    return found


# Version fields -----------------------------------------------------------------------------


def _version_rules(doc: Mapping[str, Any]) -> list[Violation]:
    found: list[Violation] = []
    kind, scope, content = doc["kind"], doc["scope"], doc["content"]
    if kind == "voice":
        found += _stock_voice(doc)
    found += _capabilities(kind, doc["capabilities"], content)
    if content is not None:
        found += locator_problems(content, scope["production_id"], "/content")
    voice = doc.get("voice")
    if voice is not None:
        found += _board_voice(voice, scope["production_id"])
    legacy = doc["legacy"]
    if legacy is not None and legacy["source_key"] != doc["provenance"].get("source_key"):
        found.append(_v(SCHEMA_INVALID, "/legacy/source_key",
                        "must be the provenance's source_key (proposal)"))
    return found


def _stock_voice(doc: Mapping[str, Any]) -> list[Violation]:
    """VOICE-1: a ``voice`` version is a declared stock voice of a known model, with no
    sample behind it. The schema has checked ``stock: true`` and that it has no bytes."""
    generator = doc["provenance"]["generator"]
    voice_id = doc["attributes"]["voice_id"]
    found = []
    # _asset_rules has already refused a voice ID that no model lists as stock.
    if stock_voice_id(voice_id) and not is_stock_voice(generator.get("model"), voice_id):
        found.append(_v(NOT_STOCK, "/attributes/voice_id",
                        f"{voice_id!r} is not a recorded stock voice of model "
                        f"{generator.get('model')!r} (VOICE-1, P-22)"))
    if "voice_id" in generator and generator["voice_id"] != voice_id:
        found.append(_v(NOT_STOCK, "/provenance/generator/voice_id",
                        "the generator's voice_id must be the asset's stock voice_id"))
    if generator.get("stock") is False:
        found.append(_v(NOT_STOCK, "/provenance/generator/stock", "a voice is a stock voice"))
    if "source_sample_sha256" in generator:
        found.append(_v(NOT_STOCK, "/provenance/generator/source_sample_sha256",
                        "a voice made from a recorded sample is a clone (story 405 excludes "
                        "cloning)"))
    if doc["provenance"]["origin"] != "declared":
        found.append(_v(NOT_STOCK, "/provenance/origin",
                        "a stock voice is declared (a definition), never generated or uploaded"))
    return found


def _capabilities(kind: str, capabilities: list[str], content: Mapping | None) -> list[Violation]:
    """Capabilities fit the kind and the media type, and an opaque photo or plate is
    never also a layer (review M6). Proposal tables: model.KIND_CAPABILITIES and
    model.CAPABILITY_MEDIA."""
    found = []
    claimed = set(capabilities)
    for i, capability in enumerate(capabilities):
        at = pointer("capabilities", i)
        if capability not in KIND_CAPABILITIES[kind]:
            found.append(_v(CAPABILITY_MISMATCH, at,
                            f"a {kind} version cannot have {capability}"))
        elif capability in LAYER_CAPABILITIES and claimed & OPAQUE_CAPABILITIES:
            found.append(_v(CAPABILITY_MISMATCH, at,
                            f"an opaque photo or plate is not a render-ready layer; {capability} "
                            "needs a cutout or keyed layer (review M6)"))
        elif content is not None and capability in CAPABILITY_MEDIA \
                and content["media_type"] not in CAPABILITY_MEDIA[capability]:
            found.append(_v(CAPABILITY_MISMATCH, at,
                            f"{content['media_type']} cannot carry {capability}"))
    return found


def locator_problems(content: Mapping[str, Any], production_id: str | None,
                     prefix: str) -> list[Violation]:
    """``store.locator_invalid`` for a locator that passed the section 8 grammar but
    does not name this content: its file name is the content's ``sha256``, its folder
    the hash's first two digits, its extension the media type's, and its production
    folder the version's own production (a global version lives under ``library/``).
    Proposal: the production rule."""
    locator, sha256 = content["locator"], content["sha256"]
    folder, _, rest = locator.partition("/sha256/")
    shard, _, name = rest.partition("/")
    digest, _, ext = name.partition(".")
    at = prefix + "/locator"
    found = []
    if digest != sha256:
        found.append(_v(LOCATOR_INVALID, at,
                        "the locator names another hash than the content's sha256"))
    elif shard != digest[:2]:
        found.append(_v(LOCATOR_INVALID, at, "the folder must be the hash's first two digits"))
    expected = MEDIA_EXTENSIONS[content["media_type"]]
    if ext != expected:
        found.append(_v(LOCATOR_INVALID, at, f"{content['media_type']} is stored as .{expected}"))
    if folder != "library" and folder != f"productions/{production_id}":
        found.append(_v(LOCATOR_INVALID, at,
                        "a production folder is the version's own production; a global version "
                        "lives under library/"))
    return found


def _board_voice(voice: Mapping[str, Any], production_id: str | None) -> list[Violation]:
    """VOICE-2 and TIME-2: one take per line, at offsets that follow from the lead, the
    gaps and the measured takes; every take from a stock voice."""
    found: list[Violation] = []
    takes = voice["takes"]
    durations = [take["duration_ms"] for take in takes]
    if len(voice["gaps_ms"]) != len(takes) - 1:
        found.append(_v(SCHEMA_INVALID, "/voice/gaps_ms",
                        f"{len(takes)} takes need {len(takes) - 1} gaps (one before each "
                        "later line)"))
    else:
        offsets = take_offsets(voice["lead_ms"], voice["gaps_ms"], durations)
        for i, (take, offset) in enumerate(zip(takes, offsets)):
            if take["offset_ms"] != offset:
                found.append(_v(SCHEMA_INVALID, pointer("voice", "takes", i, "offset_ms"),
                                f"must be {offset}: the lead, gaps and earlier takes (TIME-2)"))
        end = offsets[-1] + durations[-1]
        if voice["speech_end_ms"] != end:
            found.append(_v(SCHEMA_INVALID, "/voice/speech_end_ms",
                            f"must be {end}: the last take's end"))
    for i, take in enumerate(takes):
        if take["duration_source"] == "samples":
            expected = measured_ms(take["samples"], take["sample_rate"])
            if take["duration_ms"] != expected:
                found.append(_v(SCHEMA_INVALID, pointer("voice", "takes", i, "duration_ms"),
                                f"must be {expected}: ceil(samples * 1000 / rate) (TIME-1)"))
        if not stock_voice_id(take["voice_id"]):
            found.append(_v(NOT_STOCK, pointer("voice", "takes", i, "voice_id"),
                            f"{take['voice_id']!r} is not a recorded stock TTS voice (VOICE-1)"))
    found += _duplicates(((pointer("voice", "takes", i, "line_id"), take["line_id"])
                          for i, take in enumerate(takes)), "line")
    if voice["track"] is not None:
        found += locator_problems(voice["track"], production_id, "/voice/track")
    return found


__all__ = ["CAPABILITY_MISMATCH", "LOCATOR_INVALID", "NOT_STOCK", "REF_DUPLICATE",
           "locator_problems", "validate_asset", "validate_asset_version"]
