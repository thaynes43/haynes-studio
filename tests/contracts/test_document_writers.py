"""Generic serializers see canonical values; readers reject malformed declarations."""

import json

import pytest
from pydantic import ValidationError

from haynes_studio.api import models
from haynes_studio.errors import ContractError
from haynes_studio.library import Library
from haynes_studio.library.model import AssetVersion
from tests.build_story.fixtures import example
from tests.contracts.test_foreground_documents import declared_set


@pytest.mark.parametrize("optional", [[], None, {}, {"foreground": []}, {"foreground": None}])
@pytest.mark.parametrize("encode", [
    lambda value: "".join(json.JSONEncoder().iterencode(value.root)),
    lambda value: value.model_dump_json(),
], ids=["root-encoder", "model-dump-json"])
def test_transport_serializes_canonical_values_and_readers_refuse_tampered_empty_forms(optional, encode):
    original = example("asset-version-cast.json")
    value = models.AssetVersion(root={**original, "occlusion": optional})
    assert json.loads(encode(value)) == original
    assert Library.from_version_documents([json.loads(encode(value))]).documents() == [original]
    value.root["occlusion"] = optional
    with pytest.raises(ContractError) as refused:
        Library.from_version_documents([json.loads(encode(value))])
    assert [issue.rule for issue in refused.value.violations] == ["occlusion.noncanonical"]


def test_canonical_asset_version_has_no_raw_root_and_freezes_the_declaration():
    value = AssetVersion.from_document(declared_set())
    with pytest.raises(AttributeError):
        "".join(json.JSONEncoder().iterencode(value.root))
    with pytest.raises(TypeError):
        value.occlusion["foreground"][0]["mask"]["width"] = 1


def test_generic_json_encoder_round_trips_the_complete_mask_declaration():
    document = declared_set()
    value = models.AssetVersion(root=document)
    encoded = "".join(json.JSONEncoder().iterencode(value.root))
    assert Library.from_version_documents([json.loads(encoded)]).documents() == [document]


def test_transport_rejects_a_malformed_declaration_at_construction():
    document = declared_set()
    del document["occlusion"]["foreground"][0]["mask"]["width"]
    with pytest.raises(ValidationError):
        models.AssetVersion(root=document)


def test_reader_rejects_a_malformed_declaration_encoded_from_a_mutated_transport_root():
    value = models.AssetVersion(root=declared_set())
    del value.root["occlusion"]["foreground"][0]["mask"]["width"]
    encoded = "".join(json.JSONEncoder().iterencode(value.root))
    with pytest.raises(ContractError):
        Library.from_version_documents([json.loads(encoded)], context="write")
