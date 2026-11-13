"""The Winter Menu imported by story 404 and its library from public files, plus a
synthetic store. Results are immutable values (stories are copied before a test
changes one), so they are built once."""

from __future__ import annotations

import copy
from collections.abc import Iterable
from functools import cache

from haynes_studio.canonical.legacy_import import ImportResult, import_manifest
from haynes_studio.canonical.model import Principal
from haynes_studio.legacy import load, load_speech
from haynes_studio.library import Library
from haynes_studio.library.winter_menu import (
    WinterMenuLibrary,
    build_winter_menu_library,
    load_public_sources,
)
from tests.canonical.fixtures import NOW, OPERATOR, REVISIONS, TITLE, example, manifest_path, speech_path

BY = Principal.cli("studio legacy import", OPERATOR["iss"], OPERATOR["sub"])


@cache
def imported(revision: int = 4) -> ImportResult:
    """Story 404's import; r4 with the contract's import map, as its tests do."""
    existing = example("valid/legacy-import-map.json") if revision == 4 else None
    return import_manifest(load(manifest_path(revision)), load_speech(speech_path(revision)),
                           manifest_label=f"titles/the-winter-menu/{REVISIONS[revision][0]}",
                           operator=Principal.from_document(OPERATOR), now=NOW, existing=existing)


@cache
def sources(revision: int = 4):
    manifest, evidence, _ = REVISIONS[revision]
    return load_public_sources(TITLE, manifest, evidence)


@cache
def winter_menu(revision: int = 4) -> WinterMenuLibrary:
    result = imported(revision)
    return build_winter_menu_library(result.story, result.import_map, sources(revision), by=BY, now=NOW)


def story(revision: int = 4) -> dict:
    """A copy of the imported story (with derived values), safe to change."""
    return copy.deepcopy(imported(revision).story)


class SyntheticStore:
    """``exists(locator, sha256)`` over a set of held pairs; records every question."""

    def __init__(self, held: Iterable[tuple[str, str]]):
        self.held = set(held)
        self.asked: list[tuple[str, str]] = []

    @classmethod
    def holding(cls, library: Library, *, missing: Iterable[str] = ()) -> SyntheticStore:
        """Holds every content-bearing version's bytes except the versions in ``missing``."""
        skip = set(missing)
        return cls((v.content.locator, v.content.sha256) for v in library.versions.values()
                   if v.content is not None and v.id not in skip)

    def __call__(self, locator: str, sha256: str) -> bool:
        self.asked.append((locator, sha256))
        return (locator, sha256) in self.held


def record_id(revision: int, source_key_suffix: str) -> str:
    """The version ID the import map records for ``legacy:<job>:<suffix>``."""
    result = imported(revision)
    job = next(r["job"] for r in result.import_map["revisions"] if r["legacy_revision"] == revision)
    key = f"legacy:{job}:{source_key_suffix}"
    return next(r["id"] for r in result.import_map["story_records"] if r["source_key"] == key)
