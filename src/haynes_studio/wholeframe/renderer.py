"""The whole-frame segment renderer (story 427): a board's frames from its clip chain.

:class:`WholeFrameRenderer` implements :class:`~haynes_studio.render.base.SegmentRenderer`
for ``whole_frame`` + ``i2v`` boards. From the segment key document alone it:

1. refuses what it does not draw (:func:`check_segment`): another method, a cue, a
   layout, layers, a set, a motion style or a foreground, an unknown key input, an fps
   other than 24;
2. reads the clip set the key names by hash, and every clip it lists, re-hashing
   each (a missing clip is ``time.source_short``);
3. maps the board onto the chain by TIME-8 (:func:`~.chain.assemble`): the duplicate
   frame at each chain boundary is dropped, extra frames are trimmed and recorded in
   :attr:`WholeFrameRenderer.reports`, a short chain fails before any frame is drawn;
4. fits the clip size to the board's by the stated rule (:func:`fit_rule`): the same
   size as is; the same aspect scaled with Lanczos (E0's assembler); any other aspect
   is refused, never cropped or padded;
5. yields exactly the board's frames, decoding one clip at a time. A clip that
   decodes to fewer frames than recorded fails mid-way, so nothing is committed.

The voice envelope, ``talk`` and ``procedural_stream`` are accepted and draw nothing:
a whole-frame I2V picture has no talk bounce and no procedural layer (E0's whole-frame
film; contract section 5 names only the photo and the ``i2v:frame`` seed).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import PIL
import PIL.Image

from haynes_studio.render.base import SegmentRenderer, SegmentRequest
from haynes_studio.render.encode import decode_frames
from haynes_studio.store import BLOB_MISSING, StoreError
from haynes_studio.timebase import DELIVERY_FPS
from haynes_studio.wholeframe.chain import Assembly, assemble
from haynes_studio.wholeframe.clips import check_clip_set, read_clip_set, read_verified
from haynes_studio.wholeframe.errors import (
    CLIP_INVALID,
    METHOD_UNAVAILABLE,
    SOURCE_SHORT,
    UNSUPPORTED,
    WholeFrameError,
)

# Proposal: the segment key's compositor digest. It names the Pillow build, whose Lanczos
# scaling draws the pixels when a clip is resized (the encoder build is the encoder's).
COMPOSITOR = f"studio.wholeframe/1+pillow-{PIL.__version__}"
LANCZOS = "lanczos"

# Every input of a segment key document (keys.INVENTORY), and what this renderer does
# with it. "draw": used; "none": accepted, draws nothing on a whole-frame board;
# "absent": must be null or empty, else refused.
SEGMENT_INPUTS = {
    "kind": "draw", "scheme": "draw", "method": "draw", "frames": "draw", "width": "draw",
    "height": "draw", "fps": "draw", "whole_frame_clip": "draw", "compositor": "draw",
    "encoder": "draw", "voice_envelope": "none", "talk": "none", "procedural_stream": "none",
    "layout": "absent", "layers": "absent", "set_layer": "absent", "motion_style": "absent",
    "cues": "absent", "foreground": "absent",
}


def check_segment(inputs: Mapping[str, Any]) -> None:
    """Refuse a segment this renderer cannot draw exactly (see the module docstring)."""
    method = inputs.get("method") or {}
    layer, motion = method.get("layer"), method.get("motion")
    if layer == "whole_frame" and motion == "s2v":
        raise WholeFrameError(METHOD_UNAVAILABLE, "whole-frame speech-to-video has no adapter "
                              "(contract section 5)", where="/method")
    if (layer, motion) != ("whole_frame", "i2v"):
        raise WholeFrameError(UNSUPPORTED, f"method {layer}+{motion} is not a whole-frame I2V "
                              "board", where="/method")
    unknown = sorted(set(inputs) - set(SEGMENT_INPUTS))
    if unknown:
        raise WholeFrameError(UNSUPPORTED, f"unknown segment inputs {unknown}", where="(root)")
    for name, use in SEGMENT_INPUTS.items():
        if use == "absent" and inputs.get(name):
            what = name
            if name == "cues":
                what = "cues of type " + ", ".join(sorted({str(c.get("type")) for c in inputs[name]}))
            raise WholeFrameError(UNSUPPORTED, f"a whole-frame board draws no {what}", where=f"/{name}")
    if inputs.get("fps") != DELIVERY_FPS:
        raise WholeFrameError(UNSUPPORTED, f"fps {inputs.get('fps')!r} is not {DELIVERY_FPS}",
                              where="/fps")
    if inputs.get("whole_frame_clip") is None:
        raise WholeFrameError(SOURCE_SHORT, "the segment key names no clip", where="/whole_frame_clip")


def fit_rule(source: tuple[int, int], target: tuple[int, int]) -> str | None:
    """How a clip of ``source`` (width, height) becomes a board frame of ``target``:
    ``None`` (as is) for the same size; :data:`LANCZOS` (scaled, E0's assembler) for
    the same aspect exactly; else ``wholeframe.unsupported``: no crop, no pad."""
    (sw, sh), (tw, th) = source, target
    if (sw, sh) == (tw, th):
        return None
    if sw * th != sh * tw:
        raise WholeFrameError(UNSUPPORTED, f"a {sw}x{sh} clip is not the {tw}x{th} board's aspect; "
                              "the adapter neither crops nor pads")
    return LANCZOS


@dataclass(frozen=True)
class WholeFrameReport:
    """What one render used: the clip set, each clip's hash and share, the trim and
    the size rule. The run records it (story 406); it is not a cache input."""

    key: str
    clip_set: str
    clips: tuple[str, ...]
    assembly: Assembly
    fit: str | None
    source_size: tuple[int, int]

    def to_document(self) -> dict[str, Any]:
        return {"segment_key": self.key, "clip_set": self.clip_set, "clips": list(self.clips),
                "assembly": self.assembly.to_document(), "fit": self.fit,
                "source_size": list(self.source_size)}


@dataclass
class WholeFrameRenderer(SegmentRenderer):
    """Draws whole-frame I2V boards from their clips (see the module docstring)."""

    compositor: str = COMPOSITOR
    reports: dict[str, WholeFrameReport] = field(default_factory=dict)

    def render(self, request: SegmentRequest) -> Iterator[np.ndarray]:
        """Checks everything that can be checked before the first frame, then returns
        a generator of exactly ``request.frames`` frames."""
        inputs = request.inputs
        check_segment(inputs)
        clip_set_sha = inputs["whole_frame_clip"]
        clip_set = read_clip_set(self._read(request, clip_set_sha, "the clip set"), clip_set_sha)
        check_clip_set(clip_set, where=clip_set_sha)
        clips = clip_set["clips"]
        sizes = {(clip["width"], clip["height"]) for clip in clips}
        if len(sizes) != 1:
            raise WholeFrameError(CLIP_INVALID, f"the chain's clips differ in size: {sorted(sizes)}")
        source_size = sizes.pop()
        fit = fit_rule(source_size, (request.width, request.height))
        assembly = assemble(request.frames, [clip["frames_delivered"] for clip in clips],
                            source_fps=clip_set.get("source_fps"), fps=request.fps)
        used = [clip for clip, use in zip(clips, assembly.clips) if use.used]
        data = [self._read(request, clip["sha256"], f"clip {clip['index']}") for clip in used]
        report = WholeFrameReport(
            key=request.key, clip_set=clip_set_sha, clips=tuple(c["sha256"] for c in clips),
            assembly=assembly, fit=fit, source_size=source_size)
        return self._frames(request, assembly, used, data, fit, report)

    @staticmethod
    def _read(request: SegmentRequest, sha256: str, what: str) -> bytes:
        try:
            return read_verified(request.open, sha256)
        except StoreError as error:
            if error.code == BLOB_MISSING:
                raise WholeFrameError(SOURCE_SHORT, f"{what} is missing", where=sha256) from error
            raise
        except LookupError as error:  # a request with no input reader
            raise WholeFrameError(SOURCE_SHORT, f"{what} cannot be read: {error}", where=sha256) from error

    def _frames(self, request: SegmentRequest, assembly: Assembly, used: list[dict[str, Any]],
                data: list[bytes], fit: str | None, report: WholeFrameReport) -> Iterator[np.ndarray]:
        """The board's frames; the report is kept only once every frame was made."""
        size = (request.width, request.height)
        picks = list(assembly.picks())
        produced = 0
        for clip, blob in zip(used, data):
            index = clip["index"]
            wanted = [frame for c, frame in picks if c == index]
            if not wanted:  # only when fs > 24 skips every frame this clip offers
                continue
            last_needed = wanted[-1]
            cursor = iter(wanted)
            target = next(cursor)
            decoded = -1
            for decoded, frame in _decoded(blob, index):
                if frame.shape != (clip["height"], clip["width"], 3):
                    raise WholeFrameError(CLIP_INVALID, f"clip {index} frame {decoded} is "
                                          f"{frame.shape}, recorded {clip['width']}x{clip['height']}")
                while target == decoded:  # TIME-8 may show one source frame twice (fs < 24)
                    yield frame if fit is None else _scale(frame, size)
                    produced += 1
                    target = next(cursor, None)
                if decoded >= last_needed:
                    break
            if decoded < last_needed:
                raise WholeFrameError(SOURCE_SHORT, f"clip {index} decodes to {decoded + 1} frames; "
                                      f"frame {last_needed} is needed")
        if produced != request.frames:  # a guard: assemble() and picks() make this hold
            raise WholeFrameError(SOURCE_SHORT, f"assembled {produced} of {request.frames} frames")
        self.reports[request.key] = report


def _decoded(blob: bytes, index: int) -> Iterator[tuple[int, np.ndarray]]:
    """A stored clip's frames, numbered; a clip that stops decoding is short."""
    try:
        yield from enumerate(decode_frames(blob))
    except WholeFrameError:
        raise
    except Exception as error:  # PyAV raises its own error types for damaged media
        raise WholeFrameError(SOURCE_SHORT, f"clip {index} does not decode: "
                              f"{type(error).__name__}") from error


def _scale(frame: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    return np.asarray(PIL.Image.fromarray(frame).resize(size, PIL.Image.Resampling.LANCZOS))
