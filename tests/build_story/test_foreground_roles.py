"""The build preflight and freeze use the same role declarations as the renderer."""

from copy import deepcopy

import pytest
from PIL import Image

from haynes_studio.build import BuildInputs, build_story
from haynes_studio.build.prebuild import make_snapshot, prepare, snapshot_bytes
from haynes_studio.build.run import RunRecords, local_run_ids, new_run
from haynes_studio.errors import ContractError
from haynes_studio.layered.foreground import (
    FOREGROUND_REQUIRED, MASK_INVALID, MASK_MISSING, MASK_NOT_READY, MASK_SIZE, MASK_STALE,
    SET_LOOP_SOURCE_UNKNOWN, UNSUPPORTED,
)
from haynes_studio.library import Library
from haynes_studio.queue.inputs import freeze
from haynes_studio.stages.preflight import PreflightError
from haynes_studio.store import blob_locator
from tests.build_story import fixtures as f
from tests.layered import media
from tests.layered.test_foreground_roles import RED_BOX, SIZE, png

MASK = f.ident("asv", 70)
UNMASKED_SET = f.ident("asv", 71)
FRAME = (1080, 1920)
SOURCE = (108, 192)


def role_world(root, *, right=38, order=30):
    root.mkdir()
    world = f.World(root, f.LocalStore(root))
    a = Image.new("RGBA", SIZE)
    a.paste((255, 0, 0, 255), RED_BOX)
    still = world.still(f.STILL["a"], 10, png(a))
    world.docs[-1]["content"].update(width=SIZE[0], height=SIZE[1])
    world.loop(f.LOOP["a"], 20, still_sha=still, clip=media.doll_clip(f.LOOP_N, moving=False),
               start=media.start_image(tint=0))
    world.voice(f.VOICE["a"], 30, f.STOCK["a"])
    plate = world.still(f.PLATE, 40, png(Image.new("RGB", SOURCE)), kind="set")
    set_doc = world.docs[-1]
    set_doc["content"].update(width=SOURCE[0], height=SOURCE[1])
    mask = Image.new("L", SOURCE)
    mask.paste(255, (0, 0, right, SOURCE[1]))
    mask_sha = world.still(MASK, 70, png(mask))
    world.docs[-1].update(kind="prop", capabilities=["mask"], attributes={})
    world.docs[-1]["content"].update(width=SOURCE[0], height=SOURCE[1])
    set_doc["occlusion"] = {"foreground": [{
        "key": "table", "layer_order": order,
        "mask": {"version_id": MASK, "sha256": mask_sha, "still_sha256": plate,
                 "width": SOURCE[0], "height": SOURCE[1]},
    }]}
    template = f.story_document()
    board = next(b for b in template["boards"] if b["id"] == f.B2)
    board["cast"] = [{"slot": "a", "asset_version_id": f.STILL["a"], "motion_asset_version_id": f.LOOP["a"]}]
    board["timing"]["hold_ms"] = 125
    template.update(
        cast=[member for member in template["cast"] if member["slot"] == "a"],
        boards=[board], board_order=[board["id"]],
        layouts={"pair": {"height": 480, "bottom": 1360, "x": .5}},
        motion_style={"idle_scale": 0},
    )
    template["set"].update(motion_asset_version_id=None, foreground_edge_px=None,
                           foreground_feather_px=None)
    return world, template, set_doc


def preflight(world, document, *, read=True, **options):
    return prepare(document, library=world.library(), store=world.store if read else None,
                   toolchain=f.toolchain(), frame_size=FRAME, current_engine="fixture",
                   **options)


def replace_mask_bytes(world, locator):
    path = world.root / locator
    path.unlink()
    path.write_bytes(png(Image.new("L", SOURCE, 255)))


@pytest.mark.parametrize(("change", "code"), [
    ("missing_version", MASK_MISSING),
    ("missing_bytes", MASK_MISSING),
    ("wrong_hash", MASK_STALE),
    ("corrupt_bytes", MASK_STALE),
    ("wrong_scope", MASK_MISSING),
    ("wrong_declared_size", MASK_SIZE),
    ("candidate", MASK_NOT_READY),
    ("wrong_size", MASK_SIZE),
    ("non_binary", MASK_INVALID),
])
def test_unusable_mask_is_refused_before_any_clip(tmp_path, change, code):
    world, document, plate = role_world(tmp_path / "store")
    mask = world.docs[-1]
    pin = plate["occlusion"]["foreground"][0]["mask"]
    if change == "missing_version":
        world.docs.pop()
    elif change == "missing_bytes":
        (world.root / mask["content"]["locator"]).unlink()
    elif change == "wrong_hash":
        pin["sha256"] = "a" * 64
    elif change == "corrupt_bytes":
        replace_mask_bytes(world, mask["content"]["locator"])
    elif change == "wrong_scope":
        production = f.ident("prd", 2)
        with world.store.open(mask["content"]["locator"]) as handle:
            foreign = world.store.publish(handle, scope=production, media_type="image/png")
        mask["scope"]["production_id"] = production
        mask["content"]["locator"] = foreign.locator
        assert world.store.verify(foreign.locator, pin["sha256"]) == "present"
    elif change == "wrong_declared_size":
        # The only discrepancy is in the declaration, not the actual set/mask.
        for version in (plate, mask):
            for axis in ("width", "height"):
                del version["content"][axis]
        pin["height"] -= 1
    elif change in ("non_binary", "wrong_size"):
        image = Image.new("L", SOURCE if change == "non_binary" else (100, 100), 127)
        data = png(image)
        blob = world.store.publish(data, scope=f.PRODUCTION, media_type="image/png")
        # Retain the original declared dimensions so only the byte check sees the discrepancy.
        mask["content"].update(sha256=blob.sha256, bytes=blob.bytes, locator=blob.locator)
        pin["sha256"] = blob.sha256
    else:
        mask["state"] = "candidate"
    # Queue admission verifies these bytes before work is queued.
    result = preflight(world, document, read=False, mask_store=world.store)
    assert [p.rule for p in result.report.blocking] == [code]


@pytest.mark.parametrize("scope", ["library", f.PRODUCTION])
def test_frozen_library_and_snapshot_pin_the_exact_mask_version(tmp_path, scope):
    world, document, plate = role_world(tmp_path / "store", order=5)
    if scope == "library":
        mask = world.docs[-1]
        with world.store.open(mask["content"]["locator"]) as handle:
            blob = world.store.publish(handle, scope=scope, media_type="image/png")
        mask["scope"]["production_id"] = None
        mask["content"]["locator"] = blob.locator
    prepared = preflight(world, document)
    assert prepared.ok, prepared.report.problems
    frozen, library = freeze(prepared, studio="git:fixture")
    pin = plate["occlusion"]["foreground"][0]["mask"]
    assert {"id": MASK, "kind": "prop", "sha256": pin["sha256"]} in frozen["resolved_asset_versions"]
    set_pin = next(entry for entry in frozen["resolved_asset_versions"] if entry["id"] == f.PLATE)
    assert set_pin == {"id": f.PLATE, "kind": "set", "sha256": plate["content"]["sha256"]}
    assert {entry["id"] for entry in library} == {entry["id"] for entry in frozen["resolved_asset_versions"]}
    assert next(doc for doc in library if doc["id"] == f.PLATE)["occlusion"] == plate["occlusion"]
    assert Library.from_version_documents(library).version(MASK).content.sha256 == pin["sha256"]
    assert make_snapshot(prepared, world.library(), studio="git:fixture") == frozen



def test_disabled_foreground_refuses_build_before_clips_or_new_run(tmp_path):
    world, document, _ = role_world(tmp_path / "store")
    document["boards"][0]["layout"]["foreground"] = False
    prepared = preflight(world, document)
    [issue] = prepared.report.blocking
    assert (issue.rule, issue.path) == (FOREGROUND_REQUIRED, "/boards/0/layout/foreground")
    assert "Enable layout.foreground" in issue.message

    inputs = BuildInputs(document, world.library(), f.register(), f.toolchain())
    with pytest.raises(PreflightError) as refused:
        build_story(inputs, store=world.store, phase="all", sources=f.sources(),
                    transcriber=None, actor=f.OPERATOR)
    assert [item.rule for item in refused.value.report.blocking] == [FOREGROUND_REQUIRED]
    assert local_run_ids(world.store, f.PRODUCTION) == []


@pytest.mark.parametrize("explicit", [True, False])
def test_declared_roles_refuse_a_set_loop(tmp_path, explicit):
    world, document, plate = role_world(tmp_path / "store")
    world.loop(f.SET_LOOP, 41, still_sha=plate["content"]["sha256"], clip=media.set_clip(f.SET_N),
               start=media.set_plate(), subject="set", frames=f.SET_N)
    if explicit:
        document["set"]["motion_asset_version_id"] = f.SET_LOOP
    prepared = preflight(world, document)
    assert [item.rule for item in prepared.report.blocking] == [UNSUPPORTED]


def test_discovered_set_loop_refuses_its_masked_source_even_with_an_unmasked_still_selected(tmp_path):
    world, document, plate = role_world(tmp_path / "store")
    unmasked = deepcopy(plate)
    unmasked.update(id=UNMASKED_SET, number=2)
    del unmasked["occlusion"]
    world.docs.append(unmasked)
    world.loop(f.SET_LOOP, 41, still_sha=plate["content"]["sha256"], clip=media.set_clip(f.SET_N),
               start=media.set_plate(), subject="set", frames=f.SET_N)
    world.docs[-1]["provenance"]["generator"]["source_asset_version_ids"] = [f.PLATE]
    document["set"]["asset_version_id"] = UNMASKED_SET

    prepared = preflight(world, document)
    [issue] = prepared.report.blocking
    assert (issue.rule, issue.path) == (UNSUPPORTED, "/set/motion_asset_version_id")


@pytest.mark.parametrize("identity", ["missing-set", "wrong-provenance", "ambiguous-still"])
def test_set_loop_with_unresolved_source_is_refused(tmp_path, identity):
    world, document, plate = role_world(tmp_path / "store")
    world.loop(f.SET_LOOP, 41, still_sha=plate["content"]["sha256"], clip=media.set_clip(f.SET_N),
               start=media.set_plate(), subject="set", frames=f.SET_N)
    loop = world.docs[-1]
    document["set"].update(asset_version_id=None, motion_asset_version_id=f.SET_LOOP)
    if identity == "missing-set":
        world.docs.remove(plate)
    elif identity == "wrong-provenance":
        loop["provenance"]["generator"]["source_asset_version_ids"] = [f.STILL["a"]]
    else:
        duplicate = deepcopy(plate)
        duplicate.update(id=f.ident("asv", 74), number=2)
        duplicate.pop("occlusion")
        world.docs.append(duplicate)

    prepared = preflight(world, document)
    [issue] = prepared.report.blocking
    assert (issue.rule, issue.path) == (SET_LOOP_SOURCE_UNKNOWN, "/set/motion_asset_version_id")


@pytest.mark.parametrize("path", ["layered_photo", "layered_cache", "whole_frame_cache", "set_loop_cache"])
def test_picture_plans_refuse_unrenderable_roles_before_any_lookup(tmp_path, path):
    from haynes_studio.build.pipeline import media_format
    from haynes_studio.cache import plan_story
    from haynes_studio.canonical import Story
    from haynes_studio.layered.errors import LayeredError
    from haynes_studio.photo.plan import plan_photo

    world, document, plate = role_world(tmp_path / "store")
    board = document["boards"][0]
    if path == "whole_frame_cache":
        board["method"]["layer"] = "whole_frame"
    elif path == "set_loop_cache":
        world.loop(f.SET_LOOP, 41, still_sha=plate["content"]["sha256"], clip=media.set_clip(f.SET_N),
                   start=media.set_plate(), subject="set", frames=f.SET_N)
        world.docs[-1]["provenance"]["generator"]["source_asset_version_ids"] = [f.PLATE]
        document["set"].update(asset_version_id=None, motion_asset_version_id=f.SET_LOOP)
    else:
        board["layout"]["foreground"] = False
    story = Story.from_document(document)
    library = world.library()
    with pytest.raises(LayeredError) as refused:
        if path == "layered_photo":
            plan_photo(story, story.boards[0], library)
        else:
            plan_story(story, voices={}, voice_ids={}, blobs={v.id: v.content.sha256
                       for v in library.versions.values() if v.content is not None},
                       library=library, toolchain=f.toolchain(), media=media_format(story.media_kind),
                       content=lambda _: pytest.fail("A rejected cache plan must not ask for content"))
    assert refused.value.code == (UNSUPPORTED if path in ("whole_frame_cache", "set_loop_cache")
                                  else FOREGROUND_REQUIRED)


@pytest.mark.parametrize("fault", ["missing-set", "mismatched-set-hash"])
def test_cache_plan_requires_the_selected_set_and_its_declared_still_hash(tmp_path, fault):
    from haynes_studio.build.pipeline import media_format
    from haynes_studio.cache import plan_story
    from haynes_studio.cache.errors import KEY_INPUT_INVALID, CacheError
    from haynes_studio.canonical import Story
    from haynes_studio.layered.errors import LayeredError

    world, document, plate = role_world(tmp_path / "store")
    blobs = {v.id: v.content.sha256 for v in world.library().versions.values() if v.content is not None}
    if fault == "missing-set":
        world.docs.remove(plate)
        error, code, where = CacheError, KEY_INPUT_INVALID, "/set/asset_version_id"
    else:
        blobs[f.PLATE] = "0" * 64
        error, code, where = LayeredError, MASK_STALE, "/set/occlusion"
    story = Story.from_document(document)
    with pytest.raises(error) as refused:
        plan_story(story, voices={}, voice_ids={}, blobs=blobs, library=world.library(),
                   toolchain=f.toolchain(), media=media_format(story.media_kind),
                   content=lambda _: pytest.fail("A rejected cache plan must not ask for content"))
    assert (refused.value.code, refused.value.where) == (code, where)


def test_whole_frame_photo_plan_requires_the_selected_set_version(tmp_path):
    from haynes_studio.canonical import Story
    from haynes_studio.photo.plan import plan_photo

    world, document, plate = role_world(tmp_path / "store")
    document["boards"][0]["method"]["layer"] = "whole_frame"
    world.docs.remove(plate)
    story = Story.from_document(document)
    with pytest.raises(ContractError) as refused:
        plan_photo(story, story.boards[0], world.library())
    [issue] = refused.value.violations
    assert (issue.rule, issue.path) == ("ref.unknown", "/set/asset_version_id")


def test_layered_local_cache_reuses_the_segment_with_the_mask_drawn(tmp_path):
    import numpy as np

    from haynes_studio.render.encode import decode_frames
    from tests.support.synthetic import write_sine_wav

    world, document, _ = role_world(tmp_path / "store", right=SOURCE[0])
    sound = f.example("asset-version-cast.json")
    sound_id = f.ident("asv", 76)
    audio = write_sine_wav(tmp_path / "bed.wav", seconds=2.5, rate=48000).read_bytes()
    blob = world.store.publish(audio, scope=f.PRODUCTION, media_type="audio/wav")
    sound.update(id=sound_id, asset_id=f.ident("ast", 76), kind="sound",
                 name="Synthetic bed", scope={"production_id": f.PRODUCTION},
                 labels=[], attributes={}, capabilities=["sound_bed"], legacy=None,
                 content={"sha256": blob.sha256, "bytes": blob.bytes, "locator": blob.locator,
                          "media_type": "audio/wav"})
    sound["provenance"].update(generator={"role": "sound", "engine": "Synthetic test sine"}, source_key=None)
    world.docs.append(sound)
    document["beds"] = [{"id": f.ident("cue", 1), "type": "bed", "asset_version_id": sound_id,
                         "level_rms_dbfs": -24, "clock": "film"}]
    document["boards"][0]["timing"]["hold_ms"] = 500

    library = world.library()
    previous = f.build(world, document, library, heard="")
    reused = f.build(world, document, library, heard="")
    assert previous.run["status"] == reused.run["status"] == "succeeded", reused.run["error"]
    segment = previous.plan.boards[0].segment
    assert segment == reused.plan.boards[0].segment
    assert segment.key.value in previous.made and segment.key.value not in reused.made
    with world.store.open(blob_locator(f.PRODUCTION, segment.content, "video/mp4")) as media:
        assert np.count_nonzero(next(decode_frames(media))) == 0


@pytest.mark.parametrize(("change", "code"), [
    ("foreground", FOREGROUND_REQUIRED),
    ("missing_pin", MASK_MISSING),
    ("missing_set", "ref.unknown"),
    ("mask_bytes", MASK_STALE),
    ("set_loop_only", UNSUPPORTED),
])
def test_local_run_writer_rejects_invalid_frozen_masks(tmp_path, change, code):
    world, document, plate = role_world(tmp_path / "store")
    library = world.library()
    snapshot, _ = freeze(preflight(world, document), studio="git:fixture")
    if change in ("foreground", "missing_set"):
        snapshot["story"]["boards"][0]["layout"]["foreground"] = False
        if change == "missing_set":
            library = Library.from_version_documents(doc for doc in world.docs if doc["id"] != f.PLATE)
    elif change == "missing_pin":
        snapshot["resolved_asset_versions"] = [item for item in snapshot["resolved_asset_versions"]
                                               if item["id"] != MASK]
    elif change == "set_loop_only":
        world.loop(f.SET_LOOP, 41, still_sha=plate["content"]["sha256"], clip=media.set_clip(f.SET_N),
                   start=media.set_plate(), subject="set", frames=f.SET_N)
        loop = world.docs[-1]
        loop["provenance"]["generator"]["source_asset_version_ids"] = [f.PLATE]
        snapshot["story"]["set"].update(asset_version_id=None, motion_asset_version_id=f.SET_LOOP)
        snapshot["resolved_asset_versions"].append({
            "id": f.SET_LOOP, "kind": "motion", "sha256": loop["content"]["sha256"],
        })
        library = world.library()
    else:
        mask = library.version(MASK).content
        replace_mask_bytes(world, mask.locator)
    data, digest = snapshot_bytes(snapshot)
    run_id = f.ident("run", 1)
    run = new_run(run_id=run_id, story_id=document["id"], number=1, phase="all", snapshot={
        "sha256": digest, "locator": blob_locator(f.PRODUCTION, digest, "application/json"),
        "story_revision": document["revision"], "board_count": len(document["boards"]),
    }, queued_by=f.OPERATOR, queued_at=f.NOW)
    records = RunRecords(world.store, f.PRODUCTION)
    with pytest.raises(ContractError) as refused:
        records.create(run, data, library=library)
    assert [issue.rule for issue in refused.value.violations] == [code]
    assert records.latest(run_id) is None
