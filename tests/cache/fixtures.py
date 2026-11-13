"""A small story for the cache tests, and stand-ins for everything a build would make.

Four boards cover the three buildable methods: B1 layered S2V with three speakers
(``a``, ``b``, ``c``), B2 layered I2V with one spoken line (talk bounce), B3 a silent
whole-frame I2V board, B4 layered S2V with two speakers. The story validates against
story 404's validator. Voices, clips, the mix and the master are never made: a take's
hash and length, and any artifact's content hash, are deterministic functions of its
key (:func:`stand_in`), so a changed key means changed content and an unchanged key
the same content, exactly as a cache hit would.
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Callable
from typing import Any

from haynes_studio.cache.keys import CacheKey
from haynes_studio.cache.plan import (
    BoardVoice,
    MediaFormat,
    StoryPlan,
    TakeFacts,
    Toolchain,
    plan_story,
    take_keys,
    track_key,
)
from haynes_studio.canonical import Story, load_story

MEDIA = MediaFormat(width=360, height=640)  # contract section 14: small synthetic picture
OPERATOR = {"kind": "human", "iss": "https://authentik.example.invalid/application/o/haynes-studio/",
            "sub": "example-subject-cache"}


def ident(prefix: str, number: int) -> str:
    """A fixed, valid ``<prefix>_<ULID>`` for the fixture."""
    return f"{prefix}_01JCACHE{number:018d}"


PRODUCTION = ident("prd", 1)
STORY = ident("sty", 1)
B1, B2, B3, B4, B5 = (ident("brd", n) for n in range(1, 6))
L1, L2, L3, L4, L5, L6, L7 = (ident("lin", n) for n in range(1, 8))
STILL_A, STILL_B, STILL_C = ident("asv", 1), ident("asv", 2), ident("asv", 3)
VOICE_A, VOICE_B, VOICE_C, VOICE_N = ident("asv", 11), ident("asv", 12), ident("asv", 13), ident("asv", 14)
SET_PLATE, SET_LOOP, PHOTO_3, PHOTO_1 = ident("asv", 21), ident("asv", 22), ident("asv", 23), ident("asv", 24)
SOUND, BED_SOUND = ident("asv", 31), ident("asv", 32)
BOARD_VOICE = {B1: ident("asv", 41), B2: ident("asv", 42), B4: ident("asv", 44), B5: ident("asv", 45)}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


BLOBS = {asv: sha(f"blob:{asv}") for asv in (STILL_A, STILL_B, STILL_C, SET_PLATE, SET_LOOP,
                                             PHOTO_3, PHOTO_1, SOUND, BED_SOUND)}
VOICE_IDS = {VOICE_A: "af_heart", VOICE_B: "am_adam", VOICE_C: "bf_emma", VOICE_N: "bm_george"}


def _line(line_id: str, speaker: str, text: str, gap: int | None) -> dict[str, Any]:
    return {"id": line_id, "speaker": speaker, "text": text, "gap_before_ms": gap}


def _board(board_id: str, number: int, *, title: str, lines: list, cast: list, preset: str,
           method: tuple[str, str], seeds: dict, cues: list | None = None, hold: int | None = None,
           photo: str | None = None, foreground: bool = True, lead: int = 500) -> dict[str, Any]:
    spoken = bool(lines)
    return {
        "schema": "studio.board/v1", "id": board_id, "story_id": STORY, "number": number,
        "revision": 1, "title": title, "lines": lines,
        "timing": ({"lead_ms": lead, "tail_ms": 700, "hold_ms": None} if spoken else
                   {"lead_ms": None, "tail_ms": None, "hold_ms": hold}),
        "voice": ({"style": "cast", "current_version_id": BOARD_VOICE[board_id]} if spoken else
                  {"style": None, "current_version_id": None}),
        "photo": {"current_version_id": photo, "prompt": None, "input_asset_version_ids": []},
        "cast": [{"slot": slot, "asset_version_id": still} for slot, still in cast],
        "layout": {"preset": preset, "foreground": foreground},
        "method": {"layer": method[0], "motion": method[1]}, "seeds": seeds,
        "cues": cues or [], "notes": [], "drafted_by": OPERATOR, "origin": None,
    }


def story_document() -> dict[str, Any]:
    """The four-board fixture story, boards embedded, as a document. B1 lasts 3230 ms
    (78 frames, up to 3250 ms), so a 10 ms edit stays inside its last frame."""
    b1 = _board(B1, 1, title="Three speakers", preset="trio", method=("layered", "s2v"),
                cast=[("a", STILL_A), ("b", STILL_B), ("c", STILL_C)],
                lines=[_line(L1, "a", "We open the meeting.", None),
                       _line(L2, "b", "Objection, again.", 300),
                       _line(L3, "c", "Noted and ignored.", 300)],
                seeds={"s2v:a": 11, "s2v:b": 12, "s2v:c": 13}, photo=PHOTO_1, lead=480,
                cues=[{"id": ident("cue", 1), "type": "move", "slot": "b", "anchor": {"at_ms": 300},
                       "duration_ms": 250, "dx_px": 48, "dy_px": 0, "angle_deg": -4, "steps": 3},
                      {"id": ident("cue", 2), "type": "camera",
                       "anchor": {"after_line_id": L2, "offset_ms": 0}, "duration_ms": 350,
                       "zoom_from": 1.0, "zoom_to": 1.2, "center_px": [180, 320],
                       "easing": "ease_out_cubic"},
                      {"id": ident("cue", 3), "type": "sound", "asset_version_id": SOUND,
                       "anchor": {"after_line_id": L1, "offset_ms": 50}, "trim_ms": [0, 400],
                       "level_rms_dbfs": -22}])
    b2 = _board(B2, 2, title="Bounce", preset="pair", method=("layered", "i2v"),
                cast=[("a", STILL_A), ("c", STILL_C)],
                lines=[_line(L4, "c", "I bounce when I talk.", None)], seeds={})
    b3 = _board(B3, 3, title="Silent wide", preset="single", method=("whole_frame", "i2v"),
                cast=[], lines=[], seeds={"i2v:frame": 31}, hold=1900, photo=PHOTO_3,
                foreground=False,
                cues=[{"id": ident("cue", 4), "type": "camera", "anchor": {"at_ms": 0},
                       "duration_ms": 350, "zoom_from": 1.0, "zoom_to": 1.1,
                       "center_px": [180, 320], "easing": "ease_out_cubic"}])
    b4 = _board(B4, 4, title="Two speakers", preset="pair", method=("layered", "s2v"),
                cast=[("b", STILL_B), ("c", STILL_C)],
                lines=[_line(L5, "b", "Motion to adjourn.", None),
                       _line(L6, "c", "Seconded.", 300)],
                seeds={"s2v:b": 41, "s2v:c": 42})
    return {
        "schema": "studio.story/v1", "id": STORY, "production_id": PRODUCTION, "media_kind": "short",
        "title": "Cache fixture", "revision": 1, "format_version_id": None,
        "cast": [{"slot": "a", "name": "chair", "voice_version_id": VOICE_A},
                 {"slot": "b", "name": "rebel", "voice_version_id": VOICE_B},
                 {"slot": "c", "name": "clerk", "voice_version_id": VOICE_C}],
        "narrator_voice_version_id": VOICE_N,
        "set": {"asset_version_id": SET_PLATE, "motion_asset_version_id": SET_LOOP,
                "foreground_edge_px": [[0, 560], [360, 580]], "foreground_feather_px": 12,
                "legacy_fire": None},
        "layouts": {"single": {"height": 420, "x": 0.5, "bottom": 600},
                    "pair": {"slots": {"a": {"x": 0.3, "height": 380, "bottom": 590},
                                       "b": {"x": 0.3, "height": 380, "bottom": 590},
                                       "c": {"x": 0.7, "height": 400, "bottom": 600}}},
                    "trio": {"slots": {"a": {"x": 0.2, "height": 360, "bottom": 580},
                                       "b": {"x": 0.5, "height": 380, "bottom": 590},
                                       "c": {"x": 0.8, "height": 400, "bottom": 600}}}},
        "motion_style": {"idle_scale": 0.3, "talk_hop": 34, "talk_tilt": 3.2, "talk_shuffle": 7},
        "mix": {"line_rms_dbfs": -22, "master_lufs": -20, "true_peak_dbtp": -3.5},
        "beds": [{"id": ident("cue", 9), "type": "bed", "asset_version_id": BED_SOUND,
                  "level_rms_dbfs": -40, "clock": "film"}],
        "checks": {"asr_tolerances": {"340": "three hundred forty"}},
        "board_order": [B1, B2, B3, B4],
        "boards": [b1, b2, b3, b4],
        "origin": None,
    }


def extra_board() -> dict[str, Any]:
    """A fifth board (layered S2V, one speaker) for the "add a board" row."""
    return _board(B5, 5, title="Added", preset="single", method=("layered", "s2v"),
                  cast=[("a", STILL_A)], lines=[_line(L7, "a", "One more thing.", None)],
                  seeds={"s2v:a": 51})


def load(document: dict[str, Any]) -> Story:
    """The story model; story 404's validator must accept the document."""
    return load_story(copy.deepcopy(document), context="write", source="cache fixture")


def stand_in(key: CacheKey) -> str:
    """The content hash a build would produce for ``key``: a function of the key, so
    the same key always means the same content (a hit) and a new key new content."""
    return sha(f"made:{key.value}")


def take_ms(text: str) -> int:
    """A stand-in take length: 300 ms plus 10 ms per character (one character more is
    under one frame, so a duration change need not change the frames)."""
    return 300 + 10 * len(text)


def voices(story: Story, *, voice_ids: dict[str, str] = VOICE_IDS,
           toolchain: Toolchain = Toolchain()) -> dict[str, BoardVoice]:
    """Each spoken board's current voice, made by a stand-in TTS: a take's hash is its
    key's stand-in, its length :func:`take_ms` of the text; the track's hash is its
    key's stand-in."""
    out = {}
    for board in story.boards or ():
        if not board.spoken:
            continue
        keys = take_keys(story, board, voice_ids=voice_ids, toolchain=toolchain)
        takes = {line.id: TakeFacts(sha256=stand_in(keys[line.id]), duration_ms=take_ms(line.text))
                 for line in board.lines}
        out[board.id] = BoardVoice(takes=takes, track_sha256=stand_in(track_key(board, takes, toolchain)))
    return out


def plan(document: dict[str, Any], *, toolchain: Toolchain = Toolchain(),
         media: MediaFormat = MEDIA, blobs: dict[str, str] | None = None,
         voice_ids: dict[str, str] = VOICE_IDS,
         content: Callable[[CacheKey], str] = stand_in) -> StoryPlan:
    """The key plan of a fixture document, with stand-in voices and content."""
    story = load(document)
    return plan_story(story, voices=voices(story, voice_ids=voice_ids, toolchain=toolchain),
                      blobs=BLOBS if blobs is None else blobs, voice_ids=voice_ids,
                      toolchain=toolchain, media=media, content=content)


def board_of(document: dict[str, Any], board_id: str) -> dict[str, Any]:
    return next(board for board in document["boards"] if board["id"] == board_id)
