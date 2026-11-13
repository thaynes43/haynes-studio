"""Whole-frame boards through the plan, the clip stage and the segment cache (story 427).

The story has two whole-frame I2V boards: B2 spoken (42 frames) and B3 silent (46
frames), each a chain of two 25-frame fake clips. Clips are made by the fake source;
voices, the mix and the master are stand-ins, as in the cache tests.
"""

from __future__ import annotations

import copy

import pytest

from haynes_studio.cache import diff
from haynes_studio.cache.errors import KEY_INPUT_INVALID, CacheError
from haynes_studio.canonical.derive import board_clock
from haynes_studio.canonical.facts import Facts, VoiceVersionFacts
from haynes_studio.render.encode import decode_frames
from haynes_studio.render.synthetic import read_code
from haynes_studio.store import blob_locator
from haynes_studio.wholeframe import check_board
from haynes_studio.wholeframe.errors import CHAIN_LIMIT, METHOD_UNAVAILABLE, PHOTO_ABSENT, UNSUPPORTED
from haynes_studio.wholeframe.fake import FakeClipSource, marker
from tests.cache import fixtures as fx
from tests.cache.fixtures import B2, B3, PRODUCTION
from tests.wholeframe import helpers as h
from tests.wholeframe.test_renderer import expected_codes


@pytest.fixture
def store(tmp_path):
    store = h.new_store(tmp_path / "store")
    h.publish_photos(store)
    return store


def board_codes(store, plan, board_id):
    board = next(b for b in plan.boards if b.board_id == board_id)
    with store.open(blob_locator(PRODUCTION, board.segment.content, "video/mp4")) as handle:
        return [read_code(frame) for frame in decode_frames(handle.read())]


def test_first_build_makes_each_chain_once_and_each_board_has_exactly_its_frames(store):
    build = h.Build(store, h.story_document(), h.RUN1)
    plan = build.plan
    assert [b.frames for b in plan.boards] == [42, 46] and plan.frames == 88
    assert [r.clip_lengths for r in build.source.calls] == [(25, 25), (25, 25)]
    assert len(build.builder.rendered) == 2 and len(build.builder.spliced) == 1
    assert board_codes(store, plan, B2) == expected_codes(42, 25, 21)
    assert board_codes(store, plan, B3) == expected_codes(46, 25, 31)
    with store.open(blob_locator(PRODUCTION, plan.film_picture.content, "video/mp4")) as handle:
        assert sum(1 for _ in decode_frames(handle.read())) == 88  # TIME-11
    report = build.renderer.reports[plan.boards[1].segment.key.value]
    assert report.assembly.trimmed == 49 - 46


def test_the_spoken_board_covers_its_voice(store):
    """Frames are TIME-3's ceil(content_ms * 24 / 1000): the voice ends inside them."""
    document = h.story_document()
    story = fx.load(document)
    board = next(b for b in story.boards if b.id == B2)
    voice = fx.voices(story)[B2]
    clock = board_clock(board, Facts.build(voices=[VoiceVersionFacts(
        id=board.voice.current_version_id,
        takes_ms={line: take.duration_ms for line, take in voice.takes.items()})]))
    build = h.Build(store, document, h.RUN1)
    frames = len(board_codes(store, build.plan, B2))
    assert frames == clock.frames == (clock.content_ms * 24 + 999) // 1000
    last_end = max(span.end_ms for span in clock.spans.values())
    assert last_end <= clock.content_ms - board.timing.tail_ms and clock.content_ms * 24 <= frames * 1000


def test_second_build_of_an_unchanged_story_asks_for_nothing_and_renders_nothing(store):
    first = h.Build(store, h.story_document(), h.RUN1)
    source = FakeClipSource()
    second = h.Build(store, h.story_document(), h.RUN2, earlier=(h.RUN1,), source=source)
    assert source.calls == [] and second.clips.made == []
    assert second.builder.rendered == [] and second.builder.spliced == []
    assert second.cache.stats.made == [] and len(second.cache.stats.hits) == 5  # 2 clips, 2 segments, film
    assert second.plan.keys() == first.plan.keys()


def test_a_hold_edit_inside_the_chain_keeps_the_clips_and_renders_one_segment(store):
    first = h.Build(store, h.story_document(hold=1900), h.RUN1)
    source = FakeClipSource()
    second = h.Build(store, h.story_document(hold=2000), h.RUN2, earlier=(h.RUN1,), source=source)
    d = diff(first.plan, second.plan)
    assert f"{B3}/whole_frame_clip" in d.kept and f"{B3}/segment" in d.changed
    assert source.calls == [] and len(second.builder.rendered) == 1
    assert board_codes(store, second.plan, B3) == expected_codes(48, 25, 31)


def test_a_hold_edit_past_the_chain_asks_for_a_longer_chain(store):
    first = h.Build(store, h.story_document(hold=1900), h.RUN1)
    source = FakeClipSource()
    second = h.Build(store, h.story_document(hold=2500), h.RUN2, earlier=(h.RUN1,), source=source)
    assert f"{B3}/whole_frame_clip" in diff(first.plan, second.plan).changed
    assert [r.clip_lengths for r in source.calls] == [(25, 25, 25)]
    codes = board_codes(store, second.plan, B3)
    assert len(codes) == 60 and codes == expected_codes(60, 25, 31)
    assert codes[48:50] == [(24, marker(1, 32)), (1, marker(2, 33))]


def test_the_plan_refuses_a_board_past_the_chain_limit():
    with pytest.raises(CacheError) as error:
        fx.plan(h.story_document(hold=3100), toolchain=h.toolchain(), blobs=h.BLOBS)  # 75 > 73
    assert error.value.code == KEY_INPUT_INVALID and "chain limit" in str(error.value)


def test_check_board_lists_every_refusal():
    document = h.story_document()
    board = fx.board_of(document, B3)
    story = fx.load(document)
    ok = next(b for b in story.boards if b.id == B3)
    assert check_board(ok, frames=46, clip_frames=25) == []
    assert [v.rule for v in check_board(ok, frames=74, clip_frames=25)] == [CHAIN_LIMIT]
    edited = copy.deepcopy(document)
    b3 = fx.board_of(edited, B3)
    b3["photo"]["current_version_id"] = None
    b3["cues"] = copy.deepcopy(fx.board_of(fx.story_document(), B3)["cues"])  # a camera cue
    bad = next(b for b in fx.load(edited).boards if b.id == B3)
    assert [(v.rule, v.path) for v in check_board(bad, frames=None)] == [
        (PHOTO_ABSENT, "/photo/current_version_id"), (UNSUPPORTED, "/cues/0")]
    s2v = copy.deepcopy(document)
    fx.board_of(s2v, B2)["method"]["motion"] = "s2v"
    fx.board_of(s2v, B2)["seeds"] = {"s2v:c": 1}
    fx.board_of(s2v, B2)["cast"] = [{"slot": "c", "asset_version_id": fx.STILL_C}]
    b2 = next(b for b in fx.load(s2v).boards if b.id == B2)
    rules = check_board(b2, frames=42)
    assert [(v.rule, v.status) for v in rules] == [(METHOD_UNAVAILABLE, "unavailable")]
    layered = next(b for b in fx.load(fx.story_document()).boards if b.id == fx.B1)
    assert UNSUPPORTED in [v.rule for v in check_board(layered, frames=78)]
    assert board["photo"]["current_version_id"] is not None


def test_the_adapter_never_deletes_renames_or_writes_files_itself():
    """D17: no call in the whole-frame package removes, renames or truncates a file,
    and no file is opened directly; every write goes through the store."""
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src" / "haynes_studio" / "wholeframe"
    banned = {"unlink", "remove", "rename", "replace", "rmdir", "rmtree", "truncate"}
    paths = sorted(src.glob("*.py"))
    assert len(paths) >= 8
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute):
                assert node.attr not in banned, f"{path.name}: .{node.attr}"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id != "open", f"{path.name}: open()"
