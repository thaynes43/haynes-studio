"""Whole-frame clips as cached artifacts (story 427).

One whole-frame clip key (``whole_frame_clip_key``: photo, prompt, seed, profile and
the requested clip lengths) names one artifact: the **clip set**, a JSON record
(``studio.whole-frame-clips/v1``, **proposal**) that lists each clip of the chain by
hash with its provenance. It is committed once as a completed stage through
:class:`~haynes_studio.cache.artifacts.ArtifactCache` (outputs ``whole_frame_clip`` and
``inputs``), so the cache's rules hold: create-only, found again by the key, never
deleted, evicted or overwritten.

- **Miss:** ask the :class:`~.source.ClipSource` for the chain, check every clip
  (count, requested length, frames delivered by decoding, size, start image,
  provenance) and make the clip set record; then commit the clips and the chained
  start images as one **media stage** (``whole_frame_media-<clip set hash>``,
  **proposal**), then the clip set. Blobs first, records last, as every stage, and
  every blob is listed by a completed record, so ``store doctor`` sees no orphan.
- **Hit:** read the completed record, check that the clip set is this key's, and read
  its media stage's record in the same run: it must list exactly the clip set's clips
  and start images, each re-hashed. A missing or damaged clip fails closed; nothing is
  repaired, regenerated or skipped.

The clip set's hash is what the plan puts in the segment key, so the renderer
(:mod:`.renderer`) reads the clips by hash from there.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, BinaryIO

from haynes_studio.cache.artifacts import JSON, ArtifactCache, CachedArtifact
from haynes_studio.cache.keys import WHOLE_FRAME_CLIP, CacheKey
from haynes_studio.jsonio import parse_strict, thaw
from haynes_studio.render.clock import I2V_MAX_CLIPS
from haynes_studio.render.encode import decode_frames
from haynes_studio.stages import StageOutput, commit_stage, completed_stage
from haynes_studio.store import (
    BLOB_MISSING,
    HASH_MISMATCH,
    Store,
    StoreError,
    blob_locator,
    canonical_json,
    is_sha256,
)
from haynes_studio.wholeframe.errors import (
    CHAIN_LIMIT,
    CLIP_INVALID,
    SOURCE_SHORT,
    UNSUPPORTED,
    WholeFrameError,
)
from haynes_studio.wholeframe.source import (
    MP4,
    PHOTO,
    PNG,
    PREVIOUS_LAST_FRAME,
    ClipRequest,
    ClipSource,
    ClipSpec,
    SourceClip,
    chain_seed,
    png_bytes,
    sha256_hex,
)

SCHEMA = "studio.whole-frame-clips/v1"  # proposal: the clip set record
ADAPTER = "studio.i2v/1"  # the adapter version the key's profile must name (Toolchain default)


MEDIA_STAGE = "whole_frame_media"  # proposal: the stage that records a clip set's media
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp")  # a photo's media types (section 8)


def media_stage(clip_set_sha256: str) -> str:
    """The stage that records a clip set's clips and start images (**proposal**):
    ``whole_frame_media-<the clip set's SHA-256>``. Named by the clip set's content, so
    a failed attempt's record never collides with a retry's."""
    return f"{MEDIA_STAGE}-{clip_set_sha256}"


def media_outputs(clip_set: Mapping[str, Any]) -> dict[str, str]:
    """Output name to hash for a clip set's media stage: ``clip.<i>`` for each clip and
    ``start.<i>`` for each chained clip's start image."""
    out = {}
    for clip in clip_set["clips"]:
        out[f"clip.{clip['index']}"] = clip["sha256"]
        if clip["start_image"].get("role") == PREVIOUS_LAST_FRAME:
            out[f"start.{clip['index']}"] = clip["start_image"]["sha256"]
    return out


def _text(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise WholeFrameError(CLIP_INVALID, f"{what} is not a text")
    return value


@dataclass(frozen=True)
class Measured:
    """What the adapter measured by decoding one clip."""

    frames: int
    width: int
    height: int
    last_png: bytes


def measure(data: bytes) -> Measured:
    """Decode a clip once: its frame count, its size and its last frame as PNG.
    Undecodable bytes are ``wholeframe.clip_invalid``."""
    count, last, shape = 0, None, None
    try:
        for frame in decode_frames(data):
            if shape is None:
                shape = frame.shape
            elif frame.shape != shape:
                raise WholeFrameError(CLIP_INVALID, "the clip changes size between frames")
            last, count = frame, count + 1
    except WholeFrameError:
        raise
    except Exception as error:  # PyAV raises its own error types for damaged media
        raise WholeFrameError(CLIP_INVALID, f"the clip does not decode: {type(error).__name__}") from error
    if last is None or shape is None:
        raise WholeFrameError(SOURCE_SHORT, "the clip holds no frame")
    return Measured(frames=count, width=shape[1], height=shape[0], last_png=png_bytes(last))


def check_profile(document: Mapping[str, Any], adapter: str) -> dict[str, Any]:
    """The key's profile, if this adapter can serve it: it names ``adapter``, a whole
    ``source_fps`` and an even ``size`` ``[width, height]``; and the key asks for at
    most :data:`~haynes_studio.render.clock.I2V_MAX_CLIPS` clips. Else a refusal."""
    profile = thaw(document["profile"])
    if profile.get("adapter") != adapter:
        raise WholeFrameError(UNSUPPORTED, f"the key's profile names adapter "
                              f"{profile.get('adapter')!r}; this is {adapter!r}")
    fps, size = profile.get("source_fps"), profile.get("size")
    if isinstance(fps, bool) or not isinstance(fps, int) or fps < 1:
        raise WholeFrameError(UNSUPPORTED, f"profile source_fps {fps!r} is not a whole fps")
    if (not isinstance(size, list) or len(size) != 2
            or any(isinstance(v, bool) or not isinstance(v, int) or v < 2 or v % 2 for v in size)):
        raise WholeFrameError(UNSUPPORTED, f"profile size {size!r} is not [width, height] in even pixels")
    delivery = profile.get("delivery")
    if isinstance(delivery, Mapping) and "aspect" in delivery:
        aspect = "9:16" if size[1] > size[0] else "16:9"  # as MediaFormat.aspect names it
        if delivery["aspect"] != aspect:
            raise WholeFrameError(UNSUPPORTED, f"profile size {size} is {aspect}; the media kind "
                                  f"delivers {delivery['aspect']}")
    if len(document["clip_lengths"]) > I2V_MAX_CLIPS:
        raise WholeFrameError(CHAIN_LIMIT, f"{len(document['clip_lengths'])} clips requested; "
                              f"the chain limit is {I2V_MAX_CLIPS}")
    return profile


def production_reader(store: Store, scope: str,
                      media_types: Sequence[str] = (JSON, MP4)) -> Callable[[str], BinaryIO]:
    """A reader of blobs by hash in ``scope`` (a production ID or ``library``), for a
    ``PictureBuilder``'s ``open_input`` or a photo reader: it opens the first of
    ``media_types`` the store holds under that hash, or ``store.blob_missing``."""

    def open_input(sha256: str) -> BinaryIO:
        for media_type in media_types:
            try:
                return store.open(blob_locator(scope, sha256, media_type))
            except StoreError as error:
                if error.code != BLOB_MISSING:
                    raise
        raise StoreError(BLOB_MISSING, f"no blob {sha256} of {', '.join(media_types)} in {scope}")
    return open_input


def read_verified(open_input: Callable[[str], BinaryIO], sha256: str) -> bytes:
    """The bytes of blob ``sha256``, re-hashed (``store.hash_mismatch`` otherwise)."""
    with open_input(sha256) as handle:
        data = handle.read()
    if hashlib.sha256(data).hexdigest() != sha256:
        raise StoreError(HASH_MISMATCH, f"blob {sha256} is not the bytes it is named by")
    return data


class WholeFrameClips:
    """The whole-frame clip stage on ``cache``: a ``content`` source for
    ``whole_frame_clip`` keys (see the module docstring). ``read_photo`` returns the
    bytes of the photo the key names by hash; ``source`` makes clips on a miss."""

    def __init__(self, cache: ArtifactCache, source: ClipSource, *,
                 read_photo: Callable[[str], BinaryIO], adapter: str = ADAPTER):
        self.cache = cache
        self.source = source
        self.read_photo = read_photo
        self.adapter = adapter
        self.made: list[str] = []  # keys whose clips this stage asked the source for

    def __call__(self, key: CacheKey) -> str:
        return self.clips(key).sha256

    def clips(self, key: CacheKey) -> CachedArtifact:
        """The key's clip set: a checked hit, or made, checked, published and committed."""
        if key.kind != WHOLE_FRAME_CLIP:
            raise LookupError(f"the whole-frame clip stage makes no {key.kind} artifacts")
        profile = check_profile(key.document, self.adapter)
        found = self.cache.lookup(key, JSON)
        if found is not None:
            self._check_hit(key, found)
            return found
        return self.cache.commit(key, self._make(key, profile), JSON)

    # A miss ----------------------------------------------------------------------------

    def _make(self, key: CacheKey, profile: dict[str, Any]) -> bytes:
        document = key.document
        photo = read_verified(self.read_photo, document["photo"])
        seed = document["seed"]
        specs = tuple(ClipSpec(index=i, frames=n, seed=chain_seed(seed, i))
                      for i, n in enumerate(document["clip_lengths"]))
        request = ClipRequest(key=key.value, photo=photo, photo_sha256=document["photo"],
                              prompt=document["prompt"], seed=seed, profile=profile, clips=specs)
        clips = list(self.source.generate(request))
        self.made.append(key.value)
        records, starts = self._check_clips(request, clips)
        try:  # the whole record is made before anything is published
            data = canonical_json({
                "schema": SCHEMA, "key": key.value, "adapter": self.adapter,
                "source": _text(getattr(self.source, "name", None), "the source's name"),
                "photo": {"sha256": document["photo"]}, "prompt": document["prompt"],
                "seed": seed, "profile": profile, "clip_lengths": list(document["clip_lengths"]),
                "source_fps": profile["source_fps"], "clips": records})
        except (TypeError, ValueError) as error:
            raise WholeFrameError(CLIP_INVALID, f"the clip set is not plain JSON: {error}",
                                  where=key.value) from error
        outputs = {}
        for clip, record, start in zip(clips, records, starts):
            outputs[f"clip.{record['index']}"] = StageOutput(clip.data, MP4, record["sha256"])
            if start is not None:
                outputs[f"start.{record['index']}"] = StageOutput(
                    start, PNG, record["start_image"]["sha256"])
        # Blobs, then the media stage's record, then (in clips()) the clip set's.
        commit_stage(self.cache.store, ledger=self.cache.ledger,
                     production_id=self.cache.production_id, run_id=self.cache.run_id,
                     stage=media_stage(hashlib.sha256(data).hexdigest()), outputs=outputs)
        return data

    def _check_clips(self, request: ClipRequest, clips: Sequence[SourceClip]
                     ) -> tuple[list[dict[str, Any]], list[bytes | None]]:
        """One provenance record per clip, each measured, and each chained clip's start
        image (PNG bytes; None for the photo). Any clip that is missing, short, or of
        another length, size, seed or start image than asked fails before anything is
        published."""
        if [clip.index for clip in clips] != [spec.index for spec in request.clips]:
            missing = sorted({spec.index for spec in request.clips} - {clip.index for clip in clips})
            if missing:
                raise WholeFrameError(SOURCE_SHORT, f"the source returned no clip {missing}",
                                      where=request.key)
            raise WholeFrameError(CLIP_INVALID, "the source's clips are not the chain asked for, "
                                  "in order", where=request.key)
        width, height = request.profile["size"]
        records: list[dict[str, Any]] = []
        starts: list[bytes | None] = []
        previous = None
        for spec, clip in zip(request.clips, clips):
            where = f"{request.key} clip {spec.index}"
            if not isinstance(clip.data, bytes) or clip.media_type != MP4:
                raise WholeFrameError(CLIP_INVALID, "a clip is MP4 bytes", where=where)
            measured = measure(clip.data)
            if clip.frames_requested != spec.frames or clip.seed != spec.seed:
                raise WholeFrameError(CLIP_INVALID, f"made with {clip.frames_requested} frames and "
                                      f"seed {clip.seed}, asked {spec.frames} and {spec.seed}", where=where)
            if measured.frames < spec.frames:
                raise WholeFrameError(SOURCE_SHORT, f"delivered {measured.frames} of {spec.frames} "
                                      "frames", where=where)
            if measured.frames > spec.frames:
                raise WholeFrameError(CLIP_INVALID, f"delivered {measured.frames} frames, asked "
                                      f"{spec.frames}", where=where)
            if (measured.width, measured.height) != (width, height):
                raise WholeFrameError(CLIP_INVALID, f"{measured.width}x{measured.height}, the "
                                      f"profile asks {width}x{height}", where=where)
            if previous is None:
                start: dict[str, Any] = {"role": PHOTO, "sha256": request.photo_sha256}
            else:
                start = {"role": PREVIOUS_LAST_FRAME, "sha256": sha256_hex(previous.last_png),
                         "media_type": PNG}
            if clip.start_image_sha256 != start["sha256"]:
                raise WholeFrameError(CLIP_INVALID, f"started on {clip.start_image_sha256}, not "
                                      f"the chain's {start['role']} {start['sha256']}", where=where)
            for value, what in ((clip.engine, "its engine"), (clip.engine_job_id, "its engine job")):
                if not isinstance(value, str) or not value:
                    raise WholeFrameError(CLIP_INVALID, f"a clip names {what}", where=where)
            files = clip.files_sha256
            if (not isinstance(files, Mapping) or not files
                    or not all(isinstance(n, str) and n and is_sha256(h) for n, h in files.items())):
                raise WholeFrameError(CLIP_INVALID, "a clip names its model files, each by SHA-256",
                                      where=where)
            records.append({
                "index": spec.index, "sha256": sha256_hex(clip.data), "bytes": len(clip.data),
                "media_type": MP4, "engine": clip.engine, "engine_job_id": clip.engine_job_id,
                "seed": clip.seed, "profile": request.profile,
                "files_sha256": dict(clip.files_sha256), "start_image": start,
                "frames_requested": spec.frames, "frames_delivered": measured.frames,
                "width": measured.width, "height": measured.height, "extra": thaw(clip.extra)})
            starts.append(None if previous is None else previous.last_png)
            previous = measured
        return records, starts

    # A hit -----------------------------------------------------------------------------

    def _check_hit(self, key: CacheKey, found: CachedArtifact) -> None:
        """The clip set is this key's, and its media stage, committed in the same run,
        lists exactly its clips and start images, each re-hashed by the ledger (or
        through the store for a ledger that cannot see the blobs)."""
        with self.cache.store.open(found.blob.locator) as handle:
            clip_set = read_clip_set(handle.read(), found.sha256)
        check_clip_set(clip_set, key=key.value, where=found.blob.locator)
        stage = media_stage(found.sha256)
        cache = self.cache
        try:
            record = completed_stage(cache.ledger, production_id=cache.production_id,
                                     run_id=found.record.run_id, stage=stage,
                                     store=None if cache.ledger is cache.store else cache.store)
        except StoreError as error:
            if error.code == BLOB_MISSING:
                raise WholeFrameError(SOURCE_SHORT, f"a clip or start image of the clip set is "
                                      f"missing: {error.message}", where=error.locator) from error
            raise
        if record is None:
            raise WholeFrameError(SOURCE_SHORT, "the clip set's media stage has no completion "
                                  "record", where=stage)
        expected = media_outputs(clip_set)
        if {name: blob.sha256 for name, blob in record.blobs.items()} != expected:
            raise WholeFrameError(CLIP_INVALID, "the media stage does not list exactly the clip "
                                  "set's clips and start images", where=stage)


def read_clip_set(data: bytes, sha256: str) -> dict[str, Any]:
    """A clip set record from its bytes, re-hashed and parsed strictly."""
    if hashlib.sha256(data).hexdigest() != sha256:
        raise StoreError(HASH_MISMATCH, f"clip set {sha256} is not the bytes it is named by")
    try:
        document = parse_strict(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise WholeFrameError(CLIP_INVALID, "the clip set is not strict JSON") from error
    if not isinstance(document, dict):
        raise WholeFrameError(CLIP_INVALID, "the clip set is not a JSON object")
    return document


def check_clip_set(document: Mapping[str, Any], *, key: str | None = None,
                   where: str | None = None) -> None:
    """The clip set's shape: its schema, its key (when given), one record per
    requested clip in order, each with a hash, the frames it delivered and its size."""
    if document.get("schema") != SCHEMA:
        raise WholeFrameError(CLIP_INVALID, f"schema {document.get('schema')!r} is not {SCHEMA}",
                              where=where)
    if key is not None and document.get("key") != key:
        raise WholeFrameError(CLIP_INVALID, "the clip set was made for another key", where=where)
    fps = document.get("source_fps")
    if isinstance(fps, bool) or not isinstance(fps, int) or fps < 1:
        raise WholeFrameError(CLIP_INVALID, f"source_fps {fps!r} is not a whole fps", where=where)
    clips, lengths = document.get("clips"), document.get("clip_lengths")
    if not isinstance(clips, list) or not isinstance(lengths, list) or len(clips) != len(lengths):
        raise WholeFrameError(SOURCE_SHORT, "the clip set does not list one clip per requested "
                              "length", where=where)
    for index, clip in enumerate(clips):
        ok = (isinstance(clip, dict) and clip.get("index") == index
              and isinstance(clip.get("sha256"), str) and clip.get("media_type") == MP4
              and isinstance(clip.get("start_image"), dict)
              and all(isinstance(clip.get(name), int) and not isinstance(clip.get(name), bool)
                      for name in ("frames_requested", "frames_delivered", "width", "height")))
        if not ok:
            raise WholeFrameError(CLIP_INVALID, f"clip record {index} is malformed", where=where)
