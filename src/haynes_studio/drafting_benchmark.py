"""Score the OP455 doll-short drafting corpus from local files."""

import argparse
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from haynes_studio.api.auth import Actor
from haynes_studio.api.errors import APIError
from haynes_studio.canonical import validate_story
from haynes_studio.canonical.ids import is_id
from haynes_studio.canonical.model import Principal
from haynes_studio.drafting.document import MAX_DOCUMENT_BYTES, Draft
from haynes_studio.errors import ContractError, Violation, pointer
from haynes_studio.formats.recipe import method_violation, validate_recipe
from haynes_studio.jsonio import parse_strict, read_json, thaw
from haynes_studio.library import Library, resolve
from haynes_studio.store import canonical_json

CORPUS = Path(__file__).with_name("drafting_benchmark_data")
RESULT = "studio.drafting-benchmark-result/v1"
EVIDENCE = "studio.drafting-benchmark-evidence/v1"
LABELS = "studio.drafting-benchmark-labels/v1"
LABEL_VALUES = {"usable_as_is", "usable_with_light_edits", "not_usable"}
DRAFT_CHECKS = ("board_schema", "method", "timing", "references", "brief_invariants")
CHECKS = (*DRAFT_CHECKS, "write_scope", "edit_preservation")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def corpus_version(manifest: dict, hashes: dict[str, str]) -> str:
    """Identify the case data and exact bytes of every frozen input."""
    payload = {key: value for key, value in manifest.items() if key != "version"}
    return "sha256:" + _sha256(canonical_json({**payload, "files": hashes}))


@dataclass(frozen=True)
class Corpus:
    manifest: dict
    files: dict[str, bytes]

    @classmethod
    def load(cls, path: Path) -> "Corpus":
        manifest = read_json(path / "manifest.json").document
        files = {name: (path / name).read_bytes() for name in manifest["files"]}
        hashes = {name: _sha256(data) for name, data in files.items()}
        observed = corpus_version(manifest, hashes)
        if hashes != manifest["files"] or observed != manifest["version"]:
            changed = sorted(name for name, digest in hashes.items() if digest != manifest["files"][name])
            raise ValueError(f"Corpus seal mismatch. Expected {manifest['version']}, observed "
                             f"{observed}. Changed files: {', '.join(changed) or 'manifest'}")
        if len(manifest["cases"]) != 5:
            raise ValueError("The D46 corpus must contain exactly five cases")
        return cls(manifest, files)

    def json(self, name: str):
        return parse_strict(self.files[name].decode("utf-8"))


def _result(issues=(), *, status="pass") -> dict:
    problems = sorted(set(issues))
    return {"status": "fail" if problems else status,
            "violations": [{"code": code, "path": path} for code, path in problems]}


def _family(issue: Violation) -> str:
    if issue.rule.startswith(("method.", "layered.", "wholeframe.")):
        return "method"
    if issue.rule.startswith("time.") or issue.rule == "cue.out_of_range":
        return "timing"
    if issue.rule.startswith(("ref.", "asset.", "voice.speaker_", "voice.narrator_", "draft.set_")):
        return "references"
    return "board_schema"


def _draft_checks(draft: Draft, case: dict, story: dict, recipe: dict, library: Library) -> dict:
    groups = {check: [] for check in DRAFT_CHECKS}

    def record(issue: Violation) -> None:
        groups[_family(issue)].append((issue.rule, issue.path))

    proposed = [board.key for board in draft.boards]
    if proposed != [board["key"] for board in case["boards"]]:
        groups["brief_invariants"].append(("benchmark.board_keys", "/boards"))
    expectations = {board["key"]: board["expect"] for board in case["boards"]}
    pins = ("asset_version_id", "motion_asset_version_id")
    if any((draft.set_pins or {}).get(pin) != (story["set"] or {}).get(pin) for pin in pins):
        groups["references"].append(("draft.set_changed", "/set"))

    facts = library.facts()
    cast_slots = {member["slot"] for member in story["cast"]}
    for board in draft.boards:
        document = thaw(board.document)
        for issue in board.problems(story_cast=cast_slots, story_layouts=story["layouts"], facts=facts):
            record(issue)
        issue = method_violation(recipe, document)
        if issue is not None:
            record(Violation(issue.rule, board.path + issue.path, issue.message))
        if document["voice"]["style"] == "narrator" and story["narrator_voice_version_id"] is None:
            groups["references"].append(("voice.narrator_missing", board.path + "/voice"))
        # Resolve the proposal as part of its frozen production. Metadata is enough
        # for drafting, as in the application's draft validation.
        resolution = resolve({**story, "boards": [document]}, library, lambda _locator, _sha: True)
        for issue in resolution.problems:
            path = issue.path.removeprefix("/boards/0")
            groups["references"].append((issue.rule, board.path + path))

        projection = {
            "cast_slots": [entry["slot"] for entry in document["cast"]],
            "speakers": [line["speaker"] for line in document["lines"]],
            "photo_inputs": document["photo"]["input_asset_version_ids"],
            "sound_inputs": [cue.get("asset_version_id") for cue in document["cues"] if cue["type"] == "sound"],
            "hold_ms": document["timing"]["hold_ms"],
            "cue_times_ms": [cue["anchor"].get("at_ms") for cue in document["cues"]],
        }
        # One case assertion per field makes an otherwise valid draft's missing
        # brief requirement visible without encoding creative judgments.
        for field, expected in expectations.get(board.key, {}).items():
            if projection[field] != expected:
                groups["brief_invariants"].append(("benchmark.brief_invariant", board.path + pointer(field)))

    return {check: _result(issues) for check, issues in groups.items()}


def _scope_issues(draft: Draft | None, evidence: dict, case: dict, story: dict,
                  key_id: str) -> list[tuple[str, str]]:
    key = Principal(kind="agent", key_id=key_id)
    actor = Actor(key, grants={story["production_id"]: frozenset({"draft:write"})})
    problems = []

    def check_target(production_id: str, story_id: str, path: str) -> None:
        try:
            actor.require("draft:write", production_id)
        except APIError as error:
            problems.append((error.details["code"], path + "/production_id"))
        else:
            if story_id != story["id"]:
                problems.append(("benchmark.story_scope", path + "/story_id"))

    if draft is not None:
        check_target(draft.production_id, draft.story_id, "")
    writes = evidence.get("writes")
    if not isinstance(writes, list):
        return [*problems, ("benchmark.write_evidence_missing", "/writes")]
    expected = Counter(board["key"] for board in case["boards"])
    starting_ids = {board["draft_application"]["board_key"]: board["id"]
                    for board in story["boards"] if board.get("draft_application")}
    tool = "studio_patch_board" if story["boards"] else "studio_add_board"
    counted = Counter()
    seen_ids = set()
    for index, target in enumerate(writes):
        path = pointer("writes", index)
        if (not isinstance(target, dict) or not is_id(target.get("production_id"), "prd")
                or not is_id(target.get("story_id"), "sty") or not isinstance(target.get("board_key"), str)
                or not is_id(target.get("board_id"), "brd") or type(target.get("applied")) is not bool):
            problems.append(("benchmark.write_evidence_invalid", path))
            continue
        check_target(target["production_id"], target["story_id"], path)
        key, board_id = target["board_key"], target["board_id"]
        if (target.get("tool") != tool or not target["applied"] or board_id in seen_ids
                or (story["boards"] and starting_ids.get(key) != board_id)):
            problems.append(("benchmark.write_target", path))
        seen_ids.add(board_id)
        counted[key] += 1
    if counted != expected:
        problems.append(("benchmark.write_coverage", "/writes"))
    return problems


def _preservation(evidence: dict, case: dict, story: dict) -> dict:
    if not case["protected_boards"]:
        return _result(status="not_applicable")
    after = evidence.get("protected_boards")
    if not isinstance(after, dict) or set(after) != set(case["protected_boards"]):
        return _result([("benchmark.protected_evidence_missing", "/protected_boards")])
    before = {board["id"]: canonical_json(board) for board in story["boards"]}
    problems = []
    for board_id, raw in after.items():
        path = pointer("protected_boards", board_id)
        if not isinstance(raw, str) or raw.encode("utf-8", errors="surrogatepass") != before[board_id]:
            problems.append(("benchmark.protected_board_changed", path))
    return _result(problems)


def score(corpus: Corpus, case_id: str, data: bytes, evidence: object = None) -> dict:
    case = corpus.manifest["cases"][case_id]
    story = corpus.json(case["story"])
    recipe = corpus.json(corpus.manifest["recipe"])
    library = Library.from_version_documents(corpus.json(corpus.manifest["assets"]))
    frozen_issues = [*validate_recipe(recipe), *validate_story(story, context="write"),
                     *resolve(story, library, lambda _locator, _sha: True).problems]
    if frozen_issues:
        raise ContractError("<frozen case>", frozen_issues)
    digest = _sha256(data) if len(data) <= MAX_DOCUMENT_BYTES else None
    try:
        draft = Draft.parse(data)
    except ContractError as error:
        draft = None
        checks = {check: _result(status="not_evaluated") for check in DRAFT_CHECKS}
        checks["board_schema"] = _result((issue.rule, issue.path) for issue in error.violations)
    else:
        checks = _draft_checks(draft, case, story, recipe, library)
    if (isinstance(evidence, dict) and evidence.get("schema") == EVIDENCE
            and digest is not None and evidence.get("draft_sha256") == digest):
        scope = _scope_issues(draft, evidence, case, story, corpus.manifest["agent_key_id"])
        checks["write_scope"] = _result(scope, status="pass" if draft else "not_evaluated")
        checks["edit_preservation"] = _preservation(evidence, case, story)
    else:
        checks["write_scope"] = _result([("benchmark.write_evidence_unbound", "/draft_sha256")])
        checks["edit_preservation"] = _preservation({}, case, story)

    passed = all(check["status"] in {"pass", "not_applicable"} for check in checks.values())
    return {"schema": RESULT, "corpus_version": corpus.manifest["version"], "case_id": case_id,
            "draft_sha256": digest, "checks": checks, "verdict": "pass" if passed else "fail"}


def _valid_verdict(result: dict, case: dict) -> bool:
    checks = result.get("checks")
    if not isinstance(checks, dict) or set(checks) != set(CHECKS):
        raise ValueError("Case result must contain every check")
    passed = True
    for name, check in checks.items():
        status = check.get("status") if isinstance(check, dict) else None
        if name == "edit_preservation" and not case["protected_boards"]:
            if status != "not_applicable":
                raise ValueError("Edit preservation is not applicable to this case")
            continue
        if status not in ("pass", "fail", "not_evaluated"):
            raise ValueError("Invalid case check status")
        passed &= status == "pass"
    if result.get("verdict") != ("pass" if passed else "fail"):
        raise ValueError("Case verdict disagrees with its checks")
    return passed


def summarise(corpus: Corpus, results: list, labels: object = None) -> dict:
    cases = corpus.manifest["cases"]
    version = corpus.manifest["version"]
    by_case = {}
    verdicts = []
    for result in results:
        case_id = result.get("case_id") if isinstance(result, dict) else None
        if (not isinstance(case_id, str) or case_id not in cases or case_id in by_case
                or result.get("schema") != RESULT or result.get("corpus_version") != version):
            raise ValueError("Provide one result for each distinct case from this corpus version")
        by_case[case_id] = result
        verdicts.append(_valid_verdict(result, cases[case_id]))
    if set(by_case) != set(cases):
        raise ValueError("Provide all five case results")
    quality = {"status": "pending: Tom's labels"}
    if labels is not None:
        if (not isinstance(labels, dict) or labels.get("schema") != LABELS or labels.get("reviewer") != "Tom"
                or labels.get("corpus_version") != version or not isinstance(entries := labels.get("cases"), dict)
                or set(entries) != set(cases)):
            raise ValueError("Tom's labels must cover all five cases of this corpus version")
        count = 0
        for case_id, entry in entries.items():
            digest = by_case[case_id].get("draft_sha256")
            if (not isinstance(entry, dict) or not isinstance(label := entry.get("label"), str)
                    or label not in LABEL_VALUES or not isinstance(digest, str)
                    or re.fullmatch(r"[0-9a-f]{64}", digest) is None or entry.get("draft_sha256") != digest):
                raise ValueError(f"Invalid label or draft hash for {case_id}")
            count += label in {"usable_as_is", "usable_with_light_edits"}
        quality = {"usable_with_light_edits": count, "of": 5, "meets_minimum": count >= 4}
    return {"corpus_version": version, "structural_and_safety_all_pass": all(verdicts),
            "quality": quality}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=CORPUS, help="directory containing a frozen corpus")
    commands = parser.add_subparsers(dest="command", required=True)
    scoring = commands.add_parser("score", help="validate one draft against a frozen case")
    scoring.add_argument("draft", type=Path)
    scoring.add_argument("--case", required=True)
    scoring.add_argument("--evidence", type=Path)
    summary = commands.add_parser("summarise", help="report the D46 bar for five results")
    summary.add_argument("results", nargs=5, type=Path)
    summary.add_argument("--labels", type=Path)
    args = parser.parse_args(argv)
    try:
        corpus = Corpus.load(args.corpus)
        if args.command == "score":
            if args.case not in corpus.manifest["cases"]:
                raise ValueError(f"Unknown case. Choose from {', '.join(corpus.manifest['cases'])}")
            with args.draft.open("rb") as stream:
                data = stream.read(MAX_DOCUMENT_BYTES + 1)
            evidence = read_json(args.evidence).document if args.evidence else None
            result = score(corpus, args.case, data, evidence)
            status = int(result["verdict"] == "fail")
        else:
            results = [read_json(path).document for path in args.results]
            labels = read_json(args.labels).document if args.labels else None
            if args.labels and labels is None:
                raise ValueError("Tom's labels file must contain a labels object")
            result = summarise(corpus, results, labels)
            status = 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"{parser.prog}: {error}\n")
    print(json.dumps(result, sort_keys=True))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
