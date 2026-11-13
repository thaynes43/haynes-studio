"""The build fixture (story 406): a store holding synthetic media, a library over it,
and a story with one board of each buildable method:

- B1 layered speech-to-video: ``a`` speaks one line, ``b`` idles;
- B2 layered image-to-video: ``a`` and ``b`` idle (silent, 500 ms);
- B3 whole-frame image-to-video from an externally generated photo (silent, 500 ms).

Everything is made in memory at test time and published under ``tmp_path``: doll and
set loops from :mod:`tests.layered.media`, the board photo as a small PNG, the voices
by story 425's Kokoro client behind its fake runner. Clips come from the adapters'
fake sources and the transcript from the Whisper client behind its fake runner. The
master is a ``short`` (1080x1920, contract section 8), so the film is kept to 41 frames.
"""

from __future__ import annotations

import copy
import hashlib
import io
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np
import PIL.Image

from haynes_studio.adapters.fakes import FakeKokoro, FakeRunner, FakeWhisper
from haynes_studio.adapters.kokoro import KokoroClient
from haynes_studio.adapters.whisper import WhisperClient
from haynes_studio.build import (
    BuildInputs,
    ClipSources,
    WhisperTranscriber,
    build_story,
    local_run_ids,
    make_story_voices,
)
from haynes_studio.cache.plan import Toolchain
from haynes_studio.canonical.ids import Minter
from haynes_studio.jsonio import read_json
from haynes_studio.layered import FakeS2VSource
from haynes_studio.library import Library
from haynes_studio.library.model import locator_for
from haynes_studio.motion.winter_menu import complete_block
from haynes_studio.store import LocalStore
from haynes_studio.wholeframe.fake import FakeClipSource
from tests.layered import media
from tests.motion import fixtures as mf
from tests.support.policy import REPO_ROOT

EXAMPLES = REPO_ROOT / "docs" / "contracts" / "examples" / "valid"
REGISTER = REPO_ROOT / "docs" / "reference" / "model-licences.json"
NOW = "2026-11-13T21:00:00Z"
OPERATOR = {"kind": "cli", "command": "studio build",
            "operator": {"kind": "human",
                         "iss": "https://authentik.example.invalid/application/o/haynes-studio/",
                         "sub": "example-subject-build"}}
LOOP_N, SET_N = 13, 9


def ident(prefix: str, number: int) -> str:
    """A fixed, valid ``<prefix>_<ULID>`` for the fixture."""
    return f"{prefix}_01JB406{number:019d}"


PRODUCTION, STORY = ident("prd", 1), ident("sty", 1)
B1, B2, B3 = ident("brd", 1), ident("brd", 2), ident("brd", 3)
L1 = ident("lin", 1)
STILL = {"a": ident("asv", 1), "b": ident("asv", 2)}
LOOP = {"a": ident("asv", 3), "b": ident("asv", 4)}
PLATE, SET_LOOP, PHOTO = ident("asv", 5), ident("asv", 6), ident("asv", 7)
VOICE = {"a": ident("asv", 8), "b": ident("asv", 9)}
STOCK = {"a": "af_heart", "b": "bf_emma"}
TINT = {"a": 0, "b": 60}
SCRIPT = "Go, team two."
HEARD = "go team 2"  # the recognizer writes the number as a digit; the story tolerates it
S2V_PROFILE = {"model": "wan2.2-s2v-14b-fp8", "lora": "lightx2v-4step", "steps": 4, "cfg": 1,
               "size": [media.CLIP_W, media.CLIP_H], "chunk": 77, "source_fps": 16}
KEYING = {"keyer": "legacy:poc/cutout.py key", "key_thresholds": {"lo": 20, "hi": 70},
          "protect_boxes": [list(media.PROTECT)], "decal_box": list(media.DECAL_BOX),
          "decal_version": "erase-v2"}


def toolchain() -> Toolchain:
    """Small clips: speech-to-video and image-to-video at 144x256 (9:16), 25-frame
    image-to-video clips (4 x 6 + 1)."""
    tools = Toolchain()
    return replace(tools, s2v_profile=S2V_PROFILE, i2v_clip_frames=25,
                   i2v_profile={**tools.i2v_profile, "size": [media.CLIP_W, media.CLIP_H]})


def png(rgb: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    PIL.Image.fromarray(np.ascontiguousarray(rgb)).save(buffer, format="PNG")
    return buffer.getvalue()


def photo_png(shade: int = 90) -> bytes:
    """The whole-frame board's photo: a 144x256 gradient (the fake source never decodes
    it; its hash is the clip's input)."""
    frame = np.zeros((256, 144, 3), np.uint8)
    frame[..., 0] = np.linspace(40, 200, 256, dtype=np.uint8)[:, None]
    frame[..., 1] = shade
    frame[..., 2] = 120
    return png(frame)


def s2v_draw(n: int, start: np.ndarray) -> np.ndarray:
    return media.doll_frame(n, garble=True)


def example(name: str) -> dict[str, Any]:
    return read_json(EXAMPLES / name).document


def _scoped(doc: dict[str, Any], version_id: str, asset: int, *, number: int = 1) -> dict[str, Any]:
    doc["id"], doc["asset_id"], doc["number"] = version_id, ident("ast", asset), number
    doc["scope"] = {"production_id": PRODUCTION}
    content = doc.get("content")
    if content is not None:
        content["locator"] = locator_for(content["sha256"], content["media_type"], PRODUCTION)
    doc["provenance"]["source_key"] = f"fixture:build:{version_id}"
    if doc.get("legacy"):
        doc["legacy"]["source_key"] = doc["provenance"]["source_key"]
    return doc


@dataclass
class World:
    """A store with the library's media published, and the library's documents."""

    root: Path
    store: LocalStore
    docs: list[dict[str, Any]] = field(default_factory=list)

    def publish(self, data: bytes, media_type: str) -> str:
        return self.store.publish(data, scope=PRODUCTION, media_type=media_type).sha256

    def library(self, *extra: dict[str, Any], without: frozenset[str] = frozenset()) -> Library:
        return Library.from_version_documents(
            [*(d for d in self.docs if d["id"] not in without), *extra])

    def still(self, version_id: str, asset: int, data: bytes, *, kind: str = "cast") -> str:
        sha = self.publish(data, "image/png")
        doc = _scoped(mf.still_version(1, sha, kind=kind), version_id, asset)
        doc["content"]["bytes"] = len(data)
        self.docs.append(doc)
        return sha

    def loop(self, version_id: str, asset: int, *, still_sha: str, clip: bytes, start: bytes,
             subject: str = "doll", frames: int = LOOP_N) -> None:
        clip_sha, start_sha = self.publish(clip, "video/mp4"), self.publish(start, "image/png")
        block = mf.loop_block(still_sha256=still_sha, frames=frames, width=media.CLIP_W,
                              height=media.CLIP_H, trim={"start": 0, "frames": frames})
        block["source"] = {**block["source"], "image_sha256": start_sha}
        if subject == "set":
            block["subject"] = "set"
            block["width"], block["height"] = 180, 320
            del block["keying"]
        else:
            block["keying"] = dict(KEYING)
        doc = mf.version(None, n=1, clip=clip_sha)
        doc["motion"] = complete_block(block, clip_sha)
        doc["capabilities"] = ["set_loop"] if subject == "set" else ["motion_clip"]
        doc["content"]["bytes"] = len(clip)
        self.docs.append(_scoped(doc, version_id, asset))

    def voice(self, version_id: str, asset: int, voice_id: str) -> None:
        doc = {
            "schema": "studio.asset-version/v1", "id": version_id, "asset_id": ident("ast", asset),
            "number": 1, "kind": "voice", "name": f"{voice_id} (Kokoro stock voice)",
            "scope": {"production_id": None}, "state": "promoted", "labels": ["stock-voice"],
            "attributes": {"voice_id": voice_id, "stock": True}, "capabilities": ["tts_voice"],
            "content": None,
            "provenance": {"origin": "declared",
                           "generator": {"role": "voice", "engine": "ai/deploy/kokoro (Kokoro-82M v1.0, Wyoming)",
                                         "model": "Kokoro-82M v1.0", "voice_id": voice_id},
                           "external": None, "source_key": f"fixture:build:voice:{voice_id}",
                           "created_by": OPERATOR, "created_at": NOW},
            "licence": copy.deepcopy(example("asset-version-cast.json")["licence"]),
            "legacy": None}
        self.docs.append(doc)

    def photo(self, version_id: str, asset: int, data: bytes, *, board_id: str = B3,
              number: int = 1) -> str:
        sha = self.publish(data, "image/png")
        doc = example("asset-version-photo-external.json")
        doc["id"], doc["asset_id"], doc["number"] = version_id, ident("ast", asset), number
        doc["scope"] = {"production_id": PRODUCTION, "story_id": STORY, "board_id": board_id}
        doc["content"].update(sha256=sha, bytes=len(data), width=144, height=256,
                              locator=locator_for(sha, "image/png", PRODUCTION))
        doc["provenance"]["generator"]["source_asset_version_ids"] = []
        self.docs.append(doc)
        return sha


def make_world(path: Path) -> World:
    path.mkdir(parents=True)
    world = World(path, LocalStore(path))
    for i, slot in enumerate("ab"):
        colour = ((200, 60, 60), (60, 200, 60))[i]
        still_sha = world.still(STILL[slot], 10 + i, media.cutout(colour))
        world.loop(LOOP[slot], 20 + i, still_sha=still_sha,
                   clip=media.doll_clip(LOOP_N, moving=False, tint=TINT[slot]),
                   start=media.start_image(tint=TINT[slot]))
        world.voice(VOICE[slot], 30 + i, STOCK[slot])
    plate_sha = world.still(PLATE, 40, media.set_plate(), kind="set")
    world.loop(SET_LOOP, 41, still_sha=plate_sha, clip=media.set_clip(SET_N),
               start=media.set_plate(), subject="set", frames=SET_N)
    world.photo(PHOTO, 50, photo_png())
    return world


def _board(board_id: str, number: int, **fields: Any) -> dict[str, Any]:
    board = {
        "schema": "studio.board/v1", "id": board_id, "story_id": STORY, "number": number,
        "revision": 1, "title": f"Board {number}", "lines": [],
        "timing": {"lead_ms": None, "tail_ms": None, "hold_ms": 500},
        "voice": {"style": None, "current_version_id": None},
        "photo": {"current_version_id": None, "prompt": None, "input_asset_version_ids": []},
        "cast": [], "layout": {"preset": "pair", "foreground": True},
        "method": {"layer": "layered", "motion": "i2v"}, "seeds": {}, "cues": [], "notes": [],
        "drafted_by": OPERATOR["operator"], "origin": None}
    board.update(fields)
    return board


def story_document() -> dict[str, Any]:
    """The draft: three boards, one per buildable method, no voice made yet."""
    cast = [{"slot": "a", "asset_version_id": STILL["a"]}, {"slot": "b", "asset_version_id": STILL["b"]}]
    b1 = _board(B1, 1, lines=[{"id": L1, "speaker": "a", "text": SCRIPT, "gap_before_ms": None}],
                timing={"lead_ms": 200, "tail_ms": 340, "hold_ms": None},
                voice={"style": "cast", "current_version_id": None}, cast=copy.deepcopy(cast),
                method={"layer": "layered", "motion": "s2v"}, seeds={"s2v:a": 11})
    b2 = _board(B2, 2, cast=copy.deepcopy(cast))
    b3 = _board(B3, 3, layout={"preset": "single", "foreground": False},
                method={"layer": "whole_frame", "motion": "i2v"}, seeds={"i2v:frame": 31},
                photo={"current_version_id": PHOTO, "prompt": "a wide shot of the set",
                       "input_asset_version_ids": []})
    return {
        "schema": "studio.story/v1", "id": STORY, "production_id": PRODUCTION, "media_kind": "short",
        "title": "Build fixture", "revision": 1, "format_version_id": None,
        "cast": [{"slot": "a", "name": "captain", "voice_version_id": VOICE["a"]},
                 {"slot": "b", "name": "chair", "voice_version_id": VOICE["b"]}],
        "narrator_voice_version_id": None,
        "set": {"asset_version_id": PLATE, "motion_asset_version_id": SET_LOOP,
                "foreground_edge_px": [[0, 1700], [1080, 1760]], "foreground_feather_px": 20,
                "legacy_fire": None},
        "layouts": {"single": {"height": 900, "x": 0.5, "bottom": 1800},
                    "pair": {"slots": {"a": {"x": 0.3, "height": 700, "bottom": 1700},
                                       "b": {"x": 0.7, "height": 700, "bottom": 1700}}}},
        "motion_style": {"idle_scale": 0.3, "talk_hop": 34, "talk_tilt": 3.2, "talk_shuffle": 7},
        "mix": {"line_rms_dbfs": -22, "master_lufs": -20, "true_peak_dbtp": -3.5},
        "beds": [], "checks": {"asr_tolerances": {"2": "two"}},
        "board_order": [B1, B2, B3], "boards": [b1, b2, b3], "origin": None,
    }


def register() -> dict[str, Any]:
    return read_json(REGISTER).document


def kokoro() -> tuple[KokoroClient, FakeRunner]:
    runner = FakeRunner(FakeKokoro())
    return KokoroClient(runner), runner


def transcriber(heard: str = HEARD) -> tuple[WhisperTranscriber, FakeWhisper]:
    whisper = FakeWhisper(default=heard)
    return WhisperTranscriber(WhisperClient(FakeRunner(whisper))), whisper


def sources() -> ClipSources:
    return ClipSources(s2v=FakeS2VSource(draw=s2v_draw, extra=4), i2v=FakeClipSource())


def voiced(world: World, document: dict[str, Any] | None = None) -> tuple[dict[str, Any], Library]:
    """The draft with every spoken board's voice made (``studio voice``)."""
    client, _ = kokoro()
    result = make_story_voices(document or story_document(), world.library(), store=world.store,
                               speech=client, by=OPERATOR, now=NOW,
                               minter=Minter(clock=lambda: 1_800_000_000_000, random_bits=lambda: 5))
    assert result.ok, result.outcomes
    return result.story, result.library


_COUNTER = iter(range(1, 10_000))


def minter() -> Minter:
    """A fresh minter whose run IDs sort after every earlier one in this session."""
    base = 1_800_000_000_000 + 1000 * next(_COUNTER)
    return Minter(clock=lambda: base, random_bits=lambda: 1)


def build(world: World, document: dict[str, Any], library: Library, *, phase: str = "all",
          source: ClipSources | None = None, heard: str = HEARD, workers: int = 1,
          earlier: tuple[str, ...] | None = None, tools: Toolchain | None = None, **kwargs: Any):
    """One build of ``document`` in the world's store, searching every earlier run."""
    inputs = BuildInputs(story=document, library=library, register=register(),
                         toolchain=tools or toolchain(), studio="git:fixture")
    recognizer, _ = transcriber(heard)
    recognizer = kwargs.pop("recognizer", recognizer)
    runs = local_run_ids(world.store, PRODUCTION) if earlier is None else list(earlier)
    return build_story(inputs, store=world.store, phase=phase, sources=source or sources(),
                       transcriber=recognizer, actor=OPERATOR, earlier_runs=runs,
                       minter=minter(), workers=workers, now=lambda: NOW, **kwargs)


def board_of(document: dict[str, Any], board_id: str) -> dict[str, Any]:
    return next(board for board in document["boards"] if board["id"] == board_id)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
