"""The Winter Menu imported by story 404 resolves through a library built from public
files only, by library identifiers, against a synthetic store; with the library's
facts r4 is timed at 1087 frames. Wrong kinds, capabilities and missing bytes are
named problems, and the records hold exactly what the public evidence says."""

from __future__ import annotations

import dataclasses

import pytest

from haynes_studio.canonical import timing_summary, validate_story, with_derived
from haynes_studio.library import import_version, resolve
from haynes_studio.library.model import Scope
from haynes_studio.library.resolve import references
from haynes_studio.library.winter_menu import winter_menu_requests
from tests.canonical.fixtures import NOW, REVISIONS, example
from tests.library.fixtures import (
    BY,
    SyntheticStore,
    imported,
    record_id,
    sources,
    story,
    winter_menu,
)

CONTENT_KINDS = {"cast", "set", "sound"}


@pytest.mark.parametrize("revision", [1, 2, 3, 4])
def test_each_revision_resolves_completely_and_is_timed(revision):
    library = winter_menu(revision).library
    store = SyntheticStore.holding(library)
    resolution = resolve(imported(revision).story, library, store)
    assert resolution.complete, resolution.problems
    assert len(resolution.resolved) == len(resolution.references)
    # Every reference is a pinned library ID, and every record the import names is used.
    named = {r["id"] for r in imported(revision).import_map["story_records"]
             if r["kind"] == "asset_version"}
    assert resolution.version_ids() == named == set(library.versions)
    # Bytes are asked of the store once per content-bearing version, never for voices.
    held = {(v.content.locator, v.content.sha256) for v in library.versions.values() if v.content}
    assert sorted(store.asked) == sorted(held)
    assert {library.version(i).kind for i in named if library.version(i).content} == CONTENT_KINDS
    frames = REVISIONS[revision][2]
    assert with_derived(imported(revision).story, facts=library.facts())["derived"]["frames"] == frames


def test_r4_is_timed_and_buildable_with_the_librarys_facts():
    library = winter_menu().library
    summary = timing_summary(imported(4).story, facts=library.facts())
    assert (summary.complete, summary.frames_known, summary.build_allowed) == (True, 1087, True)
    assert [row.frames for row in summary.boards] == [153, 94, 146, 84, 83, 122, 46, 251, 108]
    # Without the library nothing is timed and Build is refused (fail closed).
    bare = timing_summary(imported(4).story)
    assert (bare.complete, bare.frames_known, bare.build_allowed) == (False, 46, False)


def test_each_resolved_reference_names_its_record_pin_and_locator():
    library = winter_menu().library
    resolution = resolve(imported(4).story, library, SyntheticStore.holding(library))
    by_path = {item.path: item for item in resolution.resolved}
    set_item = by_path["/set/asset_version_id"]
    assert set_item.sha256 == "29ab6f47227cee7aa482e83f79cb4aad9949407b4a543f5a33f846119f3c5b58"
    assert set_item.pin == set_item.sha256
    assert set_item.locator == ("productions/prd_01M79V9FC00000000000000001/sha256/29/"
                                + set_item.sha256 + ".png")
    voice = by_path["/cast/0/voice_version_id"]
    assert (voice.kind, voice.sha256, voice.locator) == ("voice", None, None)
    assert voice.pin.startswith("sha256:")
    board_voice = next(item for path, item in by_path.items() if path.endswith("/voice/current_version_id"))
    assert board_voice.kind == "board_voice" and board_voice.locator is None


def test_missing_bytes_unknown_versions_and_wrong_kinds_are_named():
    library = winter_menu().library
    still = record_id(4, "still:cutouts/a-proud.png")
    sound = record_id(4, "sfx:gavel")
    store = SyntheticStore.holding(library, missing=[still])
    document = story()
    document["beds"][0]["asset_version_id"] = still  # a still where a sound belongs
    vote = next(b for b in document["boards"] if b["number"] == 8)
    cue = next(c for c in vote["cues"] if c["type"] == "sound")
    cue["asset_version_id"] = "asv_01M79V9FC0000000000000000Z"
    resolution = resolve(document, library, store)
    rules = {(v.rule, v.path) for v in resolution.problems}
    assert ("asset.kind_mismatch", "/beds/0/asset_version_id") in rules
    assert ("asset.bytes_missing", "/beds/0/asset_version_id") in rules
    i = document["boards"].index(vote)
    j = vote["cues"].index(cue)
    assert ("ref.unknown", f"/boards/{i}/cues/{j}/asset_version_id") in rules
    users = {r.path for r in references(document) if r.version_id == still}
    assert {path for rule, path in rules if rule == "asset.bytes_missing"} == users
    assert not resolution.complete
    assert library.version(sound).kind == "sound"


def test_a_wrong_capability_fails():
    """An opaque photo is not accepted as a keyed layer (section 5, review M6)."""
    library = winter_menu().library
    opaque = import_version(library, dataclasses.replace(
        next(r for r in winter_menu_requests(imported(4).story, imported(4).import_map, sources(4))[0]
             if r.kind == "cast"),
        version_id=None, capabilities=("opaque_photo",),
        provenance={"origin": "imported", "external": None, "source_key": "test:opaque-still",
                    "generator": {"role": "image"}}), by=BY, now=NOW).library
    opaque_id = next(v.id for v in opaque.versions.values() if v.source_key == "test:opaque-still")
    document = story()
    vote = next(b for b in document["boards"] if b["number"] == 8)
    i = document["boards"].index(vote)
    vote["cast"][0]["asset_version_id"] = opaque_id
    path = f"/boards/{i}/cast/0/asset_version_id"
    resolution = resolve(document, opaque, SyntheticStore.holding(opaque))
    assert [(v.rule, v.path) for v in resolution.problems] == [("asset.capability_mismatch", path)]
    # Story 404's validators say the same with the library's facts.
    draft = {k: v for k, v in document.items() if k != "derived"}
    draft["boards"] = [{k: v for k, v in b.items() if k != "derived"} for b in draft["boards"]]
    found = [(v.rule, v.path) for v in validate_story(draft, context="write", facts=opaque.facts())]
    assert found == [("asset.capability_mismatch", path)]
    # A whole-frame board does not composite layers, so the same still is accepted.
    vote["method"]["layer"] = "whole_frame"
    vote["method"]["motion"] = "i2v"
    assert resolve(document, opaque, SyntheticStore.holding(opaque)).complete


def test_a_board_photo_is_not_a_cast_still():
    library = winter_menu().library
    board_photo = example("valid/asset-version-photo-external.json")
    from haynes_studio.library import Library

    photos = Library.from_version_documents([board_photo])
    merged = Library(assets={**library.assets, **photos.assets},
                     versions={**library.versions, **photos.versions})
    document = story()
    document["boards"][0]["cast"][0]["asset_version_id"] = board_photo["id"]
    found = {(v.rule, v.path) for v in resolve(document, merged, SyntheticStore.holding(merged)).problems}
    assert found == {("asset.kind_mismatch", "/boards/0/cast/0/asset_version_id"),
                     ("asset.capability_mismatch", "/boards/0/cast/0/asset_version_id")}


def test_a_lone_board_resolves_too():
    library = winter_menu().library
    vote = next(b for b in story()["boards"] if b["number"] == 8)
    resolution = resolve(vote, library, SyntheticStore.holding(library))
    expected = (1 + len(vote["photo"]["input_asset_version_ids"]) + len(vote["cast"])
                + sum(1 for cue in vote["cues"] if cue["type"] == "sound"))
    assert resolution.complete and len(resolution.resolved) == len(references(vote)) == expected


def test_records_hold_the_public_evidence_and_nothing_guessed():
    library = winter_menu().library
    ledger = {item["path"].split("/the-winter-menu-r4/", 1)[1]: item
              for item in sources(4).ledger["assets"]}
    timeline = {(a["kind"], a.get("cue")): a for a in sources(4).timeline["audio"]}
    for version in library.versions.values():
        document = library.document(version.id)
        assert document["licence"]["commercial_use"] == "unknown"
        assert document["licence"]["checked_at"] is None and document["licence"]["name"] is None
        assert document["provenance"]["created_at"] == NOW
        if version.content is None:
            continue
        path = version.legacy["path"]
        if path in ledger:
            assert (version.content.sha256, version.content.bytes) == (ledger[path]["sha256"],
                                                                       ledger[path]["bytes"])
        else:
            assert version.content.bytes is None
            assert version.content.sha256 == timeline[("bed", "fire")]["sha256"]
    still = library.version(record_id(4, "still:cutouts/a-proud.png"))
    contract = example("valid/asset-version-cast.json")
    assert still.content.sha256 == contract["content"]["sha256"]
    generator = still.provenance["generator"]
    for name in ("workflow_sha256", "seed", "prompt_ref", "engine_job_id"):
        assert generator[name] == contract["provenance"]["generator"][name]
    assert generator["post"]["source_sha256"] == contract["provenance"]["generator"]["post"]["source_sha256"]
    voices = [v for v in library.versions.values() if v.kind == "voice"]
    assert all(library.asset(v.asset_id).scope == Scope(None) for v in voices)
    assert sorted(library.asset(v.asset_id).attributes["voice_id"] for v in voices) == [
        "af_bella", "af_heart", "af_nicole", "bf_emma"]


def test_the_vote_board_voice_matches_the_contract_example():
    library = winter_menu().library
    ours = library.document(record_id(4, "speech:shot:8"))["voice"]
    contract = example("valid/asset-version-board-voice.json")["voice"]
    for name in ("lead_ms", "gaps_ms", "speech_end_ms", "track"):
        assert ours[name] == contract[name]
    keep = ("speaker", "text", "engine", "voice_id", "sha256", "samples", "duration_ms",
            "duration_source", "offset_ms", "heard", "heard_matches")
    assert [{k: t[k] for k in keep} for t in ours["takes"]] == \
        [{k: t[k] for k in keep} for t in contract["takes"]]


def test_the_gaps_list_what_the_public_files_do_not_hold():
    gaps = winter_menu().gaps
    by_field: dict[str, set[str]] = {}
    for gap in gaps:
        by_field.setdefault(gap.field, set()).add(gap.source_key.split(":", 2)[2])
    assert by_field["content.bytes"] == {"bed:fire"}
    assert by_field["provenance.generator.files_sha256"] == {
        "voice:af_bella", "voice:af_heart", "voice:af_nicole", "voice:bf_emma"}
    assert by_field["voice.takes[].samples, sample_rate"] == {
        f"speech:shot:{shot}" for shot in (1, 2, 3, 4, 5, 6, 8, 9)}
    assert len(by_field["licence"]) == 24
    assert set(by_field) == {"content.bytes", "provenance.generator.files_sha256",
                             "voice.takes[].samples, sample_rate", "licence"}
