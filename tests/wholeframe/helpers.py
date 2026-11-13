"""Shared set-up for the whole-frame tests: a store, a toolchain with short clips, a
story of whole-frame boards and a build through the cache. All media is synthetic and
made under ``tmp_path``.

Clips are 25 frames (4 x 6 + 1, a valid Wan length) at 360x640 so that chains of two
and three clips stay cheap; the policy's numbers at 121 frames are tested as pure
functions and once with real 121-frame clips.
"""

from __future__ import annotations

import copy
import hashlib
from dataclasses import replace
from pathlib import Path
from typing import Any

from haynes_studio.cache import ArtifactCache
from haynes_studio.cache.build import PictureBuilder
from haynes_studio.cache.keys import WHOLE_FRAME_CLIP, CacheKey, segment_key, whole_frame_clip_key
from haynes_studio.cache.plan import Toolchain
from haynes_studio.jsonio import parse_strict
from haynes_studio.render.encode import EncoderSettings
from haynes_studio.store import LocalStore, blob_locator
from haynes_studio.wholeframe import (
    COMPOSITOR,
    WholeFrameClips,
    WholeFrameRenderer,
    production_reader,
)
from haynes_studio.wholeframe.fake import FakeClipSource
from tests.cache import fixtures as fx
from tests.cache.fixtures import B2, B3, PHOTO_1, PHOTO_3, PRODUCTION, ident

CLIP = 25
SIZE = [360, 640]
RUN1, RUN2, RUN3 = ident("run", 1), ident("run", 2), ident("run", 3)
PROFILE = {"model": "wan2.2-ti2v-5b", "source_fps": 24, "size": SIZE, "adapter": "studio.i2v/1",
           "delivery": {"aspect": "9:16", "fps": 24}}


def toolchain(clip_frames: int = CLIP, size: list[int] = SIZE) -> Toolchain:
    tools = Toolchain()
    return replace(tools, compositor=COMPOSITOR, i2v_clip_frames=clip_frames,
                   i2v_profile={**tools.i2v_profile, "size": size})


def new_store(path: Path) -> LocalStore:
    path.mkdir()
    return LocalStore(path)


def photo_bytes(name: str) -> bytes:
    """A stand-in photo (the clip source never decodes it; its hash is the input)."""
    return f"synthetic photo {name}".encode()


PHOTOS = {PHOTO_1: photo_bytes("one"), PHOTO_3: photo_bytes("three")}
BLOBS = {**fx.BLOBS, **{asv: hashlib.sha256(data).hexdigest() for asv, data in PHOTOS.items()}}


def publish_photos(store: LocalStore) -> None:
    for data in PHOTOS.values():
        store.publish(data, scope="library", media_type="image/png")


def story_document(*, hold: int = 1900) -> dict[str, Any]:
    """Two whole-frame I2V boards: B2 spoken (one line, 1710 ms, 42 frames) and B3
    silent (``hold`` ms; 1900 ms is 46 frames). Both need two 25-frame clips."""
    document = fx.story_document()
    b2 = copy.deepcopy(fx.board_of(document, B2))
    b2.update(cast=[], method={"layer": "whole_frame", "motion": "i2v"}, seeds={"i2v:frame": 21},
              photo={"current_version_id": PHOTO_1, "prompt": None, "input_asset_version_ids": []},
              layout={"preset": "single", "foreground": False})
    b3 = copy.deepcopy(fx.board_of(document, B3))
    b3.update(cues=[])
    b3["timing"]["hold_ms"] = hold
    document.update(board_order=[B2, B3], boards=[b2, b3])
    return document


class Build:
    """One build of a document's picture: whole-frame clips from ``source`` through
    the clip stage, segments through :class:`WholeFrameRenderer`."""

    def __init__(self, store: LocalStore, document: dict[str, Any], run_id: str, *,
                 earlier: tuple[str, ...] = (), source: FakeClipSource | None = None,
                 tools: Toolchain | None = None):
        self.cache = ArtifactCache(store, production_id=PRODUCTION, run_id=run_id, earlier_runs=earlier)
        self.source = source or FakeClipSource()
        self.clips = WholeFrameClips(self.cache, self.source,
                                     read_photo=production_reader(store, "library", ("image/png",)))
        self.renderer = WholeFrameRenderer()
        self.builder = PictureBuilder(self.cache, self.renderer, upstream=self.upstream,
                                      open_input=production_reader(store, PRODUCTION))
        self.plan = fx.plan(document, toolchain=tools or toolchain(), blobs=BLOBS,
                            content=self.builder)

    def upstream(self, key: CacheKey) -> str:
        return self.clips(key) if key.kind == WHOLE_FRAME_CLIP else fx.stand_in(key)


def clip_key(photo: bytes = PHOTOS[PHOTO_3], *, seed: int = 31, lengths: tuple[int, ...] = (CLIP, CLIP),
             profile: dict[str, Any] | None = None) -> CacheKey:
    return whole_frame_clip_key(photo=hashlib.sha256(photo).hexdigest(), prompt="gentle motion",
                                seed=seed, profile=profile or PROFILE, clip_lengths=lengths)


def wf_segment(clip_set: str | None, frames: int, *, width: int = 360, height: int = 640,
               **overrides: Any) -> CacheKey:
    """A whole-frame segment key as the plan makes one for a silent board."""
    inputs: dict[str, Any] = dict(
        method={"layer": "whole_frame", "motion": "i2v"}, frames=frames, width=width,
        height=height, fps=24, layout=None, layers=[], set_layer=None, whole_frame_clip=clip_set,
        motion_style=None, voice_envelope=None, talk=[], cues=[], foreground=None,
        procedural_stream=7, compositor=COMPOSITOR, encoder=EncoderSettings().key_inputs())
    inputs.update(overrides)
    return segment_key(**inputs)


def blob(store: LocalStore, sha256: str, media_type: str = "video/mp4") -> Path:
    return Path(store.root) / blob_locator(PRODUCTION, sha256, media_type)


def parse(store: LocalStore, clip_set: str) -> dict[str, Any]:
    """A clip set record, read back as plain JSON."""
    return parse_strict(blob(store, clip_set, "application/json").read_text())
