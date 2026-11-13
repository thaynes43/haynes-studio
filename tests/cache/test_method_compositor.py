"""Each board's segment names the compositor of its own method (story 406): the
toolchain's ``compositor`` may map each method layer to its renderer's digest, so a
story with layered and whole-frame boards plans each segment for the renderer that
draws it. One string still serves every board (story 380's form)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from haynes_studio.cache import CacheError
from haynes_studio.cache.plan import Toolchain, diff
from tests.cache import fixtures as fx

LAYERED, WHOLE = "studio.layered/test", "studio.wholeframe/test"
SEGMENTS = {fx.B1: "layered", fx.B2: "layered", fx.B3: "whole_frame", fx.B4: "layered"}


def tools(**compositor: str) -> Toolchain:
    return replace(Toolchain(), compositor=compositor)


def segment(plan, board_id: str) -> str:
    return plan.artifacts[f"{board_id}/segment"].key.document["compositor"]


def test_each_segment_names_its_methods_compositor():
    plan = fx.plan(fx.story_document(), toolchain=tools(layered=LAYERED, whole_frame=WHOLE))
    assert {b: segment(plan, b) for b in SEGMENTS} == {
        b: LAYERED if layer == "layered" else WHOLE for b, layer in SEGMENTS.items()}


def test_one_string_still_names_every_boards_compositor():
    plan = fx.plan(fx.story_document(), toolchain=replace(Toolchain(), compositor="one/1"))
    assert {segment(plan, b) for b in SEGMENTS} == {"one/1"}
    same = fx.plan(fx.story_document())  # the default is story 380's string
    assert {segment(same, b) for b in SEGMENTS} == {Toolchain().compositor}


def test_a_methods_compositor_change_rebuilds_only_that_methods_segments():
    document = fx.story_document()
    before = fx.plan(document, toolchain=tools(layered=LAYERED, whole_frame=WHOLE))
    after = fx.plan(document, toolchain=tools(layered=LAYERED, whole_frame=WHOLE + "-2"))
    picture = {"film/picture", "film/master", "film/proxy"} | {
        n for n in after.keys() if n.startswith("check/")}
    assert diff(before, after).rebuilt == {f"{fx.B3}/segment"} | picture


def test_a_method_without_a_compositor_cannot_be_keyed():
    with pytest.raises(CacheError) as error:
        fx.plan(fx.story_document(), toolchain=tools(layered=LAYERED))
    assert error.value.code == "cache.key_input_invalid" and fx.B3 in str(error.value)
