"""Build a story from its boards (story 406): one run, from the draft to a verified
delivery, on the merged packages and nothing else.

    result = build_story(BuildInputs(story=draft, library=library, register=register,
                                     toolchain=Toolchain(...), studio="git:<commit>"),
                         store=store, phase="all", sources=sources, transcriber=whisper,
                         actor=operator)

In order:

1. **Pre-build check and snapshot** (:mod:`.prebuild`). A story whose snapshot cannot
   be pinned (an asset version the library does not hold) makes no run: the problems
   come back as ``PreflightError``. Otherwise the run is recorded ``queued`` with its
   snapshot, moved to ``running``, and a blocking problem fails it with the problem's
   code and board before any clip is asked for.
2. **The local pass** (:func:`_local_pass`): the whole story planned once with clip
   sources that only record the request they would send, so every drive track is
   made, every library timed clip resolved, every seed checked and every clip's inputs
   read before the first clip of any board is asked for. Then, in a phase that may ask
   a clip source (``all``, ``service``), the mix, which needs no clip, is made and its
   own checks run (:func:`_early_mix`). Any error fails the run here and no clip source
   has been asked.
3. **The plan** (story 380's :func:`~haynes_studio.cache.plan.plan_story`) with one
   content chain: the layered stages (drive tracks, speech-to-video clips, keyed
   frames, story 426), the whole-frame clip sets (story 427), one picture builder per
   method with its own renderer and compositor, the sound builder (story 841), and the
   transcript check (:mod:`.transcript`). The chain records, per artifact, its key, its
   hash, whether this run made it and how long it took.
4. **Checks, then delivery.** :func:`~haynes_studio.mix.film_sound` gives the mix's
   placement and the sound checks; every check on the master (sound and transcript)
   must pass before :func:`~haynes_studio.delivery.deliver` makes the phone proxy and
   publishes the delivery (``build.check_failed`` otherwise; nothing delivered). The
   plan's proxy key is answered after the plan, by the delivery: ``deliver`` makes the
   proxy itself (proposal).
5. **Verified success.** The delivery is read back (:func:`read_delivery`, which
   re-hashes the master, the proxy and the document) and must hold the plan's master;
   only then is the run ``succeeded``.

Any error stops the run as ``failed`` with its code, the board it was on and the
stage; every stage already completed stays in the store for the next run to reuse. A
live clip source's stop (:class:`~.errors.RunHeld`, story 851: any refusal of the Wan
client) records the run ``held`` instead, a safety stop a person reconciles, and nothing
further is asked of any source. A
failure after ``deliver`` returned names that delivery, whatever its read-back says. A
failure that cannot be written to the run's record raises
:class:`~.errors.RunUnrecorded` (``build.run_unrecorded``), naming the run and the
delivery; it is never returned as a result.

**Phases.** ``service`` fills the cache through the clip sources: drive tracks (the
clip requests' input), the mix and its checks (before any clip, the cheapest proof the
story's sound can be built) and the clips are made; keyed frames, segments, the film
picture, the master, its checks and the delivery are left to the offline phase, and
the run ends ``cancelled`` at that boundary (proposal: a run is not ``succeeded``
without a delivery), unless a transcript check it made or read of a cached master
failed: then it ends ``failed`` with ``build.check_failed``. ``offline`` is the same
build with sources that refuse every call (:func:`.sources.offline_sources`); it makes
the mix where the plan reaches it. ``all`` is both with the given sources.

**Live sources (story 851).** Sources that give ``check`` have it run on every clip
request of the local pass, in plan order, before the mix and before any clip is asked
for; a request the Wan client would refuse fails the run there. ``dry_run`` (the service
phase only) stops after those checks and the mix: the run ends ``cancelled`` and the
result lists the clip jobs the phase would request (``BuildResult.planned``), with
nothing asked of a service. Sources that give ``bind`` are given this run's cache before
any clip: the live chain source keeps each chain clip on it as soon as it is collected,
so a chain stopped part way gives a later run its earlier clips; the board stage lists
each kept clip (``artifacts`` kind ``wan_chain_clip``, made or reused).

**Workers.** With ``workers`` over 1 the plan runs twice after the local pass: once to
make every clip and keyed frame and collect the segments the cache lacks, which up to
``workers`` processes render and commit (each at the two-thread rule), and once more,
when every segment is a hit. The cache's create-only stages make two writers of one
artifact safe.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from haynes_studio.build.errors import (
    CHECK_FAILED,
    DELIVERY_UNVERIFIED,
    VOICE_TRACK_MISSING,
    BuildError,
    RunHeld,
    RunUnrecorded,
    failure_of,
)
from haynes_studio.build.live import KEPT, PlannedClip, planned_clips
from haynes_studio.build.prebuild import Prepared, make_snapshot, prepare, snapshot_bytes
from haynes_studio.build.provenance import Register, Use, library_uses, provenance, toolchain_record
from haynes_studio.build.run import (
    CANCELLED,
    FAILED,
    HELD,
    RUNNING,
    SUCCEEDED,
    RunRecords,
    advance,
    new_run,
)
from haynes_studio.build.sources import ClipRequested, ClipSources, recording_sources
from haynes_studio.build.transcript import CHECK as TRANSCRIPT, Transcriber, TranscriptChecks, check_spec
from haynes_studio.cache import ArtifactCache, BoardVoice, MediaFormat, StoryPlan, TakeFacts, plan_story
from haynes_studio.cache.build import PictureBuilder
from haynes_studio.cache.keys import (
    CHECK_RESULT,
    FILM_PICTURE,
    KEYED_FRAMES,
    MASTER,
    MIX,
    PROXY,
    S2V_CLIP,
    S2V_DRIVE_TRACK,
    SEGMENT,
    WHOLE_FRAME_CLIP,
    CacheKey,
)
from haynes_studio.cache.plan import LayeredMotion, Toolchain
from haynes_studio.canonical.ids import Minter, is_id
from haynes_studio.delivery import Delivery, deliver, read_delivery
from haynes_studio.delivery.model import MASTER_SIZES
from haynes_studio.delivery.publish import RECORD as DELIVERY_DOCUMENT, STAGE as DELIVERY_STAGE
from haynes_studio.jsonio import thaw
from haynes_studio.layered import COMPOSITOR as LAYERED_COMPOSITOR
from haynes_studio.layered import LayeredRenderer, LayeredStages, reader
from haynes_studio.layered.keyed import keyer_build
from haynes_studio.layered.s2v import read_provenance, record_stage
from haynes_studio.library import Library
from haynes_studio.mix import SoundBuilder, film_sound, sound_toolchain
from haynes_studio.stages import completed_stage
from haynes_studio.stages.preflight import PreflightError
from haynes_studio.store import LocalStore, Store, blob_locator, is_sha256
from haynes_studio.voice import Engine
from haynes_studio.wholeframe import COMPOSITOR as WHOLE_FRAME_COMPOSITOR
from haynes_studio.wholeframe import WholeFrameClips, WholeFrameRenderer
from haynes_studio.wholeframe.clips import IMAGE_TYPES, read_clip_set

ALL, SERVICE, OFFLINE = "all", "service", "offline"
PHASES = (ALL, SERVICE, OFFLINE)
JSON, MP4 = "application/json", "video/mp4"
COMPOSITORS = {"layered": LAYERED_COMPOSITOR, "whole_frame": WHOLE_FRAME_COMPOSITOR}
SERVICE_KINDS = frozenset({S2V_DRIVE_TRACK, S2V_CLIP, WHOLE_FRAME_CLIP})
# What the service phase looks up rather than makes, by kind (the cached artifact's type).
CACHED_MEDIA = {KEYED_FRAMES: "image/png", SEGMENT: "video/mp4", FILM_PICTURE: "video/mp4",
                MIX: "audio/wav", MASTER: "video/mp4"}
FILM_KINDS = frozenset({FILM_PICTURE, MIX, MASTER, PROXY, CHECK_RESULT})
PLAN = "plan"  # the stage of a refusal the plan makes itself (a missing seed, ...)


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class BuildInputs:
    """What a build reads: the draft (boards embedded), the library, the model licence
    register (JSON), the toolchain's profiles and the studio commit (``git:<sha>``)."""

    story: Mapping[str, Any]
    library: Library
    register: Mapping[str, Any]
    toolchain: Toolchain = field(default_factory=Toolchain)
    studio: str = "git:unknown"
    image_digest: str | None = None


@dataclass(frozen=True)
class BuildResult:
    """The run as recorded last, and what the build made (for tests and the CLI)."""

    run: Mapping[str, Any]
    plan: StoryPlan | None = None
    made: tuple[str, ...] = ()  # key values this run made
    source_calls: int = 0
    worker_made: tuple[str, ...] = ()  # segment keys worker processes rendered
    planned: tuple[PlannedClip, ...] = ()  # the clip jobs the local pass found missing, in order


def media_format(media_kind: str) -> MediaFormat:
    """The media kind's delivery picture (section 8: the master is the media kind's
    frame size at 24 fps)."""
    width, height = MASTER_SIZES[media_kind]
    return MediaFormat(width=width, height=height)


def build_toolchain(base: Toolchain) -> Toolchain:
    """``base`` with each method's compositor, the transcript check, and the mixer and
    mux of story 841 (the key inputs this build's builders must match)."""
    return sound_toolchain(replace(base, compositor=dict(COMPOSITORS),
                                   checks={TRANSCRIPT: check_spec()}))


def _stand_in(key: CacheKey) -> str:
    """A content hash for an artifact this pass does not make: a function of the key,
    never recorded as an artifact."""
    return hashlib.sha256(b"deferred:" + key.value.encode()).hexdigest()


@dataclass
class Made:
    """One content answer: the key, the hash, whether this run made it, the time."""

    key: str
    kind: str
    sha256: str
    made: bool
    seconds: float
    board_id: str | None
    deferred: bool = False


class _Chain:
    """The plan's content chain (see the module docstring), recording each answer.

    ``defer`` kinds are answered with a stand-in (the first pass with workers). With
    ``service`` set, only the service phase's kinds are made (clips, and the transcript
    of a master the cache already holds); every other artifact is looked up in the cache
    and, when it is not there, answered with a stand-in, so nothing is rendered, mixed
    or delivered and no stand-in reaches a service. With ``local`` set, it is the local
    pass (:func:`_local_pass`): drive tracks are made, each clip is a checked cache hit
    or a request the recording sources keep (a stand-in), and every other artifact is
    looked up, never made."""

    def __init__(self, build: _Build, *, defer: frozenset[str] = frozenset(),
                 service: bool = False, local: bool = False):
        self.build = build
        self.defer = defer
        self.service = service
        self.local = local
        self.segments_seen = 0
        self.records: dict[str, Made] = {}
        self.segment_board: dict[str, str] = {}
        self.segment_keys: dict[str, CacheKey] = {}
        self.stand_ins: set[str] = set()

    def _local_answer(self, key: CacheKey) -> str | None:
        """The local pass's answer, or ``None`` for a stand-in."""
        build, kind = self.build, key.kind
        if kind == S2V_DRIVE_TRACK:  # made here: a local stage, the clip request's input
            return build.route(key)
        if kind in (S2V_CLIP, WHOLE_FRAME_CLIP):
            try:  # the adapter checks the profile, a hit, and reads the request's inputs
                return build.local_clip(key)
            except ClipRequested:  # recorded by the recording source; nothing was asked
                return None
        media = CACHED_MEDIA.get(kind)
        found = None if media is None else build.cache.lookup(key, media)
        return None if found is None else found.sha256

    def _service_answer(self, key: CacheKey) -> str | None:
        """The service phase's answer, or ``None`` for a stand-in."""
        build, kind = self.build, key.kind
        if kind in SERVICE_KINDS:
            return build.route(key)
        if kind == CHECK_RESULT:  # a transcript, only of a master the cache holds
            if key.document.get("artifact") in self.stand_ins or not build.transcript.handles(key):
                return None
            return build.route(key)
        media = CACHED_MEDIA.get(kind)
        found = None if media is None else build.cache.lookup(key, media)
        return None if found is None else found.sha256

    def board_id(self, kind: str) -> str | None:
        if kind in FILM_KINDS:
            return None
        boards = self.build.boards
        return boards[self.segments_seen] if self.segments_seen < len(boards) else None

    def __call__(self, key: CacheKey) -> str:
        build, kind = self.build, key.kind
        board_id = self.board_id(kind)
        build.where = (board_id, kind)
        before = len(build.cache.stats.made)
        start = build.timer()
        if kind in self.defer:
            sha = None
        elif self.local:
            sha = self._local_answer(key)
        elif self.service:
            sha = self._service_answer(key)
        else:
            sha = build.route(key)
        deferred = sha is None
        if sha is None:
            sha = _stand_in(key)
            self.stand_ins.add(sha)
        seconds = round(max(0.0, build.timer() - start), 3)
        made = key.value in build.cache.stats.made[before:]
        self.records[key.value] = Made(key.value, kind, sha, made, seconds, board_id, deferred)
        stopped = build.sources.stopped
        stop = None if self.local or stopped is None else stopped()
        if stop is not None:  # a live source kept a clip and stopped: held, right after it
            raise stop
        if kind == SEGMENT:
            self.segment_board[key.value] = board_id or ""
            self.segment_keys[key.value] = key
            self.segments_seen += 1
        if self.local:  # what the plan refuses before its next answer (a seed) is the plan's
            build.where = (self.board_id(PLAN), PLAN)
        return sha


class _Build:
    """One run's build: the cache, the stages and builders, the content chain."""

    def __init__(self, *, store: Store, story: Any, prepared: Prepared, run_id: str,
                 earlier_runs: Sequence[str], sources: ClipSources, transcriber: Transcriber | None,
                 toolchain: Toolchain, media: MediaFormat, timer: Callable[[], float],
                 workdir: str | None):
        self.store, self.story, self.prepared = store, story, prepared
        self.production_id = story.production_id
        self.run_id, self.earlier_runs = run_id, tuple(earlier_runs)
        self.toolchain, self.media, self.timer = toolchain, media, timer
        self.boards = [board.id for board in story.ordered_boards()]
        self.where: tuple[str | None, str | None] = (None, "plan")
        self.cache = ArtifactCache(store, production_id=self.production_id, run_id=run_id,
                                   earlier_runs=self.earlier_runs)
        read = reader(store, [self.production_id, "library"])
        self.read = read
        self.sources = sources
        if sources.bind is not None:  # a live chain source keeps each clip on this run's cache
            sources.bind(self.cache)
        read_photo = reader(store, [self.production_id, "library"], IMAGE_TYPES)
        self.layered = LayeredStages(self.cache, sources.s2v, read=read)
        self.wholeframe = WholeFrameClips(self.cache, sources.i2v, read_photo=read_photo)
        # The local pass's clip stages: the same adapters on the same cache, with sources
        # that record each request and make nothing (see _local_pass).
        self.recording = recording_sources()
        self.local_layered = LayeredStages(self.cache, self.recording.s2v, read=read)
        self.local_wholeframe = WholeFrameClips(self.cache, self.recording.i2v,
                                                read_photo=read_photo)
        self.renderers = {LAYERED_COMPOSITOR: LayeredRenderer(),
                          WHOLE_FRAME_COMPOSITOR: WholeFrameRenderer()}
        self.pictures = {name: PictureBuilder(self.cache, renderer, open_input=read)
                         for name, renderer in self.renderers.items()}
        self.sound = SoundBuilder(self.cache, story=story, workdir=workdir)
        self.transcript = TranscriptChecks(self.cache, transcriber, story)
        self.worker_reports: dict[str, dict[str, Any]] = {}
        self.worker_made: list[str] = []  # segment keys worker processes made

    def route(self, key: CacheKey) -> str:
        kind = key.kind
        if self.layered.handles(key):
            return self.layered(key)
        if kind == WHOLE_FRAME_CLIP:
            return self.wholeframe(key)
        if kind == SEGMENT:
            builder = self.pictures.get(key.document["compositor"])
            if builder is None:
                raise BuildError("cache.entry_invalid", f"no renderer draws compositor "
                                 f"{key.document['compositor']!r}", stage=SEGMENT)
            return builder.segment(key).sha256
        if kind == FILM_PICTURE:
            return next(iter(self.pictures.values())).film_picture(key).sha256
        if kind in (MIX, MASTER):
            return self.sound(key)
        if kind == PROXY:
            return _stand_in(key)  # the delivery makes the proxy (see the module docstring)
        if kind == CHECK_RESULT and self.transcript.handles(key):
            return self.transcript(key)
        raise BuildError("cache.key_input_invalid", f"this build makes no {kind} artifact",
                         stage=kind)

    def local_clip(self, key: CacheKey) -> str:
        """A clip key through the local pass's stages: a checked hit, else the stage
        builds its request and the recording source raises ``ClipRequested``."""
        if key.kind == S2V_CLIP:
            return self.local_layered(key)
        return self.local_wholeframe(key)

    def plan(self, chain: _Chain) -> StoryPlan:
        prepared = self.prepared
        return plan_story(self.story, voices=_voices(self.story, prepared.document, prepared),
                          blobs=_blobs(prepared), voice_ids=_voice_ids(prepared),
                          toolchain=self.toolchain, media=self.media, content=chain,
                          motion=self._located(prepared.motion))

    def _located(self, motion: LayeredMotion | None) -> LayeredMotion | None:
        """``motion`` whose library timed-clip lookup marks where the build is: a timed
        clip answers the speaker's ``s2v_clip``, so a damaged one fails at that stage."""
        if motion is None or motion.timed is None:
            return motion
        timed = motion.timed

        def located(slot: str, still: str, drive: str, frames: int) -> Any:
            self.where = (self.where[0], S2V_CLIP)
            return timed(slot, still, drive, frames)
        return replace(motion, timed=located)

    def source_calls(self) -> int:
        return len(getattr(self.sources.s2v, "calls", ())) + len(getattr(self.sources.i2v, "calls", ()))


def _blobs(prepared: Prepared) -> dict[str, str]:
    return {item.version_id: item.sha256 for item in prepared.resolution.resolved
            if item.sha256 is not None}


def _voice_ids(prepared: Prepared) -> dict[str, str]:
    """Each voice version's stock voice name (the asset's ``voice_id``, VOICE-1)."""
    out = {}
    for item in prepared.resolution.resolved:
        if item.kind == "voice":
            voice_id = prepared.library.asset_of(item.version_id).attributes.get("voice_id")
            if isinstance(voice_id, str):
                out[item.version_id] = voice_id
    return out


def _voices(story: Any, document: Mapping[str, Any], prepared: Prepared) -> dict[str, BoardVoice]:
    """Each spoken board's current voice from the library: take hashes and lengths and
    the track's hash (story 380's ``BoardVoice``)."""
    library = prepared.library
    out = {}
    for board in story.boards or ():
        if not board.spoken or board.voice.current_version_id is None:
            continue
        version = library.version(board.voice.current_version_id)
        voice = version.voice
        if voice is None or voice.track is None:  # a legacy version records no track
            raise BuildError(VOICE_TRACK_MISSING, f"board voice {version.id} has no assembled "
                             "track, which the picture's envelope and the mix read; voice the "
                             "board again (`studio voice`) to make one", board_id=board.id,
                             stage="voice")
        out[board.id] = BoardVoice(
            takes={take.line_id: TakeFacts(sha256=take.sha256, duration_ms=take.duration_ms)
                   for take in voice.takes},
            track_sha256=voice.track.sha256)
    return out


# The run record -------------------------------------------------------------------------


def _check_entry(check: Mapping[str, Any]) -> dict[str, Any]:
    """A renderer's decal check as a run check."""
    return {"check": check["check"], "result": "pass" if check["passed"] else "fail",
            "artifact": check["artifact"], "key": check["key"], "version": str(check["version"]),
            "thresholds": check["thresholds"], "measured": check["result"]}


class _Recorder:
    """Turns the plan and the chain's answers into the run's stages and provenance."""

    def __init__(self, build: _Build, plan: StoryPlan, records: Mapping[str, Made],
                 register: Register):
        self.build, self.plan, self.records, self.register = build, plan, records, register
        self.uses: dict[str, Use] = {}
        self.unregistered: dict[str, dict[str, Any]] = {}
        self.library_inputs: set[str] = set()

    def find_stage(self, stage: str):
        return self.build.cache.finder.find(stage)

    def made(self, key: str) -> tuple[bool, float | None]:
        """Whether this run made the artifact (here or in a worker), and how long it took."""
        if key in self.build.worker_made:
            return True, self.build.worker_reports[key]["seconds"]
        found = self.records.get(key)
        if found is not None and found.made:
            return True, found.seconds
        return False, None

    def use(self, key: str | None, role: str, artifact: str, *, files: Mapping[str, str] | None = None,
            hardware: Any = None, profile: Mapping[str, Any] | None = None) -> None:
        if key is None:
            key = f"unregistered-{role}-clip-engine"
            self.unregistered.setdefault(key, {"name": f"unrecorded {role} engine", "role": role})
        use = self.uses.setdefault(key, Use(role=role))
        use.used_by.append(artifact)
        use.files.update({str(k): str(v) for k, v in (files or {}).items()})
        if isinstance(hardware, str) and use.hardware is None:
            use.hardware = hardware
        if profile is not None:
            use.profile = profile

    def s2v_clip(self, name: str, slot: str, planned: Any, made: Made | None) -> dict[str, Any]:
        entry: dict[str, Any] = {"role": "s2v_clip", "slot": slot, "sha256": planned.content,
                                 "key": planned.key.value, "made": bool(made and made.made)}
        motion = self.build.prepared.motion
        record_doc = None
        stage = self.find_stage(record_stage(planned.content))
        if stage is not None:
            with self.build.store.open(stage.blobs["record"].locator) as handle:
                record_doc = read_provenance(handle.read())
        if record_doc is not None:
            clip = record_doc["clip"]
            entry.update({"frames": clip["frames_delivered"], "fps": record_doc["source_fps"],
                          "requested_length": clip["frames_requested"], "seed": record_doc["seed"],
                          "engine": clip["engine"], "engine_job_id": clip["engine_job_id"],
                          "files_sha256": dict(clip["files_sha256"]), "trimmed": clip["trimmed"],
                          "render_s": made.seconds if made and made.made else None})
            profile = thaw(self.build.toolchain.s2v_profile)
            self.use(self.register.engine_for_model_file(profile.get("model", "")), "video", name,
                     files=clip["files_sha256"], hardware=(clip.get("extra") or {}).get("hardware"),
                     profile=profile)
        elif motion is not None and motion.timed is not None:  # a library timed clip
            version = self._library_clip(planned.content)
            if version is not None:
                entry["library_version_id"] = version
                self.library_inputs.add(version)
        return entry

    def _library_clip(self, sha256: str) -> str | None:
        library = self.build.prepared.library
        for version in library.search(kind="motion"):
            if version.content is not None and version.content.sha256 == sha256:
                return version.id
        return None

    def whole_frame(self, name: str, planned: Any, made: Made | None) -> dict[str, Any]:
        entry: dict[str, Any] = {"role": "whole_frame_clip", "slot": None, "sha256": planned.content,
                                 "key": planned.key.value, "made": bool(made and made.made)}
        try:
            with self.build.store.open(blob_locator(self.build.production_id, planned.content, JSON)) as h:
                clip_set = read_clip_set(h.read(), planned.content)
        except Exception:  # noqa: BLE001 - a record the run cannot read is not invented
            return entry
        clips = [{"index": c["index"], "sha256": c["sha256"], "frames_requested": c["frames_requested"],
                  "frames_delivered": c["frames_delivered"], "seed": c["seed"], "engine": c["engine"],
                  "engine_job_id": c["engine_job_id"], **self._kept(c)}
                 for c in clip_set.get("clips", [])]
        entry.update({"seed": clip_set.get("seed"), "fps": clip_set.get("source_fps"),
                      "requested_length": sum(clip_set.get("clip_lengths", [])) or None,
                      "chunks": len(clips), "clips": clips,
                      "render_s": made.seconds if made and made.made else None})
        profile = thaw(self.build.toolchain.i2v_profile)
        for clip in clip_set.get("clips", []):
            self.use(self.register.engine_for_model_file(profile.get("model", "")), "video", name,
                     files=clip.get("files_sha256"), hardware=(clip.get("extra") or {}).get("hardware"),
                     profile=profile)
        return entry

    def _kept(self, clip: Mapping[str, Any]) -> dict[str, Any]:
        """Where a chain clip came from (story 851): the key the live chain source kept it
        under, and whether this run collected it (``made``) or found it kept by an earlier
        run. Nothing for a clip no live source kept."""
        kept = (clip.get("extra") or {}).get("kept")
        if not isinstance(kept, Mapping) or not isinstance(kept.get("key"), str) \
                or not is_sha256(kept["key"].removeprefix("sha256:")):
            return {}
        return {"kept": {"key": kept["key"], "made": kept.get("run_id") == self.build.run_id}}

    def stages(self) -> list[dict[str, Any]]:
        build, plan = self.build, self.plan
        motion = build.prepared.motion
        by_board: dict[str, list[tuple[str, Any]]] = {}
        for name, planned in plan.artifacts.items():
            if planned.board_id is not None:
                by_board.setdefault(planned.board_id, []).append((name, planned))
        story_boards = {board.id: board for board in build.story.ordered_boards()}
        out = []
        for board_plan in plan.boards:
            board = story_boards[board_plan.board_id]
            artifacts, clips = [], []
            pinned = None if motion is None else motion.boards.get(board.id)
            for name, planned in by_board.get(board.id, []):
                made = self.records.get(planned.key.value)
                if made is not None and made.deferred:  # not made in this phase: no hash to record
                    continue
                was_made, seconds = self.made(planned.key.value)
                artifacts.append({"name": name.split("/", 1)[1], "kind": planned.key.kind,
                                  "key": planned.key.value, "sha256": planned.content,
                                  "made": was_made, "seconds": seconds})
                parts = name.split("/")
                if parts[1] == "s2v_clip":
                    clips.append(self.s2v_clip(name, parts[2], planned, made))
                elif parts[1] == "doll_clip":
                    clip = None if pinned is None else pinned.clip_for(parts[2])
                    entry = {"role": "doll_clip", "slot": parts[2], "sha256": planned.content,
                             "key": planned.key.value, "made": False}
                    if clip is not None:
                        entry.update({"library_version_id": clip.version_id, "frames": clip.record.frames,
                                      "fps": clip.record.fps, "seed": clip.record.source.seed})
                        self.library_inputs.add(clip.version_id)
                    clips.append(entry)
                elif parts[1] == "whole_frame_clip":
                    entry = self.whole_frame(name, planned, made)
                    clips.append(entry)
                    artifacts.extend(  # each chain clip a live source kept, made or reused
                        {"name": f"{KEPT}/{c['index']}", "kind": KEPT, "key": c["kept"]["key"],
                         "sha256": c["sha256"], "made": c["kept"]["made"], "seconds": None}
                        for c in entry.get("clips", ()) if "kept" in c)
            if pinned is not None and pinned.set is not None:
                clips.append({"role": "set_loop", "slot": None, "sha256": pinned.set.sha256,
                              "made": False, "library_version_id": pinned.set.version_id,
                              "frames": pinned.set.record.frames, "fps": pinned.set.record.fps})
                self.library_inputs.add(pinned.set.version_id)
            segment = board_plan.segment
            _, render_s = self.made(segment.key.value)
            report, checks = self.report(segment.key.value)
            seg_record = self.records.get(segment.key.value)
            deferred = seg_record is not None and seg_record.deferred
            out.append({"board_id": board.id, "board_number": board.number,
                        "method": {"layer": board.method.layer, "motion": board.method.motion},
                        "frames": board_plan.frames, "film_start_frame": board_plan.film_start_frame,
                        "clips": clips, "segment_sha256": None if deferred else segment.content,
                        "segment_key": None if deferred else segment.key.value,
                        "compositor": segment.key.document["compositor"],
                        "artifacts": artifacts, "report": report, "checks": checks,
                        "render_s": render_s})
        return out

    def report(self, key: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """The renderer's report and checks of a segment rendered in this run (in this
        process or a worker); a reused segment has none (its run recorded them)."""
        if key in self.build.worker_reports:
            found = self.build.worker_reports[key]
            return found["report"], [_check_entry(c) for c in found["checks"]]
        for renderer in self.build.renderers.values():
            if key in renderer.reports:
                checks = getattr(renderer, "checks", {}).get(key, [])
                return renderer.reports[key].to_document(), [_check_entry(c) for c in checks]
        return None, []


def _check_entries(results: Any) -> list[dict[str, Any]]:
    """Sound check results (story 841's ``CheckResult``) as run checks."""
    return [{"check": r.check, "result": "pass" if r.passed else "fail", "key": r.key.value,
             "sha256": r.sha256, "version": str(r.document.get("version")),
             "thresholds": r.document.get("thresholds"), "measured": r.document.get("measured")}
            for r in results]


def _sound_checks(sound: Any) -> list[dict[str, Any]]:
    return _check_entries(sound.checks)


def _transcript_entry(result: Mapping[str, Any], key: str, sha256: str) -> dict[str, Any]:
    measured = dict(result["measured"])
    return {"check": TRANSCRIPT, "result": result["result"], "key": key, "sha256": sha256,
            "version": str(result["version"]), "thresholds": result["thresholds"],
            "measured": measured, "tolerances_used": list(measured.get("tolerances_used", []))}


# The build ------------------------------------------------------------------------------


def build_story(inputs: BuildInputs, *, store: Store, phase: str, sources: ClipSources,
                transcriber: Transcriber | None, actor: Mapping[str, Any],
                earlier_runs: Sequence[str] = (), now: Callable[[], str] = utc_now,
                timer: Callable[[], float] = time.perf_counter, minter: Minter | None = None,
                workers: int = 1, run_number: int = 1, idempotency_key: str | None = None,
                workdir: str | None = None, delivery_id: str | None = None,
                dry_run: bool = False) -> BuildResult:
    """Build ``inputs.story`` as one new run (see the module docstring). ``sources``
    are the clip sources of this phase (the offline ones refuse); ``transcriber`` is
    the recognizer of the transcript check, a service: the offline phase never uses it
    and reads cached check results only. ``earlier_runs`` (newest first) are searched
    for cached artifacts. ``dry_run`` (service phase only) stops before any clip is
    asked for and lists the clip jobs (see the module docstring). Returns the run as
    last recorded."""
    if phase not in PHASES:
        raise ValueError(f"phase is one of {', '.join(PHASES)}, got {phase!r}")
    if dry_run and phase != SERVICE:
        raise ValueError("a dry run is of the service phase")
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise ValueError(f"workers is a positive integer, got {workers!r}")
    minter = minter or Minter()
    library = inputs.library
    media_kind = inputs.story.get("media_kind")
    if media_kind not in MASTER_SIZES:
        raise ValueError(f"the story's media kind {media_kind!r} has no delivery size")
    media = media_format(media_kind)
    toolchain = build_toolchain(inputs.toolchain)
    prepared = prepare(inputs.story, library=library, store=store, toolchain=toolchain,
                       frame_size=(media.width, media.height),
                       current_engine=Engine().signing_name)
    if phase == OFFLINE:  # the recognizer is a service: the offline phase reads the cache only
        transcriber = None
    return _build(inputs, prepared, store=store, phase=phase, sources=sources,
                  transcriber=transcriber, actor=actor, earlier_runs=earlier_runs, now=now,
                  timer=timer, minter=minter, workers=workers, run_number=run_number,
                  idempotency_key=idempotency_key, workdir=workdir, media=media,
                  toolchain=toolchain, delivery_id=delivery_id, dry_run=dry_run)


def _build(inputs: BuildInputs, prepared: Prepared, *, store: Store, phase: str,
           sources: ClipSources, transcriber: Transcriber | None, actor: Mapping[str, Any],
           earlier_runs: Sequence[str], now: Callable[[], str], timer: Callable[[], float],
           minter: Minter, workers: int, run_number: int, idempotency_key: str | None,
           workdir: str | None, media: MediaFormat, toolchain: Toolchain,
           delivery_id: str | None, dry_run: bool = False) -> BuildResult:
    library = inputs.library
    if prepared.story is None:  # a draft that breaks a write rule cannot be snapshotted
        raise PreflightError("<story>", prepared.report)
    try:
        snapshot = make_snapshot(prepared, library, studio=inputs.studio)
    except AssertionError as error:  # a reference the library does not hold
        if not prepared.report.ok:
            raise PreflightError("<story>", prepared.report) from error
        raise
    data, sha = snapshot_bytes(snapshot)
    story = prepared.story
    production = story.production_id
    run_id = minter.mint("run")
    records = RunRecords(store, production)
    run = new_run(run_id=run_id, story_id=story.id, number=run_number, phase=phase, snapshot={
        "sha256": sha, "story_revision": story.revision, "board_count": len(story.boards or ()),
        "locator": blob_locator(production, sha, JSON)}, queued_by=actor, queued_at=now(),
        idempotency_key=idempotency_key)
    records.create(run, data)
    run = records.write(advance(run, RUNNING, at=now(), by=actor, reason=f"build started ({phase} phase)"))
    build: _Build | None = None
    plan: StoryPlan | None = None
    checks: list[dict[str, Any]] | None = None
    stages: list[dict[str, Any]] = []
    checked_locally = False
    delivered: Delivery | None = None
    planned: tuple[PlannedClip, ...] = ()
    try:
        prepared.ensure_buildable()
        scratch = tempfile.TemporaryDirectory(prefix="studio-build-", dir=workdir)
        with scratch as scratch_dir:
            build = _Build(store=store, story=story, prepared=prepared, run_id=run_id,
                           earlier_runs=earlier_runs, sources=sources, transcriber=transcriber,
                           toolchain=toolchain, media=media, timer=timer, workdir=scratch_dir)
            register = Register(inputs.register)
            local, local_plan = _local_pass(build)  # no clip is asked for before this passes
            planned = _check_requests(build, local, local_plan, check=None if phase == OFFLINE
                                      else sources.check)
            mix_checks: list[dict[str, Any]] = []
            if phase != OFFLINE:  # a phase that may ask a clip source: the sound first
                mix_checks = checks = _early_mix(build, local_plan)
                failed = [c["check"] for c in mix_checks if c["result"] == "fail"]
                if failed:
                    raise BuildError(CHECK_FAILED, "checks of the mix did not pass: "
                                     + ", ".join(failed), stage="checks")
            checked_locally = True
            if dry_run:  # everything the service phase does before its first clip, and no more
                run = records.write(advance(
                    run, CANCELLED, at=now(), by=actor, checks=checks or None,
                    progress={"percent": 100, "stage": "dry_run"},
                    reason=f"dry run of the service phase: {len(planned)} clip jobs would be "
                           f"requested; the mix passed its {len(mix_checks)} checks; nothing was "
                           "asked of a service"))
                return BuildResult(run, local_plan, tuple(build.cache.stats.made), 0,
                                   planned=planned)
            if phase == SERVICE:
                chain = _Chain(build, service=True)
                plan = build.plan(chain)
                _keep_made(chain.records, local)
                recorder = _Recorder(build, plan, chain.records, register)
                stages = recorder.stages()
                checks = [*mix_checks, *_service_checks(build, plan, chain.records)] or None
                failed = [c["check"] for c in checks or () if c["result"] == "fail"]
                if failed:  # a cached master's transcript did not pass: never "complete"
                    build.where = (None, "checks")
                    raise BuildError(CHECK_FAILED, "checks of the cached master did not pass, so "
                                     "it will not be delivered: " + ", ".join(failed), stage="checks")
                made = sum(1 for m in chain.records.values() if m.made and m.kind in (S2V_CLIP, WHOLE_FRAME_CLIP))
                checked = sum(1 for m in chain.records.values() if m.made and m.kind == CHECK_RESULT)
                run = records.write(advance(
                    run, CANCELLED, at=now(), by=actor, stages=stages, checks=checks,
                    progress={"percent": 100, "stage": "service_phase_complete"},
                    reason=f"service phase complete: the mix passed its {len(mix_checks)} checks; "
                           f"{made} clip artifacts made and {checked} transcript checks run, the "
                           "rest found in the cache; build the picture with --offline (proposal: "
                           "a run without a delivery is never succeeded)"))
                return BuildResult(run, plan, (*build.cache.stats.made, *build.worker_made),
                                   build.source_calls(), planned=planned)
            first_pass: dict[str, Made] = {}
            if workers > 1:
                first_pass = _render_in_workers(build, workers)
            chain = _Chain(build)
            plan = build.plan(chain)
            _keep_made(chain.records, local, first_pass)
            build.where = (None, "checks")
            sound = film_sound(story, plan, build.sound)
            checks = _sound_checks(sound)
            transcript_key = plan.artifacts.get(f"check/{TRANSCRIPT}")
            if transcript_key is not None:
                result = build.transcript.result(transcript_key.content)
                checks.append(_transcript_entry(result, transcript_key.key.value, transcript_key.content))
            recorder = _Recorder(build, plan, chain.records, register)
            stages = recorder.stages()
            failed = [c["check"] for c in checks if c["result"] == "fail"]
            for stage in stages:
                failed += [f"{c['check']} ({stage['board_id']})" for c in stage["checks"]
                           if c["result"] == "fail"]
            if failed:
                raise BuildError(CHECK_FAILED, "checks did not pass, so nothing was delivered: "
                                 + ", ".join(failed), stage="checks")
            if transcript_key is not None and "asr" in register.engines:
                recorder.use("asr", "check", f"check/{TRANSCRIPT}")
            library_uses(register, library, _input_versions(prepared, recorder), recorder.uses,
                         recorder.unregistered)
            prov = provenance(register=register, uses=recorder.uses, unregistered=recorder.unregistered,
                              library=library, inputs=_input_versions(prepared, recorder),
                              toolchain=toolchain_record(studio=inputs.studio, image_digest=inputs.image_digest,
                                                         tools=_tools(toolchain)))
            outputs = {"frames": plan.frames, "fps": media.fps,
                       "picture_sha256": plan.film_picture.content, "mix_sha256": plan.mix.content,
                       "master_sha256": plan.master.content, "proxy_sha256": None,
                       "keys": {"film_picture": plan.film_picture.key.value, "mix": plan.mix.key.value,
                                "master": plan.master.key.value, "proxy": plan.proxy.key.value},
                       "placement": sound.placement}

            def succeeded(delivery_id: str, proxy_sha256: str, frames: int) -> dict[str, Any]:
                return advance(run, SUCCEEDED, at=now(), by=actor, reason="delivered and verified",
                               stages=stages, outputs={**outputs, "proxy_sha256": proxy_sha256},
                               checks=[*checks, {"check": "frame_count", "result": "pass",
                                                 "expected": plan.frames, "actual": frames}],
                               provenance=prov, delivery_id=delivery_id,
                               progress={"percent": 100, "stage": "delivered"})
            # The success record is checked before anything is delivered, so a record that
            # could not be written never leaves a delivery behind a failed run.
            records.check(succeeded(PLACEHOLDER_DELIVERY, "0" * 64, plan.frames))
            build.where = (None, "delivery")
            master_path, cleanup = _master_file(store, production, plan.master.content, scratch_dir)
            # Once deliver returns, its stage exists: a failure after this names it.
            delivered = deliver(master_path, store=store, production_id=production, run_id=run_id,
                                expected_frames=plan.frames, media_kind=story.media_kind,
                                delivery_id=delivery_id, now=_parse(now()), threads=2,
                                workdir=scratch_dir)
            cleanup()
            verified = read_delivery(store, production_id=production, run_id=run_id)
            if verified is None or verified.master.sha256 != plan.master.content or \
                    verified.id != delivered.id or verified.proxy is None:
                raise BuildError(DELIVERY_UNVERIFIED, "the delivery did not read back with the "
                                 "plan's master and a proxy", stage="delivery")
            decoded = verified.verification.decoded_frames
            if decoded != plan.frames:
                raise BuildError(DELIVERY_UNVERIFIED, f"the delivery decoded {decoded} frames, the "
                                 f"plan holds {plan.frames} (TIME-11)", stage="delivery")
            run = records.write(succeeded(verified.id, verified.proxy.sha256, decoded))
            return BuildResult(run, plan, (*build.cache.stats.made, *build.worker_made),
                               build.source_calls(), tuple(build.worker_made), planned)
    except Exception as error:  # every failure is recorded on the run, then reported
        board_id, stage = (None, "prebuild") if build is None else build.where
        stop = error if isinstance(error, RunHeld) else \
            (None if sources.stopped is None else sources.stopped())
        failure = failure_of(error if stop is None else stop, board_id=board_id, stage=stage)
        if stop is not None and stop is not error:  # the stop came first; say what followed
            then = failure_of(error)
            failure = replace(failure, message=f"{failure.message} (then {then.code}: {then.message})")
        status = FAILED if stop is None else HELD
        number = None
        if failure.board_id is not None:
            number = next((b.number for b in story.boards or () if b.id == failure.board_id), None)
        failure = replace(failure, board_number=failure.board_number or number)
        if build is not None and not checked_locally:  # the local pass: nothing was asked
            failure = replace(failure, message=f"{failure.message} (found before any clip was "
                              "requested)")
        published, unread = ((None, False) if build is None else
                             _published_delivery(store, production, run_id, delivered))
        if published is not None:  # never hidden: a failed run says what was delivered
            failure = replace(failure, message=f"{failure.message} (delivery {published} of this "
                              "run was published before the failure)")
        elif unread:
            failure = replace(failure, message=f"{failure.message} (a delivery stage of this run "
                              "may exist but could not be read)")
        reason = f"{failure.code}: {failure.message}"[:500]
        progress = {"percent": 100, "stage": failure.stage}
        try:
            try:
                run = records.write(advance(run, status, at=now(), by=actor, reason=reason,
                                            error=failure.to_document(), stages=stages,
                                            checks=checks, progress=progress,
                                            delivery_id=published))
            except AssertionError:  # detail that does not validate never hides the failure
                run = records.write(advance(run, status, at=now(), by=actor, reason=reason,
                                            error=failure.to_document(), progress=progress,
                                            delivery_id=published))
        except Exception as unrecorded:  # a store or transition error: never a quiet return
            raise RunUnrecorded(run_id=run_id, failure=failure, error=unrecorded,
                                delivery_id=published, unread_delivery=unread,
                                status=status) from unrecorded
        return BuildResult(run, plan, () if build is None else
                           (*build.cache.stats.made, *build.worker_made),
                           0 if build is None else build.source_calls(), planned=planned)


PLACEHOLDER_DELIVERY = "dlv_00000000000000000000000000"  # checks the record's shape only


def _local_pass(build: _Build) -> tuple[dict[str, Made], StoryPlan]:
    """The build's first pass, before any clip is asked of the phase's sources (review
    finding 1 of story 406): the whole story is planned with the recording sources, so
    every drive track is made (a local stage), every speaker's library timed clip is
    resolved (a damaged one stops here), every seed and every other input the plan reads
    is checked, each clip is a checked cache hit or a request whose inputs the adapter
    read and re-hashed, and every other artifact is looked up in the cache. Nothing else
    is made and no service is asked. Any error stops the run here with its own code,
    board and stage. Returns the pass's records (the drive tracks it made) and its plan,
    whose keys are real wherever no clip is an input (the mix's, for one)."""
    chain = _Chain(build, local=True)
    plan = build.plan(chain)
    return chain.records, plan


def _check_requests(build: _Build, local: Mapping[str, Made], plan: StoryPlan, *,
                    check: Callable[[Any], None] | None) -> tuple[PlannedClip, ...]:
    """The clip requests the local pass recorded (the clips the plan lacks), once each
    and in plan order, as the clip jobs a phase would request; each one checked by the
    phase's sources first when they give ``check`` (the live sources build every Wan
    request and send nothing). A refusal fails the run at the request's board, before
    any clip is asked for."""
    recorded = {r.key: r for r in (*build.recording.s2v.requests, *build.recording.i2v.requests)}
    ordered = [recorded[value] for value in local if value in recorded]
    if check is not None:
        for request in ordered:
            found = local[request.key]
            build.where = (found.board_id, found.kind)
            check(request)
    names = {planned.key.value: name for name, planned in plan.artifacts.items()}
    numbers = {board.id: board.number for board in build.story.ordered_boards()}
    return tuple(planned_clips(ordered, names, numbers))


def _early_mix(build: _Build, plan: StoryPlan) -> list[dict[str, Any]]:
    """The mix and its own checks (those on the mix, not the master), made after the
    local pass and before any clip is asked for (the confirming check's finding a). The
    mix key names the voice tracks, the sound cues, the beds and the story's levels and
    never a clip, so the local pass's plan holds the real key, and a later pass or phase
    finds the mix and its check results in the cache. A refusal (``mix.input_invalid``,
    ``cue.out_of_range``, a sound blob missing or not its hash) raises with its own code
    at stage ``mix``. Returns the checks as run checks."""
    build.where = (None, MIX)
    made = build.sound.mix(plan.mix.key)
    build.where = (None, "checks")
    return _check_entries(build.sound.checks(plan.mix.key, made.sha256, None))


def _keep_made(records: dict[str, Made], *passes: Mapping[str, Made]) -> None:
    """What an earlier pass of this run made (a drive track in the local pass, a clip in
    the workers' pass 1), with its time, kept on the final pass's records."""
    for earlier in passes:
        for value, made in earlier.items():
            if made.made and not made.deferred:
                records[value] = made


def _service_checks(build: _Build, plan: StoryPlan, records: Mapping[str, Made]
                    ) -> list[dict[str, Any]]:
    """The check results the service phase made or read (the transcript of a master the
    cache holds), as run checks; a check it left to a later phase is not listed."""
    out = []
    for planned in plan.artifacts.values():
        found = records.get(planned.key.value)
        if planned.key.kind == CHECK_RESULT and found is not None and not found.deferred:
            out.append(_transcript_entry(build.transcript.result(planned.content),
                                         planned.key.value, planned.content))
    return out


def _published_delivery(store: Store, production_id: str, run_id: str,
                        delivered: Delivery | None) -> tuple[str | None, bool]:
    """The ID of the delivery this run published, if any, and whether a delivery stage
    may exist whose ID could not be read (read-only). Once ``deliver`` has returned
    (``delivered``), the run's delivery stage exists whatever a later read says, so its
    ID is taken from there. Otherwise the stage is read back; one that does not read
    back (a blob that does not re-hash, a record that does not validate) is still named
    from its own document when that can be read."""
    if delivered is not None:
        return delivered.id, False
    try:
        found = read_delivery(store, production_id=production_id, run_id=run_id)
    except Exception:  # noqa: BLE001 - its read is not this failure; name it another way
        return _delivery_stage_id(store, production_id, run_id)
    return (None, False) if found is None else (found.id, False)


def _delivery_stage_id(store: Store, production_id: str, run_id: str) -> tuple[str | None, bool]:
    """The delivery ID a run's delivery stage names, read from the stage's document
    without re-hashing the master and the proxy (the read that failed), and whether a
    stage may exist whose ID could not be read: ``(None, False)`` when there is none."""
    try:
        if isinstance(store, LocalStore):  # sizes only: the full re-hash is what failed
            record = store.stage_record(production_id, run_id, DELIVERY_STAGE, verify=False)
        else:
            record = completed_stage(store, production_id=production_id, run_id=run_id,
                                     stage=DELIVERY_STAGE)
    except Exception:  # noqa: BLE001 - a record whose blobs are not all there
        return None, True
    if record is None:
        return None, False
    try:
        with store.open(record.blobs[DELIVERY_DOCUMENT].locator) as handle:
            document = json.loads(handle.read(1 << 20))
        found = document.get("id") if isinstance(document, dict) else None
    except Exception:  # noqa: BLE001 - nothing more can be read; the caller says so
        return None, True
    return (found, False) if is_id(found, "dlv") else (None, True)


def _parse(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _master_file(store: Store, production_id: str, sha256: str, scratch: str
                 ) -> tuple[Path, Callable[[], None]]:
    """A path to the master for ``deliver``: the local store's own file (read-only),
    else a scratch copy."""
    locator = blob_locator(production_id, sha256, MP4)
    if isinstance(store, LocalStore):
        return Path(store.root) / locator, lambda: None
    path = Path(scratch) / "master.mp4"
    with store.open(locator) as source, open(path, "xb") as out:
        out.write(source.read())
    return path, lambda: path.unlink()


def _input_versions(prepared: Prepared, recorder: _Recorder) -> list[str]:
    ids = [item.version_id for item in prepared.resolution.resolved]
    return list(dict.fromkeys([*ids, *sorted(recorder.library_inputs)]))


def _tools(toolchain: Toolchain) -> dict[str, Any]:
    return {"compositors": dict(COMPOSITORS), "encoder": thaw(toolchain.encoder),
            "s2v_adapter": toolchain.s2v_adapter, "s2v_profile": thaw(toolchain.s2v_profile),
            "i2v_profile": thaw(toolchain.i2v_profile), "drive_assembler": toolchain.drive_assembler,
            "track_assembler": toolchain.track_assembler, "splicer": toolchain.splicer,
            "mixer": toolchain.mixer, "mux": thaw(toolchain.mux), "keyer_build": keyer_build(),
            "tts_model": toolchain.tts_model}


def _render_in_workers(build: _Build, workers: int) -> dict[str, Made]:
    """Pass 1 makes every clip and keyed frame and collects the segment keys; the
    segments the cache lacks are rendered in up to ``workers`` processes. Returns pass
    1's records, so the run keeps what it made then and how long it took."""
    from haynes_studio.build.workers import render_segments
    chain = _Chain(build, defer=frozenset({SEGMENT}) | FILM_KINDS)
    build.plan(chain)
    missing = [(key, chain.segment_board.get(value)) for value, key in chain.segment_keys.items()
               if build.cache.lookup(key, MP4) is None]
    build.where = (None, SEGMENT)
    build.worker_reports.update(render_segments(build, missing, workers))
    return chain.records


__all__ = ["ALL", "BuildInputs", "BuildResult", "COMPOSITORS", "OFFLINE", "PHASES", "SERVICE",
           "build_story", "build_toolchain", "media_format", "utc_now"]
