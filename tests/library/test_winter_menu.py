"""The Winter Menu imported by story 404 resolves through a library built from public
files only, by library identifiers, against a synthetic store; with the library's
facts r4 is timed at 1087 frames. Wrong kinds, capabilities and missing bytes are
named problems, and the records hold exactly what the public evidence says."""

from __future__ import annotations

import dataclasses

import pytest

from haynes_studio.canonical import timing_summary, validate_story, with_derived
from haynes_studio.errors import ContractError
from haynes_studio.library import import_version, resolve, validate_asset_version
from haynes_studio.library.model import Scope
from haynes_studio.library.resolve import references
from haynes_studio.library.winter_menu import LicenceRegister, winter_menu_requests
from tests.canonical.fixtures import NOW, REVISIONS, example
from tests.library.fixtures import (
    BY,
    SyntheticStore,
    imported,
    record_id,
    register,
    register_document,
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
        next(r for r in winter_menu_requests(imported(4).story, imported(4).import_map, sources(4),
                                             register())[0]
             if r.kind == "cast"),
        version_id=None, capabilities=("opaque_photo",), legacy=None,
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
    assert by_field["provenance.generator.model"] == {
        "sfx:crow", "sfx:crunch", "sfx:gavel", "sfx:sting", "bed:fire"}
    # Only Stable Audio's conditional terms stay unknown; the images' and voices' are recorded.
    assert by_field["licence"] == {"sfx:crow", "sfx:crunch", "sfx:gavel", "sfx:sting", "bed:fire"}
    assert all(gap.reason.startswith("Register entry stable-audio;")
               for gap in gaps if gap.field == "licence")
    assert set(by_field) == {"content.bytes", "provenance.generator.files_sha256",
                             "provenance.generator.model", "voice.takes[].samples, sample_rate",
                             "licence"}


def test_signatures_and_pins_agree_with_the_contract_examples():
    """The contract's run snapshot and board voice example fix the definition, take and
    input signatures; the library computes the same values from public files."""
    library = winter_menu().library
    resolution = resolve(imported(4).story, library, SyntheticStore.holding(library))
    ours = {}
    for item in resolution.resolved:
        entry = item.snapshot_entry()
        key = (entry["kind"], entry.get("sha256") or entry.get("definition_signature")
               or tuple(entry["take_sha256"]))
        ours[key] = {k: v for k, v in entry.items() if k != "id"}
    contract = example("valid/run-snapshot.json")["resolved_asset_versions"]
    for entry in contract:
        key = (entry["kind"], entry.get("sha256") or entry.get("definition_signature")
               or tuple(entry["take_sha256"]))
        if key[0] == "photo":
            continue  # E0 keyframes: not in story 404's import
        assert ours[key] == {k: v for k, v in entry.items() if k != "id"}, key
    vote = library.document(record_id(4, "speech:shot:8"))["voice"]
    expected = example("valid/asset-version-board-voice.json")["voice"]
    assert vote["input_signature"] == expected["input_signature"]
    assert [t["signature"] for t in vote["takes"]] == [t["signature"] for t in expected["takes"]]


def test_facts_with_the_story_mark_changed_boards_stale():
    library = winter_menu().library
    document = story()
    summary = timing_summary(document, facts=library.facts(document))
    assert (summary.frames_known, summary.build_allowed) == (1087, True)

    def stale(change):
        edited = story()
        board = edited["boards"][0]
        change(edited, board)
        found = {(v.rule, v.path) for v in validate_story(
            {**{k: v for k, v in edited.items() if k != "derived"},
             "boards": [{k: v for k, v in b.items() if k != "derived"} for b in edited["boards"]]},
            context="queue_run", facts=library.facts(edited))}
        return ("voice.stale", "/boards/0/voice/current_version_id") in found

    assert stale(lambda s, b: b["lines"][0].update(text="Day three hundred forty-one."))
    assert stale(lambda s, b: b["timing"].update(lead_ms=5000))
    assert stale(lambda s, b: b["lines"][0].update(speaker="b"))
    assert stale(lambda s, b: s["cast"][0].update(voice_version_id=s["cast"][1]["voice_version_id"]))
    assert not stale(lambda s, b: b.update(title="Day 340"))


def test_a_story_must_embed_its_boards_and_board_versions_stay_on_their_board():
    library = winter_menu().library
    store = SyntheticStore.holding(library)
    document = story()
    del document["boards"]
    found = [(v.rule, v.path) for v in resolve(document, library, store).problems]
    assert found == [("schema.invalid", "/boards")]
    assert [v.rule for v in resolve({"schema": "studio.production/v1"}, library, store).problems] \
        == ["schema.unsupported"]
    document = story()
    document["boards"][0]["voice"]["current_version_id"] = record_id(4, "speech:shot:8")
    found = [(v.rule, v.path) for v in resolve(document, library, store).problems]
    assert found == [("asset.scope_mismatch", "/boards/0/voice/current_version_id")]
    document = story()
    document["production_id"] = "prd_01M79V9FC00000000000000009"
    found = {v.rule for v in resolve(document, library, store).problems}
    assert found == {"asset.scope_mismatch"}  # every production version; stock voices are global


def test_the_private_import_returns_the_public_versions():
    """Story 425 and 428's import: the same hashes with the store's byte counts return
    the versions built from public files; the bed keeps bytes: null."""
    library = winter_menu().library
    requests, _ = winter_menu_requests(imported(4).story, imported(4).import_map, sources(4),
                                       register())
    for request in requests:
        if request.content is None:
            continue
        size = request.content.bytes or 1_000_000
        measured = {"width": 1104, "height": 1472} if request.content.media_type == "image/png" else {}
        again = import_version(library, dataclasses.replace(
            request, content=dataclasses.replace(request.content, bytes=size, **measured)),
            by=BY, now=NOW)
        assert (again.created, again.version) == (False, library.version(request.version_id))
        assert again.version.content.width is None  # versions never change
    bed = library.version(record_id(4, "bed:fire"))
    assert bed.content.bytes is None
    # A recorded measurement still has to agree.
    still = next(r for r in requests if r.kind == "cast")
    with pytest.raises(ContractError) as caught:
        import_version(library, dataclasses.replace(still, content=dataclasses.replace(
            still.content, bytes=still.content.bytes + 1)), by=BY, now=NOW)
    assert caught.value.violations[0].rule == "idempotency.mismatch"


# Licences (story 809): the register, the library's licence objects and the contract
# examples agree.

ENGINE_KEYS = {"qwen-image", "kokoro", "stable-audio", "wan-ti2v", "wan-s2v", "asr", "controlfoley"}
TO_CONTRACT = {"allowed": "allowed", "noncommercial": "noncommercial",
               "conditional": "unknown", "unknown": "unknown"}
RESTRICTION = {"allowed": 0, "conditional": 1, "unknown": 2, "noncommercial": 3}


def _engine(key):
    return next(e for e in register_document()["engines"] if e["key"] == key)


def _file(name):
    """The register file whose recorded name is ``name`` (a contract example's file name)."""
    found = [f for f in register_document()["files"] if name in f["recorded_as"]]
    assert len(found) == 1, name
    return found[0]


def test_the_register_has_one_checked_entry_per_engine_and_file():
    document = register_document()
    engines = {e["key"]: e for e in document["engines"]}
    assert set(engines) == ENGINE_KEYS
    files = document["files"]
    assert len({f["key"] for f in files}) == len(files)
    assert {f["engine"] for f in files} == ENGINE_KEYS
    for item in files + document["engines"]:
        use, licence = item["outputs_commercial_use"], item["licence"]
        assert licence["commercial_use"] == TO_CONTRACT[use], item["key"]
        assert licence["checked_at"] == document["checked_at"] and licence["checked_by"]
        assert licence["url"].startswith("https://") and licence["name"], item["key"]
        if licence["commercial_use"] != "allowed":
            assert licence["note"], item["key"]  # the reason or the condition
    for item in files:
        assert item["source"].startswith("https://huggingface.co/"), item["key"]
        assert item["evidence"] and all(e["url"].startswith("https://") for e in item["evidence"])
    for key, engine in engines.items():
        mine = [f for f in files if f["engine"] == key]
        assert engine["files"] == [f["key"] for f in mine]
        worst = max(RESTRICTION[f["outputs_commercial_use"]] for f in mine)
        assert RESTRICTION[engine["outputs_commercial_use"]] == worst, key
    # A conditional or non-commercial term is never softened to "allowed".
    assert {k: e["outputs_commercial_use"] for k, e in engines.items()} == {
        "qwen-image": "noncommercial", "kokoro": "allowed", "stable-audio": "conditional",
        "wan-ti2v": "allowed", "wan-s2v": "allowed", "asr": "allowed",
        "controlfoley": "noncommercial"}


def test_every_register_licence_is_a_valid_licence_object():
    """Each licence object passes the asset version schema in place of the cast example's."""
    document = register_document()
    for item in document["files"] + document["engines"]:
        version = example("valid/asset-version-cast.json")
        version["licence"] = item["licence"]
        assert list(validate_asset_version(version, context="write")) == [], item["key"]


def test_each_version_takes_its_licence_from_the_register():
    library = winter_menu().library
    expected = {"cast": "qwen-image", "set": "qwen-image", "sound": "stable-audio",
                "voice": "kokoro", "board_voice": "kokoro"}
    seen = set()
    for version in library.versions.values():
        key = expected[version.kind]
        assert library.document(version.id)["licence"] == _engine(key)["licence"], version.id
        seen.add(key)
    assert len(library.versions) == 24 and seen == {"qwen-image", "stable-audio", "kokoro"}


def test_a_model_the_register_does_not_name_stays_unknown_with_its_reason():
    changed = dataclasses.replace(sources(4), prompts={**sources(4).prompts,
                                                       "models": "Some other image model"})
    requests, gaps = winter_menu_requests(imported(4).story, imported(4).import_map, changed,
                                          register())
    images = [r for r in requests if r.kind in ("cast", "set")]
    assert images and all(r.licence.commercial_use == "unknown" and r.licence.name is None
                          for r in images)
    assert "no entry for the image model 'Some other image model'" in images[0].licence.note
    keys = {g.source_key for g in gaps if g.field == "licence"}
    assert {r.provenance["source_key"] for r in images} <= keys
    # A name matches only as a whole: a later version is not the recorded one.
    assert register().licence_for("image", "Qwen-Image 2.10 int8").commercial_use == "unknown"
    assert register().licence_for("voice", "Kokoro-82M v1.0.1").commercial_use == "unknown"
    kokoro = register().licence_for("voice", "Kokoro-82M v1.0 stock voices")
    assert (kokoro.name, kokoro.commercial_use) == ("Apache-2.0", "allowed")
    for text in ("audio-authoring (Stable Audio 3 Small SFX, CPU)", "Stable Audio 3 Small-SFX"):
        assert register().licence_for("sound", text).name == \
            "Stability AI Community License Agreement"
    assert register().licence_for("image", None).commercial_use == "unknown"
    # Two engines claiming the same name is ambiguous, never a guess.
    twice = LicenceRegister(register().engines + register().engines[:1])
    licence = twice.licence_for("image", sources(4).prompts["models"])
    assert licence.commercial_use == "unknown" and "several entries" in licence.note


def test_the_contract_examples_take_their_licences_from_the_register():
    assert example("valid/asset-version-cast.json")["licence"] == _engine("qwen-image")["licence"]
    assert example("invalid/store-locator-invalid.json")["document"]["licence"] == \
        _engine("qwen-image")["licence"]
    assert example("valid/asset-version-board-voice.json")["licence"] == _engine("kokoro")["licence"]
    for run in (example("valid/run-succeeded.json"),
                example("invalid/credit-outside-video-sound.json")["document"]):
        for engine in run["provenance"]["engines"]:
            if engine["role"] == "writer":
                assert engine["licence"] is None  # a frontier agent, not a model the studio runs
                continue
            assert engine["licence"] == _engine(engine["key"])["licence"], engine["key"]
            for item in engine.get("files", []):
                assert item["licence"] == _file(item["name"])["licence"], item["name"]
