"""Check that additive renderer declarations preserve every legacy field rule."""

import json
from hashlib import sha256
from importlib.resources import files

import pytest

from haynes_studio.store import canonical_json


@pytest.mark.parametrize(("name", "legacy_sha256"), [
    ("board", "63a6024945e39e492d1a6f2a73de5206181733f663fa48206aef8bafdfd00b8e"),
    ("asset-version", "fcc54d8d1eea5c74f8523780a4a4797de61994f565f867751bc627b9d0067b39"),
    ("run-snapshot", "32de0d4e5332a4f35f85a5d03bd53611ceb637836e4adbf4380f746776274188"),
])
def test_legacy_schema_rules_match_pinned_main(name, legacy_sha256):
    # Canonical JSON hashes from pinned main fd8e4a36 also work in a shallow checkout.
    source = files("haynes_studio.schemas").joinpath(f"studio.{name}.v1.schema.json")
    schema = json.loads(source.read_bytes())
    props = schema["properties"]
    if name == "board":
        props.pop("visibility")
    elif name == "asset-version":
        props.pop("occlusion")
        schema["$defs"].pop("occlusion")
    elif name == "run-snapshot":
        props.pop("visibility_admission")
    assert sha256(canonical_json(schema)).hexdigest() == legacy_sha256
