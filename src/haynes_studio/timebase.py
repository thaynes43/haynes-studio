"""Integer time arithmetic: contract section 3, rules TIME-1 to TIME-4 and TIME-7.

Every duration is an integer in a named unit: milliseconds (``*_ms``), delivery frames
at 24 fps (``*frames``, ``*_frame``) and mix samples at 48 000 Hz (``*_sample``,
``*samples``). No float carries time. Each conversion states its rounding; most are
exact. Pure functions with no media library, safe to import anywhere.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction

DELIVERY_FPS = 24
MIX_RATE = 48_000
SAMPLES_PER_FRAME = MIX_RATE // DELIVERY_FPS  # 2000
SAMPLES_PER_MS = MIX_RATE // 1000  # 48

# TIME-4 and TIME-5 bounds, and the P-04 defaults for a new board.
HOLD_MIN_MS = 100
HOLD_MAX_MS = 120_000
TAIL_MIN_MS = 250
DEFAULT_LEAD_MS = 500
DEFAULT_GAP_MS = 300
DEFAULT_TAIL_MS = 700


def _whole(name: str, value: object, *, minimum: int | None = 0) -> int:
    """``value`` as an int, refusing bools, floats and anything below ``minimum``."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer, got {type(value).__name__}")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}, got {value}")
    return value


def ceil_div(numerator: int, denominator: int) -> int:
    """``ceil(numerator / denominator)`` in integers, for a positive denominator."""
    _whole("numerator", numerator, minimum=None)
    _whole("denominator", denominator, minimum=1)
    return -(-numerator // denominator)


def take_duration_ms(samples: int, rate: int) -> int:
    """TIME-1: a measured take lasts ``ceil(samples * 1000 / rate)`` ms, rounded up so a
    line is never shorter than its audio."""
    return ceil_div(_whole("samples", samples) * 1000, _whole("rate", rate, minimum=1))


def frames_for_ms(duration_ms: int, fps: int = DELIVERY_FPS) -> int:
    """TIME-3 and TIME-4: ``ceil(duration_ms * fps / 1000)`` frames, rounded up; at 24 fps
    that is ``(duration_ms * 24 + 999) div 1000``. The remainder (under one frame) lands
    in the tail."""
    return ceil_div(_whole("duration_ms", duration_ms) * _whole("fps", fps, minimum=1), 1000)


@dataclass(frozen=True)
class LineSpan:
    """One line on the board clock (ms from board start); the end is exclusive."""

    start_ms: int
    end_ms: int


def line_spans(lead_ms: int, durations_ms: Sequence[int],
               gaps_ms: Sequence[int | None]) -> tuple[LineSpan, ...]:
    """TIME-2: ``start[0] = lead``; ``start[i] = end[i-1] + gap[i]``;
    ``end[i] = start[i] + duration[i]``. The first gap must be ``None``."""
    if len(durations_ms) != len(gaps_ms):
        raise ValueError("durations_ms and gaps_ms differ in length")
    spans: list[LineSpan] = []
    cursor = _whole("lead_ms", lead_ms)
    for i, (duration, gap) in enumerate(zip(durations_ms, gaps_ms)):
        if i == 0:
            if gap is not None:
                raise ValueError("the first line has no gap (time.first_line_gap)")
        else:
            cursor += _whole(f"gaps_ms[{i}]", gap)
        end = cursor + _whole(f"durations_ms[{i}]", duration)
        spans.append(LineSpan(cursor, end))
        cursor = end
    return tuple(spans)


def spoken_content_ms(lead_ms: int, durations_ms: Sequence[int],
                      gaps_ms: Sequence[int | None], tail_ms: int) -> int:
    """TIME-3: ``lead + sum(durations) + sum(gaps) + tail`` for a board with lines."""
    spans = line_spans(lead_ms, durations_ms, gaps_ms)
    if not spans:
        raise ValueError("a spoken board has at least one line")
    return spans[-1].end_ms + _whole("tail_ms", tail_ms)


def film_start_frames(frames: Sequence[int]) -> tuple[int, ...]:
    """TIME-7: board *k* starts at film frame ``F[k] = sum(frames[j], j < k)``."""
    starts, total = [], 0
    for i, count in enumerate(frames):
        starts.append(total)
        total += _whole(f"frames[{i}]", count)
    return tuple(starts)


def frames_to_samples(frames: int) -> int:
    """Delivery frames to mix samples: exactly 2000 per frame."""
    return _whole("frames", frames, minimum=None) * SAMPLES_PER_FRAME


def ms_to_samples(duration_ms: int) -> int:
    """Milliseconds to mix samples: exactly 48 per ms."""
    return _whole("duration_ms", duration_ms, minimum=None) * SAMPLES_PER_MS


def mix_sample(film_frame: int, offset_ms: int) -> int:
    """TIME-7: a point ``offset_ms`` into the board that starts at ``film_frame`` is mix
    sample ``film_frame * 2000 + offset_ms * 48``. Exact; no rounded seconds between."""
    return frames_to_samples(film_frame) + ms_to_samples(offset_ms)


def display_seconds(frames: int, fps: int = DELIVERY_FPS) -> str:
    """``frames / fps`` seconds as text with 3 decimals, rounded to nearest (at 24 fps
    there are no ties). For display only; never parse it back into time."""
    exact = Fraction(_whole("frames", frames), _whole("fps", fps, minimum=1))
    thousandths = round(exact * 1000)
    return f"{thousandths // 1000}.{thousandths % 1000:03d}"


def ms_from_seconds(value: int | float | str | Decimal) -> int:
    """Decimal seconds as written in a legacy file (``0.35``, ``1.9``, ``5.163``) to whole
    milliseconds, exactly. A float is read by its shortest repr, which is the JSON text
    it came from. Raises ``ValueError`` for a value that is not a whole number of ms
    (no rounding), and ``TypeError`` for a bool or a non-number."""
    if isinstance(value, bool):
        raise TypeError("seconds must be a number, got bool")
    try:
        if isinstance(value, float):
            seconds = Decimal(repr(value))
        elif isinstance(value, (int, str, Decimal)):
            seconds = Decimal(value)
        else:
            raise TypeError(f"seconds must be a number, got {type(value).__name__}")
    except InvalidOperation:
        raise ValueError(f"{value!r} is not a number of seconds") from None
    if not seconds.is_finite():
        raise ValueError(f"{value!r} is not a finite number of seconds")
    millis = seconds * 1000
    if millis != millis.to_integral_value():
        raise ValueError(f"{value!r} s is not a whole number of milliseconds")
    return int(millis)
