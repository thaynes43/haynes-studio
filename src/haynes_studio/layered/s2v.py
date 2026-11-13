"""Speech-to-video clips as cached artifacts (story 426, keyed by ``s2v_clip_key``).

One S2V clip key (drive track, start still, prompt, negative prompt, seed, profile,
adapter) names one artifact: the clip itself, ``video/mp4``, committed through
:class:`~haynes_studio.cache.artifacts.ArtifactCache` (outputs ``s2v_clip`` and
``inputs``). Its content hash is what the keyed frames' key names as ``clip``, as a
library clip's is. Its **provenance record** (``studio.s2v-clip/v1``, **proposal**) is
committed just before it, in the same run, as the stage ``s2v_clip_record-<the clip's
SHA-256>`` (output ``record``), named by the clip's bytes so a retry after a failure
between the two commits never collides with the first.

- **Miss:** refuse a profile this adapter cannot serve; read the drive track and the
  start image by hash (re-hashed); the board's ``F`` is the drive track's length (it is
  exactly ``F / 24`` s, TIME-9); ask the source for ``L`` frames (TIME-9); check the
  answer (below); commit the record, then the clip.
- **Hit:** the completed clip, re-hashed by the ledger, and its record stage in the
  same run naming exactly this clip and key; else ``layered.clip_invalid``. Nothing is
  asked of the source, repaired or regenerated.
- **Bad answer:** fewer frames than TIME-8 needs is ``time.source_short`` (P-05: nothing
  is held); bytes that do not decode, another size, seed, length asked, start image or
  drive track, or incomplete engine facts is ``layered.clip_invalid``. More frames than
  needed are kept and trimmed when drawn (the record says how many). Nothing is
  published or committed.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from typing import Any, BinaryIO

from haynes_studio.cache.artifacts import JSON, ArtifactCache, CachedArtifact
from haynes_studio.cache.keys import S2V_CLIP, CacheKey
from haynes_studio.jsonio import parse_strict, thaw
from haynes_studio.layered.drive import track_frames
from haynes_studio.layered.errors import CLIP_INVALID, SOURCE_SHORT, UNSUPPORTED, LayeredError
from haynes_studio.layered.keyed import read_verified
from haynes_studio.layered.source import MP4, S2VClip, S2VRequest, S2VSource
from haynes_studio.render.clock import S2V_CHUNK, s2v_request_frames, source_frames_needed
from haynes_studio.render.encode import decode_frames
from haynes_studio.stages import StageOutput, commit_stage, completed_stage
from haynes_studio.store import canonical_json, is_sha256

SCHEMA = "studio.s2v-clip/v1"  # proposal: the provenance record
ADAPTER = "studio.s2v/1"  # the adapter the key must name (the Toolchain's s2v_adapter)
RECORD_STAGE = "s2v_clip_record"  # proposal
RECORD = "record"


def record_stage(clip_sha256: str) -> str:
    return f"{RECORD_STAGE}-{clip_sha256}"


def check_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    """The key's profile, if this adapter serves it: a whole ``source_fps``, an even
    ``size`` ``[width, height]`` of the media kind's aspect, and TIME-9's 77-frame
    ``chunk``. Else ``layered.unsupported``, before the source is asked."""
    profile = thaw(profile)
    fps, size, chunk = profile.get("source_fps"), profile.get("size"), profile.get("chunk")
    if isinstance(fps, bool) or not isinstance(fps, int) or fps < 1:
        raise LayeredError(UNSUPPORTED, f"profile source_fps {fps!r} is not a whole fps")
    if (not isinstance(size, list) or len(size) != 2
            or any(isinstance(v, bool) or not isinstance(v, int) or v < 2 or v % 2 for v in size)):
        raise LayeredError(UNSUPPORTED, f"profile size {size!r} is not [width, height] in even pixels")
    if chunk != S2V_CHUNK:
        raise LayeredError(UNSUPPORTED, f"profile chunk {chunk!r} is not TIME-9's {S2V_CHUNK}")
    delivery = profile.get("delivery")
    if isinstance(delivery, Mapping) and "aspect" in delivery:
        aspect = "9:16" if size[1] > size[0] else "16:9"
        if delivery["aspect"] != aspect:
            raise LayeredError(UNSUPPORTED, f"profile size {size} is {aspect}; the media kind "
                               f"delivers {delivery['aspect']}")
    return profile


def measure(data: bytes) -> tuple[int, int, int]:
    """A clip's ``(frames, width, height)`` by decoding it once."""
    count, shape = 0, None
    try:
        for frame in decode_frames(data):
            if shape is None:
                shape = frame.shape
            elif frame.shape != shape:
                raise LayeredError(CLIP_INVALID, "the clip changes size between frames")
            count += 1
    except LayeredError:
        raise
    except Exception as error:  # PyAV raises its own error types for damaged media
        raise LayeredError(CLIP_INVALID, f"the clip does not decode: {type(error).__name__}") from error
    if shape is None:
        raise LayeredError(SOURCE_SHORT, "the clip holds no frame")
    return count, shape[1], shape[0]


def check_clip(request: S2VRequest, clip: S2VClip) -> dict[str, Any]:
    """The provenance record of the source's answer, or the failure (module docstring)."""
    where = request.key
    if not isinstance(clip, S2VClip) or not isinstance(clip.data, bytes) or clip.media_type != MP4:
        raise LayeredError(CLIP_INVALID, "the source's answer is not one MP4 clip", where=where)
    frames, width, height = measure(clip.data)
    if frames < request.frames_needed:
        raise LayeredError(SOURCE_SHORT, f"the clip has {frames} frames; the {request.board_frames}"
                           f"-frame board needs {request.frames_needed} (TIME-8)", where=where)
    if [width, height] != list(request.profile["size"]):
        raise LayeredError(CLIP_INVALID, f"{width}x{height}, the profile asks "
                           f"{request.profile['size']}", where=where)
    asked = {"seed": request.seed, "frames_requested": request.frames,
             "start_image_sha256": request.start_image_sha256,
             "drive_track_sha256": request.drive_track_sha256}
    for name, value in asked.items():
        if getattr(clip, name) != value:
            raise LayeredError(CLIP_INVALID, f"made with {name} {getattr(clip, name)!r}, asked "
                               f"{value!r}", where=where)
    for value, what in ((clip.engine, "its engine"), (clip.engine_job_id, "its engine job")):
        if not isinstance(value, str) or not value:
            raise LayeredError(CLIP_INVALID, f"a clip names {what}", where=where)
    files = clip.files_sha256
    if (not isinstance(files, Mapping) or not files
            or not all(isinstance(n, str) and n and is_sha256(h) for n, h in files.items())):
        raise LayeredError(CLIP_INVALID, "a clip names its model files, each by SHA-256", where=where)
    return {
        "sha256": hashlib.sha256(clip.data).hexdigest(), "bytes": len(clip.data),
        "media_type": MP4, "frames_requested": request.frames, "frames_delivered": frames,
        "frames_needed": request.frames_needed, "trimmed": frames - request.frames_needed,
        "width": width, "height": height, "engine": clip.engine,
        "engine_job_id": clip.engine_job_id, "files_sha256": dict(files), "extra": thaw(clip.extra)}


class S2VClips:
    """The S2V clip stage on ``cache``: a ``content`` source for ``s2v_clip`` keys.
    ``read_drive`` opens a drive track by hash, ``read_image`` a start image; ``source``
    makes clips on a miss."""

    def __init__(self, cache: ArtifactCache, source: S2VSource, *,
                 read_drive: Callable[[str], BinaryIO], read_image: Callable[[str], BinaryIO],
                 adapter: str = ADAPTER):
        self.cache = cache
        self.source = source
        self.read_drive = read_drive
        self.read_image = read_image
        self.adapter = adapter
        self.made: list[str] = []  # keys this stage asked the source for

    def __call__(self, key: CacheKey) -> str:
        return self.clip(key).sha256

    def clip(self, key: CacheKey) -> CachedArtifact:
        if key.kind != S2V_CLIP:
            raise LookupError(f"the S2V clip stage makes no {key.kind} artifacts")
        document = key.document
        if document["adapter"] != self.adapter:
            raise LayeredError(UNSUPPORTED, f"the key names adapter {document['adapter']!r}; this "
                               f"is {self.adapter!r}", where="/adapter")
        profile = check_profile(document["profile"])
        found = self.cache.lookup(key, MP4)
        if found is not None:
            self._check_hit(key, found)
            return found
        drive = read_verified(self.read_drive, document["drive_track"], "the drive track")
        image = read_verified(self.read_image, document["start_still"], "the start image")
        board_frames, _ = track_frames(drive)
        request = S2VRequest(
            key=key.value, drive_track=drive, drive_track_sha256=document["drive_track"],
            start_image=image, start_image_sha256=document["start_still"],
            prompt=document["prompt"], negative_prompt=document["negative_prompt"] or "",
            seed=document["seed"], profile=profile, adapter=document["adapter"],
            frames=s2v_request_frames(board_frames), board_frames=board_frames,
            frames_needed=source_frames_needed(board_frames, profile["source_fps"]))
        clip = self.source.generate(request)
        self.made.append(key.value)
        provenance = check_clip(request, clip)
        name = getattr(self.source, "name", None)
        if not isinstance(name, str) or not name:
            raise LayeredError(CLIP_INVALID, "the source has no name")
        try:
            record = canonical_json({
                "schema": SCHEMA, "key": key.value, "adapter": self.adapter, "source": name,
                "drive_track": {"sha256": request.drive_track_sha256, "board_frames": board_frames},
                "start_image": {"sha256": request.start_image_sha256}, "prompt": request.prompt,
                "negative_prompt": request.negative_prompt, "seed": request.seed,
                "profile": profile, "source_fps": profile["source_fps"], "clip": provenance})
        except (TypeError, ValueError) as error:
            raise LayeredError(CLIP_INVALID, f"the provenance record is not plain JSON: {error}",
                               where=key.value) from error
        commit_stage(self.cache.store, ledger=self.cache.ledger,
                     production_id=self.cache.production_id, run_id=self.cache.run_id,
                     stage=record_stage(provenance["sha256"]),
                     outputs={RECORD: StageOutput(record, JSON)})
        return self.cache.commit(key, clip.data, MP4)

    def _check_hit(self, key: CacheKey, found: CachedArtifact) -> None:
        cache = self.cache
        stage = record_stage(found.sha256)
        record = completed_stage(cache.ledger, production_id=cache.production_id,
                                 run_id=found.record.run_id, stage=stage,
                                 store=None if cache.ledger is cache.store else cache.store)
        if record is None or set(record.blobs) != {RECORD}:
            raise LayeredError(CLIP_INVALID, "the clip has no provenance record", where=stage)
        with cache.store.open(record.blobs[RECORD].locator) as handle:
            document = read_provenance(handle.read())
        if document.get("key") != key.value or document.get("clip", {}).get("sha256") != found.sha256:
            raise LayeredError(CLIP_INVALID, "the provenance record names another clip or key",
                               where=stage)


def read_provenance(data: bytes) -> dict[str, Any]:
    try:
        document = parse_strict(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise LayeredError(CLIP_INVALID, "the provenance record is not strict JSON") from error
    if not isinstance(document, dict) or document.get("schema") != SCHEMA:
        raise LayeredError(CLIP_INVALID, f"the provenance record is not {SCHEMA}")
    return document


__all__ = ["ADAPTER", "RECORD_STAGE", "SCHEMA", "S2VClips", "check_clip", "check_profile",
           "measure", "read_provenance", "record_stage"]
