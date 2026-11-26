"""The build preflight and freeze use the same role declarations as the renderer."""

import pytest
from PIL import Image

from haynes_studio.build import BuildInputs, build_story
from haynes_studio.build.prebuild import make_snapshot, prepare
from haynes_studio.layered import visibility
from haynes_studio.layered.foreground import MASK_INVALID, MASK_MISSING, MASK_NOT_READY, MASK_SIZE, MASK_STALE
from haynes_studio.library import Library
from haynes_studio.queue.inputs import freeze
from tests.build_story import fixtures as f
from tests.layered import media
from tests.layered.test_foreground_roles import BOX, SIZE, png

MASK = f.ident("asv", 70)
FRAME = (1080, 1920)
SOURCE = (108, 192)


def role_world(root, *, right=38, order=30, mask_size=SOURCE):
    root.mkdir()
    world = f.World(root, f.LocalStore(root))
    a = Image.new("RGBA", SIZE)
    a.paste((255, 0, 0, 255), BOX)
    still = world.still(f.STILL["a"], 10, png(a))
    world.docs[-1]["content"].update(width=SIZE[0], height=SIZE[1])
    world.loop(f.LOOP["a"], 20, still_sha=still, clip=media.doll_clip(f.LOOP_N, moving=False),
               start=media.start_image(tint=0))
    world.voice(f.VOICE["a"], 30, f.STOCK["a"])
    plate = world.still(f.PLATE, 40, png(Image.new("RGB", SOURCE)), kind="set")
    set_doc = world.docs[-1]
    set_doc["content"].update(width=SOURCE[0], height=SOURCE[1])
    mask = Image.new("L", mask_size)
    mask.paste(255, (0, 0, right, mask_size[1]))
    mask_sha = world.still(MASK, 70, png(mask))
    world.docs[-1].update(kind="prop", capabilities=["mask"], attributes={})
    world.docs[-1]["content"].update(width=mask_size[0], height=mask_size[1])
    set_doc["occlusion"] = {"foreground": [{
        "key": "table", "layer_order": order,
        "mask": {"version_id": MASK, "sha256": mask_sha, "still_sha256": plate},
    }]}
    template = f.story_document()
    board = next(b for b in template["boards"] if b["id"] == f.B2)
    board["cast"] = [{"slot": "a", "asset_version_id": f.STILL["a"], "motion_asset_version_id": f.LOOP["a"]}]
    board["timing"]["hold_ms"] = 125
    board["layout"]["check_poses"] = [{"key": "face", "frame": 0,
                                       "targets": [{"slot": "a", "box_xyxy": list(BOX)}]}]
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


@pytest.mark.parametrize(("change", "code"), [
    ("missing_version", MASK_MISSING),
    ("missing_bytes", MASK_MISSING),
    ("wrong_hash", MASK_STALE),
    ("wrong_still", MASK_STALE),
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
    elif change == "wrong_still":
        pin["still_sha256"] = "a" * 64
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


def test_frozen_library_and_snapshot_pin_the_exact_mask_version(tmp_path):
    world, document, plate = role_world(tmp_path / "store", order=5)
    prepared = preflight(world, document)
    assert prepared.ok, prepared.report.problems
    assert prepared.visibility_evidence[0]["status"] == "visible"
    frozen, library = freeze(prepared, studio="git:fixture")
    pin = plate["occlusion"]["foreground"][0]["mask"]
    assert {"id": MASK, "kind": "prop", "sha256": pin["sha256"]} in frozen["resolved_asset_versions"]
    set_pin = next(entry for entry in frozen["resolved_asset_versions"] if entry["id"] == f.PLATE)
    assert set_pin["occlusion_signature"] == world.library().pin(f.PLATE)
    assert {entry["id"] for entry in library} == {entry["id"] for entry in frozen["resolved_asset_versions"]}
    assert next(doc for doc in library if doc["id"] == f.PLATE)["occlusion"] == plate["occlusion"]
    assert Library.from_version_documents(library).version(MASK).content.sha256 == pin["sha256"]
    assert make_snapshot(prepared, world.library(), studio="git:fixture") == frozen


def test_role_declared_set_checks_cast_without_a_board_declaration(tmp_path):
    world, document, _ = role_world(tmp_path / "store", right=70)
    document["boards"][0]["layout"].pop("check_poses")
    prepared = preflight(world, document)
    [evidence] = prepared.visibility_evidence
    assert evidence["target"] == {"slot": "a"} and evidence["status"] == "hidden"
    assert [p.rule for p in prepared.report.blocking] == [visibility.HIDDEN]


def test_hidden_stops_build_before_clips_even_with_the_artifact_in_approvals(tmp_path):
    world, document, _ = role_world(tmp_path / "store", right=70)
    prepared = preflight(world, document)
    [evidence] = prepared.visibility_evidence
    assert evidence["status"] == "hidden"
    inputs = BuildInputs(document, world.library(), f.register(), f.toolchain(),
                         visibility_overrides=(evidence["artifact"],))
    result = build_story(inputs, store=world.store, phase="all", sources=f.sources(),
                         transcriber=None, actor=f.OPERATOR)
    assert result.run["error"]["code"] == visibility.HIDDEN
    assert result.source_calls == 0
    assert result.run["checks"] == visibility.run_checks([evidence])


def test_uncertain_requires_exact_evidence_and_an_override_changes_the_run_check(tmp_path):
    world, document, _ = role_world(tmp_path / "store")
    prepared = preflight(world, document)
    [evidence] = prepared.visibility_evidence
    assert [p.rule for p in prepared.report.blocking] == [visibility.REVIEW]
    assert evidence["status"] == "uncertain"
    assert visibility.reviewable(evidence, evidence["artifact"])
    approved = preflight(world, document, visibility_overrides=(evidence["artifact"],))
    assert approved.ok
    [check] = visibility.run_checks(approved.visibility_evidence, [evidence["artifact"]])
    assert check["result"] == "overridden"
    document["boards"][0]["revision"] += 1
    changed = preflight(world, document, visibility_overrides=(evidence["artifact"],))
    assert [p.rule for p in changed.report.blocking] == [visibility.REVIEW]
    assert changed.visibility_evidence[0]["artifact"] != evidence["artifact"]


def test_explicit_disabled_foreground_still_validates_pins_and_measures_the_photo(tmp_path):
    world, document, _ = role_world(tmp_path / "store", right=70)
    document["boards"][0]["layout"]["foreground"] = False
    prepared = preflight(world, document)
    assert prepared.ok
    [evidence] = prepared.visibility_evidence
    assert evidence["status"] == "visible"
    assert prepared.foreground_roles[0].version_id == MASK


def test_unsupported_declared_targets_stop_before_measurement(tmp_path):
    world, document, plate = role_world(tmp_path / "store")
    document["boards"][0]["layout"]["check_poses"][0]["frame"] = 1
    prepared = preflight(world, document)
    assert [p.rule for p in prepared.report.blocking] == ["occlusion.unsupported"]
    assert prepared.visibility_evidence == ()
    document["boards"][0]["layout"]["check_poses"][0]["frame"] = 0
    plate["occlusion"]["focal_props"] = [{"key": "menu", "label": "menu", "depth": "background",
                                         "layer_order": 0}]
    prepared = preflight(world, document)
    assert [p.rule for p in prepared.report.blocking] == ["occlusion.unsupported"]
    assert prepared.visibility_evidence == ()
