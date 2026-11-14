"""The Winter Menu imported by story 404 and its library from public files, plus a
synthetic store. Results are immutable values (stories are copied before a test
changes one), so they are built once."""

from __future__ import annotations

import copy
import dataclasses
import hashlib
from collections.abc import Iterable
from functools import cache
from types import MappingProxyType

from haynes_studio.canonical.legacy_import import ImportResult, import_manifest
from haynes_studio.canonical.model import Principal
from haynes_studio.jsonio import read_json
from haynes_studio.legacy import load, load_speech
from haynes_studio.library import Library
from haynes_studio.library.model import Content, locator_for
from haynes_studio.library.winter_menu import (
    REGISTER_PATH,
    LicenceRegister,
    WinterMenuLibrary,
    build_winter_menu_library,
    load_licence_register,
    load_public_sources,
)
from tests.canonical.fixtures import NOW, OPERATOR, REVISIONS, TITLE, example, manifest_path, speech_path
from tests.support.policy import REPO_ROOT

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
def register_document() -> dict:
    """The model licence register as committed (story 809)."""
    return read_json(REPO_ROOT / REGISTER_PATH).document


@cache
def register() -> LicenceRegister:
    return load_licence_register(REPO_ROOT / REGISTER_PATH)


@cache
def winter_menu(revision: int = 4) -> WinterMenuLibrary:
    result = imported(revision)
    return build_winter_menu_library(result.story, result.import_map, sources(revision),
                                     licences=register(), by=BY, now=NOW)


def with_tracks(library: Library) -> Library:
    """The library with a track recorded on every board voice that has none (a content
    record only, no bytes): the legacy voices as they would be once assembled, for the
    tests of the other currency rules. A voice without a track is stale (story 857)."""
    versions = dict(library.versions)
    for version in library.versions.values():
        if version.voice is not None and version.voice.track is None:
            digest = hashlib.sha256(f"track of {version.id}".encode()).hexdigest()
            production = library.assets[version.asset_id].scope.production_id
            track = Content(sha256=digest, bytes=None, media_type="audio/wav",
                            locator=locator_for(digest, "audio/wav", production))
            versions[version.id] = dataclasses.replace(
                version, voice=dataclasses.replace(version.voice, track=track, track_note=None))
    return Library(assets=library.assets, versions=MappingProxyType(versions))


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
