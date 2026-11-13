"""The E0 clips of The Winter Menu as motion records (story 457), from public text only:
every line of the three clip record files is a record or a named gap; the r4 story
resolves its loops and timed clips; the reference's tables are the generated ones."""

from __future__ import annotations

import copy
import json
import re
from collections import Counter
from functools import cache

import pytest

from haynes_studio.library import validate_asset_version
from haynes_studio.library.model import CANDIDATE, PROMOTED
from haynes_studio.motion.record import DOLL, LOOP, MotionRecord
from haynes_studio.motion.resolve import candidates, resolve_board, resolve_story, resolve_timed
from haynes_studio.motion.winter_menu import (
    RECORD_FILES,
    E0Motion,
    build_e0_motion,
    e0_gaps,
    e0_table,
    load_e0_sources,
)
from tests.canonical.fixtures import NOW
from tests.library.fixtures import BY, imported, register, winter_menu
from tests.motion.fixtures import Verify
from tests.support.policy import REPO_ROOT

E0_DIR = REPO_ROOT / "titles" / "the-winter-menu" / "video-e0"
REFERENCE = REPO_ROOT / "docs" / "reference" / "motion-clips.md"


@cache
def sources():
    return load_e0_sources(REPO_ROOT)


@cache
def e0() -> E0Motion:
    """The r4 library of story 382 with the E0 motion records added."""
    library = winter_menu(4).library
    return build_e0_motion(sources(), production_id=imported(4).story["production_id"],
                           licences=register(), by=BY, now=NOW, library=library)


def motion_versions(result: E0Motion):
    return [v for v in result.library.versions.values() if v.kind == "motion"]


def test_every_line_of_the_three_clip_record_files_is_accounted_for():
    lines = {(name, i) for name in RECORD_FILES
             for i, line in enumerate((E0_DIR / name).read_text().splitlines(), 1) if line.strip()}
    rows = e0().rows
    assert len(lines) == 36
    assert {(row.file, row.line) for row in rows} == lines
    assert len(rows) == len(lines)
    assert Counter(row.outcome for row in rows) == {
        "doll loop": 10, "set loop": 1, "timed clip": 11, "not a motion clip": 14}
    for row in rows:
        assert (row.version_id is None) == (row.outcome == "not a motion clip")
        assert row.outcome != "not a motion clip" or row.note


def test_every_record_is_a_valid_motion_version():
    result = e0()
    versions = motion_versions(result)
    assert len(versions) == 22
    for version in versions:
        document = result.library.document(version.id)
        assert validate_asset_version(document, context="write") == [], version.id
        assert document["licence"]["commercial_use"] == "allowed"  # the register's Wan entries
    states = Counter((v.motion["use"], v.motion["subject"], v.state) for v in versions)
    assert states == {("loop", "doll", PROMOTED): 7, ("loop", "doll", CANDIDATE): 3,
                      ("loop", "set", PROMOTED): 1, ("timed", "doll", PROMOTED): 11}


def test_building_twice_returns_the_same_versions():
    result = e0()
    again = build_e0_motion(sources(), production_id=imported(4).story["production_id"],
                            licences=register(), by=BY, now=NOW, library=result.library)
    assert not any(outcome.created for outcome in again.outcomes)
    assert again.library == result.library
    assert [row.version_id for row in again.rows] == [row.version_id for row in result.rows]


def test_superseded_clips_are_earlier_versions_of_the_same_loop():
    result = e0()
    for old, new in (("layer-b-deadpan-green", "layer-b-deadpan-v2-green"),
                     ("layer-d-cheerful-green", "layer-d-cheerful-v2-green"),
                     ("layer-d-shocked-green", "layer-d-shocked-v2-green")):
        first = result.library.version(result.row(old).version_id)
        second = result.library.version(result.row(new).version_id)
        assert first.asset_id == second.asset_id
        assert (first.number, first.state, second.number, second.state) == (1, CANDIDATE, 2, PROMOTED)
        assert first.motion.get("keying") is None and second.motion["keying"]["decal_version"] == "erase-v2"


def test_the_timed_trims_are_the_contracts_worked_example():
    """Section 3's r4 table: source frames needed and returned, per board."""
    needed = {1: 102, 2: 63, 3: 97, 4: 56, 5: 55, 6: 81, 8: 167, 9: 72}
    returned = {1: 158, 2: 66, 3: 158, 4: 58, 5: 58, 6: 158, 8: 238, 9: 74}
    result = e0()
    for row in result.rows:
        if row.outcome == "timed clip":
            record = MotionRecord.from_block(result.library.version(row.version_id).motion)
            assert (record.trim_frames, record.frames) == (needed[row.board], returned[row.board])


def test_the_r4_story_resolves_its_loops_as_the_layered_s2v_film_did():
    """r4 is layered speech-to-video: every slot without a line plays its loop."""
    result = e0()
    story = imported(4).story
    resolved = resolve_story(story, result.library, Verify())
    assert all(board.complete for board in resolved), [b.problems for b in resolved]
    used = {(board.board_id, clip.slot): result.library.version(clip.version_id).legacy["path"]
            for board, data in zip(resolved, story["boards"]) for clip in board.cast}
    by_number = {b["id"]: b["number"] for b in story["boards"]}
    assert {(by_number[board], slot): path for (board, slot), path in used.items()} == {
        (7, "d"): "clips/layer-d-shocked-v2-green.mp4",
        (9, "a"): "clips/layer-a-green.mp4", (9, "c"): "clips/layer-c-suspicious-green.mp4"}
    assert all(board.set is None for board in resolved)  # no public link: pin it (below)


def test_every_promoted_loop_resolves_on_a_layered_board():
    result = e0()
    story = copy.deepcopy(imported(4).story)
    set_loop = result.row("layer-set-loop").version_id
    story["set"]["motion_asset_version_id"] = set_loop
    for board in story["boards"]:
        board["method"] = {"layer": "layered", "motion": "i2v"}
    resolved = resolve_story(story, result.library, Verify())
    assert all(board.complete for board in resolved), [b.problems for b in resolved]
    assert {board.set.version_id for board in resolved} == {set_loop}
    used = {clip.version_id for board in resolved for clip in board.cast}
    promoted_dolls = {row.version_id for row in result.rows
                      if row.outcome == "doll loop" and row.state == PROMOTED}
    cheerful = result.row("layer-d-cheerful-v2-green").version_id  # r4 places no d-cheerful
    assert used == promoted_dolls - {cheerful}
    sha = sources().stills["cutouts/d-cheerful.png"]
    assert [v.id for v in candidates(result.library, use=LOOP, subject=DOLL,
                                     still_sha256=sha)] == [cheerful]


def test_every_timed_clip_resolves_for_its_r4_board_and_speaker():
    result = e0()
    story = imported(4).story
    boards = {board["number"]: board for board in story["boards"]}
    for row in result.rows:
        if row.outcome != "timed clip":
            continue
        board = boards[row.board]
        still = next(e["asset_version_id"] for e in board["cast"] if e["slot"] == row.slot)
        record = result.library.version(row.version_id).motion
        clip, found = resolve_timed(
            result.library, Verify(), still_sha256=result.library.version(still).content.sha256,
            drive_track_sha256=record["drive_track"]["sha256"],
            board_frames=board["derived"]["frames"], slot=row.slot,
            production_id=story["production_id"])
        assert found == () and clip.version_id == row.version_id, row.name


def test_a_superseded_clip_cannot_be_played_until_its_keying_is_recorded():
    result = e0()
    story = imported(4).story
    board = copy.deepcopy(next(b for b in story["boards"] if b["number"] == 2))
    board["method"] = {"layer": "layered", "motion": "i2v"}
    board["cast"][0]["motion_asset_version_id"] = result.row("layer-b-deadpan-green").version_id
    found = resolve_board(board, result.library, Verify(), story=story)
    assert {(v.rule, v.path) for v in found.problems} == {
        ("motion.keying_missing", "/cast/0/motion_asset_version_id")}


def test_a_speech_to_video_clip_is_never_a_loop():
    result = e0()
    story = imported(4).story
    board = copy.deepcopy(next(b for b in story["boards"] if b["number"] == 1))
    board["method"] = {"layer": "layered", "motion": "i2v"}
    board["cast"][0]["motion_asset_version_id"] = result.row("s1-a-lightning").version_id
    found = resolve_board(board, result.library, Verify(), story=story)
    assert {(v.rule, v.path) for v in found.problems} == {
        ("motion.timed_not_loop", "/cast/0/motion_asset_version_id")}


def test_the_gaps_are_named():
    fields = Counter(gap.field for gap in e0().gaps)
    assert fields == {"content.bytes": 11, "provenance.generator.workflow_sha256": 13,
                      "motion.keying": 3, "motion.still_sha256": 1}


def test_no_record_holds_a_value_the_public_text_lacks():
    """Fields a gap names are left out, never filled."""
    result = e0()
    for gap in result.gaps:
        version = result.library.version(result.row(gap.clip).version_id)
        if gap.field == "content.bytes":
            assert version.content.bytes is None
        elif gap.field == "provenance.generator.workflow_sha256":
            assert "workflow_sha256" not in version.provenance["generator"]
            assert "template_sha256" not in version.motion["source"]["profile"]
        else:
            assert gap.field.split(".")[1] not in version.motion


def _between(text: str, name: str) -> str:
    match = re.search(rf"<!-- {name}:begin -->\n(.*?)<!-- {name}:end -->", text, re.S)
    assert match, name
    return match.group(1)


@pytest.mark.parametrize(("name", "render"), [("motion-e0", e0_table), ("motion-e0-gaps", e0_gaps)])
def test_the_reference_holds_the_generated_tables(name, render):
    assert _between(REFERENCE.read_text(), name) == render(e0())


def test_the_inputs_are_text_only():
    for path in (E0_DIR / "clipmap-s2v.json", E0_DIR / "decal-scores.json"):
        json.loads(path.read_text())
