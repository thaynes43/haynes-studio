"""The build preflight and freeze use the same role declarations as the renderer."""

import pytest
from PIL import Image

from haynes_studio.build import BuildInputs, build_story
from haynes_studio.build.prebuild import make_snapshot, prepare, snapshot_bytes
from haynes_studio.build.run import RunRecords, local_run_ids, new_run
from haynes_studio.errors import ContractError
from haynes_studio.layered.foreground import (
    FOREGROUND_REQUIRED, MASK_INVALID, MASK_MISSING, MASK_NOT_READY, MASK_SIZE, MASK_STALE, UNSUPPORTED,
)
from haynes_studio.library import Library
from haynes_studio.queue.inputs import freeze
from haynes_studio.stages.preflight import PreflightError
from haynes_studio.store import blob_locator
from tests.build_story import fixtures as f
from tests.layered import media
from tests.layered.test_foreground_roles import RED_BOX, SIZE, png

MASK = f.ident("asv", 70)
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
        mask["scope"]["production_id"] = production
        mask["content"]["locator"] = blob_locator(production, pin["sha256"], "image/png")
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


@pytest.mark.parametrize(("change", "code"), [
    ("foreground", FOREGROUND_REQUIRED),
    ("missing_pin", MASK_MISSING),
    ("mask_bytes", MASK_STALE),
])
def test_local_run_writer_rejects_invalid_frozen_masks(tmp_path, change, code):
    world, document, _ = role_world(tmp_path / "store")
    library = world.library()
    snapshot, _ = freeze(preflight(world, document), studio="git:fixture")
    if change == "foreground":
        snapshot["story"]["boards"][0]["layout"]["foreground"] = False
    elif change == "missing_pin":
        snapshot["resolved_asset_versions"] = [item for item in snapshot["resolved_asset_versions"]
                                               if item["id"] != MASK]
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
