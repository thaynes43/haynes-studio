"""Segments and the film picture through the store (story 380), on synthetic media.

The four-board fixture (223 frames at 360x640, 9.3 s) is rendered by the synthetic
renderer, encoded at two threads, published as completed stages and spliced. Clips,
voices and the mix are never made (their hashes are stand-ins); only picture is.
Decoded frames are compared, never encoded bytes.
"""

from __future__ import annotations

import ast
import copy
import itertools
from pathlib import Path

import numpy as np
import pytest

from haynes_studio.cache import ArtifactCache, diff, stage_name
from haynes_studio.cache.build import PictureBuilder
from haynes_studio.cache.errors import ENTRY_INVALID, FRAME_COUNT, FRAME_INVALID, CacheError
from haynes_studio.cache.keys import SEGMENT
from haynes_studio.render.base import SegmentRenderer
from haynes_studio.render.encode import decode_frames
from haynes_studio.render.synthetic import SyntheticRenderer, fingerprint, read_code
from haynes_studio.stages import StageOutput, commit_stage, completed_stage
from haynes_studio.store import LocalStore, blob_locator
from tests.cache import fixtures as fx
from tests.cache.fixtures import B1, B2, B3, B4, PRODUCTION, ident

RUN1, RUN2, RUN3 = ident("run", 1), ident("run", 2), ident("run", 3)
SRC = Path(__file__).resolve().parents[2] / "src" / "haynes_studio"


def build(store, document, run_id, earlier=(), renderer=None):
    """One build of the document's picture: the plan with a builder as its content."""
    cache = ArtifactCache(store, production_id=PRODUCTION, run_id=run_id, earlier_runs=earlier)
    builder = PictureBuilder(cache, renderer or SyntheticRenderer(), upstream=fx.stand_in)
    plan = fx.plan(document, content=builder)
    return plan, builder, cache


def film_frames(store, plan):
    locator = blob_locator(PRODUCTION, plan.film_picture.content, "video/mp4")
    with store.open(locator) as handle:
        yield from decode_frames(handle.read())


def assert_same_frames(store_a, plan_a, store_b, plan_b) -> int:
    """The two films decode to identical frames; returns the frame count."""
    count = 0
    for a, b in itertools.zip_longest(film_frames(store_a, plan_a), film_frames(store_b, plan_b)):
        assert a is not None and b is not None, f"the films differ in length at frame {count}"
        assert np.array_equal(a, b), f"frame {count} differs"
        count += 1
    return count


def assert_board_clock_order(store, plan) -> None:
    """Every decoded film frame shows its own board's frame n (board clock), boards in
    order: TIME-7 placement and TIME-11 conservation, read from the picture."""
    expected = [(n, fingerprint(board.segment.key.value))
                for board in plan.boards for n in range(board.frames)]
    seen = [read_code(frame) for frame in film_frames(store, plan)]
    assert seen == expected


def new_store(path: Path) -> LocalStore:
    path.mkdir()
    return LocalStore(path)


@pytest.fixture
def store(tmp_path):
    return new_store(tmp_path / "store")


def test_first_build_renders_every_board_and_splices_once(store):
    plan, builder, cache = build(store, fx.story_document(), RUN1)
    assert len(builder.rendered) == 4 and len(builder.spliced) == 1
    assert sorted(builder.rendered) == sorted(b.segment.key.value for b in plan.boards)
    assert plan.frames == 223
    assert_board_clock_order(store, plan)


def test_second_build_of_an_unchanged_story_renders_nothing(store):
    first, _, _ = build(store, fx.story_document(), RUN1)
    second, builder, cache = build(store, fx.story_document(), RUN2, earlier=(RUN1,))
    assert builder.rendered == [] and builder.spliced == []
    assert cache.stats.made == [] and len(cache.stats.hits) == 5  # four segments, one film
    assert second.keys() == first.keys()
    assert second.film_picture.content == first.film_picture.content
    for board in second.boards:  # every hit is a completed record of the first run
        record = completed_stage(store, production_id=PRODUCTION, run_id=RUN1,
                                 stage=stage_name(board.segment.key))
        assert record is not None and record.blobs[SEGMENT].sha256 == board.segment.content
        assert completed_stage(store, production_id=PRODUCTION, run_id=RUN2,
                               stage=stage_name(board.segment.key)) is None


def test_one_board_edit_renders_exactly_that_board_and_matches_a_full_render(store, tmp_path):
    document = fx.story_document()
    first, _, _ = build(store, document, RUN1)
    edited = copy.deepcopy(document)
    fx.board_of(edited, B2)["layout"]["preset"] = "single"  # board 2 only
    second, builder, _ = build(store, edited, RUN2, earlier=(RUN1,))
    assert builder.rendered == [next(b for b in second.boards if b.board_id == B2).segment.key.value]
    assert len(builder.spliced) == 1
    assert diff(first, second).rebuilt - {"film/picture", "film/master", "film/proxy",
                                          "check/master.decode", "check/master.transcript"} == {
        f"{B2}/segment"}
    # A full render of the edited story, in a store with no cache, decodes the same.
    fresh = new_store(tmp_path / "fresh")
    full, full_builder, _ = build(fresh, edited, RUN3)
    assert len(full_builder.rendered) == 4
    assert assert_same_frames(store, second, fresh, full) == 223
    assert_board_clock_order(store, second)


def test_reorder_reuses_every_segment_and_matches_a_full_render(store, tmp_path):
    document = fx.story_document()
    build(store, document, RUN1)
    reordered = copy.deepcopy(document)
    reordered["board_order"] = [B3, B1, B4, B2]
    second, builder, _ = build(store, reordered, RUN2, earlier=(RUN1,))
    assert builder.rendered == [] and len(builder.spliced) == 1  # board clock: no picture moved
    fresh = new_store(tmp_path / "fresh")
    full, _, _ = build(fresh, reordered, RUN3)
    assert assert_same_frames(store, second, fresh, full) == 223
    assert_board_clock_order(store, second)


def test_a_duration_edit_on_one_board_leaves_later_boards_pixels_alone(store):
    """P-06: the legacy film clock would move every later board's loops and fire."""
    document = fx.story_document()
    first, _, _ = build(store, document, RUN1)
    edited = copy.deepcopy(document)
    fx.board_of(edited, B1)["timing"]["tail_ms"] = 1700  # B1 grows; B2 to B4 start later
    second, builder, _ = build(store, edited, RUN2, earlier=(RUN1,))
    assert builder.rendered == [next(b for b in second.boards if b.board_id == B1).segment.key.value]
    starts = {b.board_id: b.film_start_frame for b in second.boards}
    assert starts[B2] > {b.board_id: b.film_start_frame for b in first.boards}[B2]
    assert_board_clock_order(store, second)


def test_a_cached_segment_is_verified_on_a_hit(store):
    plan = fx.plan(fx.story_document())
    key = plan.boards[0].segment.key
    # Another writer recorded a stage of that name whose inputs are not the key's.
    commit_stage(store, production_id=PRODUCTION, run_id=RUN1, stage=stage_name(key), outputs={
        SEGMENT: StageOutput(b"not a segment", "video/mp4"),
        "inputs": StageOutput(b"{}", "application/json")})
    cache = ArtifactCache(store, production_id=PRODUCTION, run_id=RUN2, earlier_runs=(RUN1,))
    with pytest.raises(CacheError) as caught:
        cache.lookup(key, "video/mp4")
    assert caught.value.code == ENTRY_INVALID


class _Short(SegmentRenderer):
    compositor = SyntheticRenderer.compositor

    def render(self, request):
        return list(SyntheticRenderer().render(request))[:-1]


class _Wrong(SegmentRenderer):
    compositor = SyntheticRenderer.compositor

    def render(self, request):
        return [np.zeros((request.height, request.width), dtype=np.uint8)] * request.frames


@pytest.mark.parametrize(("renderer", "code"), [(_Short(), FRAME_COUNT), (_Wrong(), FRAME_INVALID)])
def test_a_renderer_that_breaks_the_board_length_commits_nothing(store, renderer, code):
    plan = fx.plan(fx.story_document())
    key = plan.boards[2].segment.key  # the silent board, 46 frames
    builder = PictureBuilder(ArtifactCache(store, production_id=PRODUCTION, run_id=RUN1), renderer)
    with pytest.raises(CacheError) as caught:
        builder.segment(key)
    assert caught.value.code == code
    assert completed_stage(store, production_id=PRODUCTION, run_id=RUN1, stage=stage_name(key)) is None


def test_a_renderer_with_another_compositor_is_refused(store):
    class Other(SyntheticRenderer):
        compositor = "studio.render.other/1"

    key = fx.plan(fx.story_document()).boards[2].segment.key
    builder = PictureBuilder(ArtifactCache(store, production_id=PRODUCTION, run_id=RUN1), Other())
    with pytest.raises(CacheError) as caught:
        builder.segment(key)
    assert caught.value.code == ENTRY_INVALID


def test_the_cache_keeps_everything_it_made(store):
    first, _, _ = build(store, fx.story_document(), RUN1)
    edited = fx.story_document()
    fx.board_of(edited, B4)["seeds"]["s2v:b"] = 7
    build(store, edited, RUN2, earlier=(RUN1,))
    report = store.doctor()
    assert not report.dangling and not report.damaged and not report.mismatched
    for board in first.boards:  # the first run's segments are still complete
        assert completed_stage(store, production_id=PRODUCTION, run_id=RUN1,
                               stage=stage_name(board.segment.key)) is not None


def test_cache_and_render_never_delete_rename_or_overwrite():
    """D17: no call in the cache or render packages removes, renames or truncates a
    file; every write goes through the store's publication."""
    banned = {"unlink", "remove", "rename", "replace", "rmdir", "rmtree", "truncate"}
    for path in sorted([*SRC.joinpath("cache").glob("*.py"), *SRC.joinpath("render").glob("*.py")]):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                assert node.attr not in banned, f"{path.name}: .{node.attr}"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id != "open", f"{path.name}: open()"
