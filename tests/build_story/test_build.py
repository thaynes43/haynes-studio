"""Build a story from its boards (story 406): the fixture story (one layered
speech-to-video, one layered image-to-video and one whole-frame board) builds to a
verified delivery with a phone proxy; the run record lists each board's artifacts,
timings and checks, and its provenance and credits; a second build makes nothing; one
board edit rebuilds exactly what contract section 4 says; a finished run never changes.
"""

from __future__ import annotations

import copy
import json

import pytest

from haynes_studio.build import BuildError, RunRecords, validate_run, validate_run_snapshot
from haynes_studio.build.prebuild import make_snapshot, prepare, snapshot_bytes
from haynes_studio.build.pipeline import build_toolchain, media_format
from haynes_studio.build.run import advance
from haynes_studio.cache.plan import diff
from haynes_studio.delivery import read_delivery
from haynes_studio.store import blob_locator
from haynes_studio.voice import Engine
from tests.build_story import fixtures as f


PICTURE_OUTPUTS = {"film/picture", "film/master", "film/proxy", "check/master.transcript"}


def test_the_fixture_story_builds_to_a_verified_delivery_with_a_phone_proxy(world, first):
    run = first.run
    assert run["status"] == "succeeded" and run["error"] is None
    delivery = read_delivery(world.store, production_id=f.PRODUCTION, run_id=run["id"])
    assert delivery is not None and delivery.id == run["delivery_id"]
    assert delivery.master.sha256 == run["outputs"]["master_sha256"] == first.plan.master.content
    assert delivery.proxy is not None and delivery.proxy.sha256 == run["outputs"]["proxy_sha256"]
    assert (delivery.master.width, delivery.master.height) == (1080, 1920)
    assert (delivery.proxy.width, delivery.proxy.height) == (720, 1280)
    assert delivery.master.frames == delivery.proxy.frames == run["outputs"]["frames"] == 42
    assert not validate_run(run, context="read")
    assert [t["to"] for t in run["transitions"]] == ["queued", "running", "succeeded"]


def test_the_run_record_lists_each_boards_method_artifacts_timings_and_checks(first):
    run = first.run
    stages = {stage["board_id"]: stage for stage in run["stages"]}
    assert [s["method"] for s in run["stages"]] == [
        {"layer": "layered", "motion": "s2v"}, {"layer": "layered", "motion": "i2v"},
        {"layer": "whole_frame", "motion": "i2v"}]
    assert [s["frames"] for s in run["stages"]] == [18, 12, 12]
    assert [s["film_start_frame"] for s in run["stages"]] == [0, 18, 30]
    for stage in run["stages"]:
        segment = next(a for a in stage["artifacts"] if a["name"] == "segment")
        assert segment["made"] and segment["seconds"] is not None and segment["sha256"] == stage["segment_sha256"]
        assert stage["report"] is not None and stage["render_s"] is not None
        for artifact in stage["artifacts"]:
            assert artifact["key"].startswith("sha256:") and len(artifact["sha256"]) == 64
    b1, b2, b3 = (stages[b] for b in (f.B1, f.B2, f.B3))
    assert b1["compositor"] == b2["compositor"] != b3["compositor"]  # per-method compositor
    (s2v,) = [c for c in b1["clips"] if c["role"] == "s2v_clip"]
    assert s2v["slot"] == "a" and s2v["made"] and s2v["seed"] == 11 and s2v["engine_job_id"]
    assert s2v["files_sha256"] and s2v["fps"] == 16
    assert {c["role"] for c in b1["clips"]} == {"s2v_clip", "doll_clip", "set_loop"}
    assert [c["library_version_id"] for c in b2["clips"] if c["role"] == "doll_clip"] == [f.LOOP["a"], f.LOOP["b"]]
    (wf,) = b3["clips"]
    assert wf["role"] == "whole_frame_clip" and wf["chunks"] == 1 and wf["clips"][0]["seed"] == 31
    assert [c["check"] for c in b1["checks"]] == ["layered.decal_gate"] * 2  # the renderer's own
    assert all(c["result"] == "pass" for c in b1["checks"] + b2["checks"])
    assert b3["report"]["clip_set"] == wf["sha256"]
    checks = {c["check"]: c for c in run["checks"]}
    assert set(checks) >= {"mix.length", "mix.loudness", "mix.true_peak", "mix.clipping",
                           "master.loudness", "master.true_peak", "master.clipping",
                           "master.transcript", "frame_count"}
    assert all(c["result"] != "fail" for c in checks.values())
    transcript = checks["master.transcript"]
    assert transcript["result"] == "pass_with_tolerances" and transcript["tolerances_used"] == ["2"]
    assert transcript["measured"]["heard"] == f.HEARD
    assert run["outputs"]["placement"]["lines"][0]["line_id"] == f.L1


def test_provenance_names_every_engine_with_its_licence_and_credits_only_video_voice_and_sound(first):
    prov = first.run["provenance"]
    engines = {e["key"]: e for e in prov["engines"]}
    assert {"wan-s2v", "wan-ti2v", "kokoro", "qwen-image", "asr"} <= set(engines)
    for engine in prov["engines"]:
        assert engine["licence"]["commercial_use"] in ("allowed", "conditional", "noncommercial", "unknown")
        assert all(file["licence"] for file in engine["files"])
    assert engines["wan-s2v"]["profile"]["size"] == [144, 256]
    assert "brd_" in engines["wan-s2v"]["used_by"][0]  # the clip this run made
    assert set(engines["wan-ti2v"]["used_by"]) >= {f.LOOP["a"], f.LOOP["b"], f.SET_LOOP}
    credits = {c["engine_key"] for c in prov["public"]["credits"]}
    assert credits == {"wan-s2v", "wan-ti2v", "kokoro"}  # no image, check or writer engine
    # The register's "where" (deployments, nodes) stays private: never in a credit.
    assert engines["kokoro"]["hardware"] == "ai/deploy/kokoro"
    assert not any("ai/" in c["text"] or "talos" in c["text"] for c in prov["public"]["credits"])
    # An engine's licence is the most restrictive of its files (section 7): the fake
    # engine reports a file the register does not name, whose terms are unknown.
    assert engines["wan-s2v"]["licence"]["commercial_use"] == "unknown"
    assert engines["kokoro"]["licence"]["commercial_use"] == "allowed"
    assert prov["public"]["ai_generated"] is True
    assert [i["id"] for i in prov["inputs_externally_generated"]] == [f.PHOTO]  # D42
    toolchain = prov["toolchain"]
    assert toolchain["studio"] == "git:fixture" and toolchain["python"] and toolchain["ffmpeg"]
    assert set(toolchain["compositors"]) == {"layered", "whole_frame"}


def test_a_second_build_makes_nothing_and_asks_no_source(world, voiced, first):
    document, library = voiced
    sources = f.sources()
    second = f.build(world, document, library, source=sources)
    assert second.run["status"] == "succeeded"
    assert second.made == () and second.source_calls == 0
    assert second.plan.keys() == first.plan.keys()
    assert second.run["snapshot"]["sha256"] == first.run["snapshot"]["sha256"]
    assert not any(a["made"] for s in second.run["stages"] for a in s["artifacts"])
    assert all(s["report"] is None for s in second.run["stages"])  # reused: no render


def test_a_seed_edit_rebuilds_exactly_what_section_4_says(world, voiced, first):
    document, library = voiced
    edited = copy.deepcopy(document)
    f.board_of(edited, f.B3)["seeds"]["i2v:frame"] = 33
    sources = f.sources()
    built = f.build(world, edited, library, source=sources)
    assert built.run["status"] == "succeeded"
    change = diff(first.plan, built.plan)
    # Section 4, "Seed": that clip and its segment; the film picture, master, proxy and
    # checks ("picture only": the mix keeps its key). Nothing else.
    assert change.rebuilt == {f"{f.B3}/whole_frame_clip", f"{f.B3}/segment"} | PICTURE_OUTPUTS
    assert "film/mix" in change.kept and not change.added and not change.removed
    planned = built.plan.artifacts
    made = set(built.made)
    expected = {planned[n].key.value for n in change.rebuilt if n != "film/proxy"}
    assert expected <= made  # the proxy is the delivery's (see the reference)
    assert not {planned[n].key.value for n in change.kept} & made
    assert len(sources.i2v.calls) == 1 and sources.s2v.calls == []
    assert [c.seed for c in sources.i2v.calls[0].clips] == [33]


def test_a_finished_run_is_unchanged_by_later_draft_edits(world, voiced, first):
    records = RunRecords(world.store, f.PRODUCTION)
    run_id = first.run["id"]
    assert records.latest(run_id) == json.loads(json.dumps(first.run))
    snapshot = json.loads(records.snapshot(run_id))
    original, _ = voiced
    assert snapshot["story"] == {k: v for k, v in original.items() if k != "derived"}
    assert f.board_of(snapshot["story"], f.B3)["seeds"]["i2v:frame"] == 31  # not a later edit
    assert not validate_run_snapshot(snapshot, context="read")
    with pytest.raises(BuildError) as error:
        advance(first.run, "running", at=f.NOW, by=f.OPERATOR, reason="again")
    assert error.value.code == "run.transition"
    # A writer holding an older version cannot append to a terminal run either.
    older = records.history(run_id)[1]  # the running version
    assert older["status"] == "running"
    stale = advance(older, "failed", at=f.NOW, by=f.OPERATOR, reason="a late writer")
    with pytest.raises(BuildError) as error:
        RunRecords(world.store, f.PRODUCTION).write(stale)
    assert error.value.code == "run.transition"
    assert records.latest(run_id)["status"] == "succeeded"


def test_the_snapshot_is_the_same_bytes_for_the_same_draft_and_holds_no_run(world, voiced):
    document, library = voiced
    tools = build_toolchain(f.toolchain())
    media = media_format("short")
    snaps = []
    for _ in range(2):
        prepared = prepare(document, library=library, store=world.store, toolchain=tools,
                           frame_size=(media.width, media.height), current_engine=Engine().signing_name)
        snaps.append(snapshot_bytes(make_snapshot(prepared, library, studio="git:fixture")))
    assert snaps[0] == snaps[1]
    text = snaps[0][0].decode()
    assert "run_" not in text and "2026-11-13T21" not in text
    snapshot = json.loads(text)
    ids = {entry["id"] for entry in snapshot["resolved_asset_versions"]}
    assert {f.LOOP["a"], f.LOOP["b"], f.SET_LOOP, f.PHOTO, f.VOICE["a"]} <= ids
    kinds = {entry["kind"] for entry in snapshot["resolved_asset_versions"]}
    assert {"cast", "motion", "set", "photo", "voice", "board_voice"} <= kinds


def test_the_snapshot_blob_is_where_the_run_says(world, first):
    snapshot = first.run["snapshot"]
    assert snapshot["locator"] == blob_locator(f.PRODUCTION, snapshot["sha256"], "application/json")
    assert world.store.verify(snapshot["locator"], snapshot["sha256"]) == "present"
    assert snapshot["board_count"] == 3 and snapshot["story_revision"] == 1


def test_the_transcript_comparison_is_the_pocs_word_by_word_with_tolerances():
    from haynes_studio.build.transcript import compare
    assert compare("Go team two", "Go, team two.", {"2": "two"}) == {
        "exact_match": True, "match_with_tolerances": True, "tolerances_used": []}
    assert compare("go team 2", "Go, team two.", {"2": "two"})["tolerances_used"] == ["2"]
    assert not compare("stop team 2", "Go, team two.", {"2": "two"})["match_with_tolerances"]
    # A tolerance applies to the heard words only, so the script's own "2" still matches.
    assert compare("Go team 2", "Go, team 2.", {"2": "two"})["exact_match"]
