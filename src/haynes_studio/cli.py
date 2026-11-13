"""The ``studio`` command line. Standard library only; the work is in the package.

Exit status: 0 valid (or the timelines match, or the import succeeded), 1 a rule
failed (or the timelines differ), 2 a usage error, an unreadable or too deeply nested
file, or an output file that exists or cannot be written. Problems print one per line
as ``<file>: rule <code> at <path>: <message>``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO
from urllib.parse import urlsplit

from haynes_studio import __version__
from haynes_studio.canonical.ids import is_id
from haynes_studio.canonical.jsonvalues import MAX_DEPTH, too_deep
from haynes_studio.canonical.legacy_import import import_manifest
from haynes_studio.canonical.model import Principal
from haynes_studio.errors import ContractError, Violation
from haynes_studio.jsonio import read_json
from haynes_studio.legacy import manifest as legacy_manifest
from haynes_studio.legacy.speech import load_speech
from haynes_studio.legacy.timeline import (
    Comparison,
    LegacyTimeline,
    compare,
    compute,
    describe,
    load_recorded,
    ms_text,
)
from haynes_studio.timebase import SAMPLES_PER_MS, display_seconds

OK, FAILED, USAGE = 0, 1, 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="studio",
        description="Haynes Studio tooling. Reads legacy PoC files and never writes them; "
                    "`legacy import --out` creates new files only.",
        epilog="Reference: docs/reference/studio-cli.md",
    )
    parser.add_argument("--version", action="version", version=f"studio {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    legacy = commands.add_parser(
        "legacy", help="read legacy PoC manifests and evidence (read-only)",
        description="Read legacy PoC manifests and their evidence. Never writes them.")
    actions = legacy.add_subparsers(dest="action", metavar="ACTION", required=True)

    validate = actions.add_parser(
        "validate", help="validate a manifest as legacy.manifest/v1",
        description="Validate a PoC title manifest as legacy.manifest/v1 and summarize it.")
    validate.add_argument("manifest", help="a titles/<slug>/manifest*.json file")
    validate.add_argument("--json", action="store_true", help="print the result as JSON")
    validate.set_defaults(handler=_validate)

    timeline = actions.add_parser(
        "timeline", help="compute a manifest's timeline from its speech.json",
        description="Compute shot frames, film starts and the placement of every line and "
                    "sound (contract section 3), and optionally compare it with a recorded "
                    "timeline.json (rule TIME-12).")
    timeline.add_argument("manifest", help="a titles/<slug>/manifest*.json file")
    timeline.add_argument("--speech", required=True, metavar="SPEECH",
                          help="the speech.json recorded for that manifest")
    timeline.add_argument("--compare", metavar="TIMELINE",
                          help="a recorded timeline.json to compare with")
    timeline.add_argument("--json", action="store_true", help="print the result as JSON")
    timeline.set_defaults(handler=_timeline)

    imp = actions.add_parser(
        "import", help="import a manifest as one canonical story (studio.story/v1)",
        description="Map a legacy manifest and its speech.json to one canonical story with "
                    "boards, lines, cues, notes and layout references, and a "
                    "studio.legacy-import/v1 map (contract section 1). IDs come from --map "
                    "when given, so a second import returns the same IDs; otherwise they are "
                    "minted. Never writes a legacy file.")
    imp.add_argument("manifest", help="a titles/<slug>/manifest*.json file")
    imp.add_argument("--speech", required=True, metavar="SPEECH",
                     help="the speech.json recorded for that manifest")
    imp.add_argument("--map", metavar="IMPORT_MAP",
                     help="an existing studio.legacy-import/v1 map whose IDs to reuse")
    imp.add_argument("--production", metavar="PRD_ID",
                     help="the production to import into (prd_...); minted when absent and "
                          "no --map names one")
    imp.add_argument("--operator-iss", required=True, metavar="ISS",
                     help="the OIDC issuer of the person running the import")
    imp.add_argument("--operator-sub", required=True, metavar="SUB",
                     help="that person's OIDC subject (never an email or display name)")
    imp.add_argument("--out", metavar="DIR",
                     help="write story.json and legacy-import.json into DIR (created if "
                          "needed); an existing file is never overwritten")
    imp.add_argument("--json", action="store_true",
                     help="print {story, legacy_import} as JSON instead of a summary")
    imp.set_defaults(handler=_import)
    return parser


def main(argv: Sequence[str] | None = None, *, stdout: TextIO | None = None,
         stderr: TextIO | None = None) -> int:
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:  # --help, --version and usage errors
        return int(exit_.code or 0)
    # The same depth limit for every command, so the answer does not depend on how deep
    # this Python version can recurse before a loader gives up.
    for name in ("manifest", "speech", "compare"):
        path = getattr(args, name, None)
        if path is not None and _nested_too_deeply(path):
            print(f"studio: {path}: nested deeper than {MAX_DEPTH} levels", file=err)
            return USAGE
    try:
        return args.handler(args, out, err)
    except ContractError as error:
        print(error, file=err)
        return FAILED
    except OSError as error:
        if error.filename is None:  # not an input file (a closed pipe, for example)
            raise
        print(f"studio: cannot read {error.filename}: "
              f"{error.strerror or type(error).__name__}", file=err)
        return USAGE
    except RecursionError:  # a legacy loader reading a pathologically nested file
        print("studio: an input file is nested too deeply to read", file=err)
        return USAGE


# legacy validate --------------------------------------------------------------------


def _validate(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    manifest = legacy_manifest.load(args.manifest)
    spoken = [shot for shot in manifest.shots if shot.spoken]
    summary = {
        "file": manifest.source,
        "schema": manifest.schema,
        "valid": True,
        "sha256": manifest.sha256,
        "revision": manifest.revision,
        "revision_field_present": manifest.revision_field_present,
        "shots": len(manifest.shots),
        "spoken_shots": len(spoken),
        "silent_shots": len(manifest.shots) - len(spoken),
        "lines": sum(len(shot.lines) for shot in manifest.shots),
        "gaps_defaulted": sum(line.gap_defaulted for shot in manifest.shots
                              for line in shot.lines),
        "sound_cues": sum(len(shot.sfx) for shot in manifest.shots),
        "beds": len(manifest.beds),
    }
    if args.json:
        json.dump(summary, out, indent=2)
        out.write("\n")
        return OK
    revision = (f"revision {manifest.revision}" if manifest.revision_field_present
                else f"revision {manifest.revision} (no revision field)")
    out.write(
        f"{manifest.source}: valid {manifest.schema}, {revision}, "
        f"{_count(summary['shots'], 'shot')} ({summary['spoken_shots']} spoken, "
        f"{summary['silent_shots']} silent), {_count(summary['lines'], 'line')}, "
        f"{_count(summary['sound_cues'], 'sound cue')}, {_count(summary['beds'], 'bed')}\n")
    return OK


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" + ("" if number == 1 else "s")


# legacy import ----------------------------------------------------------------------

STORY_FILE, MAP_FILE = "story.json", "legacy-import.json"
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_SUBJECT_MAX = 255  # OpenID Connect Core 1.0, section 2: sub is at most 255 ASCII characters


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _label(path: str) -> str:
    """The manifest path the story records: relative to the root of the repository
    that holds it (the nearest folder with a ``.git`` entry), else only its file name.
    Never an absolute path, which would carry a private local folder into the story."""
    resolved = Path(path).resolve()
    for folder in resolved.parents:
        if (folder / ".git").exists():
            return resolved.relative_to(folder).as_posix()
    return resolved.name


def _bad_text(value: str) -> bool:
    return not value or bool(_CONTROL.search(value)) or any(c.isspace() for c in value)


def _operator_problem(iss: str, sub: str) -> str | None:
    """Why the operator's OIDC issuer or subject is unusable, or None."""
    try:
        parts = urlsplit(iss)
        issuer_ok = parts.scheme in ("https", "http") and bool(parts.hostname)
    except ValueError:
        issuer_ok = False
    if _bad_text(iss) or not issuer_ok:
        return (f"--operator-iss {iss!r} is not an OIDC issuer (an http or https URL with "
                "a host, no spaces)")
    if _bad_text(sub) or len(sub) > _SUBJECT_MAX:
        return (f"--operator-sub {sub!r} is not an OIDC subject (1 to {_SUBJECT_MAX} "
                "characters, no spaces or control characters)")
    return None


def _nested_too_deeply(path: str) -> bool:
    """True when a JSON file nests deeper than the canonical model reads. A file that
    cannot be read or parsed is left to its loader, which reports it."""
    try:
        document = read_json(path).document
    except (OSError, ValueError):
        return False
    return too_deep(document)


def _read_map(path: str) -> dict:
    """An import map file's document. ``ValueError`` if it is not JSON, ``OSError`` if
    unreadable, :class:`ContractError` if it is not a JSON object."""
    document = read_json(path).document
    if too_deep(document):
        raise ValueError(f"{path}: nested deeper than {MAX_DEPTH} levels")
    if not isinstance(document, dict):
        kind = "null" if document is None else type(document).__name__
        raise ContractError(path, [Violation(
            "schema.invalid", "", f"an import map must be a JSON object, not {kind}")])
    return document


def _import(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    if args.production is not None and not is_id(args.production, "prd"):
        print(f"studio: --production {args.production!r} is not a prd_ ID", file=err)
        return USAGE
    problem = _operator_problem(args.operator_iss, args.operator_sub)
    if problem:
        print(f"studio: {problem}", file=err)
        return USAGE
    out_dir = Path(args.out) if args.out is not None else None
    if out_dir is not None:
        existing = [str(out_dir / name) for name in (STORY_FILE, MAP_FILE)
                    if os.path.lexists(out_dir / name)]
        if existing:
            print(f"studio: will not overwrite {', '.join(existing)}", file=err)
            return USAGE
    existing_map = None
    if args.map is not None:
        try:
            existing_map = _read_map(args.map)
        except ContractError:  # a rule failure (exit 1), not a usage error
            raise
        except ValueError as error:
            print(f"studio: {error}", file=err)
            return USAGE
    manifest = legacy_manifest.load(args.manifest)
    result = import_manifest(
        manifest, load_speech(args.speech), manifest_label=_label(args.manifest),
        operator=Principal(kind="human", iss=args.operator_iss, sub=args.operator_sub),
        now=_now(), existing=existing_map, production_id=args.production,
        map_label=args.map or "<import map>")
    if out_dir is not None:
        written = _write_outputs(out_dir, result, err)
        if written is None:
            return USAGE
    if args.json:
        json.dump({"story": result.story, "legacy_import": result.import_map}, out, indent=2,
                  ensure_ascii=False)
        out.write("\n")
        return OK
    story = result.story
    boards = story["boards"]
    derived = story["derived"]
    given = f", {result.given} given" if result.given else ""
    out.write(
        f"{manifest.source}: imported revision {manifest.revision} as story {story['id']} "
        f"(production {story['production_id']}, {story['media_kind']}): "
        f"{_count(len(boards), 'board')}, "
        f"{_count(sum(len(b['lines']) for b in boards), 'line')}, "
        f"{_count(sum(len(b['cues']) for b in boards), 'cue')}, "
        f"{_count(sum(len(b['notes']) for b in boards), 'note')}, "
        f"{_count(len(story['beds']), 'bed')}; {derived['frames']} frames "
        f"({display_seconds(derived['frames'])} s); IDs: {result.reused} from the map, "
        f"{result.minted} minted{given}\n")
    for board, number in ((b, b["number"]) for b in boards):
        d = board["derived"]
        out.write(f"  B{number:02d} {board['id']} shot {board['origin']['legacy_shot']}: "
                  f"{d['frames']} frames from film frame {d['film_start_frame']}, "
                  f"{board['method']['layer']} {board['method']['motion']}, voice "
                  f"{d['voice_state']}, photo {d['photo_state']}\n")
    if out_dir is not None:
        out.write(f"wrote {out_dir / STORY_FILE} and {out_dir / MAP_FILE}\n")
    return OK


def _write_outputs(out_dir: Path, result, err: TextIO) -> list[Path] | None:
    """Create ``story.json`` then ``legacy-import.json`` in ``out_dir``; the paths
    written, or None after printing which file could not be written and which was.
    Outputs are create-only: nothing already written is deleted or renamed."""
    written: list[Path] = []
    targets = [(out_dir / STORY_FILE, result.story), (out_dir / MAP_FILE, result.import_map)]
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        _cannot_write(out_dir, error, written, err)
        return None
    for path, document in targets:
        try:
            _create(path, document)
        except OSError as error:
            _cannot_write(path, error, written, err)
            return None
        written.append(path)
    return written


def _cannot_write(path: Path, error: OSError, written: list[Path], err: TextIO) -> None:
    done = (f"; {', '.join(str(p) for p in written)} was already written and is left as "
            "it is (choose a new --out folder)" if written else "; nothing was written")
    print(f"studio: cannot write {path}: {error.strerror or type(error).__name__}{done}",
          file=err)


def _create(path: Path, document: dict) -> None:
    """Write a new JSON file; ``FileExistsError`` if it appeared meanwhile."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    with os.fdopen(os.open(path, flags, 0o644), "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


# legacy timeline --------------------------------------------------------------------


def _timeline(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    manifest = legacy_manifest.load(args.manifest)
    timeline = compute(manifest, load_speech(args.speech))
    comparison = None
    if args.compare:
        label, recorded = load_recorded(args.compare)
        comparison = compare(timeline, recorded, source=label)
    if args.json:
        json.dump(_timeline_json(timeline, comparison), out, indent=2)
        out.write("\n")
    else:
        _timeline_text(timeline, comparison, out)
    if comparison is None:
        return OK
    for violation in comparison.violations():
        print(f"{comparison.recorded}: {violation}", file=err)
    return OK if comparison.ok else FAILED


def _timeline_json(timeline: LegacyTimeline, comparison: Comparison | None) -> dict:
    result = {
        "manifest": timeline.manifest,
        "speech": timeline.speech,
        "fps": 24,
        "sample_rate": 48_000,
        "frames": timeline.frames,
        "samples": timeline.samples,
        "display_seconds": display_seconds(timeline.frames),
        "shots": [
            {
                "shot": shot.shot_id,
                "spoken": shot.spoken,
                "content_ms": shot.content_ms,
                "frames": shot.frames,
                "start_frame": shot.start_frame,
                "end_frame": shot.end_frame,
                "lines": [{"k": line.k, "doll": line.doll, "start_ms": line.start_ms,
                           "end_ms": line.end_ms, "start_sample": line.start_sample,
                           "end_sample": line.end_sample} for line in shot.lines],
                "sfx": [{"cue": sound.cue, "start_ms": sound.start_ms,
                         "start_sample": sound.start_sample, "end_sample": sound.end_sample,
                         "cut_at_film_end": sound.cut_at_film_end} for sound in shot.sfx],
            }
            for shot in timeline.shots
        ],
        "beds": [{"name": bed.name, "start_sample": bed.start_sample,
                  "end_sample": bed.end_sample} for bed in timeline.beds],
    }
    if comparison is not None:
        result["comparison"] = {
            "recorded": comparison.recorded,
            "match": comparison.ok,
            "checks": len(comparison.checks),
            "mismatches": [str(violation) for violation in comparison.violations()],
            "max_audio_diff_ms": ms_text(_max_audio_diff(comparison)).lstrip("+"),
        }
    return result


def _max_audio_diff(comparison: Comparison):
    diffs = [abs(check.diff_ms) for check in comparison.checks
             if check.allowance == "1 ms" and check.diff_ms is not None]
    return max(diffs, default=0)


def _timeline_text(timeline: LegacyTimeline, comparison: Comparison | None,
                   out: TextIO) -> None:
    out.write(f"{timeline.manifest} with {timeline.speech}\n")
    out.write(f"{'shot':>4}  {'kind':<6}  {'content_ms':>10}  {'frames':>6}  "
              f"{'film frames':>11}  {'lines':>5}  {'sfx':>3}\n")
    for shot in timeline.shots:
        frames = f"{shot.start_frame}-{shot.end_frame}"
        out.write(f"{shot.shot_id:>4}  {'spoken' if shot.spoken else 'silent':<6}  "
                  f"{shot.content_ms:>10}  {shot.frames:>6}  {frames:>11}  "
                  f"{len(shot.lines):>5}  {len(shot.sfx):>3}\n")
    out.write(f"total {timeline.frames} frames at 24 fps "
              f"({display_seconds(timeline.frames)} s), {timeline.samples} samples at 48 kHz\n")
    for shot in timeline.shots:
        for line in shot.lines:
            out.write(f"  shot {shot.shot_id} line {line.k} ({line.doll}): "
                      f"{line.start_ms}-{line.end_ms} ms, samples "
                      f"{line.start_sample}-{line.end_sample}\n")
        for sound in shot.sfx:
            end = "untrimmed" if sound.end_sample is None else str(sound.end_sample)
            cut = ", cut at film end" if sound.cut_at_film_end else ""
            out.write(f"  shot {shot.shot_id} sfx {sound.cue}: {sound.start_ms} ms, samples "
                      f"{sound.start_sample}-{end}{cut}\n")
    for bed in timeline.beds:
        out.write(f"  bed {bed.name}: samples {bed.start_sample}-{bed.end_sample}\n")
    if comparison is None:
        return
    worst = ms_text(_max_audio_diff(comparison)).lstrip("+")
    verdict = "match" if comparison.ok else f"{len(comparison.mismatches)} mismatch(es)"
    out.write(f"compared with {comparison.recorded}: {verdict}; {len(comparison.checks)} "
              f"checks (frames exact, shot times to 4 decimals, lines and sounds within "
              f"{SAMPLES_PER_MS} samples = 1 ms; largest audio difference {worst} ms)\n")
