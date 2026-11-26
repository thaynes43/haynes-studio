"""Canonical set declarations validate before library or transport serialization."""

from copy import deepcopy
from dataclasses import replace

import pytest

from haynes_studio.errors import ContractError
from haynes_studio.library import Library, VersionRequest, import_version
from haynes_studio.library.model import Asset, AssetVersion, version_document
from haynes_studio.store import canonical_json
from haynes_studio.canonical import load_story, to_document
from tests.build_story.fixtures import NOW, example, ident
from tests.library.fixtures import BY
from tests.motion.fixtures import still_version


def declared_set():
    plate = still_version(73, "c" * 64, kind="set")
    plate["content"].update(width=64, height=32)
    plate["occlusion"] = {"foreground": [{
        "key": "counter", "layer_order": 11,
        "mask": {"version_id": ident("asv", 72), "sha256": "b" * 64,
                 "still_sha256": "c" * 64, "width": 64, "height": 32},
    }]}
    return plate


def request(document):
    asset, version = Asset.from_version_document(document), AssetVersion.from_document(document)
    return VersionRequest(kind=asset.kind, name=asset.name, scope=asset.scope,
                          capabilities=version.capabilities, content=version.content, licence=version.licence,
                          provenance=version.provenance, state=version.state, labels=asset.labels,
                          attributes=asset.attributes, legacy=version.legacy, occlusion=version.occlusion,
                          version_id=version.id, asset_id=asset.id)


@pytest.mark.parametrize("optional", [[], None, {}, {"foreground": []}, {"foreground": None}])
def test_asset_version_readers_refuse_noncanonical_empty_declarations(optional):
    doc = example("asset-version-cast.json")
    with_empty = {**doc, "occlusion": optional}
    for read in (AssetVersion.from_document, lambda doc: Library.from_version_documents([doc])):
        with pytest.raises(ContractError) as refused:
            read(with_empty)
        assert [(issue.rule, issue.path) for issue in refused.value.violations] == [
            ("occlusion.noncanonical", "/occlusion"),
        ]
    typed = replace(AssetVersion.from_document(doc), occlusion=optional)
    assert version_document(typed, Asset.from_version_document(doc)) == doc


@pytest.mark.parametrize("field", ["version_id", "sha256", "still_sha256", "width", "height"])
def test_mask_pin_requires_its_complete_identity_at_model_construction(field):
    doc = declared_set()
    del doc["occlusion"]["foreground"][0]["mask"][field]
    with pytest.raises(ContractError):
        AssetVersion.from_document(doc)
    with pytest.raises(ContractError):
        Library.from_version_documents([doc], context="write")


@pytest.mark.parametrize(("field", "value"), [
    ("label", "counter"), ("hint", {"kind": "point", "xy": [0, 0]}),
])
def test_roles_reject_fields_outside_the_mask_declaration(field, value):
    doc = declared_set()
    doc["occlusion"]["foreground"][0][field] = value
    with pytest.raises(ContractError):
        AssetVersion.from_document(doc)


def test_declarations_reject_focal_props():
    doc = declared_set()
    doc["occlusion"]["focal_props"] = []
    with pytest.raises(ContractError):
        AssetVersion.from_document(doc)


@pytest.mark.parametrize(("field", "value", "code"), [
    ("still_sha256", "d" * 64, "occlusion.mask_stale"),
    ("width", 63, "occlusion.mask_size"),
    ("height", 31, "occlusion.mask_size"),
])
def test_mask_declarations_pin_the_original_set_still(field, value, code):
    doc = declared_set()
    doc["occlusion"]["foreground"][0]["mask"][field] = value
    with pytest.raises(ContractError) as error:
        AssetVersion.from_document(doc)
    assert error.value.violations[0].rule == code


@pytest.mark.parametrize("field", ["key", "layer_order"])
def test_roles_have_unique_keys_and_orders(field):
    doc = declared_set()
    [first] = doc["occlusion"]["foreground"]
    second = deepcopy(first)
    second["key"], second["layer_order"] = "railing", 12
    second[field] = first[field]
    doc["occlusion"]["foreground"].append(second)
    with pytest.raises(ContractError) as error:
        AssetVersion.from_document(doc)
    assert error.value.violations[0].rule == "ref.duplicate"


def test_transport_normalizes_an_integral_layer_order_and_reader_requires_an_integer():
    from haynes_studio.api.models import AssetVersion as TransportAssetVersion

    doc = declared_set()
    doc["occlusion"]["foreground"][0]["layer_order"] = 11.0
    with pytest.raises(ContractError) as refused:
        Library.from_version_documents([doc])
    assert refused.value.violations[0].rule == "occlusion.noncanonical"
    model = TransportAssetVersion.model_validate(doc)
    assert type(model.root["occlusion"]["foreground"][0]["layer_order"]) is int


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
    plate = declared_set()
    base = import_version(Library(), request(plate), by=BY, now=NOW)
    plate["occlusion"]["foreground"][0]["layer_order"] = 12
    revised = replace(request(plate), version_id=None)
    new = import_version(base.library, revised, by=BY, now=NOW)
    assert new.created and new.version.number == 2
    assert base.version.content == new.version.content
    assert new.library.pin(base.version.id) != new.library.pin(new.version.id)
    repeated = import_version(new.library, revised, by=BY, now=NOW)
    assert not repeated.created and repeated.version == new.version
