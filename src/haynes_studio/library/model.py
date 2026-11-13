"""Read-only models of the library records (contract sections 7 and 9).

An **asset** (``ast_``) is a library item: kind, name, scope, labels and attributes.
Its labels are mutable metadata (P-21); everything else about it is fixed when it is
made. An **asset version** (``asv_``) is one immutable version of an asset, numbered
1, 2, ... per asset: content, provenance and capabilities never change (D15). Its
``state`` moves only from ``candidate`` to ``promoted``; a licence moves from
``unknown`` to a checked value only by an appended record (section 7).

A version document as a read returns it (``studio.asset-version/v1``, the contract's
examples) carries its asset's kind, name, scope, labels and attributes as well;
:func:`version_document` joins them, :meth:`Asset.from_version_document` splits them
off again. :func:`pin` is the one place that says what a version *is*: its content
hash, or for the definition-only kinds a signature of the definition or the takes.

Nothing here reads files or calls services.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any

from haynes_studio.canonical.jsonvalues import normalize
from haynes_studio.canonical.model import Principal, to_document
from haynes_studio.jsonio import freeze, thaw

ASSET_SCHEMA = "studio.asset/v1"
ASSET_VERSION_SCHEMA = "studio.asset-version/v1"

KINDS = ("cast", "costume", "set", "prop", "sound", "motion", "voice", "character_card",
         "photo", "board_voice")
CAPABILITIES = ("rgba_cutout", "keyed_layer", "mask", "opaque_photo", "opaque_plate",
                "motion_clip", "set_loop", "tts_voice", "sound_effect", "sound_bed",
                "board_voice")
CANDIDATE, PROMOTED, BOARD = "candidate", "promoted", "board"
STATES = (CANDIDATE, PROMOTED, BOARD)
BOARD_KINDS = frozenset({"photo", "board_voice"})
DEFINITION_KINDS = frozenset({"voice", "board_voice"})  # no bytes: content is null

LAYER_CAPABILITIES = frozenset({"rgba_cutout", "keyed_layer"})  # section 5, review M6
OPAQUE_CAPABILITIES = frozenset({"opaque_photo", "opaque_plate"})

# Proposal (story 382): which capabilities each kind may claim. Section 9 lists the
# kinds and capabilities but does not pair them.
KIND_CAPABILITIES: Mapping[str, frozenset[str]] = MappingProxyType({
    "cast": frozenset({"rgba_cutout", "keyed_layer", "mask", "opaque_photo"}),
    "costume": frozenset({"rgba_cutout", "keyed_layer", "mask", "opaque_photo"}),
    "prop": frozenset({"rgba_cutout", "keyed_layer", "mask", "opaque_photo"}),
    "set": frozenset({"opaque_plate", "rgba_cutout", "keyed_layer", "mask"}),
    "motion": frozenset({"motion_clip", "set_loop", "keyed_layer", "mask"}),
    "sound": frozenset({"sound_effect", "sound_bed"}),
    "voice": frozenset({"tts_voice"}),
    "board_voice": frozenset({"board_voice"}),
    "photo": frozenset({"opaque_photo"}),
    "character_card": frozenset(),
})

# Proposal (story 382): the media types a capability needs. A JPEG has no alpha, so it
# cannot be an RGBA cutout.
CAPABILITY_MEDIA: Mapping[str, frozenset[str]] = MappingProxyType({
    "rgba_cutout": frozenset({"image/png", "image/webp"}),
    "keyed_layer": frozenset({"image/png", "image/webp", "video/mp4"}),
    "mask": frozenset({"image/png", "image/webp", "video/mp4"}),
    "opaque_photo": frozenset({"image/png", "image/jpeg", "image/webp"}),
    "opaque_plate": frozenset({"image/png", "image/jpeg", "image/webp", "video/mp4"}),
    "motion_clip": frozenset({"video/mp4"}),
    "set_loop": frozenset({"video/mp4"}),
    "sound_effect": frozenset({"audio/wav"}),
    "sound_bed": frozenset({"audio/wav"}),
})

# The store's extension for each validated media type (section 8).
MEDIA_EXTENSIONS: Mapping[str, str] = MappingProxyType({
    "video/mp4": "mp4", "audio/wav": "wav", "image/png": "png", "image/jpeg": "jpg",
    "image/webp": "webp", "application/json": "json",
})

KOKORO = "Kokoro-82M v1.0"
# Stock TTS voices this repository records as stock (VOICE-1, P-22): the four of the
# Winter Menu ledger (evidence-r4/production.json, "Kokoro-82M v1.0 stock voices ...;
# no cloning") and am_puck (docs/reference/services.md, OP341). The full stock list is
# read from the server with a Wyoming Describe, never assumed (services.md); a voice
# outside this list is refused (fail closed) until it is recorded here.
STOCK_VOICES: Mapping[str, frozenset[str]] = MappingProxyType({
    KOKORO: frozenset({"af_bella", "af_heart", "af_nicole", "am_puck", "bf_emma"}),
})


def is_stock_voice(model: str | None, voice_id: str | None) -> bool:
    return voice_id is not None and voice_id in STOCK_VOICES.get(model or "", frozenset())


def stock_voice_id(voice_id: str | None) -> bool:
    """True when ``voice_id`` is a recorded stock voice of any model."""
    return any(voice_id in ids for ids in STOCK_VOICES.values())


def signature(value: Any) -> str:
    """``sha256:`` plus the hex SHA-256 of canonical JSON (section 4: UTF-8, sorted keys,
    no whitespace, no NaN or Infinity, floats in shortest round-trip form, so a speed of
    ``1.0`` is ``1.0``). Times are integers already."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def locator_for(sha256: str, media_type: str, production_id: str | None) -> str:
    """The content-addressed locator of section 8: ``library/...`` for the global
    library, ``productions/<production_id>/...`` for a production's folder."""
    folder = "library" if production_id is None else f"productions/{production_id}"
    return f"{folder}/sha256/{sha256[:2]}/{sha256}.{MEDIA_EXTENSIONS[media_type]}"


def measured_ms(samples: int, rate: int) -> int:
    """TIME-1: ``ceil(samples * 1000 / rate)``, in integers."""
    return -(-samples * 1000 // rate)


# Records ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Scope:
    production_id: str | None  # None: the global library
    story_id: str | None = None  # board-scoped kinds only
    board_id: str | None = None

    _omit_none = ("story_id", "board_id")

    @classmethod
    def from_document(cls, doc: Mapping[str, Any]) -> Scope:
        return cls(production_id=doc["production_id"], story_id=doc.get("story_id"),
                   board_id=doc.get("board_id"))


@dataclass(frozen=True, slots=True)
class Content:
    sha256: str
    bytes: int | None  # None: not in the public record (a legacy import from evidence)
    media_type: str
    locator: str
    width: int | None = None
    height: int | None = None

    _omit_none = ("width", "height")

    @classmethod
    def from_document(cls, doc: Mapping[str, Any] | None) -> Content | None:
        if doc is None:
            return None
        return cls(sha256=doc["sha256"], bytes=doc["bytes"], media_type=doc["media_type"],
                   locator=doc["locator"], width=doc.get("width"), height=doc.get("height"))


@dataclass(frozen=True, slots=True)
class Licence:
    """Section 7. ``commercial_use`` is ``unknown`` until a check is recorded."""

    name: str | None
    url: str | None
    commercial_use: str
    attribution_required: bool | None
    checked_at: str | None
    checked_by: Principal | None
    note: str | None

    @classmethod
    def unknown(cls, note: str) -> Licence:
        return cls(name=None, url=None, commercial_use="unknown", attribution_required=None,
                   checked_at=None, checked_by=None, note=note)

    @classmethod
    def from_document(cls, doc: Mapping[str, Any]) -> Licence:
        by = doc["checked_by"]
        return cls(name=doc["name"], url=doc["url"], commercial_use=doc["commercial_use"],
                   attribution_required=doc["attribution_required"],
                   checked_at=doc["checked_at"],
                   checked_by=None if by is None else Principal.from_document(by),
                   note=doc["note"])


@dataclass(frozen=True, slots=True)
class Take:
    """One line's take in a board voice (VOICE-2)."""

    line_id: str
    speaker: str
    text: str
    voice_version_id: str
    engine: str
    voice_id: str
    sha256: str
    sample_rate: int | None
    samples: int | None
    duration_ms: int
    duration_source: str  # "samples" (TIME-1) or "legacy_duration_s"
    offset_ms: int
    heard: str | None
    heard_matches: bool | None
    signature: str

    @classmethod
    def from_document(cls, doc: Mapping[str, Any]) -> Take:
        return cls(**{name: doc.get(name) for name in cls.__slots__})


@dataclass(frozen=True, slots=True)
class BoardVoice:
    """A board voice version's takes and their offsets (VOICE-2, TIME-2)."""

    input_signature: str
    lead_ms: int
    gaps_ms: tuple[int, ...]
    speech_end_ms: int
    track: Content | None  # the assembled track; None when it was never assembled
    takes: tuple[Take, ...]
    track_note: str | None = None

    _omit_none = ("track_note",)

    @classmethod
    def from_document(cls, doc: Mapping[str, Any] | None) -> BoardVoice | None:
        if doc is None:
            return None
        return cls(input_signature=doc["input_signature"], lead_ms=doc["lead_ms"],
                   gaps_ms=tuple(doc["gaps_ms"]), speech_end_ms=doc["speech_end_ms"],
                   track=Content.from_document(doc["track"]),
                   takes=tuple(Take.from_document(t) for t in doc["takes"]),
                   track_note=doc.get("track_note"))

    @property
    def takes_ms(self) -> Mapping[str, int]:
        """Line ID to measured duration: what story 404's ``VoiceVersionFacts`` takes."""
        return MappingProxyType({take.line_id: take.duration_ms for take in self.takes})


@dataclass(frozen=True, slots=True)
class Asset:
    id: str
    kind: str
    name: str
    scope: Scope
    labels: tuple[str, ...]  # mutable metadata (P-21): changed only through set_labels
    attributes: Mapping[str, Any]
    revision: int = 1  # P-02: goes up on every label change
    created_at: str | None = None
    updated_at: str | None = None
    created_by: Principal | None = None

    _omit_none = ("created_at", "updated_at", "created_by")

    @classmethod
    def from_document(cls, doc: Mapping[str, Any]) -> Asset:
        doc = normalize(doc)
        by = doc.get("created_by")
        return cls(id=doc["id"], kind=doc["kind"], name=doc["name"],
                   scope=Scope.from_document(doc["scope"]), labels=tuple(doc["labels"]),
                   attributes=freeze(doc["attributes"]), revision=doc["revision"],
                   created_at=doc.get("created_at"), updated_at=doc.get("updated_at"),
                   created_by=None if by is None else Principal.from_document(by))

    @classmethod
    def from_version_document(cls, doc: Mapping[str, Any], *, revision: int = 1) -> Asset:
        """The asset a version document describes (its joined asset fields)."""
        doc = normalize(doc)
        return cls(id=doc["asset_id"], kind=doc["kind"], name=doc["name"],
                   scope=Scope.from_document(doc["scope"]), labels=tuple(doc["labels"]),
                   attributes=freeze(doc["attributes"]), revision=revision)

    def to_document(self) -> dict[str, Any]:
        return {"schema": ASSET_SCHEMA, **to_document(self)}


@dataclass(frozen=True, slots=True)
class AssetVersion:
    """One immutable version. ``provenance`` and ``legacy`` stay verbatim, read-only
    JSON; :attr:`source_key` and :attr:`origin` read from it."""

    id: str
    asset_id: str
    number: int
    kind: str
    state: str
    capabilities: tuple[str, ...]
    content: Content | None
    provenance: Mapping[str, Any]
    licence: Licence
    legacy: Mapping[str, Any] | None = None
    voice: BoardVoice | None = None

    @classmethod
    def from_document(cls, doc: Mapping[str, Any]) -> AssetVersion:
        doc = normalize(doc)
        return cls(id=doc["id"], asset_id=doc["asset_id"], number=doc["number"],
                   kind=doc["kind"], state=doc["state"],
                   capabilities=tuple(doc["capabilities"]),
                   content=Content.from_document(doc["content"]),
                   provenance=freeze(doc["provenance"]),
                   licence=Licence.from_document(doc["licence"]),
                   legacy=None if doc.get("legacy") is None else freeze(doc["legacy"]),
                   voice=BoardVoice.from_document(doc.get("voice")))

    @property
    def source_key(self) -> str | None:
        return self.provenance.get("source_key")

    @property
    def origin(self) -> str:
        return self.provenance["origin"]

    def has(self, capability: str) -> bool:
        return capability in self.capabilities

    def with_state(self, state: str) -> AssetVersion:
        return replace(self, state=state)


def version_document(version: AssetVersion, asset: Asset) -> dict[str, Any]:
    """The ``studio.asset-version/v1`` document a read returns: the version's own
    fields joined with its asset's kind, name, scope, labels and attributes."""
    out = {
        "schema": ASSET_VERSION_SCHEMA, "id": version.id, "asset_id": version.asset_id,
        "number": version.number, "kind": version.kind, "name": asset.name,
        "scope": to_document(asset.scope), "state": version.state,
        "labels": list(asset.labels), "attributes": thaw(asset.attributes),
        "capabilities": list(version.capabilities), "content": to_document(version.content),
        "provenance": thaw(version.provenance), "licence": to_document(version.licence),
        "legacy": thaw(version.legacy),
    }
    if version.voice is not None:
        out["voice"] = to_document(version.voice)
    return out


# What a version is ----------------------------------------------------------------------


def definition_signature(version: AssetVersion, asset: Asset) -> str:
    """A ``voice`` version's identity (section 8 "definition_signature"): canonical JSON
    of ``{engine, stock, voice_id}``, where ``engine`` is the TTS model
    (``Kokoro-82M v1.0``), as the contract's ``run-snapshot.json`` computes it."""
    generator = version.provenance.get("generator") or {}
    return signature({"engine": generator.get("model"), "stock": asset.attributes.get("stock"),
                      "voice_id": asset.attributes.get("voice_id")})


def take_signature(engine: str, voice_id: str, text: str, speed: float) -> str:
    """VOICE-3: canonical JSON of ``{engine, voice_id, text (NFC), speed}``, where
    ``engine`` is the TTS model or its digest, as the contract's board voice example
    computes it."""
    return signature({"engine": engine, "voice_id": voice_id,
                      "text": unicodedata.normalize("NFC", text), "speed": speed})


def input_signature(take_signatures: list[str], lead_ms: int, gaps_ms: list[int]) -> str:
    """VOICE-3 version signature: the takes plus lead and gaps (the contract's board
    voice example)."""
    return signature({"takes": list(take_signatures), "lead_ms": lead_ms,
                      "gaps_ms": list(gaps_ms)})


def takes_signature(voice: BoardVoice) -> str:
    """A ``board_voice`` version's identity: its input signature and take hashes
    (section 8). The offsets follow from the input signature (lead and gaps)."""
    return signature({"input_signature": voice.input_signature,
                      "takes": [take.sha256 for take in voice.takes]})


def pin(version: AssetVersion, asset: Asset) -> str:
    """What a version is, as a snapshot pins it (section 8): the content's ``sha256``
    (64 hex digits), or ``sha256:<hex>`` of the definition (``voice``) or of the input
    signature and take hashes (``board_voice``). Two versions of one asset never share
    a pin; re-importing the same pin under the same source key returns that version."""
    if version.content is not None:
        return version.content.sha256
    if version.voice is not None:
        return takes_signature(version.voice)
    return definition_signature(version, asset)


def content_fields(version: AssetVersion) -> dict[str, Any]:
    """The fields that never change once a version exists (D15), as plain JSON: what an
    idempotent re-import must agree with. ``state`` and ``licence`` are left out (they
    move by explicit promotion and appended licence records), and so are the creation
    principal and time, which a re-import cannot reproduce."""
    provenance = {key: value for key, value in thaw(version.provenance).items()
                  if key not in ("created_at", "created_by")}
    return {"kind": version.kind, "capabilities": sorted(version.capabilities),
            "content": to_document(version.content), "provenance": provenance,
            "legacy": thaw(version.legacy), "voice": to_document(version.voice)}


def take_offsets(lead_ms: int, gaps_ms: tuple[int, ...] | list[int],
                 durations_ms: tuple[int, ...] | list[int]) -> list[int]:
    """TIME-2: each take's start from board start."""
    offsets: list[int] = []
    for i in range(len(durations_ms)):
        offsets.append(lead_ms if i == 0 else offsets[-1] + durations_ms[i - 1] + gaps_ms[i - 1])
    return offsets


__all__ = [
    "ASSET_SCHEMA", "ASSET_VERSION_SCHEMA", "BOARD", "BOARD_KINDS", "CANDIDATE", "CAPABILITIES",
    "CAPABILITY_MEDIA", "DEFINITION_KINDS", "KINDS", "KIND_CAPABILITIES", "KOKORO",
    "LAYER_CAPABILITIES", "MEDIA_EXTENSIONS", "OPAQUE_CAPABILITIES", "PROMOTED", "STATES",
    "STOCK_VOICES", "Asset", "AssetVersion", "BoardVoice", "Content", "Licence", "Scope", "Take",
    "content_fields", "definition_signature", "input_signature", "is_stock_voice",
    "locator_for",
    "measured_ms", "pin", "signature", "stock_voice_id", "take_offsets", "take_signature",
    "takes_signature",
    "version_document",
]
