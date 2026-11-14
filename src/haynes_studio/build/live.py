"""Live clip sources of the service phase (story 851): the build's speech-to-video and
whole-frame clip requests made on the studio's two RTX 3090s through story 842's
:class:`~haynes_studio.adapters.wan.WanClipClient`. Glue only: every guard is the
client's (docs/reference/legacy-adapters.md), and nothing here retries, waits, loops,
clears or catches a refusal in order to go on.

- **One journal per store**, at :func:`journal_path` (``<store root>/wan-journal.jsonl``),
  given to the one client of every run of that store. The client sees no journal it
  was not given, so no other path is ever used, and nothing here deletes, moves, empties
  or clears it.
- **One request, one call.** A speech-to-video request becomes one
  :class:`~haynes_studio.adapters.wan.SpeechToVideo` and one ``render``; a whole-frame
  chain one :class:`~haynes_studio.adapters.wan.ImageToVideo` and one ``render`` per
  clip not already kept (below), in order, each clip after the first starting on the
  last frame of the one before (:func:`~haynes_studio.wholeframe.source.last_frame_png`).
  The inputs go as
  the adapter gives them (start image, drive track, prompt, negative prompt, seed,
  size, length); a key whose profile the client cannot make as asked is refused before
  anything is sent (``build.live_unsupported``).
- **A job the journal still holds is settled first.** After a lost answer the client
  keeps the job as in flight or uncollected. When the next request is the one that job
  was made for (the graph the client rebuilds for it under that job ID hashes to the
  journal's ``graph_sha256``), it is collected with ``recover``, read-only, never
  rendered again; any other request stops the phase (``build.wan_unsettled``).
- **A chain clip collected is kept at once** (:class:`KeptClips`). As soon as the chain
  source has a clip of a chain from ``render`` or ``recover``, it commits it, create-only,
  as its own cached artifact (kind ``wan_chain_clip``, the MP4, with its Wan record in a
  provenance stage named by the same key), found again by :func:`kept_key`: only what
  the clip request is. Before it asks the client for any chain clip it looks for that
  key, and a kept clip (re-hashed; a damaged one fails closed with the store's code) is
  used without a ``render`` or a ``recover``. So a chain stopped at clip *k* (a refusal,
  a crash) gives the next phase clips 0 to *k - 1* from the store, and only clip *k* and
  later are asked for.
- **Any refusal stops the phase.** Every exception the client raises (busy lease or
  API, unknown or competing work, GPUs that did not cool, an unsettled or uncollected
  job, a journal it cannot read or hold, a failed job, a lost or unreadable answer)
  becomes :class:`~haynes_studio.build.errors.RunHeld`: the run is recorded ``held``
  with the code, the job and what a person must check, and the sources refuse every
  later call without asking the client.
- **The client is made on the first clip request**, so a phase whose clips are all
  cached never reads the journal, and a refusal while the client is made (a journal
  it cannot read) is a held run like any other.

:func:`planned_clips` lists the clip jobs a service phase would request (the local
pass's requests) and :func:`estimate` gives each one's GPU time from the E0 records;
the dry run (``studio build --phase service --dry-run``) prints both and asks nothing.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from haynes_studio.adapters import wan
from haynes_studio.adapters.errors import (
    BUSY,
    COMMAND_FAILED,
    COMPETING_WORK,
    JOB_FAILED,
    JOURNAL_FAILED,
    NOT_FOUND,
    PIN_MISMATCH,
    RESPONSE_INVALID,
    TIMEOUT,
)
from haynes_studio.build.errors import (
    DRY_RUN_ASKED,
    INTERNAL,
    LIVE_UNSUPPORTED,
    WAN_UNSETTLED,
    BuildError,
    RunHeld,
)
from haynes_studio.cache.artifacts import ArtifactCache
from haynes_studio.cache.errors import ENTRY_INVALID, CacheError
from haynes_studio.cache.keys import CacheKey, make_key
from haynes_studio.jsonio import parse_strict, thaw
from haynes_studio.layered.source import S2VClip, S2VRequest, S2VSource
from haynes_studio.stages import StageOutput, commit_stage, completed_stage
from haynes_studio.store import HASH_MISMATCH, StoreError, canonical_json
from haynes_studio.wholeframe.source import ClipRequest, ClipSource, ClipSpec, SourceClip, last_frame_png

JOURNAL_NAME = "wan-journal.jsonl"
S2V_STAGE, I2V_STAGE = "s2v_clip", "whole_frame_clip"
# A chain clip the glue keeps (proposal): its cache kind, its provenance stage and schema.
KEPT = "wan_chain_clip"
KEPT_RECORD = "wan_chain_clip_record"
KEPT_SCHEMA = "studio.wan-chain-clip/v1"
MP4, JSON, RECORD = "video/mp4", "application/json", "record"
# What the Wan client makes (story 842), as the cache keys' profiles name it: a key that
# asks for anything else is refused before anything is sent. ``size`` is passed as given
# (the client checks it); ``delivery`` and ``adapter`` are the key's own.
S2V_MAKES = {"model": "wan2.2-s2v-14b-fp8", "lora": "lightx2v-4step", "steps": 4, "cfg": 1,
             "chunk": wan.CHUNK, "source_fps": wan.FPS}
I2V_MAKES = {"model": "wan2.2-ti2v-5b", "source_fps": wan.I2V_FPS}
S2V_KEYS = frozenset(S2V_MAKES) | {"size", "delivery"}
I2V_KEYS = frozenset(I2V_MAKES) | {"size", "adapter", "delivery"}
# The E0 clip records of the checkout this code runs from (an editable install).
E0_RECORDS = Path(__file__).resolve().parents[3] / "titles" / "the-winter-menu" / "video-e0"
E0_FILES = ("clip-records.jsonl", "clip-records-layers.jsonl", "clip-records-s2v.jsonl")


def journal_path(store_root: str | Path) -> Path:
    """The one Wan journal of a store: ``<store root>/wan-journal.jsonl``, for every run
    of that store (P-842-08). Keep the store on a local file system (``flock``)."""
    return Path(store_root) / JOURNAL_NAME


# Requests --------------------------------------------------------------------------------


def _profile(profile: Mapping[str, Any], makes: Mapping[str, Any], keys: frozenset[str],
             what: str) -> tuple[int, int]:
    """The key's ``[width, height]`` if the Wan client makes this profile, else
    ``build.live_unsupported``."""
    profile = thaw(profile)
    extra = sorted(set(profile) - keys)
    wrong = sorted(k for k, v in makes.items() if profile.get(k) != v)
    if extra or wrong:
        named = ", ".join([*(f"{k}={profile.get(k)!r} (the client makes {makes[k]!r})" for k in wrong),
                           *(f"{k} (not a setting the client has)" for k in extra)])
        raise BuildError(LIVE_UNSUPPORTED, f"the Wan client cannot make this {what} profile as "
                         f"its key asks: {named}; nothing was sent", stage=S2V_STAGE if what == "s2v"
                         else I2V_STAGE)
    size = profile.get("size")
    if not isinstance(size, list) or len(size) != 2:
        raise BuildError(LIVE_UNSUPPORTED, f"the {what} profile has no [width, height] size",
                         stage=S2V_STAGE if what == "s2v" else I2V_STAGE)
    return size[0], size[1]


def s2v_request(request: S2VRequest, story: str) -> wan.SpeechToVideo:
    """The one Wan speech-to-video request of a layered clip request, its inputs as
    given; ``story`` is the work package the Wan ledger records the job under. A request
    the client refuses is ``adapter.request_invalid`` (an empty negative prompt among
    them: the Wan graph needs one, and none is invented)."""
    width, height = _profile(request.profile, S2V_MAKES, S2V_KEYS, "s2v")
    made = wan.SpeechToVideo(image_png=request.start_image, drive_wav=request.drive_track,
                             board_frames=request.board_frames, prompt=request.prompt,
                             seed=request.seed, story=story, width=width, height=height,
                             negative=request.negative_prompt)
    if made.length != request.frames:  # both TIME-9; a difference is a bug, never a job
        raise BuildError(LIVE_UNSUPPORTED, f"the Wan client asks {made.length} frames, the key "
                         f"{request.frames}; nothing was sent", stage=S2V_STAGE)
    return made


def i2v_request(request: ClipRequest, spec: ClipSpec, start_png: bytes, story: str
                ) -> wan.ImageToVideo:
    """The Wan image-to-video request of clip ``spec`` of a whole-frame chain, starting
    on ``start_png`` (the photo for clip 0, else the previous clip's last frame). The
    chain request names no negative prompt; the client's own (E0's) is used."""
    width, height = _profile(request.profile, I2V_MAKES, I2V_KEYS, "i2v")
    return wan.ImageToVideo(image_png=start_png, prompt=request.prompt, seed=spec.seed,
                            story=story, width=width, height=height, length=spec.frames)


def check_request(request: S2VRequest | ClipRequest, story: str) -> None:
    """Every Wan request ``request`` would become, built and checked, sending nothing:
    run on the local pass's requests before any clip is asked for. A chain's later start
    images are not known yet; the photo stands in (only its PNG signature is checked)."""
    if isinstance(request, S2VRequest):
        s2v_request(request, story)
    else:
        for spec in request.clips:
            i2v_request(request, spec, request.photo, story)


# The client, one per phase ------------------------------------------------------------------

_CHECKS = {
    WAN_UNSETTLED: "the journal holds a Wan job made for another request: read the journal "
                   "and /videos/<job_id>; collect it with recover(<its own request>, job_id) "
                   "or, once a person has checked it, WanClipClient.clear_in_flight(); never "
                   "resubmit to get past it",
    COMPETING_WORK: "foreign work was seen on the Wan engine: inspect the prompt IDs the halt "
                    "names on the engine queue and history; only a person calls "
                    "WanClipClient.clear_halt(), and only after that",
    JOURNAL_FAILED: "read the journal file and the Wan service (its engine queue and the "
                    "ledger of every job the journal names); never delete, move, empty or "
                    "replace the journal or its .lock file to get past it",
    JOB_FAILED: "the job failed and made no clip: read /videos/<job_id> and the engine queue. "
                "If the held record's in_flight names the job (its prompt was accepted), the "
                "build keeps asking recover, which refuses, so only a person settles it: once "
                "the ledger reads failed and the queue holds nothing of it, "
                "WanClipClient.clear_in_flight(); otherwise the client settled it and the next "
                "service phase asks for the clip again",
    PIN_MISMATCH: "a pinned snippet or template does not hash to its pin; nothing was sent: "
                  "check the checkout",
    INTERNAL: "an error with no code (a bug, or the system): read the journal and "
              "/videos/<job_id> for any job it names before anything else",
}
_BUSY = ("read the journal (FileJournal(path).read_state()) and /videos/<job_id> for the job "
         "it names, then the API's /health, its compute lease and the engine queue; a job "
         "whose ledger reads succeeded is collected by the next service phase with recover, "
         "never rendered again; a job with no ledger needs a person to check the api "
         "container before WanClipClient.clear_in_flight(); a journal held by another "
         "process means finding that process, never pointing a run at another file")
_LOST = ("the command failed or its answer was lost: read the journal; if it names a job "
         "(in_flight), read /videos/<job_id>: a finished job is collected by the next service "
         "phase of the same draft and --wan-story with recover, never rendered again; one with "
         "no ledger is a person's to check")
_CHECKS[RESPONSE_INVALID] = (
    "an answer did not read as this request's: a probe answer, a clip cut in transfer or "
    "failing its checks, or a ledger that is not this request's job (another --wan-story, "
    "seed or input). Read the journal and /videos/<job_id>: a cut transfer is collected by "
    "the next service phase of the same draft and --wan-story with recover; a clip that "
    "fails its checks, or a ledger of another request, stays held until a person inspects "
    "it and calls WanClipClient.clear_in_flight()")
_CHECKS[TIMEOUT] = _CHECKS[COMMAND_FAILED] = _LOST


def _check_for(code: str) -> str:
    if code == BUSY:
        return _BUSY
    if code == NOT_FOUND:
        return ("the job has no ledger (it may never have started): check the api container, "
                "then a person may call WanClipClient.clear_in_flight()")
    return _CHECKS.get(code, _LOST)


class WanClips:
    """The one Wan client of a phase, with its journal at the store's fixed path: every
    clip request goes through :meth:`make`, which settles a job the journal holds first
    (``recover`` for the same request, a stop otherwise), renders once, and turns any
    refusal into :class:`RunHeld`. After a stop, every later call is refused with the
    same stop and the client is not asked. ``calls`` records each client call made
    (``render`` or ``recover``, with the job ID a recover named)."""

    def __init__(self, journal: Path, *, story: str, runner: Any,
                 client_options: Mapping[str, Any] | None = None):
        self.journal_path = Path(journal)
        self.story = story
        self.runner = runner
        self.client_options = dict(client_options or {})
        self.client: wan.WanClipClient | None = None
        self.calls: list[tuple[str, str | None]] = []
        self.stopped: RunHeld | None = None

    def _client(self) -> wan.WanClipClient:
        if self.client is None:  # loads the journal: a job or halt it holds blocks this process
            self.client = wan.WanClipClient(self.runner, journal=wan.FileJournal(self.journal_path),
                                            **self.client_options)
        return self.client

    def make(self, request: wan.WanRequest, *, stage: str,
             collected: Sequence[Mapping[str, Any]] = (), keepable: bool = True) -> wan.WanClip:
        """One clip for ``request``: recovered when the journal holds the job made for
        it, else rendered once. ``collected`` names the clips of this chain already
        in hand (each kept), so a stop records them; ``keepable`` says the caller can
        hand a clip kept on a competing-work stop to its adapter (false for a chain clip
        before the last: the adapter takes a chain whole, so that clip is named on the
        stop and not returned)."""
        if self.stopped is not None:
            raise self.stopped
        try:
            client = self._client()
            held = wan.WanClipClient.in_flight()
            if held is not None:
                if held.graph_sha256 != wan.graph_sha256(client.graph(request, held.job_id)):
                    raise BuildError(WAN_UNSETTLED, f"the journal holds Wan job {held.job_id} "
                                     f"({held.state}), made for another request than this one")
                self.calls.append(("recover", held.job_id))
                return client.recover(request, held.job_id)
            self.calls.append(("render", None))
            return client.render(request)
        except Exception as error:  # every refusal stops the phase; nothing goes on
            clip = getattr(error, "clip", None)
            kept = getattr(error, "code", None) == COMPETING_WORK and isinstance(clip, wan.WanClip)
            self.stopped = self._held(error, stage, collected, handed=kept and keepable)
            if kept and keepable:
                # Foreign work during this request's own job: its clip passed every check
                # and the client kept it (guard 27). It is handed to the adapter, cached,
                # and the build stops held right after (ClipSources.stopped); the stop
                # also refuses every later call, so nothing more is submitted.
                return clip
            raise self.stopped from None

    def _held(self, error: Exception, stage: str, collected: Sequence[Mapping[str, Any]],
              *, handed: bool) -> RunHeld:
        code = getattr(error, "code", None)
        if not isinstance(code, str) or not code:
            code = INTERNAL
        message = getattr(error, "message", None) or f"{type(error).__name__}: {error}"
        holding = wan.WanClipClient.in_flight()
        halt = wan.WanClipClient.halted()
        job_id = getattr(error, "job_id", None) or (holding.job_id if holding else None)
        detail: dict[str, Any] = {
            "journal": str(self.journal_path),
            "in_flight": None if holding is None else {"job_id": holding.job_id,
                                                       "state": holding.state},
            "halt": None if halt is None else {"job_id": halt.job_id,
                                               "unexpected_work_seen": list(halt.unexpected_work_seen)},
            "collected_before_stop": [dict(c) for c in collected]}
        clip = getattr(error, "clip", None)  # competing work: checked and kept by the client
        if isinstance(clip, wan.WanClip):  # handed to the adapter, or not (a chain's earlier clip)
            detail["clip_kept"] = {"job_id": clip.job_id, "sha256": clip.sha256,
                                   "handed_to_adapter": handed}
        return RunHeld(code, message, job_id=job_id, check=_check_for(code), detail=detail,
                       stage=stage)


def _extra(clip: wan.WanClip) -> dict[str, Any]:
    """The clip's whole Wan record, kept with the adapter's provenance (no field lost)."""
    return {"wan": json.loads(json.dumps(clip.record))}


class WanS2VSource(S2VSource):
    """Layered speech-to-video clips on the Wan client: one ``SpeechToVideo`` per request."""

    name = "studio.build.wan-s2v/1"

    def __init__(self, clips: WanClips):
        self.clips = clips
        self.calls: list[S2VRequest] = []

    def generate(self, request: S2VRequest) -> S2VClip:
        made = s2v_request(request, self.clips.story)
        self.calls.append(request)
        clip = self.clips.make(made, stage=S2V_STAGE)
        record = clip.record
        return S2VClip(data=clip.data, seed=record["seed"], frames_requested=record["frames_requested"],
                       start_image_sha256=clip.start_image_sha256,
                       drive_track_sha256=record["inputs"]["audio"]["sha256"], engine=clip.engine,
                       engine_job_id=clip.job_id, files_sha256=clip.files_sha256, extra=_extra(clip))


def kept_key(made: wan.ImageToVideo, profile: Mapping[str, Any], source: str) -> CacheKey:
    """The key of one kept chain clip: only what its Wan request is (the start image's
    hash, the prompt, the client's negative prompt, the seed, the size, the length), the
    key's profile and the source's name and version. Not the chain, the clip's place in
    it or ``--wan-story``: the same request in another chain, or under another story,
    finds the same clip, as a cached chain does."""
    return make_key(KEPT, {"start_image": made.image_sha256, "prompt": made.prompt,
                           "negative_prompt": made.negative, "seed": made.seed,
                           "size": [made.width, made.height], "length": made.length,
                           "profile": thaw(profile), "source": source})


def kept_record_stage(key: CacheKey) -> str:
    """The stage that holds a kept clip's provenance record: ``wan_chain_clip_record-
    <the key's 64 hex digits>`` (proposal), committed before the clip's cache entry. Named
    by the key, not the clip's hash: two requests may give the same bytes."""
    return f"{KEPT_RECORD}-{key.hex}"


@dataclass(frozen=True)
class Kept:
    """A kept chain clip: the clip as the client gave it (bytes and Wan record), its key,
    the run whose stage holds it and whether this call found it there (``reused``)."""

    clip: wan.WanClip
    key: CacheKey
    run_id: str
    reused: bool

    def collected(self, index: int) -> dict[str, Any]:
        """What a stop records of it (``collected_before_stop``)."""
        return {"index": index, "job_id": self.clip.job_id, "sha256": self.clip.sha256,
                "kept": self.key.value, "reused": self.reused}


class KeptClips:
    """The chain clips the glue keeps, on the store, ledger and run search of ``cache``
    (the run's): each one a cached artifact of kind ``wan_chain_clip`` (the MP4) whose
    provenance record (``studio.wan-chain-clip/v1``: the key, the source, the clip's hash
    and size and its whole Wan record) is its own stage, committed first. Create-only,
    found again from any later run by its key, never deleted. Its own cache statistics,
    so the run's ``made`` lists only the plan's artifacts."""

    def __init__(self, cache: ArtifactCache):
        self.cache = ArtifactCache(cache.store, production_id=cache.production_id,
                                   run_id=cache.run_id, ledger=cache.ledger, finder=cache.finder)

    def keep(self, key: CacheKey, clip: wan.WanClip, *, source: str) -> Kept:
        """Commit ``clip`` under ``key`` in this run: its record's stage, then the clip."""
        cache = self.cache
        try:
            record = canonical_json({"schema": KEPT_SCHEMA, "key": key.value, "source": source,
                                     "clip": {"sha256": clip.sha256, "bytes": len(clip.data),
                                              "media_type": MP4},
                                     "wan": clip.record})
        except (TypeError, ValueError) as error:
            raise CacheError(ENTRY_INVALID, f"the Wan record is not plain JSON: {error}",
                             where=key.value) from error
        commit_stage(cache.store, ledger=cache.ledger, production_id=cache.production_id,
                     run_id=cache.run_id, stage=kept_record_stage(key),
                     outputs={RECORD: StageOutput(record, JSON)})
        made = cache.commit(key, clip.data, MP4)
        return Kept(clip, key, made.record.run_id, reused=False)

    def find(self, key: CacheKey) -> Kept | None:
        """The clip kept under ``key``, checked, or ``None``. A clip or record that is not
        as recorded is the store's error, and an entry that is not this key's clip is
        ``cache.entry_invalid``: both fail closed, and nothing is rendered in its place."""
        cache = self.cache
        found = cache.lookup(key, MP4)  # the local ledger re-hashes the clip here
        if found is None:
            return None
        stage = kept_record_stage(key)
        record = completed_stage(cache.ledger, production_id=cache.production_id,
                                 run_id=found.record.run_id, stage=stage,
                                 store=None if cache.ledger is cache.store else cache.store)
        if record is None or set(record.blobs) != {RECORD}:
            raise CacheError(ENTRY_INVALID, "the kept chain clip has no provenance record",
                             where=stage)
        document_bytes = _read(cache, record.blobs[RECORD].locator, record.blobs[RECORD].sha256)
        try:
            document = parse_strict(document_bytes.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise CacheError(ENTRY_INVALID, "the kept clip's record is not strict JSON",
                             where=stage) from error
        if not isinstance(document, dict):
            document = {}
        wan_record, named = document.get("wan"), document.get("clip")
        if (not isinstance(wan_record, dict) or not isinstance(named, dict)
                or document.get("schema") != KEPT_SCHEMA or document.get("key") != key.value
                or named.get("sha256") != found.sha256
                or wan_record.get("clip_sha256") != found.sha256):
            raise CacheError(ENTRY_INVALID, "the kept clip's record names another key or clip",
                             where=stage)
        data = _read(cache, found.blob.locator, found.sha256)
        return Kept(wan.WanClip(data, wan_record), key, found.record.run_id, reused=True)


def _read(cache: ArtifactCache, locator: str, sha256: str) -> bytes:
    """A blob's bytes, re-hashed (``store.hash_mismatch`` otherwise)."""
    with cache.store.open(locator) as handle:
        data = handle.read()
    if hashlib.sha256(data).hexdigest() != sha256:
        raise StoreError(HASH_MISMATCH, f"blob {sha256} is not the bytes it is named by",
                         locator=locator)
    return data


class WanChainSource(ClipSource):
    """Whole-frame clip chains on the Wan client: one ``ImageToVideo`` per clip, in
    order, clip *k* starting on clip *k - 1*'s last frame. Each clip is a kept clip when
    one is there (no client call), else asked of the client and kept at once
    (:class:`KeptClips`, on the cache the build gives :meth:`bind`)."""

    name = "studio.build.wan-i2v/1"

    def __init__(self, clips: WanClips):
        self.clips = clips
        self.calls: list[ClipRequest] = []
        self.kept: KeptClips | None = None

    def bind(self, cache: ArtifactCache) -> None:
        """Keep this run's chain clips on ``cache``: the build calls it before any clip."""
        self.kept = KeptClips(cache)

    def generate(self, request: ClipRequest) -> list[SourceClip]:
        if self.clips.stopped is not None:  # a stopped phase asks nothing, kept clips included
            raise self.clips.stopped
        check_request(request, self.clips.story)
        kept = self.kept
        if kept is None:  # never a clip that could not be kept
            raise BuildError(INTERNAL, "the chain source was given no cache to keep its clips "
                             "on (ClipSources.bind); nothing was sent", stage=I2V_STAGE)
        self.calls.append(request)
        out: list[SourceClip] = []
        collected: list[dict[str, Any]] = []
        start = request.photo
        for number, spec in enumerate(request.clips, 1):
            made = i2v_request(request, spec, start, self.clips.story)
            key = kept_key(made, request.profile, self.name)
            found = kept.find(key)
            if found is None:
                clip = self.clips.make(made, stage=I2V_STAGE, collected=collected,
                                       keepable=number == len(request.clips))
                found = kept.keep(key, clip, source=self.name)
            clip = found.clip
            record = clip.record
            out.append(SourceClip(index=spec.index, data=clip.data, seed=record["seed"],
                                  frames_requested=record["frames_requested"],
                                  start_image_sha256=clip.start_image_sha256, engine=clip.engine,
                                  engine_job_id=clip.job_id, files_sha256=clip.files_sha256,
                                  extra={**_extra(clip), "kept": {"key": key.value,
                                                                  "run_id": found.run_id}}))
            collected.append(found.collected(spec.index))
            start = last_frame_png(clip.data)
        return out


class _DryRun(S2VSource, ClipSource):
    """A dry run's source: never asked (the dry run stops before any clip); refuses."""

    name = "studio.build.dry-run"

    def generate(self, request: Any) -> Any:
        raise BuildError(DRY_RUN_ASKED, f"a dry run asks no clip source ({request.key})")


@dataclass(frozen=True)
class LiveParts:
    """What :func:`live_sources` made, for the command line and tests."""

    clips: WanClips | None
    s2v: S2VSource
    i2v: ClipSource
    check: Callable[[S2VRequest | ClipRequest], None]
    bind: Callable[[ArtifactCache], None] | None = None


def live_sources(store_root: str | Path, *, story: str, runner: Any = None, dry_run: bool = False,
                 client_options: Mapping[str, Any] | None = None) -> LiveParts:
    """The live sources of a store's service phase: one :class:`WanClips` on the
    store's journal (:func:`journal_path`) and ``runner`` (the real ``kubectl exec``
    runner when ``None``), or with ``dry_run`` sources that refuse and no client.
    ``client_options`` (``clock``, ``wall``, ``sleep``, ``new_job_id``) are for tests;
    the journal is never one of them."""
    def check(request: S2VRequest | ClipRequest) -> None:
        check_request(request, story)

    if dry_run:
        return LiveParts(None, _DryRun(), _DryRun(), check)
    if runner is None:
        from haynes_studio.adapters.runner import SubprocessRunner  # noqa: PLC0415
        runner = SubprocessRunner()
    options = dict(client_options or {})
    if "journal" in options:
        raise TypeError("the journal is the store's own; it is never passed in")
    clips = WanClips(journal_path(store_root), story=story, runner=runner, client_options=options)
    chains = WanChainSource(clips)
    return LiveParts(clips, WanS2VSource(clips), chains, check, chains.bind)


# The dry run ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class PlannedClip:
    """One Wan job a service phase would request, in the order it would be asked."""

    kind: str  # "s2v" or "i2v"
    board_id: str
    board_number: int | None
    slot: str | None  # the speaker (speech-to-video)
    index: int | None  # the clip's place in its chain (whole-frame)
    frames: int  # the requested length (TIME-9 for speech-to-video)
    seed: int
    width: int
    height: int
    chunks: int | None  # speech-to-video only
    key: str

    def to_document(self) -> dict[str, Any]:
        return {"kind": self.kind, "board_id": self.board_id, "board_number": self.board_number,
                "slot": self.slot, "index": self.index, "frames": self.frames, "seed": self.seed,
                "size": [self.width, self.height], "chunks": self.chunks, "key": self.key}


def planned_clips(requests: Iterable[S2VRequest | ClipRequest], names: Mapping[str, str],
                  numbers: Mapping[str, int]) -> list[PlannedClip]:
    """The Wan jobs of ``requests`` (the local pass's, in order). ``names`` maps a key to
    its planned artifact (``<board>/s2v_clip/<slot>``), ``numbers`` a board to its number."""
    out = []
    for request in requests:
        name = names.get(request.key, "")
        board = name.split("/", 1)[0]
        width, height = (thaw(request.profile).get("size") or [0, 0])[:2]
        if isinstance(request, S2VRequest):
            chunks = -(-request.frames // wan.CHUNK)
            out.append(PlannedClip("s2v", board, numbers.get(board), name.rsplit("/", 1)[-1], None,
                                   request.frames, request.seed, width, height, chunks, request.key))
        else:
            out.extend(PlannedClip("i2v", board, numbers.get(board), None, spec.index, spec.frames,
                                   spec.seed, width, height, None, request.key)
                       for spec in request.clips)
    return out


@dataclass(frozen=True)
class E0Clip:
    """One E0 clip job's GPU time (``render_s``: the job; ``wall_s``: with cool-down)."""

    kind: str
    width: int
    height: int
    frames: int
    chunks: int | None
    render_s: float
    wall_s: float
    source: str


def e0_clips(directory: str | Path = E0_RECORDS) -> list[E0Clip]:
    """The E0 clip records' timings: image-to-video jobs (records without ``method``)
    and speech-to-video jobs on the lightning profile (``method`` ``s2v-lightning``);
    the one 20-step speech job (``method`` ``s2v``) is another profile and is left out.
    A missing file gives no records (the estimate then says none were read)."""
    out = []
    for name in E0_FILES:
        path = Path(directory) / name
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            method = row.get("method")
            if method not in (None, "s2v-lightning"):
                continue
            kind = "i2v" if method is None else "s2v"
            out.append(E0Clip(kind, row["width"], row["height"], row["length"],
                              row.get("chunks") if kind == "s2v" else None,
                              float(row["render_s"]), float(row["wall_s"]), f"{name}:{number}"))
    return out


@dataclass(frozen=True)
class Estimate:
    """A clip's GPU time from the E0 records of the same shape: the range of the jobs'
    ``render_s`` and the longest ``wall_s`` (a job with its cool-down wait), or none."""

    render_s: tuple[float, float] | None
    wall_s_max: float | None
    records: int
    basis: str

    def to_document(self) -> dict[str, Any]:
        return {"render_s": None if self.render_s is None else list(self.render_s),
                "wall_s_max": self.wall_s_max, "records": self.records, "basis": self.basis}


def estimate(clip: PlannedClip, records: Sequence[E0Clip]) -> Estimate:
    """``clip``'s GPU time from E0 (proposal): speech-to-video jobs of the same size and
    chunk count; image-to-video jobs of the same size and at least its length (E0 ran
    121 frames only, so a shorter clip's figure is an upper bound)."""
    if clip.kind == "s2v":
        same = [r for r in records if r.kind == "s2v" and (r.width, r.height) == (clip.width, clip.height)
                and r.chunks == clip.chunks]
        lengths = sorted({r.frames for r in same})
        bound = ("" if not same or lengths[0] <= clip.frames <= lengths[-1] else
                 " (an upper bound)" if clip.frames < lengths[0] else " (a lower bound)")
        basis = (f"E0 speech-to-video jobs at {clip.width}x{clip.height}, {clip.chunks} chunk(s), "
                 f"of {', '.join(map(str, lengths)) or '?'} frames{bound}")
    else:
        same = [r for r in records if r.kind == "i2v" and (r.width, r.height) == (clip.width, clip.height)
                and r.frames >= clip.frames]
        lengths = sorted({r.frames for r in same})
        basis = (f"E0 image-to-video jobs at {clip.width}x{clip.height} of "
                 f"{', '.join(map(str, lengths)) or '?'} frames"
                 + (" (an upper bound)" if same and min(lengths) > clip.frames else ""))
    if not records:
        return Estimate(None, None, 0, "no E0 records were read")
    if not same:
        return Estimate(None, None, 0, f"no E0 job of this shape ({clip.kind} {clip.width}x"
                        f"{clip.height}, {clip.frames} frames)")
    render = [r.render_s for r in same]
    return Estimate((min(render), max(render)), max(r.wall_s for r in same), len(same), basis)


def dry_run_report(clips: Sequence[PlannedClip], records: Sequence[E0Clip]) -> dict[str, Any]:
    """The dry run's listing: each clip with its estimate, and the totals (unknown when
    any clip has no E0 job of its shape)."""
    rows, low, high, wall, known = [], 0.0, 0.0, 0.0, True
    for clip in clips:
        found = estimate(clip, records)
        rows.append({**clip.to_document(), "estimate": found.to_document()})
        if found.render_s is None:
            known = False
        else:
            low, high, wall = low + found.render_s[0], high + found.render_s[1], wall + found.wall_s_max
    total = {"jobs": len(clips), "render_s": [round(low, 1), round(high, 1)] if known else None,
             "wall_s_max": round(wall, 1) if known else None,
             "basis": "the sum of each job's E0 range" if known else
             "unknown: no E0 records were read" if not records else
             "unknown: a job has no E0 job of its shape"}
    return {"clips": rows, "total": total}


def dry_run_text(report: Mapping[str, Any]) -> str:
    lines = []
    for row in report["clips"]:
        where = f"slot {row['slot']}" if row["kind"] == "s2v" else f"clip {row['index']}"
        chunks = f", {row['chunks']} chunk(s)" if row["chunks"] else ""
        found = row["estimate"]
        time_text = ("no E0 estimate" if found["render_s"] is None else
                     f"GPU {found['render_s'][0]:g}-{found['render_s'][1]:g} s, at most "
                     f"{found['wall_s_max']:g} s with cool-down ({found['records']} E0 jobs)")
        lines.append(f"  {row['kind']} board {row['board_number']} {row['board_id']} {where}: "
                     f"{row['frames']} frames at {row['size'][0]}x{row['size'][1]}{chunks}, seed "
                     f"{row['seed']}; {time_text}")
    total = report["total"]
    if total["render_s"] is None:
        lines.append(f"  total: {total['jobs']} Wan job(s); {total['basis']}")
    else:
        lines.append(f"  total: {total['jobs']} Wan job(s), GPU {total['render_s'][0]:g}-"
                     f"{total['render_s'][1]:g} s, at most {total['wall_s_max']:g} s with cool-down")
    return "\n".join(lines)


__all__ = ["E0Clip", "E0_RECORDS", "Estimate", "I2V_MAKES", "JOURNAL_NAME", "KEPT", "KEPT_SCHEMA",
           "Kept", "KeptClips", "LiveParts", "PlannedClip", "S2V_MAKES", "WanChainSource",
           "WanClips", "WanS2VSource", "check_request", "dry_run_report", "dry_run_text",
           "e0_clips", "estimate", "i2v_request", "journal_path", "kept_key", "kept_record_stage",
           "live_sources", "planned_clips", "s2v_request"]
