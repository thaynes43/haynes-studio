"""Library operations: idempotent import, the next number for changed bytes, pins that
never move, labels outside version content, explicit and idempotent promotion, the
section 9 filters and the facts story 404 takes."""

from __future__ import annotations

import dataclasses

import pytest

from haynes_studio.canonical.ids import Minter
from haynes_studio.errors import ContractError
from haynes_studio.library import (
    EMPTY,
    Library,
    import_version,
    pin,
    promote,
    set_labels,
)
from haynes_studio.library.library import Outcome, VersionRequest
from haynes_studio.library.model import Content, Licence, Scope, content_fields, version_document
from haynes_studio.library.winter_menu import build_winter_menu_library, winter_menu_requests
from tests.canonical.fixtures import NOW, example
from tests.library.fixtures import BY, imported, record_id, register, sources, winter_menu

LATER = "2026-11-14T09:00:00Z"
OTHER = "0" * 63 + "1"


def minter():
    return Minter(clock=lambda: 1_800_000_000_000, random_bits=lambda: 7)


def requests():
    result = imported(4)
    return winter_menu_requests(result.story, result.import_map, sources(4), register())[0]


def still_request(**changes) -> VersionRequest:
    request = next(r for r in requests() if r.kind == "cast")
    return dataclasses.replace(request, **changes)


def with_bytes(request: VersionRequest, sha256: str) -> VersionRequest:
    content = request.content
    locator = content.locator.replace(content.sha256, sha256).replace(
        f"/{content.sha256[:2]}/", f"/{sha256[:2]}/")
    return dataclasses.replace(request, version_id=None,
                               content=dataclasses.replace(content, sha256=sha256, locator=locator))


def test_importing_the_same_source_twice_is_idempotent():
    first = winter_menu()
    result = imported(4)
    second = build_winter_menu_library(result.story, result.import_map, sources(4),
                                       licences=register(), by=BY, now=LATER,
                                       library=first.library)
    assert first.created == len(first.library.versions) == 24
    assert second.created == 0
    assert second.library == first.library
    assert [o.version.id for o in second.outcomes] == [o.version.id for o in first.outcomes]


def test_every_version_takes_the_id_the_import_map_records():
    library = winter_menu().library
    named = {r["id"] for r in imported(4).import_map["story_records"] if r["kind"] == "asset_version"}
    assert set(library.versions) == named
    assert len(library.assets) == 24  # one asset per source key


def test_changed_bytes_make_the_next_number_and_pins_stay():
    library = winter_menu().library
    old_id = record_id(4, "still:cutouts/a-proud.png")
    old = library.version(old_id)
    before = library.document(old_id)
    changed = import_version(library, with_bytes(still_request(), OTHER), by=BY, now=LATER,
                             minter=minter())
    assert changed.created
    new = changed.version
    assert (new.asset_id, new.number) == (old.asset_id, 2)
    assert new.id != old_id and new.content.sha256 == OTHER
    after = changed.library
    assert after.version(old_id) == old  # the pinned ID still names the same bytes
    assert after.pin(old_id) == old.content.sha256
    assert after.document(old_id) == before
    assert after.latest(old.asset_id) == new  # pickers only
    # The old bytes again return version 1, never a third number.
    again = import_version(after, still_request(version_id=None), by=BY, now=LATER, minter=minter())
    assert (again.created, again.version.id) == (False, old_id)
    # The changed bytes again return version 2.
    repeat = import_version(after, with_bytes(still_request(), OTHER), by=BY, now=LATER, minter=minter())
    assert (repeat.created, repeat.version.id) == (False, new.id)


def test_same_bytes_with_other_immutable_fields_is_a_mismatch():
    library = winter_menu().library
    for change in ({"capabilities": ("keyed_layer",)},
                   {"provenance": {**still_request().provenance, "external": None, "origin": "derived"}}):
        with pytest.raises(ContractError) as caught:
            import_version(library, still_request(**change), by=BY, now=LATER)
        assert [v.rule for v in caught.value.violations] == ["idempotency.mismatch"]


def test_ids_are_never_reused_or_renamed():
    library = winter_menu().library
    old_id = record_id(4, "still:cutouts/a-proud.png")
    other_id = record_id(4, "still:cutouts/b-deadpan.png")
    with pytest.raises(ContractError) as caught:  # the same bytes under another ID
        import_version(library, still_request(version_id=other_id), by=BY, now=LATER)
    assert caught.value.violations[0].rule == "idempotency.mismatch"
    with pytest.raises(ContractError) as caught:  # new bytes under an ID in use
        import_version(library, dataclasses.replace(with_bytes(still_request(), OTHER),
                                                    version_id=other_id), by=BY, now=LATER)
    assert caught.value.violations[0].rule == "ref.duplicate"
    assert library.version(old_id).id == old_id


def test_a_source_key_names_one_asset():
    library = winter_menu().library
    for change, path in (({"kind": "prop"}, "/kind"), ({"scope": Scope(None)}, "/scope"),
                         ({"attributes": {"character_slot": "a", "expression": "smug"}}, "/attributes")):
        with pytest.raises(ContractError) as caught:
            import_version(library, with_bytes(still_request(**change), OTHER), by=BY, now=LATER)
        assert [(v.rule, v.path) for v in caught.value.violations] == [("idempotency.mismatch", path)]


def test_an_import_needs_a_source_key_and_a_valid_version():
    request = still_request(version_id=None)
    with pytest.raises(ContractError) as caught:
        import_version(EMPTY, dataclasses.replace(request, provenance={
            **request.provenance, "source_key": None}), by=BY, now=NOW)
    assert caught.value.violations[0].rule == "asset.source_key_required"
    with pytest.raises(ContractError) as caught:
        import_version(EMPTY, dataclasses.replace(request, capabilities=("opaque_photo", "keyed_layer")),
                       by=BY, now=NOW)
    assert [v.rule for v in caught.value.violations] == ["asset.capability_mismatch"]
    with pytest.raises(ContractError) as caught:
        import_version(EMPTY, dataclasses.replace(request, licence=Licence(
            name=None, url=None, commercial_use="allowed", attribution_required=None,
            checked_at=None, checked_by=None, note=None)), by=BY, now=NOW)
    assert {v.rule for v in caught.value.violations} == {"schema.invalid"}


def test_labels_are_mutable_metadata_outside_version_content():
    library = winter_menu().library
    version_id = record_id(4, "still:cutouts/a-proud.png")
    asset = library.asset_of(version_id)
    version = library.version(version_id)
    relabelled = set_labels(library, asset.id, ["Yellowbirds", "A", "hero"], now=LATER,
                            revision=asset.revision)
    assert relabelled.asset(asset.id).labels == ("Yellowbirds", "A", "hero")
    assert relabelled.asset(asset.id).revision == asset.revision + 1
    assert relabelled.version(version_id) == version
    assert relabelled.pin(version_id) == library.pin(version_id)
    assert content_fields(relabelled.version(version_id)) == content_fields(version)
    assert relabelled.document(version_id)["labels"] == ["Yellowbirds", "A", "hero"]
    assert [v.id for v in relabelled.search(labels=["hero"])] == [version_id]
    with pytest.raises(ContractError) as caught:
        set_labels(relabelled, asset.id, ["x"], now=LATER, revision=asset.revision)
    assert (caught.value.violations[0].rule, caught.value.violations[0].status) == (
        "conflict.revision", "conflict")
    with pytest.raises(ContractError):
        set_labels(library, asset.id, "abc", now=LATER)
    with pytest.raises(ContractError) as caught:
        set_labels(library, asset.id, ["A", "A"], now=LATER)
    assert caught.value.violations[0].rule == "ref.duplicate"


def test_candidates_are_hidden_until_promoted_explicitly_and_idempotently():
    request = with_bytes(still_request(state="candidate"), OTHER)
    request = dataclasses.replace(request, legacy=None,
                                  provenance={**request.provenance, "source_key": "test:candidate"})
    outcome = import_version(EMPTY, request, by=BY, now=NOW, minter=minter())
    library, candidate = outcome.library, outcome.version
    assert library.search() == () and library.latest(candidate.asset_id) is None
    assert library.search(include_candidates=True) == (candidate,)
    promoted = promote(library, candidate.id, by=BY, now=LATER)
    assert promoted.created and promoted.version.state == "promoted"
    assert (promoted.version.id, promoted.library.pin(candidate.id)) == (candidate.id, library.pin(candidate.id))
    again = promote(promoted.library, candidate.id, by=BY, now=LATER)
    assert (again.created, again.library) == (False, promoted.library)
    assert promoted.library.latest(candidate.asset_id) == promoted.version


def test_promoting_a_board_photo_makes_one_derived_library_version():
    board = Library.from_version_documents([example("valid/asset-version-photo-external.json")])
    board_id = "asv_01M79V9FC00000000000000012"
    first = promote(board, board_id, by=BY, now=LATER, minter=minter())
    derived = first.version
    assert first.created and derived.id != board_id
    assert (derived.kind, derived.state, derived.number) == ("photo", "promoted", 1)
    assert derived.origin == "derived"
    assert derived.provenance["generator"]["source_asset_version_ids"] == (board_id,)
    assert derived.content == board.version(board_id).content
    assert first.library.asset(derived.asset_id).scope == Scope("prd_01M79V9FC00000000000000001")
    assert first.library.version(board_id) == board.version(board_id)
    again = promote(first.library, board_id, by=BY, now=LATER, minter=minter())
    assert (again.created, again.version.id) == (False, derived.id)
    assert promote(first.library, derived.id, by=BY, now=LATER).created is False


def test_a_board_voice_stays_on_its_board():
    library = winter_menu().library
    with pytest.raises(ContractError) as caught:
        promote(library, record_id(4, "speech:shot:8"), by=BY, now=LATER)
    assert caught.value.violations[0].rule == "asset.not_promotable"
    with pytest.raises(ContractError) as caught:
        promote(library, "asv_01M79V9FC0000000000000000Z", by=BY, now=LATER)
    assert caught.value.violations[0].rule == "ref.unknown"


def test_search_filters_kind_labels_production_and_board():
    library = winter_menu().library
    story = imported(4).story
    assert len(library.search(kind="sound")) == 5
    assert len(library.search(kind="voice")) == 4
    a_stills = library.search(labels=["the-winter-menu", "A"])
    assert {library.asset_of(v.id).attributes["character_slot"] for v in a_stills} == {"a"}
    assert len(a_stills) == 2
    assert len(library.search(production_id=story["production_id"])) == 24  # voices are global
    assert library.search(production_id="prd_01M79V9FC00000000000000009", kind="cast") == ()
    assert len(library.search(production_id="prd_01M79V9FC00000000000000009")) == 4  # the voices
    vote = next(b for b in story["boards"] if b["number"] == 8)
    named = {vote["voice"]["current_version_id"], *vote["photo"]["input_asset_version_ids"],
             *(c["asset_version_id"] for c in vote["cast"]),
             *(c["asset_version_id"] for c in vote["cues"] if c["type"] == "sound")}
    assert {v.id for v in library.search(board=vote)} == named


def test_capabilities_and_takes_without_knowing_the_storage():
    library = winter_menu().library
    still = record_id(4, "still:cutouts/a-proud.png")
    assert library.has_capability(still, "rgba_cutout")
    assert not library.has_capability(still, "keyed_layer")
    assert not library.has_capability("asv_01M79V9FC0000000000000000Z", "rgba_cutout")
    vote = next(b for b in imported(4).story["boards"] if b["number"] == 8)
    takes = library.takes(record_id(4, "speech:shot:8"))
    assert [t.line_id for t in takes] == [line["id"] for line in vote["lines"]]
    assert [t.duration_ms for t in takes] == [1003, 811, 875, 512, 1024, 1152]
    with pytest.raises(ContractError):
        library.takes(still)


def test_facts_match_story_404s_measured_takes():
    library = winter_menu().library
    facts = library.facts()
    expected = imported(4).facts
    assert set(facts.voice_versions) == set(expected.voice_versions)
    for version_id, voice in expected.voice_versions.items():
        assert dict(facts.voice_versions[version_id].takes_ms) == dict(voice.takes_ms)
    assert facts.capabilities[record_id(4, "set:cutouts/set.png")] == frozenset({"opaque_plate"})
    assert len(facts.capabilities) == 24


def test_the_contract_examples_load_as_a_library():
    documents = [example(f"valid/asset-version-{name}.json") for name in ("cast", "board-voice",
                                                                            "photo-external")]
    library = Library.from_version_documents(documents)
    for document in documents:
        assert library.document(document["id"]) == document
    assert library.pin("asv_01M79V9FC00000000000000001") == documents[0]["content"]["sha256"]
    assert library.pin("asv_01M79V9FC0000000000000000Y").startswith("sha256:")


def test_a_library_refuses_records_that_do_not_fit():
    library = winter_menu().library
    versions = list(library.versions.values())
    assets = list(library.assets.values())
    one = versions[0]
    with pytest.raises(ContractError) as caught:
        Library.build(assets, versions + [dataclasses.replace(one, id="asv_01M79V9FC0000000000000000Z")])
    assert {v.rule for v in caught.value.violations} == {"ref.duplicate"}  # number 1 twice
    with pytest.raises(ContractError) as caught:
        Library.build([a for a in assets if a.id != one.asset_id], versions)
    assert [v.rule for v in caught.value.violations] == ["ref.unknown"]
    assert Library.build(assets, versions) == library


def test_an_import_into_a_slice_is_refused():
    library = winter_menu().library
    grown = import_version(library, with_bytes(still_request(), OTHER), by=BY, now=LATER,
                           minter=minter()).library
    old_id = record_id(4, "still:cutouts/a-proud.png")
    sliced = Library.build(grown.assets.values(),
                           [v for v in grown.versions.values() if v.id != old_id])
    with pytest.raises(ContractError) as caught:
        import_version(sliced, with_bytes(still_request(), "f" * 64), by=BY, now=LATER)
    assert caught.value.violations[0].rule == "ref.unknown"


def test_definition_only_pins():
    library = winter_menu().library
    voice_id = record_id(4, "voice:af_heart")
    voice = library.version(voice_id)
    assert voice.content is None and library.pin(voice_id).startswith("sha256:")
    other = dataclasses.replace(voice, provenance={**voice.provenance,
                                                   "generator": {**voice.provenance["generator"],
                                                                 "model": "Kokoro-82M v1.1"}})
    assert pin(other, library.asset_of(voice_id)) != library.pin(voice_id)
    document = version_document(voice, library.asset_of(voice_id))
    assert document["content"] is None and document["attributes"] == {"voice_id": "af_heart", "stock": True}


def test_outcomes_report_creation():
    outcome = winter_menu().outcomes[0]
    assert isinstance(outcome, Outcome) and outcome.created
    assert isinstance(outcome.version.content, Content)
