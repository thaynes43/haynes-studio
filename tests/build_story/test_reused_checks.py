"""A reused segment still shows its lettering-track check (story 860 item e).

The decal gate runs when a layered segment is rendered; a build that finds the segment
in the cache renders nothing, so the gate does not run again. Its board stage still
lists each layer's decal result (the check, the slot, the lowest score over the frames
the board shows, the floor and the result), read from the keyed-frames record the cache
holds, and it is the result the rendering run recorded.
"""

from __future__ import annotations

from haynes_studio.build import offline_sources
from tests.build_story import fixtures as f


def checks_by_board(run):
    return {stage["board_id"]: stage["checks"] for stage in run["stages"]}


def test_a_build_of_cached_segments_lists_the_decal_results_of_the_build_that_rendered_them(
        world, voiced, first):
    rendered = checks_by_board(first.run)
    assert all(stage["report"] is not None for stage in first.run["stages"])  # rendered there
    document, library = voiced
    reused = f.build(world, document, library, phase="offline", source=offline_sources())
    assert reused.run["status"] == "succeeded" and reused.made == ()  # nothing rendered
    assert all(stage["report"] is None for stage in reused.run["stages"])  # every segment reused
    assert checks_by_board(reused.run) == rendered
    # Each layered board lists its two dolls' gates in draw order; the whole-frame board none.
    for board_id in (f.B1, f.B2):
        checks = rendered[board_id]
        assert [c["slot"] for c in checks] == ["a", "b"]
        for check in checks:
            assert check["check"] == "layered.decal_gate" and check["result"] == "pass"
            assert check["thresholds"] == {"min_ecc": 0.8}
            assert check["measured"]["min_ecc"] >= 0.8 and check["measured"]["frames_gated"] > 0
    assert rendered[f.B3] == []


def test_the_reused_results_name_the_keyed_artifacts_of_the_stage(world, voiced, first):
    document, library = voiced
    reused = f.build(world, document, library, phase="offline", source=offline_sources())
    for stage in reused.run["stages"]:
        keyed = {a["name"].split("/", 1)[1]: a["sha256"] for a in stage["artifacts"]
                 if a["kind"] == "keyed_frames"}
        assert {c["slot"]: c["artifact"] for c in stage["checks"]} == keyed
