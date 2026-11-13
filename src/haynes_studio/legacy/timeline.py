"""The legacy timeline: a manifest and its speech.json in, shot frames, film starts and
the placement of every line and sound out, in integers (contract rules TIME-1 to
TIME-4, TIME-7 and TIME-10). :func:`compare` checks it against a recorded
``timeline.json`` under rule TIME-12.

Comparison allowances:

- frames per shot and in total: exact;
- shot starts and ends and ``total_s`` (recorded to 4 decimals): exact at that
  precision, so within 0.05 ms of ``frames / 24``;
- line and sound starts and ends (recorded to 3 decimals): within 1 ms (48 samples),
  the TIME-12 allowance. The legacy editor rounded shot starts to 0.1 ms before placing
  samples and recorded line ends from the resampled audio, not ``duration_s``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

from haynes_studio.errors import ContractError, Violation, pointer
from haynes_studio.jsonio import read_json
from haynes_studio.legacy.manifest import INVALID, LegacyManifest, Shot
from haynes_studio.legacy.speech import LegacySpeech, Take, pair
from haynes_studio.timebase import (
    DELIVERY_FPS,
    MIX_RATE,
    SAMPLES_PER_MS,
    film_start_frames,
    frames_for_ms,
    frames_to_samples,
    line_spans,
    mix_sample,
    ms_to_samples,
    spoken_content_ms,
)

CUE_OUT_OF_RANGE = "cue.out_of_range"
TIMELINE_MISMATCH = "legacy.timeline_mismatch"
CUE_ALLOWANCE_SAMPLES = SAMPLES_PER_MS  # 1 ms (TIME-12)
SHOT_TIME_PRECISION = Fraction(1, 20_000)  # half of 0.0001 s, the 4-decimal record


@dataclass(frozen=True, slots=True)
class LineTiming:
    k: int
    doll: str
    start_ms: int  # board clock (TIME-2)
    end_ms: int
    start_sample: int  # film clock, mix samples (TIME-7)
    end_sample: int


@dataclass(frozen=True, slots=True)
class SoundTiming:
    index: int  # position in the shot's sfx list
    cue: str
    start_ms: int  # board clock
    start_sample: int  # film clock
    end_sample: int | None  # start plus the trimmed length, cut at film end; None untrimmed
    cut_at_film_end: bool


@dataclass(frozen=True, slots=True)
class ShotTiming:
    index: int
    shot_id: int
    spoken: bool
    content_ms: int  # spoken: lead + takes + gaps + tail (TIME-3); silent: duration (TIME-4)
    frames: int
    start_frame: int  # film frame (TIME-7)
    lines: tuple[LineTiming, ...]
    sfx: tuple[SoundTiming, ...]

    @property
    def end_frame(self) -> int:
        return self.start_frame + self.frames


@dataclass(frozen=True, slots=True)
class BedTiming:
    name: str
    start_sample: int
    end_sample: int


@dataclass(frozen=True, slots=True)
class LegacyTimeline:
    manifest: str  # source labels
    speech: str
    frames: int
    shots: tuple[ShotTiming, ...]
    beds: tuple[BedTiming, ...]

    @property
    def samples(self) -> int:
        return frames_to_samples(self.frames)


def _board_ms(shot: Shot, takes: Mapping[tuple[int, int], Take]) -> tuple[int, tuple]:
    """(content_ms, line spans) of one shot."""
    if not shot.spoken:
        return shot.duration_ms, ()
    durations = [takes[(shot.id, line.k)].duration_ms for line in shot.lines]
    gaps = [line.gap_ms for line in shot.lines]
    spans = line_spans(shot.lead_ms, durations, gaps)
    return spoken_content_ms(shot.lead_ms, durations, gaps, shot.tail_ms), spans


def compute(manifest: LegacyManifest, speech: LegacySpeech) -> LegacyTimeline:
    """The timeline of ``manifest`` with the takes of ``speech``. Raises
    :class:`ContractError` if a line has no take or a sound starts outside its shot."""
    takes = pair(manifest, speech)
    boards = [_board_ms(shot, takes) for shot in manifest.shots]
    frames = [frames_for_ms(content_ms) for content_ms, _ in boards]
    starts = film_start_frames(frames)
    total = sum(frames)
    film_end = frames_to_samples(total)
    found: list[Violation] = []
    shots = []
    for shot, (content_ms, spans), count, start in zip(manifest.shots, boards, frames, starts):
        lines = tuple(
            LineTiming(k=line.k, doll=line.doll, start_ms=span.start_ms, end_ms=span.end_ms,
                       start_sample=mix_sample(start, span.start_ms),
                       end_sample=mix_sample(start, span.end_ms))
            for line, span in zip(shot.lines, spans))
        sounds = []
        for cue in shot.sfx:
            anchor = cue.anchor
            if anchor.after_line is None:
                at_ms = anchor.at_ms
            else:
                at_ms = spans[anchor.after_line].end_ms + anchor.offset_ms
            if not 0 <= ms_to_samples(at_ms) < frames_to_samples(count):
                found.append(Violation(
                    CUE_OUT_OF_RANGE, pointer("shots", shot.index, "sfx", cue.index),
                    f"sound {cue.cue!r} starts at {at_ms} ms, outside shot {shot.id} "
                    f"({count} frames)"))
                continue
            first = mix_sample(start, at_ms)
            trim = manifest.sound(cue.cue).trim_ms
            end = None if trim is None else first + ms_to_samples(trim[1] - trim[0])
            sounds.append(SoundTiming(
                index=cue.index, cue=cue.cue, start_ms=at_ms, start_sample=first,
                end_sample=None if end is None else min(end, film_end),
                cut_at_film_end=end is not None and end > film_end))
        shots.append(ShotTiming(index=shot.index, shot_id=shot.id, spoken=shot.spoken,
                                content_ms=content_ms, frames=count, start_frame=start,
                                lines=lines, sfx=tuple(sounds)))
    if found:
        raise ContractError(manifest.source, found)
    return LegacyTimeline(
        manifest=manifest.source, speech=speech.source, frames=total, shots=tuple(shots),
        beds=tuple(BedTiming(name=bed.name, start_sample=0, end_sample=film_end)
                   for bed in manifest.beds))


# Comparison -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Check:
    """One compared value. Seconds are exact fractions; ``diff_ms`` is computed minus
    recorded."""

    item: str  # "shot 8", "shot 8 line 4", "shot 8 sfx gavel", "bed fire", "film"
    field: str  # "frames", "start", "end", "count", "id", "cue"
    computed: Any
    recorded: Any
    allowance: str  # "exact", "4 decimals", "1 ms"
    ok: bool
    diff_ms: Fraction | None = None


@dataclass(frozen=True)
class Comparison:
    recorded: str  # source label
    checks: tuple[Check, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    @property
    def mismatches(self) -> tuple[Check, ...]:
        return tuple(check for check in self.checks if not check.ok)

    def violations(self) -> list[Violation]:
        return [Violation(TIMELINE_MISMATCH, "", describe(check)) for check in self.mismatches]


def seconds(value: Any) -> Fraction:
    """A recorded JSON number of seconds as an exact fraction (a float by its repr)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{value!r} is not a number of seconds")
    return Fraction(Decimal(repr(value)) if isinstance(value, float) else value)


def ms_text(value: Fraction) -> str:
    """Milliseconds as signed text with 3 decimals, for reports."""
    thousandths = round(value * 1000)
    sign = "-" if thousandths < 0 else "+"
    thousandths = abs(thousandths)
    return f"{sign}{thousandths // 1000}.{thousandths % 1000:03d}"


def describe(check: Check) -> str:
    diff = "" if check.diff_ms is None else f", diff {ms_text(check.diff_ms)} ms"
    return (f"{check.item} {check.field}: computed {check.computed}, recorded "
            f"{check.recorded} ({check.allowance}{diff})")


def _exact(item: str, field: str, computed: Any, recorded: Any) -> Check:
    return Check(item, field, computed, recorded, "exact", computed == recorded)


def _time(item: str, field: str, computed_s: Fraction, recorded: Any, *,
          shot_precision: bool) -> Check:
    recorded_s = seconds(recorded)
    diff = computed_s - recorded_s
    if shot_precision:
        ok, allowance = abs(diff) <= SHOT_TIME_PRECISION, "4 decimals"
    else:
        ok, allowance = abs(diff) <= Fraction(CUE_ALLOWANCE_SAMPLES, MIX_RATE), "1 ms"
    return Check(item, field, _seconds_text(computed_s), recorded, allowance, ok, diff * 1000)


def _seconds_text(value: Fraction) -> str:
    """Exact seconds rounded to 4 decimals, as text, for reports only."""
    units = round(value * 10_000)
    return f"{units // 10_000}.{units % 10_000:04d}"


def _frame_s(frame: int) -> Fraction:
    return Fraction(frame, DELIVERY_FPS)


def _sample_s(sample: int) -> Fraction:
    return Fraction(sample, MIX_RATE)


def _recorded_problems(document: Any) -> list[Violation]:
    """Shape problems of a recorded timeline.json that would stop the comparison."""
    if not isinstance(document, dict):
        return [Violation(INVALID, "", "timeline.json must be an object")]
    found = []

    def number(value: Any) -> bool:
        return isinstance(value, int | float) and not isinstance(value, bool)

    if not number(document.get("total_s")):
        found.append(Violation(INVALID, "/total_s", "must be a number of seconds"))
    for name, fields in (("shots", ("shot", "start_s", "end_s", "frames")),
                         ("audio", ("kind", "start_s", "end_s"))):
        items = document.get(name)
        if not isinstance(items, list):
            found.append(Violation(INVALID, pointer(name), "must be an array"))
            continue
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                found.append(Violation(INVALID, pointer(name, i), "must be an object"))
                continue
            for field in fields:
                value = item.get(field)
                wanted = isinstance(value, str) if field == "kind" else number(value)
                if not wanted:
                    found.append(Violation(INVALID, pointer(name, i, field),
                                           "missing or of the wrong type"))
    return found


def compare(timeline: LegacyTimeline, recorded: Any, *, source: str = "<document>") -> Comparison:
    """Check a computed timeline against a recorded ``timeline.json`` document. Raises
    :class:`ContractError` if the record is not shaped like one."""
    problems = _recorded_problems(recorded)
    if problems:
        raise ContractError(source, problems)
    checks: list[Check] = []
    rec_shots = recorded["shots"]
    checks.append(_exact("film", "shot count", len(timeline.shots), len(rec_shots)))
    for shot, rec in zip(timeline.shots, rec_shots):
        item = f"shot {shot.shot_id}"
        checks.append(_exact(item, "id", shot.shot_id, rec["shot"]))
        checks.append(_exact(item, "frames", shot.frames, rec["frames"]))
        checks.append(_time(item, "start", _frame_s(shot.start_frame), rec["start_s"],
                            shot_precision=True))
        checks.append(_time(item, "end", _frame_s(shot.end_frame), rec["end_s"],
                            shot_precision=True))
    checks.append(_exact("film", "frames", timeline.frames,
                         sum(rec["frames"] for rec in rec_shots)))
    checks.append(_time("film", "total", _frame_s(timeline.frames), recorded["total_s"],
                        shot_precision=True))

    audio = recorded["audio"]
    kinds = {"line", "sfx", "bed"}
    for i, entry in enumerate(audio):
        if entry["kind"] not in kinds:
            checks.append(Check(f"audio {i}", "kind", "line, sfx or bed", entry["kind"],
                                "exact", False))
    rec_lines = {(entry.get("shot"), entry.get("k", 0)): entry
                 for entry in audio if entry["kind"] == "line"}
    lines = [(shot, line) for shot in timeline.shots for line in shot.lines]
    checks.append(_exact("film", "line count", len(lines), len(rec_lines)))
    for shot, line in lines:
        item = f"shot {shot.shot_id} line {line.k}"
        rec = rec_lines.get((shot.shot_id, line.k))
        if rec is None:
            checks.append(Check(item, "start", line.start_sample, "absent", "exact", False))
            continue
        checks.append(_time(item, "start", _sample_s(line.start_sample), rec["start_s"],
                            shot_precision=False))
        checks.append(_time(item, "end", _sample_s(line.end_sample), rec["end_s"],
                            shot_precision=False))

    rec_sounds = [entry for entry in audio if entry["kind"] == "sfx"]
    sounds = [(shot, sound) for shot in timeline.shots for sound in shot.sfx]
    checks.append(_exact("film", "sfx count", len(sounds), len(rec_sounds)))
    for (shot, sound), rec in zip(sounds, rec_sounds):  # the editor recorded them in shot order
        item = f"shot {shot.shot_id} sfx {sound.cue}"
        checks.append(_exact(item, "cue", sound.cue, rec.get("cue")))
        checks.append(_time(item, "start", _sample_s(sound.start_sample), rec["start_s"],
                            shot_precision=False))
        if sound.end_sample is not None:
            checks.append(_time(item, "end", _sample_s(sound.end_sample), rec["end_s"],
                                shot_precision=False))

    rec_beds = {entry.get("cue"): entry for entry in audio if entry["kind"] == "bed"}
    checks.append(_exact("film", "bed count", len(timeline.beds), len(rec_beds)))
    for bed in timeline.beds:
        item = f"bed {bed.name}"
        rec = rec_beds.get(bed.name)
        if rec is None:
            checks.append(Check(item, "start", bed.start_sample, "absent", "exact", False))
            continue
        checks.append(_time(item, "start", _sample_s(bed.start_sample), rec["start_s"],
                            shot_precision=False))
        checks.append(_time(item, "end", _sample_s(bed.end_sample), rec["end_s"],
                            shot_precision=False))
    return Comparison(recorded=source, checks=tuple(checks))


def load_recorded(path: str | Path) -> tuple[str, Any]:
    """(label, document) of a recorded timeline.json, read without changing it."""
    try:
        parsed = read_json(path)
    except ValueError as error:
        raise ContractError(str(path), [Violation(INVALID, "", str(error).split(": ", 1)[-1])]) \
            from None
    return parsed.label, parsed.document
