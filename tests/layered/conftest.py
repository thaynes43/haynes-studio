"""One synthetic world and one first build for the layered tests that build, shared
by the session so the clips are keyed and the boards rendered once (CPU rule)."""

from __future__ import annotations

import pytest

from tests.layered import helpers as h


@pytest.fixture(scope="session")
def world(tmp_path_factory):
    return h.make_world(tmp_path_factory.mktemp("layered") / "store")


@pytest.fixture(scope="session")
def first(world):
    return h.build(world, h.story_document(), h.RUN[1])
