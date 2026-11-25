"""The adapter leaves the stored board, asset-version and run-snapshot contracts intact."""

from hashlib import sha256
from importlib.resources import files

import pytest


@pytest.mark.parametrize(("name", "main_sha256"), [
    ("studio.board.v1.schema.json", "439ac86fc89195bd550e6d94a92eaff7b830545b64ddef3880f13a397cfc3f3b"),
    ("studio.asset-version.v1.schema.json", "541cb13225de1cd4cc3a2db0cf78042bcbefc28df2a6dbae441f0cb47349fc16"),
    ("studio.run-snapshot.v1.schema.json", "5067adf160d5bb6852ec0f317cf2416a491c83643284bffbd9f0b90c51d12735"),
])
def test_stored_schema_bytes_match_main(name, main_sha256):
    # Raw bytes from origin/main at 470a90af73a2201e6542b5d867853dce6facad04.
    # Pin the hashes so this also runs in a shallow CI checkout or from a wheel.
    schema = files("haynes_studio.schemas").joinpath(name)
    assert sha256(schema.read_bytes()).hexdigest() == main_sha256
