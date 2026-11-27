"""Bounded text decoding and cue parsing for the filesystem subtitle source."""

from __future__ import annotations

import codecs
import re
from dataclasses import dataclass, field
from html import unescape

from .errors import AdapterError

MAX_FILE_CUES = 10_000
MAX_CUE_CHARACTERS = 4_096
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_BLOCK_BREAK = re.compile(r"\n(?:[ \t]*\n)+")
_VTT_HEADER = re.compile(r"WEBVTT(?:[ \t]+[^\n]*)?")
_VTT_NOTE = re.compile(r"NOTE(?:[ \t]+[^\n]*)?")
_TIMING = re.compile(r"([^ \t]+)[ \t]+-->[ \t]+([^ \t]+)(?:[ \t]+(.*))?")
_SRT_TIME = re.compile(r"([0-9]{1,3}):([0-5][0-9]):([0-5][0-9])[,.]([0-9]{3})")
_VTT_TIME = re.compile(r"(?:([0-9]{2,3}):)?([0-5][0-9]):([0-5][0-9])\.([0-9]{3})")
_MARKUP = re.compile(r"<(?:/?[A-Za-z][^<>\n]*|[0-9][0-9:.]*)>|\{\\[^{}\n]{1,64}\}")


@dataclass(frozen=True, slots=True)
class Cue:
    """One parsed cue, numbered from one in file order."""

    number: int
    start_ms: int
    end_ms: int
    text: str = field(repr=False)


def refusal(code: str, message: str) -> AdapterError:
    return AdapterError(code, "subtitles", message)


def plain_text(text: str) -> str:
    return unescape(_MARKUP.sub("", text))


def _decode(data: bytes, *, vtt: bool, allow_windows_1252: bool) -> str:
    if not vtt and data.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        raise refusal("subtitle.encoding", "Unsupported subtitle encoding")
    if not vtt and data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        encodings = ("utf-16",)
    elif not vtt and allow_windows_1252 and not data.startswith(codecs.BOM_UTF8):
        encodings = ("utf-8-sig", "cp1252")
    else:
        encodings = ("utf-8-sig",)
    for encoding in encodings:
        try:
            return data.decode(encoding).replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError:
            continue
    raise refusal("subtitle.encoding", "Unsupported subtitle encoding")


def _stamp(value: str, grammar: re.Pattern[str]) -> int:
    match = grammar.fullmatch(value)
    if match is None:
        raise refusal("subtitle.format", "Subtitle timing is invalid")
    hours, minutes, seconds, millis = (int(group or 0) for group in match.groups())
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis


def parse_cues(data: bytes, *, vtt: bool, allow_windows_1252: bool) -> tuple[Cue, ...]:
    text = _decode(data, vtt=vtt, allow_windows_1252=allow_windows_1252)
    if _CONTROL.search(text):
        raise refusal("subtitle.format", "Subtitle contains a control character")
    blocks = iter(_BLOCK_BREAK.split(text.rstrip(" \t\n")))
    if vtt:
        header_block = next(blocks, "")
        header = header_block.split("\n", 1)[0]
        if _VTT_HEADER.fullmatch(header) is None or "-->" in header_block:
            raise refusal("subtitle.format", "WebVTT header is invalid")

    grammar = _VTT_TIME if vtt else _SRT_TIME
    cues = []
    for block in blocks:
        if not block.strip():
            continue
        first, _, rest = block.partition("\n")
        if vtt and (first in {"STYLE", "REGION"} or _VTT_NOTE.fullmatch(first)):
            if "-->" in block:
                raise refusal("subtitle.format", "WebVTT metadata overlaps a cue")
            continue
        if "-->" not in first and (vtt or re.fullmatch(r"[0-9]+", first.strip())):
            first, _, rest = rest.partition("\n")
        timing = _TIMING.fullmatch(first.strip())
        if timing is None or "-->" in rest or (not vtt and timing[3] is not None):
            raise refusal("subtitle.format", "Subtitle cue is invalid")
        start, end = _stamp(timing[1], grammar), _stamp(timing[2], grammar)
        if start >= end:
            raise refusal("subtitle.format", "Subtitle cue must have positive duration")
        if len(cues) == MAX_FILE_CUES or len(rest) > MAX_CUE_CHARACTERS:
            raise refusal("subtitle.limit", "Subtitle exceeds the cue parsing limits")
        content = plain_text(rest).strip()
        if _CONTROL.search(content):
            raise refusal("subtitle.format", "Subtitle contains a control character")
        cues.append(Cue(len(cues) + 1, start, end, content))
    if not cues:
        raise refusal("subtitle.format", "Subtitle contains no cues")
    return tuple(cues)
