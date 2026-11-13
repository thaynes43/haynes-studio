"""Blob references and the stage completion record (contract section 8).

A stage record lists every blob of one finished stage. In the product it is a
Postgres row; in the local adapter it is a create-only JSON file at
``productions/<production_id>/records/<run_id>/<stage>.json``. Its bytes are canonical
JSON (section 4: UTF-8, keys sorted, no whitespace, no NaN) and hold **no time and no
writer** (proposal): the same stage outputs always give the same record bytes, so a
retried or concurrent commit of the same outputs is an idempotent ``EEXIST`` and one
with other outputs is ``store.collision``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from haynes_studio.jsonio import parse_strict
from haynes_studio.store.errors import LOCATOR_INVALID, RECORD_INVALID, StoreError
from haynes_studio.store.layout import (
    check_production_id,
    check_run_id,
    check_stage,
    is_sha256,
    parse_locator,
)

STAGE_RECORD_SCHEMA = "studio.stage-record/v1"  # proposal: a local-adapter file, not an API type
# Proposal: a stage lists at most this many outputs. The local adapter holds one open
# descriptor per output while it records the stage (well under the usual 1024 limit).
MAX_OUTPUTS = 256
# Proposal: an output name is a record key, not a path ("s2v_clip:a", "segment").
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_FIELDS = {"schema", "production_id", "run_id", "stage", "blobs"}
_BLOB_FIELDS = {"sha256", "bytes", "media_type", "locator"}


def canonical_json(value: Any) -> bytes:
    """Canonical JSON bytes (contract section 4): UTF-8, keys sorted, no whitespace,
    no NaN or Infinity; floats in Python's shortest round-trip form."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


@dataclass(frozen=True, slots=True)
class Blob:
    """One published blob: its hash, size, media type and locator."""

    sha256: str
    bytes: int
    media_type: str
    locator: str

    def __post_init__(self) -> None:
        parsed = parse_locator(self.locator)
        if not is_sha256(self.sha256) or parsed.sha256 != self.sha256:
            raise StoreError(LOCATOR_INVALID, f"the locator does not name hash {self.sha256!r}",
                             locator=self.locator)
        if parsed.media_type != self.media_type:
            raise StoreError(LOCATOR_INVALID,
                             f"the locator's extension is not media type {self.media_type!r}",
                             locator=self.locator)
        if type(self.bytes) is not int or self.bytes < 0:
            raise StoreError(RECORD_INVALID, f"bytes must be a non-negative integer, got {self.bytes!r}")

    def to_document(self) -> dict[str, Any]:
        return {"sha256": self.sha256, "bytes": self.bytes, "media_type": self.media_type,
                "locator": self.locator}


def check_name(name: object) -> str:
    if not isinstance(name, str) or _NAME.fullmatch(name) is None:
        raise StoreError(RECORD_INVALID, "an output name is 1 to 128 of A-Z, a-z, 0-9, "
                         f"'_', '.', ':' and '-', starting with a letter or digit, got {name!r}")
    return name


@dataclass(frozen=True, slots=True)
class StageRecord:
    """A completed stage: every blob it published, by output name. Its blobs live in
    the production's folder."""

    production_id: str
    run_id: str
    stage: str
    blobs: Mapping[str, Blob]

    def __post_init__(self) -> None:
        check_production_id(self.production_id)
        check_run_id(self.run_id)
        check_stage(self.stage)
        if not self.blobs:
            raise StoreError(RECORD_INVALID, "a stage record lists at least one blob")
        if len(self.blobs) > MAX_OUTPUTS:
            raise StoreError(RECORD_INVALID, f"a stage record lists at most {MAX_OUTPUTS} "
                             f"blobs, got {len(self.blobs)}")
        blobs = {}
        for count, (name, blob) in enumerate(self.blobs.items(), start=1):
            if count > MAX_OUTPUTS:  # counted as copied: a mapping may lie about its length
                raise StoreError(RECORD_INVALID, f"a stage record lists at most {MAX_OUTPUTS} "
                                 "blobs")
            check_name(name)
            if not isinstance(blob, Blob):
                raise StoreError(RECORD_INVALID, f"output {name!r} is not a Blob")
            if parse_locator(blob.locator).production_id != self.production_id:
                raise StoreError(LOCATOR_INVALID, f"output {name!r} is not in production "
                                 f"{self.production_id}'s folder", locator=blob.locator)
            blobs[name] = blob
        object.__setattr__(self, "blobs", MappingProxyType(dict(sorted(blobs.items()))))

    def to_document(self) -> dict[str, Any]:
        return {"schema": STAGE_RECORD_SCHEMA, "production_id": self.production_id,
                "run_id": self.run_id, "stage": self.stage,
                "blobs": {name: blob.to_document() for name, blob in self.blobs.items()}}

    def encode(self) -> bytes:
        """The record's canonical JSON bytes (what the local adapter stores)."""
        return canonical_json(self.to_document())

    @classmethod
    def decode(cls, data: bytes, *, source: str) -> StageRecord:
        """A record from its stored bytes; ``store.record_invalid`` if they are not a
        well-formed ``studio.stage-record/v1`` in canonical form."""
        try:
            document = parse_strict(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError) as error:
            raise StoreError(RECORD_INVALID, f"not strict JSON: {type(error).__name__}",
                             locator=source) from None
        try:
            record = cls._from_document(document)
        except StoreError as error:
            raise StoreError(RECORD_INVALID, error.message, locator=source) from None
        if record.encode() != data:
            raise StoreError(RECORD_INVALID, "not in canonical form", locator=source)
        return record

    @classmethod
    def _from_document(cls, document: Any) -> StageRecord:
        if not isinstance(document, dict) or set(document) != _FIELDS:
            raise StoreError(RECORD_INVALID, f"a stage record has exactly the fields {sorted(_FIELDS)}")
        if document["schema"] != STAGE_RECORD_SCHEMA:
            raise StoreError(RECORD_INVALID, f"schema {document['schema']!r} is not {STAGE_RECORD_SCHEMA!r}")
        blobs = document["blobs"]
        if not isinstance(blobs, dict) or not all(
                isinstance(blob, dict) and set(blob) == _BLOB_FIELDS for blob in blobs.values()):
            raise StoreError(RECORD_INVALID, f"each blob has exactly the fields {sorted(_BLOB_FIELDS)}")
        return cls(production_id=document["production_id"], run_id=document["run_id"],
                   stage=document["stage"], blobs={name: Blob(**blob) for name, blob in blobs.items()})
