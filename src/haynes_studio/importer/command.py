"""``python -m haynes_studio.importer``: the private input import's command line (story 846).

    python -m haynes_studio.importer --story DIR/story.json --map DIR/legacy-import.json \\
        --operator-iss ISS --operator-sub SUB --store ROOT --dry-run
    python -m haynes_studio.importer ... --store ROOT --out NEW_DIR \\
        --authorized-by https://work.haynesnetwork.com/work_packages/428

``--story`` and ``--map`` are what ``studio legacy import --out DIR`` writes for r4. The
library is built from public files (stories 382 and 457) on top of ``--library`` when
given, so a second run on the first run's ``library.json`` creates nothing. A run reads
the Wan volume through the real runner (``kubectl exec``) and needs ``--authorized-by``,
the full URL of the work package that authorizes the read; ``--dry-run`` reads nothing
from the Wan volume, writes nothing, and never makes a runner. ``--out`` must not exist:
the run creates it with ``import-report.json`` and ``library.json``, create-only.

Exit status: 0 the import completed with no mismatch; 1 it stopped, a read returned other
bytes, or reads were made and none found its file; 2 a usage error, an unreadable input,
or an ``--out`` that exists.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlsplit

from haynes_studio.adapters import recovery
from haynes_studio.adapters.errors import AdapterError
from haynes_studio.adapters.runner import Runner, SubprocessRunner
from haynes_studio.adapters.wan_ledger import LedgerReader
from haynes_studio.adapters.wan_volume import VolumeReader
from haynes_studio.canonical.model import Principal
from haynes_studio.errors import ContractError
from haynes_studio.importer.plan import E0Line, PlanError, plan_import
from haynes_studio.importer.run import Readers, dry_run, run_import
from haynes_studio.jsonio import read_json
from haynes_studio.library.library import EMPTY, Library
from haynes_studio.library.winter_menu import (
    REGISTER_PATH,
    build_winter_menu_library,
    load_licence_register,
    load_public_sources,
)
from haynes_studio.motion.winter_menu import build_e0_motion, load_e0_sources
from haynes_studio.store.local import LocalStore

PROG = "python -m haynes_studio.importer"
COMMAND = "studio private import"  # the Principal's command (proposal)
REPORT_FILE, LIBRARY_FILE = "import-report.json", "library.json"
TITLE = "titles/the-winter-menu"
MAP_FILE = "docs/reference/legacy-recovery-map.json"
WORK_PACKAGE = re.compile(r"https://work\.haynesnetwork\.com/work_packages/[1-9][0-9]{0,8}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SUBJECT_MAX = 255


class UsageError(Exception):
    pass


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=PROG, description="Read The Winter Menu's private inputs read-only from the Wan "
        "volume into a new store, and check each against its public record (story 846).")
    p.add_argument("--repo", default=".", help="the haynes-studio checkout whose public records "
                   "to read (default: the current folder)")
    p.add_argument("--story", required=True, help="the r4 story (story.json from `studio legacy "
                   "import --out`)")
    p.add_argument("--map", required=True, help="its import map (legacy-import.json)")
    p.add_argument("--library", help="a library file (a JSON array of asset versions) to import "
                   "into, such as an earlier run's library.json")
    p.add_argument("--store", help="the new store's root folder (it must exist)")
    p.add_argument("--out", help="a new folder for import-report.json and library.json")
    p.add_argument("--operator-iss", required=True, help="the OIDC issuer of the person running it")
    p.add_argument("--operator-sub", required=True, help="their OIDC subject (never an email)")
    p.add_argument("--authorized-by", help="the full work package URL that authorizes the live "
                   "read (required unless --dry-run)")
    p.add_argument("--dry-run", action="store_true", help="list what would be read; read "
                   "nothing from the Wan volume and write nothing")
    p.add_argument("--json", action="store_true", help="print the report as JSON")
    return p


def _bad_text(value: str) -> bool:
    return not value or bool(_CONTROL.search(value)) or any(c.isspace() for c in value)


def _operator(iss: str, sub: str) -> Principal:
    try:
        parts = urlsplit(iss)
        issuer_ok = parts.scheme in ("https", "http") and bool(parts.hostname)
    except ValueError:
        issuer_ok = False
    if _bad_text(iss) or not issuer_ok:
        raise UsageError("--operator-iss is not an OIDC issuer (an http or https URL with a host)")
    if _bad_text(sub) or len(sub) > _SUBJECT_MAX or "@" in sub:
        raise UsageError(f"--operator-sub is not an OIDC subject (1 to {_SUBJECT_MAX} characters, "
                         "no spaces, control characters or @)")
    return Principal.cli(COMMAND, iss, sub)


def _check(args: argparse.Namespace) -> None:
    if args.dry_run:
        return
    if not args.store:
        raise UsageError("--store is required unless --dry-run")
    if not args.out:
        raise UsageError("--out is required unless --dry-run")
    if not args.authorized_by or not WORK_PACKAGE.fullmatch(args.authorized_by):
        raise UsageError("--authorized-by must be the full URL of the authorizing work package, "
                         "https://work.haynesnetwork.com/work_packages/<id>")
    if os.path.lexists(args.out):
        raise UsageError(f"--out {args.out} already exists; a run writes a new folder")


def _document(path: str) -> Any:
    return read_json(path).document


def load_inputs(repo: Path, story: dict, import_map: dict, library: Library, *, by: Principal,
                now: str) -> tuple[Library, dict, list[E0Line], dict[str, int]]:
    """The library (built from public files on top of ``library``), the recovery map and
    the E0 lines, from the checkout at ``repo``. Reads text and JSON only."""
    recovery_map = recovery.build(repo)
    committed = read_json(repo / MAP_FILE).document
    if committed != recovery_map:
        raise PlanError(f"{MAP_FILE} is not the map built from the public files; rebuild it")
    if any(row["sha256"] == recovery.MISSING for row in recovery_map["rows"]):
        raise PlanError("a recovery map row has no public hash; nothing can verify it")
    licences = load_licence_register(repo / REGISTER_PATH)
    winter = build_winter_menu_library(story, import_map, load_public_sources(
        repo / TITLE, "manifest-r4.json", "evidence-r4"), licences=licences, by=by, now=now,
        library=library)
    sources = load_e0_sources(repo)
    e0 = build_e0_motion(sources, production_id=story["production_id"], licences=licences, by=by,
                         now=now, library=winter.library)
    records = {(file, line): record for file, line, record in sources.records}
    lines = [E0Line(row.file, row.line, row.outcome, records[(row.file, row.line)])
             for row in e0.rows]
    created = {"winter_menu": sum(o.created for o in winter.outcomes),
               "e0_motion": sum(o.created for o in e0.outcomes)}
    return e0.library, recovery_map, lines, created


def _create(path: Path, document: Any) -> None:
    data = (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def _summary(report: dict[str, Any], out: TextIO) -> None:
    totals = report["totals"]
    if report["dry_run"]:
        out.write(f"dry run: {totals['rows']} rows, {totals['hashes']} distinct hashes; "
                  + ", ".join(f"{k} {totals[k]}" for k in ("held", "copy", "to_read", "not_read",
                                                           "stop") if k in totals)
                  + f"; at most {totals['reads_at_most']} reads; nothing read or written\n")
        for item in report["hashes"]:
            sources = ", ".join(" ".join(f"{k}={v}" for k, v in s.items() if k != "path")
                                for s in item["sources"]) or (item["unread"] or "")
            out.write(f"  {item['sha256'][:16]} {item['would']:<8} {len(item['rows'])} rows: "
                      f"{sources}\n")
        return
    out.write(f"{totals['rows']} rows: {totals['verified']} verified, {totals['absent']} absent, "
              f"{totals['mismatch']} mismatch; {totals['hashes']} hashes, {totals['hashes_read']} "
              f"read, {totals['bytes_read']} bytes read, {totals['bytes_published']} published, "
              f"{report['elapsed_s']} s\n")
    for role, counts in totals["by_role"].items():
        out.write(f"  {role:<12} " + ", ".join(f"{k} {v}" for k, v in counts.items()) + "\n")
    if report["stopped"]:
        out.write(f"stopped: {report['stopped']['code']}: {report['stopped']['message']}\n")
    lacks = report["lacks"] or {}
    for problem in lacks.get("story", []) + lacks.get("layered_loops", []):
        out.write(f"lacks: {problem['rule']} at {problem['path']}: {problem['message']}\n")


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: Sequence[str] | None = None, *, stdout: TextIO | None = None,
         stderr: TextIO | None = None, runner_factory: Callable[[], Runner] = SubprocessRunner,
         now: Callable[[], str] = _now, clock: Callable[[], float] | None = None) -> int:
    """Run the command. ``runner_factory`` is called once, only for a run (never for a
    dry run); tests pass a fake."""
    out, err = stdout or sys.stdout, stderr or sys.stderr
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exit_:
        return 2 if exit_.code else 0
    try:
        by = _operator(args.operator_iss, args.operator_sub)
        _check(args)
        started = now()
        story, import_map = _document(args.story), _document(args.map)
        library = Library.from_version_documents(_document(args.library)) if args.library else EMPTY
        library, recovery_map, lines, created = load_inputs(Path(args.repo), story, import_map,
                                                            library, by=by, now=started)
        plan = plan_import(recovery_map, lines, library, production_id=story["production_id"])
        store = LocalStore(args.store) if args.store else None
    except UsageError as error:
        err.write(f"{PROG}: {error}\n")
        return 2
    except (OSError, ValueError, KeyError, TypeError, ContractError, AdapterError) as error:
        err.write(f"{PROG}: cannot read the inputs: {type(error).__name__}: {error}\n")
        return 2
    if args.dry_run:
        report = dry_run(plan, store=store, now=now)
        report["library"] = {"versions": len(library.versions), "created_now": created}
        if args.json:
            json.dump(report, out, indent=2, sort_keys=True)
            out.write("\n")
        else:
            _summary(report, out)
        return 0
    runner = runner_factory()
    readers = Readers(ledger=LedgerReader(runner), volume=VolumeReader(runner))
    kwargs = {} if clock is None else {"clock": clock}
    result = run_import(plan, store=store, library=library, readers=readers, story=story, by=by,
                        now=now, authorized_by=args.authorized_by, **kwargs)
    report = result.report
    report["library"] = {"versions": len(result.library.versions), "created_now": created}
    target = Path(args.out)
    try:
        target.mkdir()
        _create(target / REPORT_FILE, report)
        _create(target / LIBRARY_FILE, result.library.documents())
    except OSError as error:
        err.write(f"{PROG}: cannot write {target}: {error}\n")
        json.dump(report, err, sort_keys=True)  # the only copy of what was read
        err.write("\n")
        return 2
    if args.json:
        json.dump(report, out, indent=2, sort_keys=True)
        out.write("\n")
    else:
        _summary(report, out)
    if result.found_nothing:
        err.write(f"{PROG}: no read found its file; check the cluster context and the container "
                  "before reading anything else\n")
    return 1 if result.stopped or result.mismatched or result.found_nothing else 0


__all__ = ["LIBRARY_FILE", "REPORT_FILE", "load_inputs", "main"]
