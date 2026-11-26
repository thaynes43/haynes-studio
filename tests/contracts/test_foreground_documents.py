"""Serialization and source-coordinate bounds at library and run writer boundaries."""

from dataclasses import replace

import pytest

from haynes_studio.api import models
from haynes_studio.build.prebuild import snapshot_bytes
from haynes_studio.build.run import RunRecords, new_run
from haynes_studio.canonical import load_story, to_document
from haynes_studio.canonical.model import Board
from haynes_studio.errors import ContractError
from haynes_studio.jsonio import parse_strict
from haynes_studio.library import Library, VersionRequest, import_all, import_version
from haynes_studio.library.model import Asset, AssetVersion, version_document
from haynes_studio.store import LocalStore, blob_locator, canonical_json
from tests.build_story.fixtures import NOW, OPERATOR, example, ident
from tests.library.fixtures import BY
from tests.motion.fixtures import still_version


@pytest.mark.parametrize("optional", [[], None])
def test_board_and_snapshot_normalize_absent_pose_forms(optional):
    snapshot = example("run-snapshot.json")
    before, sha = snapshot_bytes(snapshot)
    board = snapshot["story"]["boards"][0]
    original = Board.canonical_document(board)
    board["layout"]["check_poses"] = optional
    assert load_story(snapshot["story"]).boards[0].layout.check_poses is None
    assert to_document(Board.from_document(board)) == to_document(Board.from_document(original))
    transported = models.Board(root=board)
    assert parse_strict(transported.model_dump_json()) == original
    assert snapshot_bytes(snapshot) == (before, sha)


@pytest.mark.parametrize("optional", [[], None, {}, {"foreground": [], "focal_props": None}])
def test_asset_version_normalizes_absent_declarations(optional):
    doc = example("asset-version-cast.json")
    with_empty = {**doc, "occlusion": optional}
    library = Library.from_version_documents([with_empty], context="write")
    assert library.documents() == [doc]
    value = models.AssetVersion(root=with_empty)
    assert parse_strict(value.model_dump_json()) == doc
    typed = AssetVersion.from_document(with_empty)
    assert version_document(typed, Asset.from_version_document(doc)) == doc


def test_direct_run_writer_normalizes_snapshot_at_its_persistence_boundary(tmp_path):
    snapshot = example("run-snapshot.json")
    original, sha = snapshot_bytes(snapshot)
    snapshot["story"]["boards"][0]["layout"]["check_poses"] = []
    raw = canonical_json(snapshot)
    assert raw != original
    story = snapshot["story"]
    production = story["production_id"]
    locator = blob_locator(production, sha, "application/json")
    run = new_run(run_id=ident("run", 968), story_id=story["id"], number=1,
                  snapshot={"sha256": sha, "story_revision": story["revision"],
                            "board_count": len(story["boards"]), "locator": locator},
                  queued_by=OPERATOR, queued_at=NOW, phase="all")
    store = LocalStore(tmp_path)
    RunRecords(store, production).create(run, raw)
    with store.open(locator) as handle:
        assert handle.read() == original


def pair(axis, value):
    prop = still_version(72, "b" * 64)
    prop.update(kind="prop", attributes={}, capabilities=["rgba_cutout"])
    prop["content"].pop("width", None)
    prop["content"].pop("height", None)
    prop["content"][axis] = value
    plate = still_version(73, "c" * 64, kind="set")
    xy = [value, 10] if axis == "width" else [10, value]
    plate["occlusion"] = {"focal_props": [{
        "key": "menu", "label": "menu", "depth": "separate", "layer_order": 11,
        "source_asset_version_id": prop["id"], "hint": {"kind": "point", "xy": xy},
    }]}
    return prop, plate


def request(document):
    asset, version = Asset.from_version_document(document), AssetVersion.from_document(document)
    return VersionRequest(kind=asset.kind, name=asset.name, scope=asset.scope,
                          capabilities=version.capabilities, content=version.content, licence=version.licence,
                          provenance=version.provenance, state=version.state, labels=asset.labels,
                          attributes=asset.attributes, legacy=version.legacy, occlusion=version.occlusion,
                          version_id=version.id, asset_id=asset.id)


@pytest.mark.parametrize("axis", ["width", "height"])
@pytest.mark.parametrize("set_first", [False, True])
@pytest.mark.parametrize("empty", [[], None, {"foreground": [], "focal_props": None}])
def test_version_documents_bound_each_known_source_axis_in_either_order(axis, set_first, empty):
    prop, plate = pair(axis, 32)
    prop["occlusion"] = empty
    documents = [plate, prop] if set_first else [prop, plate]
    with pytest.raises(ContractError) as error:
        Library.from_version_documents(documents, context="write")
    assert error.value.violations[0].path == "/occlusion/focal_props/0/hint/xy"


@pytest.mark.parametrize("axis", ["width", "height"])
@pytest.mark.parametrize("set_first", [False, True])
@pytest.mark.parametrize("idempotent", [False, True])
def test_import_bounds_follow_the_resolved_id_and_each_known_axis(axis, set_first, idempotent):
    prop_doc, plate_doc = pair(axis, 32)
    prop, plate = request(prop_doc), request(plate_doc)
    library = Library()
    if idempotent:
        legacy = replace(prop, content=replace(prop.content, width=None, height=None))
        library = import_version(library, legacy, by=BY, now=NOW).library
        prop = replace(prop, version_id=None)
    ordered = [plate, prop] if set_first else [prop, plate]
    with pytest.raises(ContractError) as error:
        import_all(library, ordered, by=BY, now=NOW)
    assert error.value.violations[0].path == "/occlusion/focal_props/0/hint/xy"


def test_declaration_rejects_a_reversed_box_before_importing():
    prop, plate = pair("width", 32)
    plate["occlusion"]["focal_props"][0]["hint"] = {"kind": "box", "xyxy": [20, 6, 10, 18]}
    with pytest.raises(ContractError) as error:
        import_all(Library(), [request(prop), request(plate)], by=BY, now=NOW)
    assert error.value.violations[0].path == "/occlusion/focal_props/0/hint/xyxy"


def test_legacy_story_nine_boards_and_three_versions_match_pinned_main():
    from hashlib import sha256

    def digest(data):
        return sha256(canonical_json(data)).hexdigest()

    story = load_story(example("story-winter-menu-r4.json"))
    assert digest(to_document(story)) == "0532748ce14ee933f57f09de721581113cf6d1af5d39f477566b84cc28a2d220"
    assert [digest(to_document(board)) for board in story.boards] == [
        "d1442f3c765aa1acad1a8b9771133cd2f1795625c04354217814131f97e92fd5",
        "b204ce4ec4492accce0d01f09809a2c039b75330597b46efb00698e9b7fb25a4",
        "45d6759bc839aa1f415a8b38525397f88cdbb240411dec017a7b43805731cc11",
        "6edb4260f533e8508b9fc59af81c45f12fbb1df51569b8c3d2741703dfb6278a",
        "5fadfd6bac754e7d85b586448e243701dfb0f2d1a0f06c678c45774be5b6a2bc",
        "0b348b612fdaa879f3ce35c8ceb5499040bdfc3ac0756cdee044749d80a6d26b",
        "0c02faf6977d710f207dd7cc11cb4ee1c3869a0167aaf0ca19f2f1587cb14ad4",
        "47904d25673bfd22ed8b815edfc77d46a553f5634e62eac841ad2066ff95139c",
        "3bcd0b700f0d535e662b7fadf2f554330d8a78b08e19b4531d7899bf2aec2345",
    ]
    expected = {
        "cast": ("0bed0e0ba32539363867664eaa51b34706493823e126ba90a8ec12c20d02168d",
                 "4ea3005f4effebda7f4ce9b083da55e8529db4269c96104364e5dc74b25969de"),
        "photo-external": ("a79de5197daa6d9b561e18da5757ea6d88f8dd64b3f59ae41e8028d97eb3de1e",
                           "2fddb36d8a16f71d834ccf755ab06a24632704bcdec96acc818f004b4ba7fb55"),
        "board-voice": ("97d54bb789e3fcbfef7cc377b9826b12e30a34fdb244b1dc023c40d990e10c1b",
                        "sha256:0835d6ec3ddcf6cf0a18b360577ece35cc757fd821100de0a1ac7e01f35eda78"),
    }
    for kind, (version_hash, pin) in expected.items():
        library = Library.from_version_documents([example(f"asset-version-{kind}.json")])
        [document] = library.documents()
        assert (digest(document), library.pin(document["id"])) == (version_hash, pin)


def test_changed_declaration_makes_a_new_immutable_set_version_with_the_same_plate_bytes():
    prop, plate = pair("width", 32)
    hint = plate["occlusion"]["focal_props"][0]["hint"]
    hint["xy"] = [10, 10]
    base = import_version(Library(), request(plate), by=BY, now=NOW)
    changed = request(plate)
    hint["xy"] = [11, 10]
    revised = replace(request(plate), version_id=None)
    assert changed.occlusion != revised.occlusion
    new = import_version(base.library, revised, by=BY, now=NOW)
    assert new.created and new.version.number == 2
    assert base.version.content == new.version.content
    assert new.library.pin(base.version.id) != new.library.pin(new.version.id)
    repeated = import_version(new.library, revised, by=BY, now=NOW)
    assert not repeated.created and repeated.version == new.version
