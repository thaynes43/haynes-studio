"""The import plan, from the real public records: every row of the recovery map and
every E0 clip record line is planned once, each distinct hash is one item, and the
sources are only what this story may read."""

from __future__ import annotations

import copy
from collections import Counter
from dataclasses import replace

import pytest

from haynes_studio.adapters.recovery import build as build_recovery_map
from haynes_studio.importer.plan import (
    JOB_OUTPUT,
    LEDGER_ASSET,
    NEVER_DELIVERED,
    NOT_READ_RENDER,
    NOT_READ_WHOLE_FRAME,
    UPLOAD,
    E0Line,
    PlanError,
    plan_import,
)
from haynes_studio.library.library import EMPTY
from tests.importer.twin import public
from tests.support.policy import REPO_ROOT


def plan():
    p = public()
    return plan_import(p.recovery_map, p.lines, p.library, production_id=p.story["production_id"])


def test_every_recovery_row_and_e0_line_is_planned_once():
    p, result = public(), plan()
    keys = [row.key for row in result.rows]
    assert len(keys) == len(set(keys))
    recovery = [row["key"] for row in p.recovery_map["rows"]]
    assert [k for k in keys if not k.startswith("e0:")] == recovery and len(recovery) == 98
    e0 = [k for k in keys if k.startswith("e0:") and not k.startswith(("e0:start_image:",
                                                                         "e0:drive_track:"))]
    assert e0 == [f"e0:{line.file}:{line.line}:{line.record['name']}" for line in p.lines]
    assert len(e0) == 36
    assert Counter(row.role for row in result.rows) == {
        "render": 8, "still": 25, "set": 4, "sfx": 11, "bed": 3, "take": 38, "keyframe": 9,
        "doll_loop": 10, "set_loop": 1, "timed_clip": 11, "not_motion": 14, "start_image": 11,
        "drive_track": 11}
    # Every row's hash is one item, every item's rows are rows.
    assert {item.sha256 for item in result.items} == {row.sha256 for row in result.rows}
    assert sorted(k for item in result.items for k in item.rows) == sorted(keys)
    assert len(result.items) == 101


def test_the_recovery_map_is_the_one_built_from_public_files():
    assert public().recovery_map == build_recovery_map(REPO_ROOT)


def test_sources_are_only_the_wan_volume_reads():
    result = plan()
    by_role = {}
    for item in result.items:
        for key in item.rows:
            role = next(r.role for r in result.rows if r.key == key)
            by_role.setdefault(role, set()).update(s.kind for s in item.sources)
    assert by_role["still"] == by_role["sfx"] == by_role["take"] == by_role["set"] == {LEDGER_ASSET}
    assert by_role["keyframe"] == by_role["start_image"] == by_role["drive_track"] == {UPLOAD}
    assert by_role["doll_loop"] == by_role["set_loop"] == by_role["timed_clip"] == {JOB_OUTPUT}
    assert by_role["bed"] == by_role["not_motion"] == set()
    assert by_role["render"] == {LEDGER_ASSET}  # only set-left-s221, which is the set's bytes


def test_unread_rows_say_why():
    result = plan()
    unread = {row.key: row.unread for row in result.rows if row.unread}
    assert {k for k, why in unread.items() if why == NEVER_DELIVERED} == {
        "r2:bed:sfx/fire-s701.wav", "r3:bed:sfx/fire-s701.wav", "r4:bed:sfx/fire-s701.wav"}
    assert sum(why == NOT_READ_RENDER for why in unread.values()) == 8
    assert sum(why == NOT_READ_WHOLE_FRAME for why in unread.values()) == 14
    bed = result.item(next(r.sha256 for r in result.rows if r.role == "bed"))
    assert bed.sources == () and bed.unread == NEVER_DELIVERED
    the_set = result.item(next(r.sha256 for r in result.rows if r.key == "r1:render:set-left-s221.png"))
    assert the_set.sources and "r4:set:cutouts/set.png" in the_set.rows and the_set.unread is None


def test_each_hash_is_read_from_its_sources_in_row_order_once_each():
    result = plan()
    still = result.item(next(r.sha256 for r in result.rows if r.key == "r4:still:cutouts/a-proud.png"))
    assert [s.kind for s in still.sources] == [LEDGER_ASSET] * 4
    assert len(set(still.sources)) == 4  # r1 to r4's ledgers, each once
    assert all(s.path.startswith("/workspace/output/productions/the-winter-menu-r") for s in still.sources)
    for item in result.items:
        assert len(item.sources) == len(set(item.sources))


def test_uploads_are_named_by_their_hash_and_jobs_by_their_id():
    result = plan()
    for item in result.items:
        for source in item.sources:
            if source.kind == UPLOAD:
                suffix = {"image/png": ".png", "audio/wav": ".wav"}[item.media_type]
                assert source.name == item.sha256[:16] + suffix
                assert source.path == "/workspace/input/studio-e0/" + source.name
            if source.kind == JOB_OUTPUT:
                assert len(source.name) == 32 and source.path is None


def test_items_go_where_their_versions_are_else_the_production():
    p, result = public(), plan()
    production = p.story["production_id"]
    for item in result.items:
        assert item.scopes == (production,)
        for version_id in item.versions:
            assert p.library.version(version_id).content.sha256 == item.sha256
    clips = [i for i in result.items if i.media_type == "video/mp4" and i.sources]
    assert len(clips) == 22 and all(len(i.versions) == 1 for i in clips)


def test_the_plan_reads_nothing():
    """Planning touches no store and no service: it takes values only."""
    p = public()
    assert plan_import(p.recovery_map, p.lines, EMPTY, production_id="prd_x").items


def _map_with(row_change):
    p = public()
    rows = copy.deepcopy(p.recovery_map["rows"])  # never the cached map's own rows
    row_change(rows)
    return {**p.recovery_map, "rows": rows}


@pytest.mark.parametrize("change,message", [
    (lambda rows: rows[0].update(role="poster"), "unknown role"),
    (lambda rows: rows[0].update(file="a-base-s101.gif"), "no media type"),
    (lambda rows: rows.append({**rows[0]}), "two rows have this key"),
    (lambda rows: rows.append({**rows[8], "key": "x", "file": "cutouts/a-proud.wav"}), "in another row"),
    (lambda rows: next(r for r in rows if r["role"] == "keyframe")["locators"][0].update(
        path="/workspace/input/studio-e0/../../jobs/x.png"), "upload path"),
])
def test_records_that_disagree_are_a_plan_error(change, message):
    p = public()
    with pytest.raises(PlanError, match=message):
        plan_import(_map_with(change), p.lines, p.library, production_id=p.story["production_id"])


def test_an_e0_line_with_an_unknown_outcome_is_a_plan_error():
    p = public()
    lines = list(p.lines)
    lines[0] = replace(lines[0], outcome="a poster")
    with pytest.raises(PlanError, match="unknown outcome"):
        plan_import(p.recovery_map, lines, p.library, production_id="prd_x")


def test_a_version_of_another_media_type_is_a_plan_error():
    p = public()
    line = next(line for line in p.lines if line.outcome == "doll loop")
    still = next(r for r in p.recovery_map["rows"] if r["role"] == "still")
    odd = E0Line(line.file, 99, "doll loop", {**line.record, "name": "odd", "clip_sha256": still["sha256"]})
    with pytest.raises(PlanError):
        plan_import(p.recovery_map, [*p.lines, odd], p.library, production_id="prd_x")
