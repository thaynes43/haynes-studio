"""Every artifact's key for one story (story 380): the key plan.

:func:`plan_story` walks a story's boards in ``board_order`` and computes each
artifact's key with the pure functions of :mod:`haynes_studio.cache.keys`, in the order
the artifacts depend on one another. A key takes the *content hash* of what it is made
from, so the plan asks ``content(key)`` for each artifact it needs downstream: a build
answers from the cache (a hit) or by making it (a miss); a key-only test answers with a
deterministic stand-in. Two plans of one story differ exactly where a key changed,
which is how the invalidation table of contract section 4 is tested.

Inputs are resolved before planning (never looked up here): the story with its boards
embedded, each spoken board's current voice (take hashes and durations, and its
track's hash), every asset version's content hash, each voice version's stock voice,
the toolchain and the media format. Identifiers name artifacts in the plan; they are
never key inputs. Board timing is story 404's (:func:`~haynes_studio.canonical.derive.board_clock`).

The layered path (story 426) plans from **pinned motion records** when ``motion`` is
given (:class:`LayeredMotion`, made by :func:`haynes_studio.layered.pin.pin_story` with
story 457's resolver): every doll clip, its keyed frames, the loop's length and phase,
the set loop and a speaker's start image and keying come from the records, and the
toolchain's motion and keying placeholders are not read. Without ``motion`` the plan
keeps story 380's placeholders, for key-only callers; the layered renderer refuses a
segment planned that way, so such a plan cannot be built.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from haynes_studio.cache.errors import KEY_INPUT_INVALID, CacheError
from haynes_studio.cache.keys import (
    CacheKey,
    make_key,
    board_voice_track_key,
    check_result_key,
    film_picture_key,
    keyed_frames_key,
    master_key,
    mix_key,
    motion_clip_key,
    proxy_key,
    s2v_clip_key,
    s2v_drive_track_key,
    segment_key,
    voice_take_key,
    whole_frame_clip_key,
)
from haynes_studio.canonical.derive import BoardClock, board_clock, resolve_anchor
from haynes_studio.canonical.facts import Facts, VoiceVersionFacts
from haynes_studio.canonical.methods import status as method_status
from haynes_studio.canonical.model import NARRATOR, Board, CameraCue, MoveCue, SoundCue, Story
from haynes_studio.jsonio import thaw
from haynes_studio.render.clock import (
    SET_SLOT,
    board_stream,
    i2v_clip_lengths,
    loop_period,
    loop_phase,
    source_frames_needed,
)
from haynes_studio.render.encode import EncoderSettings, encoder_build
from haynes_studio.timebase import DELIVERY_FPS, MIX_RATE, mix_sample

Content = Callable[[CacheKey], str]
"""Answers an artifact's content hash for its key (a build: the cache; a test: a
stand-in)."""

_FROZEN_EMPTY: Mapping[str, Any] = MappingProxyType({})


def _frozen(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value))


@dataclass(frozen=True)
class MediaFormat:
    """The media kind's delivery picture: frame size and fps (contract sections 3 and
    5). Generated clips are made for its aspect and fps (**proposal**): a media kind
    change regenerates every clip, a size change at the same aspect does not. Both
    media kinds deliver at 24 fps (P-20) and board frames are counted at 24 fps
    (TIME-3), so another fps is refused rather than half applied."""

    width: int
    height: int
    fps: int = DELIVERY_FPS

    def __post_init__(self) -> None:
        for name in ("width", "height"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 2 or value % 2:
                raise ValueError(f"{name} is a positive even integer, got {value!r}")
        if self.fps != DELIVERY_FPS:  # TIME-3 counts board frames at 24 fps (section 3)
            raise ValueError(f"contract v1 delivers at {DELIVERY_FPS} fps, got {self.fps!r}")

    @property
    def aspect(self) -> str:
        return "9:16" if self.height > self.width else "16:9"

    def delivery(self) -> dict[str, Any]:
        return {"aspect": self.aspect, "fps": self.fps}


@dataclass(frozen=True)
class TakeFacts:
    """One take of a board voice version: the take's content hash and measured length."""

    sha256: str
    duration_ms: int


@dataclass(frozen=True)
class BoardVoice:
    """A spoken board's current voice version, resolved: one take per line ID and the
    assembled track's content hash (contract section 10, VOICE-2)."""

    takes: Mapping[str, TakeFacts]
    track_sha256: str


@dataclass(frozen=True)
class Toolchain:
    """Every tool, profile and setting a key names (P-07). The defaults are
    placeholders a build replaces with the pinned digests of its run's toolchain."""

    tts_model: str = "kokoro-82m-v1.0"
    take_rate: int = 24_000
    speed: float = 1.0
    track_assembler: str = "studio.voice.track/1"
    mix_rate: int = MIX_RATE
    drive_assembler: str = "studio.s2v.drive/1"
    drive_rate: int = 24_000  # story 426: the takes' rate, so a drive track needs no resampling
    s2v_adapter: str = "studio.s2v/1"
    s2v_profile: Mapping[str, Any] = field(default_factory=lambda: _frozen({
        "model": "wan2.2-s2v-14b-fp8", "lora": "lightx2v-4step", "steps": 4, "cfg": 1,
        "size": [576, 1024], "chunk": 77, "source_fps": 16}))
    s2v_prompt: str = "a felt doll talking, stop-motion"
    s2v_negative_prompt: str = ""
    motion_profile: Mapping[str, Any] = field(default_factory=lambda: _frozen({
        "model": "wan2.2-ti2v-5b", "frames": 121, "source_fps": 24, "size": [576, 1024],
        "adapter": "studio.motion/1"}))
    motion_prompt: str = "a felt doll idling on green, stop-motion"
    motion_seed: int = 0
    i2v_profile: Mapping[str, Any] = field(default_factory=lambda: _frozen({
        "model": "wan2.2-ti2v-5b", "source_fps": 24, "size": [576, 1024],
        "adapter": "studio.i2v/1"}))
    i2v_prompt: str = "stop-motion felt dolls, gentle motion"
    i2v_clip_frames: int = 121
    keyer: str = "studio.keyer/1"
    key_thresholds: Mapping[str, Any] = field(default_factory=lambda: _frozen({"green": 0.4}))
    protect_boxes: tuple[Any, ...] = ()
    decal_box: tuple[int, ...] | None = None
    decal_version: str | None = None
    # One digest for every board, or one per method layer (``{"layered": ...,
    # "whole_frame": ...}``, story 406), so each board's segment names the compositor of
    # its own method's renderer.
    compositor: str | Mapping[str, str] = "studio.render.synthetic/1"
    encoder: Mapping[str, Any] = field(default_factory=lambda: _frozen(EncoderSettings().key_inputs()))
    procedural_seed: int = 0
    splicer: str = "studio.splice/1"
    mixer: str = "studio.mixer/1"
    mux: Mapping[str, Any] = field(default_factory=lambda: _frozen({
        "audio": "aac", "container": "mp4", "build": encoder_build()}))
    proxy_profile: Mapping[str, Any] = field(default_factory=lambda: _frozen({
        "codec": "libx264", "size": [720, 1280], "max_bytes_per_60s": 25_000_000,
        "build": encoder_build()}))
    checks: Mapping[str, Mapping[str, Any]] = field(default_factory=lambda: _frozen({
        "master.decode": {"on": "master", "version": "1", "thresholds": {}},
        "master.transcript": {"on": "master", "version": "1", "thresholds": {},
                              "transcript": True}}))


@dataclass(frozen=True)
class LayeredMotion:
    """The pinned motion records of a story's layered boards (story 426), resolved
    before planning by story 457's resolver (:func:`haynes_studio.layered.pin.pin_story`).

    ``boards`` maps a layered board's ID to its ``BoardMotion`` resolved as layered I2V,
    so every cast entry has its loop (a speaker's loop gives her speech-to-video start
    image and keying, **proposal**) and the set its loop or none. ``timed(slot,
    still_sha256, drive_track_sha256, board_frames)`` answers a library timed clip made
    from that drive track, or None (the build then makes one). ``decal_min_ecc`` is the
    decal gate of a clip made in the build (``poc/decal.py MIN_ECC``). ``keyer_build``
    names the library builds the keyer runs on; it is appended to each record's keyer
    in the keyed frames' cache key (``<keyer>@<build>``, **proposal**, P-07), so a new
    OpenCV, scipy, numpy, Pillow or PyAV keys the frames again."""

    boards: Mapping[str, Any]
    timed: Callable[[str, str, str, int], Any] | None = None
    decal_min_ecc: float = 0.8
    keyer_build: str | None = None


@dataclass(frozen=True)
class Planned:
    """One artifact of the plan: its name (with board, line or slot), its key and its
    content hash as ``content`` answered."""

    name: str
    key: CacheKey
    content: str
    board_id: str | None = None


@dataclass(frozen=True)
class BoardPlan:
    board_id: str
    frames: int
    film_start_frame: int
    segment: Planned


@dataclass(frozen=True)
class StoryPlan:
    artifacts: Mapping[str, Planned]
    boards: tuple[BoardPlan, ...]
    frames: int
    film_picture: Planned
    mix: Planned
    master: Planned
    proxy: Planned

    def keys(self) -> dict[str, str]:
        """Artifact name to key value."""
        return {name: planned.key.value for name, planned in self.artifacts.items()}


@dataclass(frozen=True)
class KeyDiff:
    """Two plans compared by artifact name."""

    changed: frozenset[str]
    kept: frozenset[str]
    added: frozenset[str]
    removed: frozenset[str]

    @property
    def rebuilt(self) -> frozenset[str]:
        """Artifacts the second plan cannot reuse: changed or new."""
        return self.changed | self.added


def diff(before: StoryPlan, after: StoryPlan) -> KeyDiff:
    a, b = before.keys(), after.keys()
    both = a.keys() & b.keys()
    return KeyDiff(changed=frozenset(n for n in both if a[n] != b[n]),
                   kept=frozenset(n for n in both if a[n] == b[n]),
                   added=frozenset(b.keys() - a.keys()), removed=frozenset(a.keys() - b.keys()))


def _bad(message: str, where: str) -> CacheError:
    return CacheError(KEY_INPUT_INVALID, message, where=where)


def _resolve(blobs: Mapping[str, str], version_id: str | None, where: str) -> str:
    if version_id is None or version_id not in blobs:
        raise _bad(f"asset version {version_id!r} is not resolved to a content hash", where)
    return blobs[version_id]


def speaker_voice(story: Story, speaker: str) -> str | None:
    """The voice version that speaks for ``speaker``: the cast slot's voice, or the
    story's narrator voice for ``narrator``."""
    if speaker == NARRATOR:
        return story.narrator_voice_version_id
    return next((m.voice_version_id for m in story.cast if m.slot == speaker), None)


def take_keys(story: Story, board: Board, *, voice_ids: Mapping[str, str],
              toolchain: Toolchain) -> dict[str, CacheKey]:
    """Line ID to the take's key (section 4: voice take). ``voice_ids`` maps each voice
    asset version to its stock voice name."""
    out = {}
    for line in board.lines:
        version = speaker_voice(story, line.speaker)
        if version not in voice_ids:
            raise _bad(f"no stock voice for speaker {line.speaker!r}", f"{board.id}/{line.id}")
        out[line.id] = voice_take_key(tts_model=toolchain.tts_model, voice_id=voice_ids[version],
                                      text=line.text, speed=toolchain.speed,
                                      sample_rate=toolchain.take_rate)
    return out


def track_key(board: Board, takes: Mapping[str, TakeFacts], toolchain: Toolchain) -> CacheKey:
    """The board voice track's key from its takes, lead and gaps."""
    return board_voice_track_key(
        takes=[takes[line.id].sha256 for line in board.lines], lead_ms=board.timing.lead_ms,
        gaps_ms=[line.gap_before_ms for line in board.lines[1:]], mix_rate=toolchain.mix_rate,
        assembler=toolchain.track_assembler)


def _clock(board: Board, voice: BoardVoice | None) -> BoardClock:
    facts = Facts()
    if board.spoken:
        if voice is None or board.voice.current_version_id is None:
            raise _bad("a spoken board has no current voice (voice.absent): Build is refused", board.id)
        facts = Facts.build(voices=[VoiceVersionFacts(
            id=board.voice.current_version_id,
            takes_ms={line_id: take.duration_ms for line_id, take in voice.takes.items()})])
    clock = board_clock(board, facts)
    if clock is None:
        raise _bad("the board's voice does not cover its lines (voice.stale): Build is refused", board.id)
    return clock


def _picture_cues(board: Board, clock: BoardClock) -> list[dict[str, Any]]:
    """Move and camera cues, anchors resolved to ms from board start, in board order."""
    cues: list[dict[str, Any]] = []
    for cue in board.cues:
        if isinstance(cue, MoveCue):
            cues.append({"type": "move", "slot": cue.slot, "start_ms": resolve_anchor(cue.anchor, clock),
                         "duration_ms": cue.duration_ms, "dx_px": cue.dx_px, "dy_px": cue.dy_px,
                         "angle_deg": cue.angle_deg, "steps": cue.steps})
        elif isinstance(cue, CameraCue):
            cues.append({"type": "camera", "start_ms": resolve_anchor(cue.anchor, clock),
                         "duration_ms": cue.duration_ms, "zoom_from": cue.zoom_from,
                         "zoom_to": cue.zoom_to, "center_px": list(cue.center_px),
                         "easing": cue.easing})
    return cues


class _Planner:
    def __init__(self, story: Story, *, voices: Mapping[str, BoardVoice], blobs: Mapping[str, str],
                 voice_ids: Mapping[str, str], toolchain: Toolchain, media: MediaFormat,
                 content: Content, motion: LayeredMotion | None = None):
        self.story, self.voices, self.blobs = story, voices, blobs
        self.voice_ids, self.tools, self.media, self.content = voice_ids, toolchain, media, content
        self.motion = motion
        self.artifacts: dict[str, Planned] = {}

    def add(self, name: str, key: CacheKey, board_id: str | None = None,
            content: str | None = None) -> str:
        if name in self.artifacts:
            raise _bad("an artifact name is planned twice", name)
        sha = self.content(key) if content is None else content
        self.artifacts[name] = Planned(name=name, key=key, content=sha, board_id=board_id)
        return sha

    def loop_frames(self) -> int:
        """N of a ping-pong loop (TIME-8a: 121): the motion profile's ``frames``, the
        one source for doll clips and the set loop (**proposal**: a library loop of
        another length needs its own N, which the library does not record yet)."""
        return thaw(self.tools.motion_profile)["frames"]

    def profile(self, base: Mapping[str, Any]) -> dict[str, Any]:
        return {**thaw(base), "delivery": self.media.delivery()}

    def keyed(self, board: Board, slot: str, clip: str, still: str) -> str:
        tools = self.tools
        return self.add(f"{board.id}/keyed/{slot}", keyed_frames_key(
            clip=clip, still=still, key_thresholds=tools.key_thresholds,
            protect_boxes=list(tools.protect_boxes), decal_box=tools.decal_box,
            decal_version=tools.decal_version, keyer=tools.keyer), board.id)

    def doll_layer(self, board: Board, slot: str, still: str) -> dict[str, Any]:
        tools = self.tools
        clip = self.add(f"{board.id}/doll_clip/{slot}", motion_clip_key(
            still=still, prompt=tools.motion_prompt, seed=tools.motion_seed,
            profile=self.profile(tools.motion_profile)), board.id)
        return {"slot": slot, "still": still, "clip": clip,
                "keyed": self.keyed(board, slot, clip, still), "role": "doll",
                "phase": loop_phase(board.id, slot, loop_period(self.loop_frames()))}

    def s2v_layer(self, board: Board, slot: str, still: str, clock: BoardClock,
                  voice: BoardVoice) -> dict[str, Any]:
        tools = self.tools
        lines = [(voice.takes[line.id].sha256, clock.spans[line.id].start_ms)
                 for line in board.lines if line.speaker == slot]
        drive = self.add(f"{board.id}/drive/{slot}", s2v_drive_track_key(
            speaker=slot, lines=lines, frames=clock.frames, fps=self.media.fps,
            rate=tools.drive_rate, assembler=tools.drive_assembler), board.id)
        seed = board.seeds.get(f"s2v:{slot}")
        if seed is None:
            raise _bad(f"no seed s2v:{slot} on the board (the server writes one)", board.id)
        clip = self.add(f"{board.id}/s2v_clip/{slot}", s2v_clip_key(
            drive_track=drive, start_still=still, prompt=tools.s2v_prompt,
            negative_prompt=tools.s2v_negative_prompt, seed=seed,
            profile=self.profile(tools.s2v_profile), adapter=tools.s2v_adapter), board.id)
        return {"slot": slot, "still": still, "clip": clip,
                "keyed": self.keyed(board, slot, clip, still), "role": "s2v", "phase": None}

    # The pinned path (story 426) -------------------------------------------------------

    def board_motion(self, board: Board) -> Any:
        """The board's resolved records; a blocking problem stops the plan with its own
        code (``motion.clip_absent`` for a cast still without a loop)."""
        assert self.motion is not None
        resolved = self.motion.boards.get(board.id)
        if resolved is None:
            raise _bad("the layered board's motion records are not resolved", board.id)
        if not resolved.complete:
            first = next(v for v in resolved.problems if v.status != "warning")
            raise CacheError(first.rule, first.message, where=f"{board.id}{first.path}")
        return resolved

    def pinned_keyed(self, board: Board, slot: str, clip: str, start: str, keying: Any) -> str:
        """The keyed frames of ``clip`` with a record's keying inputs; the decal's still
        is the clip's start image (story 457's proposal), the keyer carries its build."""
        if keying is None:  # the resolver refuses a doll clip without keying; kept explicit
            raise _bad(f"slot {slot}'s clip records no keying (motion.keying_missing)", board.id)
        assert self.motion is not None
        build = self.motion.keyer_build
        return self.add(f"{board.id}/keyed/{slot}", keyed_frames_key(
            clip=clip, still=start, key_thresholds=thaw(keying.key_thresholds),
            protect_boxes=[list(box) for box in keying.protect_boxes],
            decal_box=None if keying.decal_box is None else list(keying.decal_box),
            decal_version=keying.decal_version,
            keyer=keying.keyer if build is None else f"{keying.keyer}@{build}"), board.id)

    def pinned_doll(self, board: Board, slot: str, still: str, clip: Any) -> dict[str, Any]:
        """An idle doll from its pinned loop (TIME-8a): the library clip (not made by
        the build), its keyed frames, its N and its phase on this board."""
        record = clip.record
        self.add(f"{board.id}/doll_clip/{slot}", clip.identity.clip, board.id, content=clip.sha256)
        return {"slot": slot, "still": still, "clip": clip.sha256,
                "keyed": self.pinned_keyed(board, slot, clip.sha256, record.source.image_sha256,
                                           record.keying), "role": "doll",
                "phase": clip.phase, "play": "loop", "trim_start": record.trim_start,
                "trim_frames": record.trim_frames, "source_fps": record.fps,
                "clip_frames": record.frames, "decal_min_ecc": record.keying.decal_min_ecc}

    def pinned_s2v(self, board: Board, slot: str, still: str, clock: BoardClock,
                   voice: BoardVoice, loop: Any) -> dict[str, Any]:
        """A speaker's speech-to-video layer (TIME-8, TIME-9): her drive track; then a
        library timed clip made from it with the board's seed, or a clip the build makes
        from her loop's start image, keyed with her loop's keying inputs (**proposals**)."""
        tools = self.tools
        lines = [(voice.takes[line.id].sha256, clock.spans[line.id].start_ms)
                 for line in board.lines if line.speaker == slot]
        drive = self.add(f"{board.id}/drive/{slot}", s2v_drive_track_key(
            speaker=slot, lines=lines, frames=clock.frames, fps=self.media.fps,
            rate=tools.drive_rate, assembler=tools.drive_assembler), board.id)
        seed = board.seeds.get(f"s2v:{slot}")
        if seed is None:
            raise _bad(f"no seed s2v:{slot} on the board (the server writes one)", board.id)
        timed = None if self.motion.timed is None else self.motion.timed(slot, still, drive, clock.frames)
        if timed is not None and timed.record.source.seed == seed:
            # A library clip made from this drive track with the board's seed; another
            # seed is a re-roll, so the build makes a new clip (contract section 4).
            record = timed.record
            self.add(f"{board.id}/s2v_clip/{slot}", timed.identity.clip, board.id, content=timed.sha256)
            return {"slot": slot, "still": still, "clip": timed.sha256,
                    "keyed": self.pinned_keyed(board, slot, timed.sha256, record.source.image_sha256,
                                               record.keying), "role": "s2v",
                    "phase": None, "play": "timed", "trim_start": record.trim_start,
                    "trim_frames": record.trim_frames, "source_fps": record.fps,
                    "clip_frames": record.frames, "decal_min_ecc": record.keying.decal_min_ecc}
        start, keying = loop.record.source.image_sha256, loop.record.keying
        profile = self.profile(tools.s2v_profile)
        if list(profile.get("size", [])) != [loop.record.width, loop.record.height]:
            # The loop's keying boxes are in its own pixels; another clip size moves them.
            raise _bad(f"slot {slot}'s loop is {loop.record.width}x{loop.record.height}; the S2V "
                       f"profile makes {profile.get('size')}, where its keying boxes do not apply",
                       board.id)
        clip = self.add(f"{board.id}/s2v_clip/{slot}", s2v_clip_key(
            drive_track=drive, start_still=start, prompt=tools.s2v_prompt,
            negative_prompt=tools.s2v_negative_prompt, seed=seed, profile=profile,
            adapter=tools.s2v_adapter), board.id)
        keyed = self.pinned_keyed(board, slot, clip, start, keying)
        fs = profile["source_fps"]
        return {"slot": slot, "still": still, "clip": clip, "keyed": keyed, "role": "s2v",
                "phase": None, "play": "timed", "trim_start": 0,
                "trim_frames": source_frames_needed(clock.frames, fs, self.media.fps),
                "source_fps": fs, "clip_frames": None, "decal_min_ecc": self.motion.decal_min_ecc}

    def pinned_set(self, plate: str | None, clip: Any) -> dict[str, Any]:
        """The set layer: the plate and, when the story pins or the library promotes
        one, the set loop with its N and its phase on this board (TIME-8a)."""
        if clip is None:
            return {"plate": plate, "loop": None, "phase": None, "trim_start": None,
                    "trim_frames": None, "clip_frames": None}
        record = clip.record
        return {"plate": plate, "loop": clip.sha256, "phase": clip.phase,
                "trim_start": record.trim_start, "trim_frames": record.trim_frames,
                "clip_frames": record.frames}

    def compositor(self, board: Board) -> str:
        """The compositor digest of the board's method: the toolchain's one digest, or
        its entry for the board's method layer (story 406); a layer without an entry
        cannot be keyed."""
        compositor = self.tools.compositor
        if isinstance(compositor, str):
            return compositor
        if board.method.layer not in compositor:
            raise _bad(f"the toolchain names no compositor for {board.method.layer} boards", board.id)
        return compositor[board.method.layer]

    def board(self, board: Board, film_start: int) -> tuple[BoardPlan, dict[str, Any] | None,
                                                              list[dict[str, Any]]]:
        story, tools, media = self.story, self.tools, self.media
        voice = self.voices.get(board.id) if board.spoken else None
        clock = _clock(board, voice)
        track = None
        if board.spoken:
            assert voice is not None
            for line_id, key in take_keys(story, board, voice_ids=self.voice_ids, toolchain=tools).items():
                self.add(f"{board.id}/take/{line_id}", key, board.id, voice.takes[line_id].sha256)
            track = self.add(f"{board.id}/voice_track", track_key(board, voice.takes, tools),
                             board.id, voice.track_sha256)
        method = {"layer": board.method.layer, "motion": board.method.motion}
        if method_status(board.method.layer, board.method.motion) != "buildable":
            raise _bad(f"method {method} cannot be built (method.unavailable)", board.id)
        stills = {entry.slot: _resolve(self.blobs, entry.asset_version_id, f"{board.id}/cast/{entry.slot}")
                  for entry in board.cast}
        layers: list[dict[str, Any]] = []
        layout = set_layer = motion_style = foreground = whole_clip = None
        if board.method.layer == "layered":
            speakers = {line.speaker for line in board.lines}
            pinned = None if self.motion is None else self.board_motion(board)
            for entry in board.cast:  # draw order
                still = stills[entry.slot]
                if board.method.motion == "s2v" and entry.slot in speakers:
                    assert voice is not None
                    layers.append(self.s2v_layer(board, entry.slot, still, clock, voice) if pinned is None
                                  else self.pinned_s2v(board, entry.slot, still, clock, voice,
                                                       pinned.clip_for(entry.slot)))
                elif pinned is None:
                    layers.append(self.doll_layer(board, entry.slot, still))
                else:
                    layers.append(self.pinned_doll(board, entry.slot, still, pinned.clip_for(entry.slot)))
            if board.layout.preset not in story.layouts:
                raise _bad(f"layout preset {board.layout.preset!r} is not in the story", board.id)
            layout = thaw(story.layouts[board.layout.preset])
            story_set = story.set
            if story_set is not None and pinned is not None:
                set_layer = self.pinned_set(
                    None if story_set.asset_version_id is None else
                    _resolve(self.blobs, story_set.asset_version_id, "set"), pinned.set)
            elif story_set is not None:
                loop = (None if story_set.motion_asset_version_id is None else
                        _resolve(self.blobs, story_set.motion_asset_version_id, "set/motion"))
                set_layer = {
                    "plate": (None if story_set.asset_version_id is None else
                              _resolve(self.blobs, story_set.asset_version_id, "set")),
                    "loop": loop,
                    "phase": None if loop is None else loop_phase(board.id, SET_SLOT,
                                                                  loop_period(self.loop_frames()))}
            if story_set is not None:
                if board.layout.foreground and story_set.foreground_edge_px is not None:
                    foreground = {"edge_px": [list(p) for p in story_set.foreground_edge_px],
                                  "feather_px": story_set.foreground_feather_px}
            motion_style = None if story.motion_style is None else thaw(story.motion_style)
        else:  # whole_frame + i2v (whole_frame + s2v is refused above)
            photo = _resolve(self.blobs, board.photo.current_version_id, f"{board.id}/photo")
            seed = board.seeds.get("i2v:frame")
            if seed is None:
                raise _bad("no seed i2v:frame on the board (the server writes one)", board.id)
            needed = source_frames_needed(clock.frames, thaw(tools.i2v_profile)["source_fps"], media.fps)
            try:  # story 427's chain policy; a board past its chain limit cannot be built
                lengths = i2v_clip_lengths(needed, tools.i2v_clip_frames)
            except ValueError as error:
                raise _bad(f"whole-frame chain limit: {error}", board.id) from error
            whole_clip = self.add(f"{board.id}/whole_frame_clip", whole_frame_clip_key(
                photo=photo, prompt=tools.i2v_prompt, seed=seed,
                profile=self.profile(tools.i2v_profile), clip_lengths=lengths), board.id)
        segment = segment_key(
            method=method, frames=clock.frames, width=media.width, height=media.height,
            fps=media.fps, layout=layout, layers=layers, set_layer=set_layer,
            whole_frame_clip=whole_clip, motion_style=motion_style, voice_envelope=track,
            talk=[{"speaker": line.speaker, "start_ms": clock.spans[line.id].start_ms,
                   "end_ms": clock.spans[line.id].end_ms} for line in board.lines],
            cues=_picture_cues(board, clock), foreground=foreground,
            procedural_stream=board_stream(tools.procedural_seed, board.id),
            compositor=self.compositor(board), encoder=tools.encoder)
        self.add(f"{board.id}/segment", segment, board.id)
        voice_track = None if track is None else {
            "track": track, "start_frame": film_start,
            "spans": [[clock.spans[line.id].start_ms, clock.spans[line.id].end_ms] for line in board.lines]}
        sounds = []
        for cue in board.cues:
            if isinstance(cue, SoundCue):
                sounds.append({"sound": _resolve(self.blobs, cue.asset_version_id, f"{board.id}/{cue.id}"),
                               "start_sample": mix_sample(film_start, resolve_anchor(cue.anchor, clock)),
                               "trim_ms": None if cue.trim_ms is None else list(cue.trim_ms),
                               "level_rms_dbfs": cue.level_rms_dbfs})
        plan = BoardPlan(board_id=board.id, frames=clock.frames, film_start_frame=film_start,
                         segment=self.artifacts[f"{board.id}/segment"])
        return plan, voice_track, sounds

    def film(self) -> StoryPlan:
        story, tools = self.story, self.tools
        boards, tracks, sounds, start = [], [], [], 0
        for board in story.ordered_boards():
            plan, track, board_sounds = self.board(board, start)
            boards.append(plan)
            tracks.extend([track] if track else [])
            sounds.extend(board_sounds)
            start += plan.frames
        picture = self.add("film/picture", film_picture_key(
            segments=[(b.segment.content, b.frames) for b in boards], splicer=tools.splicer))
        beds = [{"sound": _resolve(self.blobs, bed.asset_version_id, f"beds/{bed.id}"),
                 "level_rms_dbfs": bed.level_rms_dbfs, "clock": bed.clock} for bed in story.beds]
        mix = self.add("film/mix", mix_key(
            voice_tracks=tracks, sounds=sounds, beds=beds, line_rms_dbfs=story.mix.line_rms_dbfs,
            master_lufs=story.mix.master_lufs, true_peak_dbtp=story.mix.true_peak_dbtp,
            frames=start, rate=tools.mix_rate, mixer=tools.mixer))
        master = self.add("film/master", master_key(picture=picture, mix=mix, mux=tools.mux))
        proxy = self.add("film/proxy", proxy_key(master=master, profile=tools.proxy_profile))
        made = {"film_picture": picture, "mix": mix, "master": master, "proxy": proxy}
        tolerances = None if story.checks.asr_tolerances is None else thaw(story.checks.asr_tolerances)
        script = [[line.speaker, line.text] for board in story.ordered_boards() for line in board.lines]
        for name, spec in sorted(tools.checks.items()):
            thresholds = dict(thaw(spec.get("thresholds", {})))
            if spec.get("transcript"):
                # Proposal: a transcript check compares the master with the script, so
                # the script (NFC, in film order) and the story's tolerances are inputs.
                thresholds["asr_tolerances"] = tolerances
                thresholds["script_sha256"] = make_key("script", {"lines": script}).hex
            self.add(f"check/{name}", check_result_key(artifact=made[spec["on"]], check=name,
                                                       version=spec["version"], thresholds=thresholds))
        return StoryPlan(artifacts=MappingProxyType(dict(self.artifacts)), boards=tuple(boards),
                         frames=start, film_picture=self.artifacts["film/picture"],
                         mix=self.artifacts["film/mix"], master=self.artifacts["film/master"],
                         proxy=self.artifacts["film/proxy"])


def plan_story(story: Story, *, voices: Mapping[str, BoardVoice], blobs: Mapping[str, str],
               voice_ids: Mapping[str, str], toolchain: Toolchain, media: MediaFormat,
               content: Content, motion: LayeredMotion | None = None) -> StoryPlan:
    """The key plan of a story with embedded boards (see the module docstring).
    ``voices`` maps each spoken board's ID to its current voice; ``blobs`` maps asset
    version IDs to content hashes; ``voice_ids`` maps voice versions to stock voice
    names. An untimed board, an unresolved asset or an unavailable method is
    ``cache.key_input_invalid``: the pre-build check refuses those first. ``motion``
    (story 426) plans the layered boards from pinned motion records; a blocking motion
    problem stops the plan with its own code (``motion.clip_absent`` and the others of
    story 457's resolver)."""
    if story.boards is None:
        raise _bad("the story's boards must be embedded", story.id)
    return _Planner(story, voices=voices, blobs=blobs, voice_ids=voice_ids, toolchain=toolchain,
                    media=media, content=content, motion=motion).film()
