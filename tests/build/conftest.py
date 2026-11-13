"""One world and one first build shared by the build tests (CPU rule: the fixture's
layered boards render at the delivery size once per session)."""

from __future__ import annotations

import pytest

from tests.build import fixtures as f


@pytest.fixture(scope="session")
def world(tmp_path_factory):
    return f.make_world(tmp_path_factory.mktemp("build") / "store")


@pytest.fixture(scope="session")
def voiced(world):
    return f.voiced(world)


@pytest.fixture(scope="session")
def first(world, voiced):
    document, library = voiced
    return f.build(world, document, library)
