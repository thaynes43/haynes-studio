"""Shared set-up for the layered tests: a store holding synthetic media, a library of
pinned motion records over it, a story of layered boards, and a build through the
cache. All media is drawn in memory (:mod:`tests.layered.media`) and published under
``tmp_path``; nothing is read from the repository's titles.

The world is small: boards at 360x640, doll clips at 144x256, 13-frame doll loops
(period 24), a 9-frame set loop (period 16), speech-to-video at 16 fps. Dolls hold
still in their clips (only the frame-number bars change), and the test story's motion
style is zero by default, so a board frame's pixels say which source frame each layer
showed (:meth:`World.read_slot`).
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np

from haynes_studio.cache import ArtifactCache, BoardVoice, TakeFacts, plan_story
from haynes_studio.cache.build import PictureBuilder
from haynes_studio.cache.plan import MediaFormat, StoryPlan, Toolchain, take_keys
from haynes_studio.canonical import load_story
from haynes_studio.layered import COMPOSITOR, FakeS2VSource, LayeredRenderer, LayeredStages, reader
from haynes_studio.layered import compose
from haynes_studio.layered.keyed import read_record
from haynes_studio.layered.pin import pin_story
from haynes_studio.library import Library
from haynes_studio.motion.winter_menu import complete_block
from haynes_studio.render.encode import decode_frames
from haynes_studio.store import LocalStore, blob_locator
from haynes_studio.voice.track import assemble, read_wav
from tests.cache import fixtures as fx
from tests.cache.fixtures import PRODUCTION, VOICE_IDS, ident
from tests.layered import media
from tests.motion import fixtures as mf

MEDIA = MediaFormat(width=360, height=640)
LOOP_N, SET_N = 13, 9
B1, B2, B4 = fx.B1, fx.B2, fx.B4
L1, L2, L3, L4, L5, L6, L7 = fx.L1, fx.L2, fx.L3, fx.L4, fx.L5, fx.L6, fx.L7
STILL = {slot: ident("asv", 100 + i) for i, slot in enumerate("abc")}
STILL2 = {"a": ident("asv", 110)}  # a second version of a's still (its own loop)
LOOP = {slot: ident("asv", 120 + i) for i, slot in enumerate("abc")}
LOOP2 = {"a": ident("asv", 130)}
PLATE, SET_LOOP = ident("asv", 140), ident("asv", 141)
TINT = {"a": 0, "b": 60, "c": 120}
KEYING = {"keyer": "legacy:poc/cutout.py key", "key_thresholds": {"lo": 20, "hi": 70},
          "protect_boxes": [list(media.PROTECT)], "decal_box": list(media.DECAL_BOX),
          "decal_version": "erase-v2"}
S2V_PROFILE = {"model": "wan2.2-s2v-14b-fp8", "lora": "lightx2v-4step", "steps": 4, "cfg": 1,
               "size": [media.CLIP_W, media.CLIP_H], "chunk": 77, "source_fps": 16}
TOOLS = replace(Toolchain(), compositor=COMPOSITOR, s2v_profile=S2V_PROFILE)
STILL_STYLE = {"idle_scale": 0, "talk_hop": 0, "talk_tilt": 0, "talk_shuffle": 0}
LAYOUTS = {
    "single": {"height": 300, "x": 0.5, "bottom": 600},
    "pair": {"slots": {"a": {"x": 0.3, "height": 200, "bottom": 560},
                       "b": {"x": 0.3, "height": 200, "bottom": 560},
                       "c": {"x": 0.72, "height": 220, "bottom": 580}}},
    "trio": {"slots": {"a": {"x": 0.2, "height": 200, "bottom": 560},
                       "b": {"x": 0.5, "height": 200, "bottom": 560},
                       "c": {"x": 0.8, "height": 200, "bottom": 560}}},
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def take_ms(text: str) -> int:
    return fx.take_ms(text)


def s2v_draw(n: int, start: np.ndarray) -> np.ndarray:
    """The fake engine's frame ``n``: the doll holding still, frame number in its bars."""
    return media.doll_frame(n, garble=True)


@dataclass
class World:
    """A store with the library's media published, and the records over it."""

    store: LocalStore
    blobs: dict[str, str] = field(default_factory=dict)  # version ID to content hash
    docs: list[dict[str, Any]] = field(default_factory=list)
    takes: dict[tuple[str, str], tuple[str, int]] = field(default_factory=dict)

    def publish(self, data: bytes, media_type: str) -> str:
        return self.store.publish(data, scope=PRODUCTION, media_type=media_type).sha256

    def library(self, *extra: Mapping[str, Any], without: frozenset[str] = frozenset()) -> Library:
        return Library.from_version_documents(
            [*(d for d in self.docs if d["id"] not in without), *extra])

    def read(self, sha256: str) -> bytes:
        for media_type in ("image/png", "video/mp4", "audio/wav"):
            locator = blob_locator(PRODUCTION, sha256, media_type)
            if self.store.verify(locator, sha256) == "present":
                with self.store.open(locator) as handle:
                    return handle.read()
        raise KeyError(sha256)

    def voices(self, story) -> dict[str, BoardVoice]:
        """Each spoken board's voice: real takes (tones, 24 kHz) and the assembled
        board track, published; a take's hash is its bytes'."""
        out = {}
        for board in story.boards or ():
            if not board.spoken:
                continue
            keys = take_keys(story, board, voice_ids=VOICE_IDS, toolchain=TOOLS)
            takes, pcm = {}, []
            for i, line in enumerate(board.lines):
                pitch = 180 + int(hashlib.sha256(line.text.encode()).hexdigest()[:4], 16) % 200
                data = media.take(take_ms(line.text), seed=i, pitch=pitch)  # new text, new audio
                takes[line.id] = TakeFacts(sha256=self.publish(data, "audio/wav"),
                                           duration_ms=take_ms(line.text))
                pcm.append(read_wav(data))
                assert keys[line.id]  # the key exists; its content is the take's hash
            starts, at = [], board.timing.lead_ms
            for i, line in enumerate(board.lines):
                at += 0 if i == 0 else line.gap_before_ms
                starts.append(at)
                at += takes[line.id].duration_ms
            track = assemble(pcm, starts, at)
            out[board.id] = BoardVoice(takes=takes, track_sha256=self.publish(track, "audio/wav"))
        return out


def loop_doc(world: World, version_id: str, asset: int, *, still_sha: str, clip: bytes,
             start: bytes, subject: str = "doll", frames: int = LOOP_N, number: int = 1,
             state: str = "promoted", keying: Mapping[str, Any] | None = KEYING,
             decal_min_ecc: float | None = None) -> dict[str, Any]:
    clip_sha, start_sha = world.publish(clip, "video/mp4"), world.publish(start, "image/png")
    block = mf.loop_block(still_sha256=still_sha, frames=frames, width=media.CLIP_W,
                          height=media.CLIP_H, trim={"start": 0, "frames": frames})
    block["source"] = {**block["source"], "image_sha256": start_sha}
    if subject == "set":
        block["subject"] = "set"
        block["width"], block["height"] = 180, 320
        del block["keying"]
    elif keying is not None:
        block["keying"] = {**keying, **({} if decal_min_ecc is None else {"decal_min_ecc": decal_min_ecc})}
    doc = mf.version(None, n=1, clip=clip_sha, state=state)
    doc["motion"] = complete_block(block, clip_sha)
    doc["capabilities"] = ["set_loop"] if subject == "set" else ["motion_clip"]
    doc["number"] = number
    doc["content"]["bytes"] = len(clip)
    return fx.scoped(doc, version_id, asset)


def still_doc(world: World, version_id: str, asset: int, data: bytes, *, kind: str = "cast",
              number: int = 1) -> dict[str, Any]:
    still_sha = world.publish(data, "image/png")
    world.blobs[version_id] = still_sha
    doc = fx.scoped(mf.still_version(1, still_sha, kind=kind), version_id, asset)
    doc["number"] = number
    doc["content"]["bytes"] = len(data)
    return doc


def make_world(path: Path, *, weak: str | None = None) -> World:
    """The store and library. ``weak`` names a slot whose loop cannot be tracked."""
    path.mkdir()
    world = World(LocalStore(path))
    for i, slot in enumerate("abc"):
        colour = ((200, 60, 60), (60, 200, 60), (60, 60, 200))[i]
        world.docs.append(still_doc(world, STILL[slot], 200 + i, media.cutout(colour)))
        clip = media.doll_clip(LOOP_N, moving=False, tint=TINT[slot], weak=slot == weak)
        world.docs.append(loop_doc(world, LOOP[slot], 220 + i, still_sha=world.blobs[STILL[slot]],
                                   clip=clip, start=media.start_image(tint=TINT[slot])))
    world.docs.append(still_doc(world, STILL2["a"], 200, media.cutout((220, 120, 60)), number=2))
    world.docs.append(loop_doc(world, LOOP2["a"], 220, still_sha=world.blobs[STILL2["a"]], number=2,
                               clip=media.doll_clip(LOOP_N, moving=False, tint=30),
                               start=media.start_image(tint=30)))
    world.docs.append(still_doc(world, PLATE, 240, media.set_plate(), kind="set"))
    world.docs.append(loop_doc(world, SET_LOOP, 241, still_sha=world.blobs[PLATE], subject="set",
                               clip=media.set_clip(SET_N), start=media.set_plate(), frames=SET_N))
    world.blobs[SET_LOOP] = sha(media.set_clip(SET_N))
    return world


def story_document(*, b1_lead: int = 100, style: Mapping[str, Any] | None = None,
                   foreground: bool = False, set_loop: bool = True) -> dict[str, Any]:
    """Three layered boards: B1 layered S2V (a, b, c speak), B2 layered I2V (a idle, c
    speaks: bounce), B4 layered S2V (b, c speak; a idle). Short lines keep them short."""
    def line(line_id, speaker, text, gap):
        return {"id": line_id, "speaker": speaker, "text": text, "gap_before_ms": gap}
    b1 = fx._board(B1, 1, title="Three speakers", preset="trio", method=("layered", "s2v"),
                   cast=[("a", STILL["a"]), ("b", STILL["b"]), ("c", STILL["c"])],
                   lines=[line(L1, "a", "Go.", None), line(L2, "b", "No.", 100),
                          line(L3, "c", "So.", 100)],
                   seeds={"s2v:a": 11, "s2v:b": 12, "s2v:c": 13}, lead=b1_lead, foreground=foreground)
    b2 = fx._board(B2, 2, title="Bounce", preset="pair", method=("layered", "i2v"),
                   cast=[("a", STILL["a"]), ("c", STILL["c"])], lines=[line(L4, "c", "Hop.", None)],
                   seeds={}, lead=100, foreground=foreground)
    b4 = fx._board(B4, 4, title="Two speakers", preset="trio", method=("layered", "s2v"),
                   cast=[("a", STILL["a"]), ("b", STILL["b"]), ("c", STILL["c"])],
                   lines=[line(L5, "b", "Up.", None), line(L6, "c", "Ok.", 100)],
                   seeds={"s2v:b": 41, "s2v:c": 42}, lead=100, foreground=foreground)
    document = fx.story_document()
    document.update(
        boards=[b1, b2, b4], board_order=[B1, B2, B4], layouts=copy.deepcopy(LAYOUTS),
        motion_style=dict(STILL_STYLE if style is None else style), beds=[],
        set={"asset_version_id": PLATE, "motion_asset_version_id": SET_LOOP if set_loop else None,
             "foreground_edge_px": [[0, 600], [360, 620]], "foreground_feather_px": 12,
             "legacy_fire": None})
    return document


@dataclass
class Build:
    plan: StoryPlan
    builder: PictureBuilder
    stages: LayeredStages
    renderer: LayeredRenderer
    source: FakeS2VSource
    cache: ArtifactCache


def build(world: World, document: dict[str, Any], run_id: str, earlier: tuple[str, ...] = (), *,
          source: FakeS2VSource | None = None, library: Library | None = None,
          tools: Toolchain = TOOLS) -> Build:
    """One build of the document's picture with the layered stages and renderer."""
    cache = ArtifactCache(world.store, production_id=PRODUCTION, run_id=run_id, earlier_runs=earlier)
    read = reader(world.store, [PRODUCTION, "library"])
    source = source or FakeS2VSource(draw=s2v_draw, extra=4)
    stages = LayeredStages(cache, source, read=read)
    renderer = LayeredRenderer()

    def upstream(key):
        return stages(key) if stages.handles(key) else fx.stand_in(key)
    builder = PictureBuilder(cache, renderer, upstream=upstream, open_input=read)
    story = load_story(copy.deepcopy(document), context="write", source="layered fixture")
    lib = library or world.library()
    plan = plan_story(story, voices=world.voices(story), blobs=world.blobs, voice_ids=VOICE_IDS,
                      toolchain=tools, media=MEDIA, content=builder,
                      motion=pin_story(document, lib, world.store.verify, production_id=PRODUCTION))
    return Build(plan=plan, builder=builder, stages=stages, renderer=renderer, source=source,
                 cache=cache)


def segment_frames(world: World, plan: StoryPlan, board_id: str) -> list[np.ndarray]:
    sha256 = plan.artifacts[f"{board_id}/segment"].content
    return list(decode_frames(world.read(sha256)))


def read_slot(world: World, plan: StoryPlan, board_id: str, slot: str, frame: np.ndarray,
              layouts: Mapping[str, Any] = LAYOUTS, preset: str = "trio") -> int:
    """The frame number a static doll shows on a board frame, read off its bars: the
    keyed crop box from its keyed artifact, scaled to the slot's height and placed."""
    keyed = world.read(plan.artifacts[f"{board_id}/keyed/{slot}"].content)
    x0, y0, x1, y1 = read_record(keyed)["box"]
    spec = compose.slot_of(layouts[preset], slot)
    scale = spec.height / (y1 - y0)
    width = max(1, round((x1 - x0) * scale))
    where = compose.place((width, spec.height), spec, MEDIA.width, slot)
    return media.read_number(frame, where.x + (42 - x0) * scale,
                             where.y + (media.STRIP_Y + 15 - y0) * scale, scale)


RUN = {n: ident("run", n) for n in range(1, 30)}
Change = Callable[[dict[str, Any]], None]
