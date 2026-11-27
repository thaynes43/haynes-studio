"""Compatibility with loop admission and planning on main at 0239c60."""

from copy import deepcopy

import pytest

from haynes_studio.build.prebuild import snapshot_bytes
from haynes_studio.cache import plan_story
from haynes_studio.cache.plan import MediaFormat
from haynes_studio.motion.winter_menu import complete_block
from haynes_studio.queue.inputs import freeze, prepare_queue
from haynes_studio.render.clock import SET_SLOT, loop_phase, loop_period
from tests.build_story import fixtures as f
from tests.cache.fixtures import stand_in

# Computed by freezing the same fixture on main at 0239c602.
SNAPSHOT_DIGEST = {
    False: "d9946b09a47b374f1e59bdbb4c01fcb863ae33c260e277ba2fd98c74f5d8c7f3",
    True: "dce1e2644b32df2faa2fd724f490fad5ffe574d727b320c35697018b8a721ec9",
}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("legacy-loops")
    world = f.World(root, f.LocalStore(root))
    for index, slot in enumerate("ab"):
        still = world.still(f.STILL[slot], 10 + index, f"cast {slot}".encode())
        world.loop(f.LOOP[slot], 20 + index, still_sha=still, clip=f"loop {slot}".encode(), start=b"green")
        world.voice(f.VOICE[slot], 30 + index, f.STOCK[slot])
    plate = world.still(f.PLATE, 40, b"set plate", kind="set")
    world.loop(f.SET_LOOP, 41, still_sha=plate, clip=b"set loop", start=b"set plate", subject="set")
    return world


@pytest.mark.parametrize(("still_hash", "selected"), [
    ("absent", False), ("absent", True), ("unmatched", False), ("duplicate", False),
    ("duplicate", True), ("different-provenance", False), ("matching", False), ("matching", True),
])
def test_legacy_loop_admission_plan_and_snapshot_match_main(world, still_hash, selected):
    document = f.story_document()
    document.update(board_order=[f.B2], boards=[document["boards"][1]])
    if not selected:
        document["set"]["asset_version_id"] = None
    loop, plate = (deepcopy(next(doc for doc in world.docs if doc["id"] == id_))
                   for id_ in (f.SET_LOOP, f.PLATE))
    extras = [loop]
    if still_hash == "absent":
        del loop["motion"]["still_sha256"]
    elif still_hash in ("unmatched", "different-provenance"):
        loop["motion"]["still_sha256"] = "e" * 64
        if still_hash == "different-provenance":
            loop["provenance"]["generator"]["source_asset_version_ids"] = [f.PLATE]
    elif still_hash == "duplicate":
        extras.append({**plate, "id": f.ident("asv", 74), "asset_id": f.ident("ast", 74), "legacy": None,
                       "provenance": {**plate["provenance"], "source_key": None}})
    loop["motion"] = complete_block(loop["motion"], loop["content"]["sha256"])
    library = world.library(*extras, without={f.SET_LOOP})
    prepared = prepare_queue(document, library)
    assert prepared.ok, prepared.report.problems
    snapshot, _ = freeze(prepared, studio="git:fixture")
    assert snapshot_bytes(snapshot)[1] == SNAPSHOT_DIGEST[selected]
    plan = plan_story(prepared.story, voices={}, voice_ids={}, library=library,
                      blobs={v.id: v.content.sha256 for v in library.versions.values() if v.content},
                      toolchain=f.toolchain(), media=MediaFormat(width=1080, height=1920),
                      content=stand_in, motion=prepared.motion)
    [board] = plan.boards
    assert board.frames == 12
    assert board.segment.key.document["set_layer"] == {
        "plate": plate["content"]["sha256"] if selected else None,
        "loop": loop["content"]["sha256"], "phase": loop_phase(f.B2, SET_SLOT, loop_period(f.LOOP_N)),
        "trim_start": 0, "trim_frames": f.LOOP_N, "clip_frames": f.LOOP_N,
    }
