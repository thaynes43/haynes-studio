"""Small synthetic motion records: JSON documents only, no media. Every block's keys
come from the identity function, so a fixture is valid until a test changes it."""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from typing import Any

from haynes_studio.library import Library
from haynes_studio.library.model import locator_for
from haynes_studio.motion.record import playback
from haynes_studio.motion.winter_menu import complete_block
from haynes_studio.store.base import MISMATCH, MISSING, PRESENT
from tests.canonical.fixtures import example

PRODUCTION = "prd_01M79V9FC00000000000000001"
NOW = "2026-11-13T07:00:00Z"
CREATED_BY = {"kind": "worker", "worker_id": "story 457 fixtures"}


def ident(prefix: str, n: int) -> str:
    return f"{prefix}_01M79V9FC0000000000000{n:04d}"


def sha(char: str) -> str:
    return char * 64


STILL_A = "4ea3005f4effebda7f4ce9b083da55e8529db4269c96104364e5dc74b25969de"  # cast example
STILL_B = sha("b")
SET_STILL = sha("5")
GREEN_A = sha("6")  # the green start image the engine animated
DRIVE = sha("d")


def unknown_licence() -> dict[str, Any]:
    return {"name": None, "url": None, "commercial_use": "unknown", "attribution_required": None,
            "checked_at": None, "checked_by": None, "note": "fixture"}


def loop_block(**changes: Any) -> dict[str, Any]:
    """A doll loop: 121 frames at 24 fps on green, keyed with a decal (E0's shape)."""
    block = {
        "use": "loop", "subject": "doll", "still_sha256": STILL_A, "frames": 121, "fps": 24,
        "width": 576, "height": 1024, "trim": {"start": 0, "frames": 121},
        "source": {"image_sha256": GREEN_A, "prompt": "a plastic doll bobs on green",
                   "negative_prompt": "extra dolls", "seed": 311,
                   "profile": {"model": "Wan2.2 TI2V-5B", "adapter": "studio.motion/1",
                               "length": 121, "fps": 24},
                   "engine_job_id": "job-311"},
        "keying": {"keyer": "studio.keyer/1", "key_thresholds": {"lo": 20, "hi": 70},
                   "protect_boxes": [[240, 400, 440, 600]], "decal_box": [266, 699, 453, 779],
                   "decal_version": "erase-v2", "decal_min_ecc": 0.8},
    }
    block.update(changes)
    return block


def set_block(**changes: Any) -> dict[str, Any]:
    block = loop_block(subject="set", still_sha256=SET_STILL)
    del block["keying"]
    block["source"] = {**block["source"], "image_sha256": SET_STILL, "prompt": "an empty campsite",
                       "seed": 301}
    block.update(changes)
    return block


def timed_block(**changes: Any) -> dict[str, Any]:
    """A speech-to-video clip for a 153-frame board: 158 frames at 16 fps, 102 used."""
    block = loop_block(use="timed", frames=158, fps=16, trim={"start": 0, "frames": 102},
                       drive_track={"sha256": DRIVE, "board_frames": 153})
    block["source"] = {**block["source"], "adapter": "studio.s2v/1", "seed": 510,
                       "profile": {"model": "Wan2.2 S2V-14B", "steps": 4, "cfg": 1, "fps": 16}}
    block.update(changes)
    return block


def version(block: Mapping[str, Any] | None, *, n: int, clip: str, asset: int | None = None,
            number: int = 1, state: str = "promoted", capabilities: Iterable[str] | None = None,
            keys: bool = True, source_key: str | None = None) -> dict[str, Any]:
    """A ``studio.asset-version/v1`` motion document (``block`` None: no motion block)."""
    subject = (block or {}).get("subject", "doll")
    caps = list(capabilities) if capabilities is not None else (
        ["set_loop"] if subject == "set" else ["motion_clip"])
    doc = {
        "schema": "studio.asset-version/v1", "id": ident("asv", n),
        "asset_id": ident("ast", asset if asset is not None else n), "number": number,
        "kind": "motion", "name": f"clip {n}", "scope": {"production_id": PRODUCTION},
        "state": state, "labels": [], "attributes": {}, "capabilities": caps,
        "content": {"sha256": clip, "bytes": 1000 + n, "media_type": "video/mp4",
                    "locator": locator_for(clip, "video/mp4", PRODUCTION)},
        "provenance": {"origin": "generated",
                       "generator": {"role": "video", "model": "Wan2.2 TI2V-5B"},
                       "external": None, "source_key": source_key,
                       "created_by": CREATED_BY, "created_at": NOW},
        "licence": unknown_licence(), "legacy": None,
    }
    if block is not None:
        doc["motion"] = complete_block(block, clip) if keys else placeholder(block)
    return doc


def placeholder(block: Mapping[str, Any]) -> dict[str, Any]:
    """``block`` with its playback and with zero keys, for inputs no key accepts."""
    out = copy.deepcopy(dict(block))
    out["playback"] = playback(out["use"], out["trim"]["frames"])
    out["keys"] = {"clip": "sha256:" + "0" * 64, "identity": "sha256:" + "0" * 64}
    if "keying" in out:
        out["keys"]["keyed"] = "sha256:" + "0" * 64
    return out


def still_version(n: int, still: str, *, kind: str = "cast") -> dict[str, Any]:
    """A cast still (or a set plate) with bytes ``still``."""
    doc = example("valid/asset-version-cast.json")
    doc["id"], doc["asset_id"] = ident("asv", n), ident("ast", n)
    doc["content"]["sha256"] = still
    doc["content"]["locator"] = locator_for(still, "image/png", PRODUCTION)
    doc["provenance"]["source_key"] = doc["legacy"]["source_key"] = f"fixture:still-{n}"
    if kind == "set":
        doc.update(kind="set", capabilities=["opaque_plate"], attributes={}, labels=[])
    return doc


CAST_A, CAST_B, SET_PLATE = 1, 2, 3  # still version numbers in :func:`library`


def library(*motion_docs: Mapping[str, Any]) -> Library:
    """The three stills plus the given motion versions."""
    stills = [still_version(CAST_A, STILL_A), still_version(CAST_B, STILL_B),
              still_version(SET_PLATE, SET_STILL, kind="set")]
    return Library.from_version_documents([*stills, *motion_docs])


def board(*cast: Mapping[str, Any], layer: str = "layered", motion: str = "i2v",
          lines: Iterable[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """The fields of a ``studio.board/v1`` document the resolver reads."""
    return {"schema": "studio.board/v1", "id": ident("brd", 1),
            "method": {"layer": layer, "motion": motion}, "cast": [dict(c) for c in cast],
            "lines": [dict(line) for line in lines]}


def entry(slot: str = "a", still: int = CAST_A, pin: int | None = None) -> dict[str, Any]:
    out = {"slot": slot, "asset_version_id": ident("asv", still)}
    if pin is not None:
        out["motion_asset_version_id"] = ident("asv", pin)
    return out


def story(*boards: Mapping[str, Any], set_pin: int | None = None,
          set_plate: int | None = SET_PLATE) -> dict[str, Any]:
    return {"schema": "studio.story/v1", "production_id": PRODUCTION,
            "set": {"asset_version_id": None if set_plate is None else ident("asv", set_plate),
                    "motion_asset_version_id": None if set_pin is None else ident("asv", set_pin)},
            "boards": [dict(b) for b in boards]}


class Verify:
    """A synthetic ``Store.verify``: every pair is present unless named missing or
    mismatched; records each question."""

    def __init__(self, missing: Iterable[str] = (), mismatch: Iterable[str] = ()):
        self.missing, self.mismatch = set(missing), set(mismatch)
        self.asked: list[tuple[str, str]] = []

    def __call__(self, locator: str, sha256: str) -> str:
        self.asked.append((locator, sha256))
        if sha256 in self.missing:
            return MISSING
        if sha256 in self.mismatch:
            return MISMATCH
        return PRESENT
