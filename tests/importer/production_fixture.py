"""Synthetic examples of the story 942 flat archive layouts."""

from dataclasses import dataclass
import hashlib
from pathlib import Path

from haynes_studio.build.run import advance, new_run
from haynes_studio.canonical.ids import Minter
from haynes_studio.delivery.model import MASTER_SIZES, PROXY_SIZES, proxy_byte_limit
from haynes_studio.store import Blob, StageRecord, blob_locator, canonical_json
from tests.build_story.fixtures import NOW, OPERATOR, example
from tests.delivery.media import write_master

FRAMES = 3
KIND = "short"
NAME = "Fixture short"


def facts(path):
    data = path.read_bytes()
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


@dataclass
class FixtureArchive:
    root: Path
    receipt: Path
    name: str
    production_id: str
    run: dict
    delivery_id: str
    snapshot: dict
    asset: dict
    recovered: bool
    shared_asset: dict | None

    def args(self):
        args = ["import-production", str(self.root), "--receipt", str(self.receipt),
                "--name", self.name, "--media-type", KIND]
        return args + (["--recovered"] if self.recovered else [])

    def files(self):
        return {path.name: facts(path) for path in self.root.iterdir()}


def make_archive(parent, *, recovered=False, production_id=None, story_id=None, delivery_id=None,
                 board_id=None, note_id=None, story_source_key=None, board_source_key=None,
                 asset_id=None, asset_version_id=None, asset_source_key=None, with_shared_asset=False,
                 board_creator=None):
    parent.mkdir(exist_ok=True)
    archive = parent / ("recovered-cut" if recovered else "canonical-cut")
    archive.mkdir()

    def write(name, value):
        path = archive / name
        path.write_bytes(canonical_json(value))
        return path

    ids = Minter()
    production_id = production_id or ids.mint("prd")
    story_id = story_id or ids.mint("sty")
    board_id = board_id or ids.mint("brd")
    name = f"{NAME} {production_id}"
    run_id = ids.mint("run")
    delivery_id = delivery_id or ids.mint("dlv")
    asset = example("asset-version-photo-external.json")
    asset.update(id=asset_version_id or ids.mint("asv"), asset_id=asset_id or ids.mint("ast"), scope={
        "production_id": production_id, "story_id": story_id, "board_id": board_id,
    })
    content = asset["content"]
    content["locator"] = blob_locator(production_id, content["sha256"], content["media_type"])
    asset["provenance"]["generator"]["source_asset_version_ids"] = []
    if asset_source_key is not None:
        asset["provenance"]["source_key"] = asset_source_key
    shared_asset = None
    if with_shared_asset:
        shared_asset = example("asset-version-cast.json")
        shared_asset.update(id=ids.mint("asv"), asset_id=ids.mint("ast"), scope={"production_id": None})
        content = shared_asset["content"]
        content["locator"] = blob_locator("library", content["sha256"], content["media_type"])
    versions = [asset, shared_asset] if shared_asset is not None else [asset]
    story = example("story-winter-menu-r4.json")
    story.pop("derived", None)
    board = story["boards"][0]
    story_origin = {**story["origin"], "source_key": story_source_key} if story_source_key else None
    board_origin = {**board["origin"], "source_key": board_source_key} if board_source_key else None
    board.pop("derived", None)
    board.update(id=board_id, story_id=story_id, title="Synthetic board", lines=[], origin=board_origin,
                 notes=[{"id": note_id, "text": "Synthetic note"}] if note_id else [],
                 timing={"lead_ms": None, "tail_ms": None, "hold_ms": 125},
                 voice={"style": None, "current_version_id": None},
                 photo={"current_version_id": asset["id"], "prompt": None,
                        "input_asset_version_ids": [shared_asset["id"]] if shared_asset else []},
                 cast=[], layout={"preset": "default", "foreground": False},
                 method={"layer": "whole_frame", "motion": "i2v"}, seeds={"i2v:frame": 1})
    if board_creator is not None:
        board.update(created_by=board_creator, drafted_by=board_creator)
    story.update(id=story_id, production_id=production_id, origin=story_origin, board_order=[board_id],
                 boards=[board], cast=[], narrator_voice_version_id=None, set=None, beds=[],
                 layouts={"default": {}}, motion_style=None, title=name)
    snapshot = {
        "schema": "studio.run-snapshot/v1", "story": story,
        "resolved_asset_versions": [
            {"id": version["id"], "kind": version["kind"], "sha256": version["content"]["sha256"]}
            for version in versions
        ],
        "toolchain_request": {"studio": "git:fixture"},
    }
    snapshot_hash = hashlib.sha256(canonical_json(snapshot)).hexdigest()
    run = new_run(run_id=run_id, story_id=story_id, number=4, snapshot={
        "sha256": snapshot_hash, "story_revision": story["revision"], "board_count": 1,
        "locator": blob_locator(production_id, snapshot_hash, "application/json"),
    }, queued_by=OPERATOR, queued_at=NOW, phase="all")
    run = advance(run, "running", at=NOW, by=OPERATOR, reason="Fixture render")
    blobs, records = {}, {}
    for role, filename, size in (("master", "final.mp4", MASTER_SIZES[KIND]),
                                ("proxy", "proxy.mp4", PROXY_SIZES[KIND])):
        width, height = size
        path = write_master(archive / filename, frames=FRAMES, width=width, height=height)
        records[role] = facts(path)
        blobs[role] = Blob(**records[role], media_type="video/mp4",
                           locator=blob_locator(production_id, records[role]["sha256"], "video/mp4"))
    outputs = {f"{role}_sha256": media["sha256"] for role, media in records.items()}
    run = advance(run, "succeeded", at=NOW, by=OPERATOR, reason="Fixture delivery",
                  delivery_id=delivery_id, progress={"stage": "delivered", "percent": 100},
                  checks=[{"check": "frame_count", "result": "pass", "actual": FRAMES, "expected": FRAMES}],
                  outputs={**outputs, "fps": 24, "frames": FRAMES},
                  provenance={"toolchain": {"studio": "git:fixture"}, "engines": [], "usage": None,
                              "inputs_externally_generated": [], "public": {"ai_generated": True, "credits": []}})
    write("run.json", run)
    if recovered:
        write("delivery.json", {
            "schema": "studio.recovered-delivery/proposal", "is_original_delivery_document": False,
            "run_id": run_id, "delivery_id": delivery_id, "frames": FRAMES, "fps": 24, **records,
        })
        write("ledger.json", {
            "id": "a" * 32, "kind": "edited_production", "state": "succeeded", "title": name,
            "story": "fixture", "preset": "studio-private-view", "created_at": 1795277519,
            "finished_at": 1795277520, "output": f"productions/{archive.name}/proxy.mp4",
            **records["proxy"], "assets": [], "telemetry": {}, "provenance": {
                "production_id": production_id, "story_id": story_id, "run_id": run_id,
                "delivery_id": delivery_id, "plays": "proxy", **outputs,
            },
        })
    else:
        delivery = {
            "schema": "studio.delivery/v1", "id": delivery_id, "run_id": run_id, "created_at": NOW,
            "store": {"adapter": "local", "writable": True},
            "verification": {"decoded_frames": FRAMES, "expected_frames": FRAMES, "sha256_verified": True,
                             "proxy_under_bytes": proxy_byte_limit(FRAMES)},
            "legacy": None,
        }
        for role, sizes in (("master", MASTER_SIZES), ("proxy", PROXY_SIZES)):
            width, height = sizes[KIND]
            delivery[role] = {**blobs[role].to_document(), "width": width, "height": height,
                              "fps": 24, "frames": FRAMES, "video_codec": "h264", "audio_codec": "aac",
                              "legacy_path": None}
        record = facts(write("delivery.json", delivery))
        blobs["delivery"] = Blob(**record, media_type="application/json",
                                 locator=blob_locator(production_id, record["sha256"], "application/json"))
        write("delivery-stage.json", StageRecord(production_id, run_id, "delivery", blobs).to_document())
        write("snapshot.json", snapshot)
        write("asset-versions.json", versions)
        write("transcript-run.json", {"fixture": "transcript-run"})
        write("wan-clip.json", {"fixture": "wan-clip"})
        write("wan-service-run.json", {"fixture": "wan-service-run"})
    fixture = FixtureArchive(archive, parent / "receipt.json", name, production_id, run, delivery_id,
                             snapshot, asset, recovered, shared_asset)
    fixture.receipt.write_bytes(canonical_json(fixture.files()))
    return fixture
