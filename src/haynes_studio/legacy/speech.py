"""A legacy ``speech.json`` (one Kokoro take per line), read-only, and its pairing with
a manifest's lines.

A take's ``duration_ms`` is the recorded ``duration_s`` (3 decimals) in whole
milliseconds, ``duration_source: legacy_duration_s`` (contract rule TIME-1). Records
without ``k`` (r1, r2) read as ``k = 0``, as ``edit.speech_records`` did; that is
allowed only where the shot has a single line.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from haynes_studio.errors import ContractError, Violation, pointer
from haynes_studio.jsonio import read_json
from haynes_studio.legacy.manifest import INVALID, LegacyManifest
from haynes_studio.schemas import UNKNOWN_FIELD
from haynes_studio.timebase import SECONDS_LIMIT, ms_from_seconds

DURATION_SOURCE = "legacy_duration_s"
SPEECH_MISMATCH = "legacy.speech_mismatch"
TOP_FIELDS = ("service", "lines")
TAKE_FIELDS = ("shot", "k", "doll", "voice", "text", "file", "duration_s", "sha256", "heard",
               "heard_matches")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class Take:
    index: int  # position in speech.json lines[]
    shot: int
    k: int
    k_present: bool
    doll: str
    voice: str | None
    text: str
    file: str
    duration_ms: int
    sha256: str


@dataclass(frozen=True, slots=True)
class LegacySpeech:
    source: str
    sha256: str | None
    service: str | None
    takes: tuple[Take, ...]

    duration_source = DURATION_SOURCE


def _is_int(value: Any, minimum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def validate_speech(document: Any) -> list[Violation]:
    """Every shape problem of a speech.json document; empty means it can be read."""
    if not isinstance(document, dict):
        return [Violation(INVALID, "", "speech.json must be an object")]
    found = [Violation(UNKNOWN_FIELD, pointer(key), f"unknown field {key!r}")
             for key in sorted(set(document) - set(TOP_FIELDS))]
    if "service" in document and not isinstance(document["service"], str):
        found.append(Violation(INVALID, "/service", "must be of type string"))
    lines = document.get("lines")
    if not isinstance(lines, list):
        return found + [Violation(INVALID, "/lines", "must be an array of takes")]
    keys: dict[tuple[int, int], int] = {}
    for i, take in enumerate(lines):
        base = pointer("lines", i)
        if not isinstance(take, dict):
            found.append(Violation(INVALID, base, "must be an object"))
            continue
        found += [Violation(UNKNOWN_FIELD, base + pointer(key), f"unknown field {key!r}")
                  for key in sorted(set(take) - set(TAKE_FIELDS))]
        found += [Violation(INVALID, base, f"{name!r} is a required property")
                  for name in ("shot", "doll", "text", "file", "duration_s", "sha256")
                  if name not in take]
        if "shot" in take and not _is_int(take["shot"], 1):
            found.append(Violation(INVALID, base + "/shot", "must be an integer of at least 1"))
        if "k" in take and not _is_int(take["k"], 0):
            found.append(Violation(INVALID, base + "/k", "must be an integer of at least 0"))
        for name in ("doll", "text", "file", "voice"):
            if name in take and not isinstance(take[name], str):
                found.append(Violation(INVALID, base + pointer(name), "must be of type string"))
        if "sha256" in take and not (isinstance(take["sha256"], str)
                                     and _HEX64.match(take["sha256"])):
            found.append(Violation(INVALID, base + "/sha256", "must be 64 lower-case hex digits"))
        duration = take.get("duration_s")
        if "duration_s" in take:
            if isinstance(duration, bool) or not isinstance(duration, int | float) \
                    or not 0 < duration < SECONDS_LIMIT:
                found.append(Violation(INVALID, base + "/duration_s",
                                       "must be a finite number of seconds greater than 0"))
            else:
                try:
                    ms_from_seconds(duration)
                except ValueError:
                    found.append(Violation("time.not_integer_ms", base + "/duration_s",
                                           f"{duration!r} s is not a whole number of milliseconds"))
        if _is_int(take.get("shot"), 1) and _is_int(take.get("k", 0), 0):
            key = (take["shot"], take.get("k", 0))
            if key in keys:
                found.append(Violation(INVALID, base, f"a second take for shot {key[0]} "
                                                      f"line {key[1]} (first at /lines/{keys[key]})"))
            keys.setdefault(key, i)
    return sorted(found, key=lambda v: (v.path, v.rule))


def speech_from_document(document: Any, *, source: str = "<document>",
                         sha256: str | None = None) -> LegacySpeech:
    problems = validate_speech(document)
    if problems:
        raise ContractError(source, problems)
    return LegacySpeech(
        source=source,
        sha256=sha256,
        service=document.get("service"),
        takes=tuple(
            Take(index=i, shot=take["shot"], k=take.get("k", 0), k_present="k" in take,
                 doll=take["doll"], voice=take.get("voice"), text=take["text"],
                 file=take["file"], duration_ms=ms_from_seconds(take["duration_s"]),
                 sha256=take["sha256"])
            for i, take in enumerate(document["lines"])),
    )


def load_speech(path: str | Path) -> LegacySpeech:
    """Read a speech.json file (never written)."""
    try:
        parsed = read_json(path)
    except ValueError as error:
        raise ContractError(str(path), [Violation(INVALID, "", str(error).split(": ", 1)[-1])]) \
            from None
    return speech_from_document(parsed.document, source=parsed.label, sha256=parsed.sha256)


def pair(manifest: LegacyManifest, speech: LegacySpeech) -> Mapping[tuple[int, int], Take]:
    """The take for every manifest line, keyed ``(shot id, k)``. Raises
    :class:`ContractError` (``legacy.speech_mismatch``, paths into speech.json) when a
    line has no take, a take has no line, or a take's doll or text differs."""
    by_key = {(take.shot, take.k): take for take in speech.takes}
    found: list[Violation] = []
    paired: dict[tuple[int, int], Take] = {}
    for shot in manifest.shots:
        for line in shot.lines:
            take = by_key.get((shot.id, line.k))
            if take is None:
                found.append(Violation(SPEECH_MISMATCH, "/lines",
                                       f"no take for shot {shot.id} line {line.k}"))
                continue
            path = pointer("lines", take.index)
            if not take.k_present and len(shot.lines) > 1:
                found.append(Violation(SPEECH_MISMATCH, path,
                                       f"a take without k on shot {shot.id}, which has "
                                       f"{len(shot.lines)} lines"))
            if take.doll != line.doll:
                found.append(Violation(SPEECH_MISMATCH, path + "/doll",
                                       f"doll {take.doll!r}, the manifest line has {line.doll!r}"))
            if take.text != line.text:
                found.append(Violation(SPEECH_MISMATCH, path + "/text",
                                       f"text differs from shot {shot.id} line {line.k}"))
            paired[(shot.id, line.k)] = take
    for take in speech.takes:
        if (take.shot, take.k) not in paired:
            found.append(Violation(SPEECH_MISMATCH, pointer("lines", take.index),
                                   f"take for shot {take.shot} line {take.k} has no manifest line"))
    if found:
        raise ContractError(speech.source, sorted(found, key=lambda v: (v.path, v.rule)))
    return paired
