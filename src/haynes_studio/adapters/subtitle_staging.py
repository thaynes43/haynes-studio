"""Prepare an original situation summary and requests for the existing archive."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from html import unescape

from haynes_studio.canonical.jsonvalues import too_deep
from haynes_studio.jsonio import parse_strict

from ._subtitle_text import plain_text, refusal
from .errors import RequestInvalid
from .subtitles import SceneRead

DEFAULT_MAX_SOURCE_WORDS = 4
_MAX_SUMMARY_CHARS = 4_000
_MAX_ARCHIVE_BYTES = 256 * 1024
_WORDS = re.compile(r"[^\W_]+")


@dataclass(frozen=True, slots=True)
class SituationBeat:
    """A paraphrased beat covering the next cue_count cues in scene time order."""

    cue_count: int
    description: str = field(repr=False)


def _words(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKC", text).casefold()
    letters = "".join(
        ch for ch in folded if ch not in "'’ʼ" and unicodedata.category(ch) != "Cf"
    )
    return _WORDS.findall(letters)


def _runs(text: str, size: int) -> Iterator[tuple[str, ...]]:
    words = _words(text)
    for offset in range(len(words) - size + 1):
        yield tuple(words[offset:offset + size])


def _json_values(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _json_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _json_values(item)


def _valid_text(text: str, max_bytes: int) -> None:
    if not isinstance(text, str) or len(text) > max_bytes:
        raise refusal("subtitle.staging_text", "Staging text exceeds its limit or is invalid")
    try:
        size = len(text.encode("utf-8"))
    except UnicodeError:
        raise refusal("subtitle.staging_text", "Staging text must be valid UTF-8") from None
    if size > max_bytes:
        raise refusal("subtitle.staging_text", "Staging text exceeds its limit")


class SceneStaging:
    """Guard the summary and each archive write for a single in-memory passage."""

    def __init__(self, scene: SceneRead, *, max_source_words: int = DEFAULT_MAX_SOURCE_WORDS):
        if type(max_source_words) is not int or not 1 <= max_source_words <= 8:
            raise RequestInvalid("subtitle.staging", "Allowed source word run must be between 1 and 8")
        self._scene = scene
        self._run_size = max_source_words + 1
        self._source_runs = set(_runs("\n".join(cue.text for cue in scene.cues), self._run_size))
        file_order = sorted(scene.cues, key=lambda cue: cue.number)
        self._source_runs.update(_runs("\n".join(cue.text for cue in file_order), self._run_size))

    def _require_safe(self, text: str) -> None:
        # The archive preserves markup literally, so check that view as well as
        # rendered text. Decode entities even when they appear inside a tag.
        views = dict.fromkeys((text, unescape(text), plain_text(text)))
        if any(run in self._source_runs for view in views for run in _runs(view, self._run_size)):
            raise refusal("subtitle.verbatim", "Staging text repeats consecutive source words")

    def summarize(self, *, conflict: str, beats: Sequence[SituationBeat]) -> str:
        """Combine abstract roles and conflict with paraphrased beats and cue timings."""
        _valid_text(conflict, _MAX_SUMMARY_CHARS)
        if not conflict.strip() or not 1 <= len(beats) <= len(self._scene.cues):
            raise RequestInvalid("subtitle.staging", "Supply a conflict and beats covering the scene")
        cue_index = 0
        plain = [conflict.strip()]
        summary = [f"Conflict — {plain[0]}"]
        for beat in beats:
            _valid_text(beat.description, _MAX_SUMMARY_CHARS)
            if type(beat.cue_count) is not int or beat.cue_count < 1 or not beat.description.strip():
                raise RequestInvalid("subtitle.staging", "Each beat needs cue coverage and a description")
            end = cue_index + beat.cue_count
            if end > len(self._scene.cues):
                raise RequestInvalid("subtitle.staging", "Beat coverage exceeds the scene")
            cues = self._scene.cues[cue_index:end]
            description = beat.description.strip()
            plain.append(description)
            summary.append(f"{cues[0].start_ms}–{max(cue.end_ms for cue in cues)} ms — {description}")
            cue_index = end
        if cue_index != len(self._scene.cues):
            raise RequestInvalid("subtitle.staging", "Beats must cover the whole scene")
        result = "\n".join(summary)
        _valid_text(result, _MAX_SUMMARY_CHARS)
        self._require_safe("\n".join(plain))
        self._require_safe(result)
        return result

    def archive_payload(self, *, text: str, title: str | None = None) -> dict:
        """Return guarded text and adapted provenance for archive create or append."""
        _valid_text(text, _MAX_ARCHIVE_BYTES)
        if title is not None:
            _valid_text(title, 80 * 4)
        prefix = f"{title}\n" if title is not None else ""
        self._require_safe(prefix + text)
        # Storyboard text is JSON. Decode escaped words and check runs across text
        # fields without treating structural keys as part of the dialogue.
        if text.lstrip().startswith(("{", "[", '"')):
            try:
                document = parse_strict(text)
            except RecursionError:
                raise refusal("subtitle.staging_text", "Staging JSON exceeds its nesting limit") from None
            except ValueError:
                # Plain prose may start with a brace. The archive validates storyboards.
                document = None
            if too_deep(document):
                raise refusal("subtitle.staging_text", "Staging JSON exceeds its nesting limit")
            self._require_safe(prefix + "\n".join(_json_values(document)))
        payload = {
            "text": text,
            "provenance": {"origin": "adapted", "source_locator": self._scene.source_locator},
        }
        if title is not None:
            payload["title"] = title
        return payload
