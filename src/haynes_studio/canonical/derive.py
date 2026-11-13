"""Derived values (contract sections 2 and 3): pure functions of the documents and the
measured takes, in integers through :mod:`haynes_studio.timebase`.

- A spoken board is timed only with a current voice version whose takes cover its
  lines exactly (TIME-6); its length is TIME-3 with its explicit lead, gaps and tail.
- A silent board is timed by its hold (TIME-4).
- Board *k* starts at film frame ``F[k] = sum(frames[j], j < k)`` (TIME-7); after an
  untimed board, later starts are unknown (``None``).
- Absent, stale and generating voices and photos are explicit states, never inferred
  from a null alone.
- Every number reaches :mod:`haynes_studio.timebase` as an int: models and facts are
  normalized when built, and the entry points here normalize again (an integral float
  such as ``1900.0`` is the integer 1900).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from haynes_studio.canonical.facts import PHOTO, VOICE, Facts
from haynes_studio.canonical.jsonvalues import integral
from haynes_studio.canonical.methods import UNAVAILABLE, status
from haynes_studio.canonical.model import (
    STORY_TIMING_SCHEMA,
    Anchor,
    Board,
    BoardDerived,
    BoardTimingRow,
    BuildBlocker,
    DocWarning,
    FormatLength,
    Story,
    StoryDerived,
    StoryTiming,
)
from haynes_studio.timebase import (
    DELIVERY_FPS,
    LineSpan,
    display_seconds,
    frames_for_ms,
    line_spans,
)

TIMED, UNTIMED = "timed", "untimed"
NOT_NEEDED, ABSENT, GENERATING, CURRENT, STALE = (
    "not_needed", "absent", "generating", "current", "stale")
LENGTH_EXCEEDED = "format.length_exceeded"
METHOD_UNAVAILABLE = "method.unavailable"


@dataclass(frozen=True, slots=True)
class BoardClock:
    """A timed board on its own clock: content, frames and each line's span (ms)."""

    content_ms: int
    frames: int
    spans: Mapping[str, LineSpan]

    def contains(self, start_ms: int) -> bool:
        """TIME-10: a resolved start lies in ``[0, board length)``, compared in mix
        samples as story 378 does (``start * 48 < frames * 2000``)."""
        return 0 <= start_ms * DELIVERY_FPS < self.frames * 1000


def _voice_base(board: Board, facts: Facts) -> str:
    """absent, stale or current, ignoring running jobs."""
    version = facts.voice_versions.get(board.voice.current_version_id or "")
    if version is None:
        return ABSENT
    if not version.matches_board or set(version.takes_ms) != {line.id for line in board.lines}:
        return STALE
    return CURRENT


def voice_state(board: Board, facts: Facts) -> str:
    """``not_needed`` on a silent board; ``generating`` while a voice job runs;
    otherwise ``absent``, ``stale`` or ``current`` (VOICE-4)."""
    if not board.spoken:
        return NOT_NEEDED
    if (board.id, VOICE) in facts.generating:
        return GENERATING
    return _voice_base(board, facts)


def photo_state(board: Board, facts: Facts) -> str:
    if (board.id, PHOTO) in facts.generating:
        return GENERATING
    version = facts.photo_versions.get(board.photo.current_version_id or "")
    if version is None:
        return ABSENT
    return CURRENT if version.matches_board else STALE


def untimed_reason(board: Board, facts: Facts) -> str | None:
    """``voice.absent`` or ``voice.stale`` for an untimed spoken board, else None."""
    if not board.spoken:
        return None
    base = _voice_base(board, facts)
    return None if base == CURRENT else f"voice.{base}"


def board_clock(board: Board, facts: Facts) -> BoardClock | None:
    """The board's timing, or None while it is untimed (TIME-6)."""
    if not board.spoken:
        hold = integral(board.timing.hold_ms)
        return BoardClock(content_ms=hold, frames=frames_for_ms(hold),
                          spans=MappingProxyType({}))
    if _voice_base(board, facts) != CURRENT:
        return None
    takes = facts.voice_versions[board.voice.current_version_id].takes_ms
    spans = line_spans(integral(board.timing.lead_ms),
                       [integral(takes[line.id]) for line in board.lines],
                       [integral(line.gap_before_ms) for line in board.lines])
    content = spans[-1].end_ms + integral(board.timing.tail_ms)
    return BoardClock(content_ms=content, frames=frames_for_ms(content),
                      spans=MappingProxyType({line.id: span
                                              for line, span in zip(board.lines, spans)}))


def resolve_anchor(anchor: Anchor, clock: BoardClock) -> int:
    """A cue anchor in ms from board start: ``at_ms``, or the end of the named line
    plus ``offset_ms`` (contract section 6)."""
    if anchor.at_ms is not None:
        return integral(anchor.at_ms)
    return clock.spans[anchor.after_line_id].end_ms + integral(anchor.offset_ms)


def board_derived(board: Board, facts: Facts, film_start_frame: int | None) -> BoardDerived:
    clock = board_clock(board, facts)
    return BoardDerived(
        timing_state=TIMED if clock else UNTIMED,
        content_ms=clock.content_ms if clock else None,
        frames=clock.frames if clock else None,
        film_start_frame=film_start_frame if clock else None,
        voice_state=voice_state(board, facts),
        photo_state=photo_state(board, facts),
    )


def boards_derived(boards: Sequence[Board], facts: Facts) -> tuple[BoardDerived, ...]:
    """Derived values for boards in film order (TIME-7): a start is known only while
    every earlier board is timed."""
    out, start = [], 0
    for board in boards:
        clock = board_clock(board, facts)
        out.append(board_derived(board, facts, start))
        start = start + clock.frames if (clock and start is not None) else None
    return tuple(out)


def _seconds_text(ms: int) -> str:
    text = format(Decimal(ms) / 1000, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def length_warning(frames_known: int, complete: bool,
                   length: FormatLength | None) -> DocWarning | None:
    """D45: a warning when the story (or, while incomplete, its timed boards
    already) runs past the format's maximum. Build stays allowed."""
    frames_known = integral(frames_known)
    if length is None or frames_known * 1000 <= length.max_ms * DELIVERY_FPS:
        return None
    runs = display_seconds(frames_known)
    limit = _seconds_text(length.max_ms)
    message = (f"The story runs {runs} s, past the format maximum of {limit} s." if complete
               else f"Timed boards already run {runs} s, past the format maximum of {limit} s.")
    return DocWarning(code=LENGTH_EXCEEDED, severity="warning", message=message,
                      build_allowed=True, decision="D45")


def method_warnings(boards: Sequence[Board]) -> tuple[DocWarning, ...]:
    """``method.unavailable`` for each board whose method saves but cannot be built
    (whole-frame speech-to-video, section 5), in film order."""
    return tuple(
        DocWarning(code=METHOD_UNAVAILABLE, severity="warning", build_allowed=False,
                   message=(f"Board B{board.number:02d} ({board.id}) uses "
                            f"{board.method.layer} {board.method.motion}, which has no "
                            "adapter yet: it saves, and Build refuses it."))
        for board in boards if status(board.method.layer, board.method.motion) == UNAVAILABLE)


def story_derived(story: Story, boards: Sequence[Board], facts: Facts, *,
                  format_length: FormatLength | None = None,
                  highest_number_issued: int | None = None) -> StoryDerived:
    """A story's totals from its boards in ``board_order``. ``highest_number_issued``
    is the largest board number ever given in the story, removed boards included
    (numbers are never reused); by default the largest number among ``boards``.
    ``warnings`` lists each board's ``method.unavailable``, then the D45 length
    warning."""
    derived = boards_derived(boards, facts)
    timed = [d for d in derived if d.timing_state == TIMED]
    frames = sum(d.frames for d in timed)
    highest = max([integral(b.number) for b in boards] +
                  [integral(highest_number_issued) or 0])
    warning = length_warning(frames, len(timed) == len(derived), format_length)
    return StoryDerived(
        board_count=len(boards), next_board_number=highest + 1, timed_boards=len(timed),
        untimed_boards=len(derived) - len(timed), frames=frames, fps=DELIVERY_FPS,
        duration_ms=frames * 1000 // DELIVERY_FPS,
        warnings=method_warnings(boards) + ((warning,) if warning else ()),
    )


def story_timing(story: Story, boards: Sequence[Board], facts: Facts, *,
                 blockers: Sequence[BuildBlocker] = (),
                 format_length: FormatLength | None = None) -> StoryTiming:
    """The ``studio.story-timing/v1`` summary. ``blockers`` are the story's
    ``queue_run`` violations (see :func:`haynes_studio.canonical.timing_summary`)."""
    derived = boards_derived(boards, facts)
    rows = tuple(BoardTimingRow(board_id=board.id, state=d.timing_state, frames=d.frames,
                                film_start_frame=d.film_start_frame,
                                reason=untimed_reason(board, facts) if d.frames is None else None)
                 for board, d in zip(boards, derived))
    frames = sum(row.frames for row in rows if row.frames is not None)
    complete = all(row.state == TIMED for row in rows)
    warning = length_warning(frames, complete, format_length)
    return StoryTiming(
        schema=STORY_TIMING_SCHEMA, story_id=story.id, story_revision=story.revision,
        fps=DELIVERY_FPS, boards=rows, frames_known=frames, complete=complete,
        format_length=format_length, warnings=(warning,) if warning else (),
        build_allowed=not blockers, build_blockers=tuple(blockers),
    )
