"""The board clock (contract section 4, P-06; TIME-8, TIME-8a and TIME-9).

All picture runs on the board clock: frame 0 is the board's first frame, wherever the
board lands in the film. Nothing here takes a film frame, a film offset or a board's
place in the story, so nothing a board draws can depend on the film clock.

- Looping layers start at ``int(sha256(board_id + ":" + slot)[:8], 16) mod period``
  (:func:`loop_phase`), stable across edits and reorders.
- Procedural randomness is a pure function of ``(seed, board_id, index)``
  (:func:`procedural_random`); no generator state carries from one board to the next.
- Generation seeds are explicit on the board (``seeds``); nothing here makes one.

Pure functions, integers only; legacy-mode rendering (stories 378 and 425) keeps the
film clock and does not use this module.
"""

from __future__ import annotations

import hashlib

from haynes_studio.timebase import DELIVERY_FPS, ceil_div

SET_SLOT = "set"  # proposal: the slot name of the set loop in its phase
S2V_CHUNK = 77  # TIME-9: speech-to-video chunks of 77 source frames
I2V_CLIP_FRAMES = 121  # TI2V-5B: 121 frames at 24 fps (section 3)
I2V_MAX_CLIPS = 3  # proposal (story 427): the longest whole-frame chain E0 delivered


def _whole(name: str, value: object, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer, got {type(value).__name__}")
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}, got {value}")
    return value


def loop_period(length: int) -> int:
    """TIME-8a: a ping-pong loop of ``length`` source frames repeats every
    ``2 * length - 2`` frames (a one-frame loop every frame)."""
    _whole("length", length, 1)
    return max(1, 2 * length - 2)


def pingpong(index: int, length: int) -> int:
    """TIME-8a: the source frame a ping-pong loop of ``length`` frames shows at
    ``index`` (0, 1, ..., N-1, N-2, ..., 1, 0, 1, ...). Legacy ``pingpong()``."""
    _whole("index", index)
    period = loop_period(length)
    j = index % period
    return j if j < length else period - j


def loop_phase(board_id: str, slot: str, period: int) -> int:
    """P-06: a looping layer's start phase, ``int(sha256(board_id + ":" + slot)[:8], 16)
    mod period``, so it never moves when another board changes or the boards are
    reordered."""
    if not isinstance(board_id, str) or not isinstance(slot, str):
        raise TypeError("board_id and slot are texts")
    digest = hashlib.sha256(f"{board_id}:{slot}".encode()).hexdigest()
    return int(digest[:8], 16) % _whole("period", period, 1)


def loop_frame(board_frame: int, phase: int, length: int) -> int:
    """TIME-8a: board frame ``n`` of a looping layer shows source frame
    ``pingpong(n + phase, length)``."""
    return pingpong(_whole("board_frame", board_frame) + _whole("phase", phase), length)


def source_frame(board_frame: int, source_fps: int, fps: int = DELIVERY_FPS) -> int:
    """TIME-8: board frame ``n`` of a board-specific clip shows source frame
    ``floor(n * fs / fps)`` (``floor(2n / 3)`` at 16 fps)."""
    return (_whole("board_frame", board_frame) * _whole("source_fps", source_fps, 1)
            // _whole("fps", fps, 1))


def source_frames_needed(frames: int, source_fps: int, fps: int = DELIVERY_FPS) -> int:
    """TIME-8: a board of ``frames`` frames needs ``floor((F - 1) * fs / fps) + 1``
    source frames of a board-specific clip."""
    return source_frame(_whole("frames", frames, 1) - 1, source_fps, fps) + 1


def s2v_request_frames(frames: int) -> int:
    """TIME-9: the speech-to-video length requested for a board of ``frames`` frames:
    ``L = 4 * ceil(F / 6) + 1``, then ``77 * ceil(L / 77)`` when ``L > 77``."""
    length = 4 * ceil_div(_whole("frames", frames, 1), 6) + 1
    return S2V_CHUNK * ceil_div(length, S2V_CHUNK) if length > S2V_CHUNK else length


def i2v_chain_frames(clip_lengths: tuple[int, ...] | list[int]) -> int:
    """The distinct source frames a chain of whole-frame clips yields: every clip after
    the first starts on the previous clip's last frame, which is dropped, so a chain
    gives ``sum(lengths) - (clips - 1)`` frames (E0: 241 from two 121-frame clips)."""
    lengths = [_whole(f"clip_lengths[{i}]", n, 1) for i, n in enumerate(clip_lengths)]
    if not lengths:
        raise ValueError("a chain has at least one clip")
    return sum(lengths) - (len(lengths) - 1)


def i2v_clip_lengths(frames_needed: int, clip_frames: int = I2V_CLIP_FRAMES,
                     max_clips: int = I2V_MAX_CLIPS) -> tuple[int, ...]:
    """The whole-frame chain policy (story 427, a **proposal** from the E0 evidence):
    the clip lengths requested for a board that needs ``frames_needed`` source frames
    (TIME-8).

    - Every clip is a whole clip of ``clip_frames`` (121, the only length E0 made), so
      a hold or tail edit that still fits the same chain keeps the clips (section 4).
    - A board longer than one clip **chains**: each later clip starts on the previous
      clip's last frame and adds ``clip_frames - 1`` new frames, so ``n`` clips cover
      ``1 + n * (clip_frames - 1)`` frames (121, 241, 361). Extra frames are trimmed by
      the renderer. No stretch (it would break TIME-8's 24 fps mapping) and no hold.
    - At most ``max_clips`` clips (3: 361 frames, 15.04 s, E0's longest chain, shot 8),
      because drift compounds along a chain; a longer board is a ``ValueError``."""
    needed = _whole("frames_needed", frames_needed, 1)
    size = _whole("clip_frames", clip_frames, 2)  # a chain adds clip_frames - 1 frames per clip
    limit = _whole("max_clips", max_clips, 1)
    count = 1 if needed <= size else 1 + ceil_div(needed - size, size - 1)
    if count > limit:
        raise ValueError(f"{needed} source frames need {count} chained clips of {size}; the "
                         f"chain limit is {limit} clips ({1 + limit * (size - 1)} frames)")
    return (size,) * count


def board_stream(seed: int, board_id: str) -> int:
    """The 64-bit stream number of a board's procedural randomness: the first 16 hex
    digits of ``sha256("<seed>:<board_id>")``. A segment key carries this number, not
    the board ID."""
    _whole("seed", seed)
    if not isinstance(board_id, str):
        raise TypeError("board_id is a text")
    return int(hashlib.sha256(f"{seed}:{board_id}".encode()).hexdigest()[:16], 16)


def stream_random(stream: int, index: int) -> int:
    """Draw ``index`` of a board's procedural stream: a 64-bit integer, a pure
    function of the two numbers (no generator state)."""
    _whole("stream", stream)
    _whole("index", index)
    return int(hashlib.sha256(f"{stream}:{index}".encode()).hexdigest()[:16], 16)


def procedural_random(seed: int, board_id: str, index: int) -> int:
    """P-06: procedural randomness as a pure function of ``(seed, board_id, index)``."""
    return stream_random(board_stream(seed, board_id), index)
