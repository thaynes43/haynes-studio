"""The mix and the master through the store (story 841), on the cache fixture story.

The four-board fixture of story 380 (223 frames at 360x640) gets real synthetic voice
tracks, a real sound cue and a real bed; its picture is the synthetic renderer's. The
plan is made with the picture builder and the sound builder as its content, as a run
would make it. Completed stages are found again by key: a second build mixes, muxes
and renders nothing, and a mix-only edit rebuilds the mix and the master and no
picture.
"""

from __future__ import annotations

import copy
import dataclasses
import json
from pathlib import Path

import pytest

from haynes_studio.cache import CacheError, Toolchain, diff, plan_story
from haynes_studio.cache.keys import MASTER, MIX
from haynes_studio.delivery.media import inspect
from haynes_studio.mix import MixError, board_ranges, check_cues, film_sound, placement_key
from haynes_studio.mix.audio import read_pcm
from haynes_studio.mix.build import CheckResult, SoundBuilder
from haynes_studio.store import BLOB_MISSING, LocalStore, StoreError, blob_locator
from tests.cache import fixtures as fx
from tests.cache.fixtures import B1, B2, B4, PRODUCTION, ident
from tests.mix.fixtures import TOOLCHAIN, Build, sha

RUN1, RUN2 = ident("run", 1), ident("run", 2)


@pytest.fixture
def store(tmp_path: Path) -> LocalStore:
    (tmp_path / "store").mkdir()
    return LocalStore(tmp_path / "store")


def stages(store: LocalStore, kind: str) -> list[str]:
    """Completed stages of ``kind`` in the production, any run."""
    records = Path(store.root) / "productions" / PRODUCTION / "records"
    if not records.exists():
        return []
    return sorted(p.stem for p in records.glob(f"*/{kind}-*.json"))


def blob(store: LocalStore, sha256: str, media_type: str) -> bytes:
    with store.open(blob_locator(PRODUCTION, sha256, media_type)) as handle:
        return handle.read()


def test_a_build_makes_the_mix_and_master_once_and_a_second_build_finds_them(store, tmp_path):
    first = Build(store, fx.story_document(), RUN1)
    plan = first.plan()
    assert first.sound.stats.mixed == [plan.mix.key.value]
    assert first.sound.stats.muxed == [plan.master.key.value]
    result = film_sound(first.story, plan, first.sound)
    assert result.passed, [r.document for r in result.checks]
    assert (result.mix.sha256, result.master.sha256) == (plan.mix.content, plan.master.content)

    # TIME-11: 223 frames, the mix exactly 223 x 2000 samples, the master both.
    assert plan.frames == 223
    mix_pcm = read_pcm(blob(store, result.mix.sha256, "audio/wav"), where="mix")
    assert mix_pcm.samples.shape == (223 * 2000, 2)
    master = tmp_path / "master.mp4"
    master.write_bytes(blob(store, result.master.sha256, "video/mp4"))
    report = inspect(master, width=360, height=640, expected_frames=223)
    assert report.ok, report.problems
    assert report.audio_samples == 223 * 2000

    # The run's placement record names the story's boards, lines, cue and bed.
    placement = result.placement
    assert [b["frames"] for b in placement["boards"]] == [b.frames for b in plan.boards]
    lines = {(p["board_id"], p["line_id"]): p for p in placement["lines"]}
    assert set(lines) == {(B1, fx.L1), (B1, fx.L2), (B1, fx.L3), (B2, fx.L4), (B4, fx.L5),
                          (B4, fx.L6)}
    b4 = next(b for b in plan.boards if b.board_id == B4)
    assert lines[(B4, fx.L5)]["start_sample"] == b4.film_start_frame * 2000 + 500 * 48  # TIME-7
    (sound,) = placement["sounds"]
    assert (sound["board_id"], sound["cue_id"]) == (B1, ident("cue", 3))
    l1 = lines[(B1, fx.L1)]
    assert sound["start_sample"] == l1["board_end_ms"] * 48 + 50 * 48  # 50 ms after line 1
    assert sound["end_sample"] - sound["start_sample"] == 400 * 48  # trim [0, 400]
    assert placement["beds"][0]["bed_id"] == ident("cue", 9)
    assert {r.check for r in result.checks} == {
        "mix.length", "mix.loudness", "mix.true_peak", "mix.clipping", "master.loudness",
        "master.true_peak", "master.clipping"}
    assert stages(store, "mix_placement") == [f"mix_placement-{placement_key(plan.mix.key).hex}"]

    # A second build of the unchanged story: everything is a hit.
    second = Build(store, fx.story_document(), RUN2, earlier=[RUN1])
    again = second.plan()
    assert again.keys() == plan.keys()
    assert (second.sound.stats.mixed, second.sound.stats.muxed) == ([], [])
    assert (second.picture.rendered, second.picture.spliced) == ([], [])
    repeat = film_sound(second.story, again, second.sound)
    assert second.sound.stats.checked == []
    assert [r.sha256 for r in repeat.checks] == [r.sha256 for r in result.checks]
    assert repeat.placement == placement
    assert len(stages(store, MIX)) == len(stages(store, MASTER)) == 1


def edit_cue_level(document):
    fx.board_of(document, B1)["cues"][2]["level_rms_dbfs"] = -18


def edit_bed_level(document):
    document["beds"][0]["level_rms_dbfs"] = -36


def edit_target(document):
    document["mix"]["master_lufs"] = -18


def edit_cue_anchor(document):
    fx.board_of(document, B1)["cues"][2]["anchor"] = {"at_ms": 900}


@pytest.mark.parametrize("edit", [edit_cue_level, edit_bed_level, edit_target, edit_cue_anchor])
def test_a_mix_only_edit_rebuilds_the_mix_and_master_and_no_picture(store, edit):
    first = Build(store, fx.story_document(), RUN1)
    before = first.plan()
    document = fx.story_document()
    edit(document)
    second = Build(store, document, RUN2, earlier=[RUN1])
    after = second.plan()
    changes = diff(before, after)
    assert {"film/mix", "film/master"} <= changes.changed
    assert all(name in ("film/mix", "film/master", "film/proxy") or name.startswith("check/")
               for name in changes.changed), sorted(changes.changed)
    assert not changes.added and not changes.removed
    assert (second.picture.rendered, second.picture.spliced) == ([], [])
    assert second.sound.stats.mixed == [after.mix.key.value]
    assert second.sound.stats.muxed == [after.master.key.value]
    assert film_sound(second.story, after, second.sound).passed


def sound_only(store, document, *, blobs=None) -> Build:
    """A build whose picture is a stand-in, for refusals that come before the master."""
    return Build(store, document, RUN1, blobs=blobs)


def test_a_cue_outside_its_board_fails_without_a_mix_or_master(store):
    document = fx.story_document()
    # Board 1 is 78 frames (3250 ms): 3300 ms lies in board 2.
    fx.board_of(document, B1)["cues"][2]["anchor"] = {"at_ms": 3300}
    build = sound_only(store, document)
    with pytest.raises(MixError) as error:
        build.plan(content=build.sound)
    assert error.value.code == "cue.out_of_range"
    assert B1 in error.value.where and ident("cue", 3) in error.value.where
    assert stages(store, MIX) == stages(store, MASTER) == stages(store, "mix_placement") == []


def test_a_missing_sound_fails_without_a_master(store):
    build = sound_only(store, fx.story_document(), blobs={fx.SOUND: sha(b"never published")})
    with pytest.raises(StoreError) as error:
        build.plan(content=build.sound)
    assert error.value.code == BLOB_MISSING
    assert stages(store, MIX) == stages(store, MASTER) == []


def test_a_builder_refuses_a_key_for_another_mixer_or_mux(store):
    build = sound_only(store, fx.story_document())
    for toolchain in (Toolchain(), dataclasses.replace(TOOLCHAIN, mux={"audio": "aac"})):
        with pytest.raises(CacheError) as error:
            plan_story(build.story, voices=build.voices, blobs=build.blobs, voice_ids=fx.VOICE_IDS,
                       toolchain=toolchain, media=fx.MEDIA, content=build.sound)
        assert error.value.code == "cache.entry_invalid"


def test_board_ranges_and_cue_checks_from_the_key_and_the_story(store):
    build = sound_only(store, fx.story_document())
    plan = build.plan(content=fx.stand_in)
    ranges = board_ranges(build.story, plan.mix.key.document)
    assert [(r.board_id, r.start_frame, r.frames) for r in ranges] == [
        (b.board_id, b.film_start_frame, b.frames) for b in plan.boards]
    check_cues(build.story, plan.mix.key.document)  # in range: no error
    document = copy.deepcopy(dict(plan.mix.key.inputs()))
    document["frames"] += 1
    with pytest.raises(MixError) as error:
        board_ranges(build.story, document)
    assert error.value.code == "time.conservation"


def test_ensure_passed_names_every_failed_check(store):
    first = Build(store, fx.story_document(), RUN1)
    result = film_sound(first.story, first.plan(), first.sound)
    result.ensure_passed()
    bad = dict(result.checks[0].document, passed=False)
    failing = dataclasses.replace(result, checks=(CheckResult(
        check=result.checks[0].check, key=result.checks[0].key, sha256=result.checks[0].sha256,
        document=bad), *result.checks[1:]))
    assert not failing.passed
    with pytest.raises(MixError) as error:
        failing.ensure_passed()
    assert error.value.code == "mix.check_failed" and result.checks[0].check in str(error.value)
    # The cached results are JSON documents whose key is the check's key.
    raw = json.loads(blob(store, result.checks[0].sha256, "application/json"))
    assert raw["check"] == result.checks[0].check and raw["passed"] is True


def test_the_sound_code_never_deletes_renames_or_truncates():
    """D17: nothing in the mix package removes, renames or truncates a file. Every
    artifact is published through the cache; the master's one scratch file lives in a
    private temporary folder outside the store, as story 381's proxy does."""
    import ast

    banned = {"unlink", "remove", "rename", "replace", "rmdir", "rmtree", "truncate",
              "ftruncate", "chmod", "removedirs", "renames"}
    source = Path(__file__).resolve().parents[2] / "src" / "haynes_studio" / "mix"
    for path in sorted(source.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and not (
                    node.attr == "replace" and isinstance(node.value, ast.Name)
                    and node.value.id == "dataclasses"):  # a copy of a frozen dataclass
                assert node.attr not in banned, f"{path.name}: .{node.attr}"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in banned, f"{path.name}: {node.func.id}()"
