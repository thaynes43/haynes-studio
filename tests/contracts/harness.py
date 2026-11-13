"""Contract-example harness (contract section 14, "Contract examples").

Every file under docs/contracts/examples/ is checked here:

- it parses as JSON and is an object of a known schema type;
- an invalid case has the ``studio.invalid-case/v1`` wrapper, its ``rule`` is in the
  rule index (section 15) and its ``expect`` matches that rule's status;
- if the registry (tests/contracts/registry.py) has a validator for the document's
  type, a valid example must validate and an invalid case must fail with exactly its
  rule and expected status; with no validator the example is reported PENDING by
  type, never skipped.

Problems are reported as ``<path>: [rule <code>: ]<check>: <message>``: codes and
paths only, never the environment.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple

from tests.support.policy import REPO_ROOT

CONTRACT = REPO_ROOT / "docs" / "contracts" / "studio-contracts-v1.md"
EXAMPLES_DIR = REPO_ROOT / "docs" / "contracts" / "examples"

# Section 2, "Schema names": the v1 types other than the test wrapper.
STUDIO_TYPES = (
    "production", "story", "board", "asset", "asset-version", "job", "run",
    "run-snapshot", "delivery", "go-live-approval", "story-timing", "legacy-import",
    "method-capabilities",
)
# Documents without a schema field: the legacy manifest (section 2, detected by its
# shots, frame and job fields) and the error envelope (section 12).
LEGACY_MANIFEST = "legacy.manifest"
ERROR_ENVELOPE = "error"
ALL_TYPES = (*STUDIO_TYPES, LEGACY_MANIFEST, ERROR_ENVELOPE)

INVALID_CASE_SCHEMA = "studio.invalid-case/v1"
WRAPPER_FIELDS = ("schema", "rule", "expect", "context", "path", "why", "document")
EXPECT = ("invalid", "unavailable", "forbidden")
CASE_CONTEXTS = ("write", "queue_run")
# The context a valid example is checked in: a document as the server returns or
# exchanges it, so `derived` fields are present.
READ_CONTEXT = "read"
WARNING = "warning"
# User-property names the validator test records; tests/contracts/conftest.py reads them.
PENDING = "contract_pending"
CHECKED = "contract_type"

_SCHEMA = re.compile(r"^studio\.(?P<type>[a-z][a-z0-9-]*)/v(?P<major>[1-9][0-9]*)$")
_POINTER = re.compile(r"^(/([^~/]|~[01])*)*$")
_JSON_KINDS = {list: "array", str: "string", int: "number", float: "number",
               bool: "boolean", type(None): "null"}


class Violation(NamedTuple):
    """One rule a validator reports. ``status`` is invalid, unavailable, forbidden or warning."""

    rule: str
    status: str
    path: str


# validator(document, context=...) -> violations; empty means the document is valid.
Validator = Callable[..., Iterable[Any]]


@dataclass(frozen=True)
class Rule:
    code: str
    status: str
    row: tuple[str, ...]  # every code in the same index row
    examples: tuple[str, ...]  # invalid-example file names the row links to


@dataclass(frozen=True)
class Example:
    path: Path
    label: str  # repository-relative path, used in every message
    kind: str  # "valid" or "invalid"
    data: Any = field(repr=False)
    document: Any = field(repr=False)
    type: str | None
    rule: str | None


@dataclass(frozen=True)
class Problem:
    label: str
    check: str
    message: str
    rule: str | None = None

    def __str__(self) -> str:
        rule = f"rule {self.rule}: " if self.rule else ""
        return f"{self.label}: {rule}{self.check}: {self.message}"


# Contract ---------------------------------------------------------------------


def _section(text: str, number: int) -> str:
    match = re.search(rf"^## {number}\. .*?(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    if not match:
        raise ValueError(f"contract has no section {number}")
    return match.group(0)


def load_rule_index(contract: Path = CONTRACT) -> dict[str, Rule]:
    """Rule code -> Rule, from the section 15 table."""
    rules: dict[str, Rule] = {}
    for line in _section(contract.read_text(encoding="utf-8"), 15).splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4 or not cells[0].startswith("`"):
            continue
        codes = re.findall(r"`([^`]+)`", cells[0])
        status = cells[1].replace("`", "")
        linked = tuple(re.findall(r"\(examples/invalid/([^)]+\.json)\)", cells[3]))
        for code in codes:
            rules[code] = Rule(code=code, status=status, row=tuple(codes), examples=linked)
    if not rules:
        raise ValueError("contract section 15 has no rule rows")
    return rules


def listed_types(contract: Path = CONTRACT) -> tuple[str, ...]:
    """The types named in section 2's "Types in v1" sentence, the wrapper excluded."""
    text = " ".join(_section(contract.read_text(encoding="utf-8"), 2).split())
    match = re.search(r"Types in v1: (.*?)\.(?: |$)", text)
    if not match:
        raise ValueError("contract section 2 has no 'Types in v1' sentence")
    sentence = match.group(1).split("and the test wrapper")[0]
    return tuple(re.findall(r"`([^`]+)`", sentence))


# Examples ---------------------------------------------------------------------


def discover(examples_dir: Path = EXAMPLES_DIR) -> list[Path]:
    """Every file under the examples directory, sorted."""
    return sorted(path for path in examples_dir.rglob("*") if path.is_file())


def _label(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def document_type(document: Any) -> str:
    """The schema type of a document, or raise ValueError naming why not."""
    if not isinstance(document, dict):
        kind = _JSON_KINDS.get(type(document), type(document).__name__)
        raise ValueError(f"is a JSON {kind}, not an object")
    if "schema" in document:
        schema = document["schema"]
        match = _SCHEMA.match(schema) if isinstance(schema, str) else None
        if not match:
            raise ValueError(f"schema {schema!r} is not studio.<type>/v<major>")
        if match["type"] not in STUDIO_TYPES:
            raise ValueError(f"schema type {match['type']!r} is not a v1 type (section 2)")
        return match["type"]
    if set(document) == {"error"} and isinstance(document["error"], dict):
        return ERROR_ENVELOPE
    if {"shots", "frame", "job"} <= set(document):
        return LEGACY_MANIFEST
    raise ValueError(
        "has no schema field and is neither an error envelope nor a legacy manifest"
    )


def load(path: Path, *, examples_dir: Path = EXAMPLES_DIR,
         root: Path = REPO_ROOT) -> tuple[Example | None, list[Problem]]:
    """Parse one example. Returns (example, problems); example is None if unusable."""
    label = _label(path, root)
    try:
        kind = path.relative_to(examples_dir).parts[0]
    except (ValueError, IndexError):
        kind = ""
    if kind not in ("valid", "invalid") or path.parent == examples_dir:
        return None, [Problem(label, "example.location", "must be under valid/ or invalid/")]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        first = str(error).splitlines()[0] if str(error) else type(error).__name__
        return None, [Problem(label, "example.json", f"not JSON: {first}")]

    problems: list[Problem] = []
    rule = None
    document = data
    if kind == "invalid":
        if not isinstance(data, dict):
            return None, [Problem(label, "case.wrapper", "an invalid case must be an object")]
        rule = data.get("rule") if isinstance(data.get("rule"), str) else None
        problems += _wrapper_problems(label, data, rule)
        if "document" not in data:
            return None, problems
        document = data["document"]
    elif isinstance(data, dict) and data.get("schema") == INVALID_CASE_SCHEMA:
        return None, [Problem(label, "example.location", "an invalid case is under valid/")]

    try:
        doc_type = document_type(document)
    except ValueError as error:
        where = "document " if kind == "invalid" else ""
        problems.append(Problem(label, "example.type", f"{where}{error}", rule))
        return None, problems
    example = Example(path=path, label=label, kind=kind, data=data, document=document,
                      type=doc_type, rule=rule)
    return example, problems


def _wrapper_problems(label: str, data: Mapping, rule: str | None) -> list[Problem]:
    problems = []

    def bad(message: str) -> None:
        problems.append(Problem(label, "case.wrapper", message, rule))

    if data.get("schema") != INVALID_CASE_SCHEMA:
        bad(f"schema must be {INVALID_CASE_SCHEMA!r}")
    missing = [name for name in WRAPPER_FIELDS if name not in data]
    unknown = sorted(set(data) - set(WRAPPER_FIELDS))
    if missing:
        bad(f"missing field(s): {', '.join(missing)}")
    if unknown:
        bad(f"unknown field(s): {', '.join(unknown)}")
    if "rule" in data and rule is None:
        bad("rule must be a string")
    if "expect" in data and data["expect"] not in EXPECT:
        bad(f"expect must be one of {', '.join(EXPECT)}")
    if "context" in data and data["context"] not in CASE_CONTEXTS:
        bad(f"context must be one of {', '.join(CASE_CONTEXTS)}")
    if "path" in data and not (isinstance(data["path"], str) and _POINTER.match(data["path"])):
        bad("path must be a JSON Pointer")
    if "why" in data and not (isinstance(data["why"], str) and data["why"].strip()):
        bad("why must be a sentence")
    return problems


def check_example(path: Path, rules: Mapping[str, Rule], *,
                  examples_dir: Path = EXAMPLES_DIR, root: Path = REPO_ROOT) -> list[Problem]:
    """All shape problems of one example: parse, wrapper, type, rule index."""
    example, problems = load(path, examples_dir=examples_dir, root=root)
    data = example.data if example else None
    if example is None or example.kind != "invalid" or example.rule is None:
        return problems
    entry = rules.get(example.rule)
    if entry is None:
        problems.append(Problem(example.label, "case.rule_unknown",
                                "not in the contract's rule index (section 15)", example.rule))
    elif data.get("expect") in EXPECT and data["expect"] not in re.findall(r"[a-z_]+", entry.status):
        problems.append(Problem(
            example.label, "case.expect_mismatch",
            f"expect {data['expect']!r} but the rule index says {entry.status!r}", example.rule,
        ))
    return problems


def check_index_links(rules: Mapping[str, Rule], examples_dir: Path = EXAMPLES_DIR, *,
                      root: Path = REPO_ROOT) -> list[Problem]:
    """Every invalid example the rule index links to exists and declares that rule."""
    problems = []
    seen: set[str] = set()
    for entry in rules.values():
        for name in entry.examples:
            if name in seen:
                continue
            seen.add(name)
            path = examples_dir / "invalid" / name
            label = _label(path, root)
            if not path.is_file():
                problems.append(Problem(label, "index.link", "linked from section 15 but missing",
                                        entry.code))
                continue
            example, _ = load(path, examples_dir=examples_dir, root=root)
            declared = example.rule if example else None
            if declared not in entry.row:
                problems.append(Problem(label, "index.link",
                                        f"section 15 links it for {entry.code}, it declares {declared}",
                                        entry.code))
    return problems


# Validators -------------------------------------------------------------------


def _normalize(found: Iterable[Any]) -> list[Violation]:
    result = []
    for item in found:
        if hasattr(item, "rule"):
            result.append(Violation(str(item.rule), str(item.status), str(item.path)))
        else:
            rule, status, path = item
            result.append(Violation(str(rule), str(status), str(path)))
    return result


def _run(validator: Validator, example: Example, context: str) -> list[Violation]:
    try:
        return _normalize(validator(example.document, context=context))
    except Exception as error:
        error.add_note(f"{example.label}: validator for {example.type!r} raised "
                       f"in context {context!r}")
        raise


def _describe(violations: Iterable[Violation]) -> str:
    listed = [f"{v.rule} ({v.status}) at {v.path or '/'}" for v in violations]
    return ", ".join(listed) if listed else "nothing"


def check_with_validator(example: Example, validator: Validator) -> list[Problem]:
    """Run the registered validator against one example, per section 14."""
    if example.kind == "valid":
        found = _run(validator, example, READ_CONTEXT)
        blocking = [v for v in found if v.status != WARNING]
        if blocking:
            return [Problem(example.label, "validator.rejects_valid",
                            f"expected valid, got {_describe(blocking)}")]
        return []

    expect, context = example.data["expect"], example.data["context"]
    problems = []
    if context == "queue_run":
        saved = [v for v in _run(validator, example, "write") if v.status != WARNING]
        if saved:
            problems.append(Problem(
                example.label, "validator.write_rejects",
                f"a queue_run case must save; write reported {_describe(saved)}", example.rule,
            ))
    found = [v for v in _run(validator, example, context) if v.status != WARNING]
    rules = {v.rule for v in found}
    if rules != {example.rule}:
        problems.append(Problem(
            example.label, "validator.mismatch",
            f"expected exactly {example.rule} in context {context}, got {_describe(found)}",
            example.rule,
        ))
    elif any(v.status != expect for v in found):
        problems.append(Problem(
            example.label, "validator.status",
            f"expected status {expect}, got {_describe(found)}", example.rule,
        ))
    return problems


def pending_types(validators: Mapping[str, Validator],
                  examples: Iterable[Example] = ()) -> list[tuple[str, int]]:
    """(type, example count) for every known type without a registered validator."""
    counts: dict[str, int] = {}
    for example in examples:
        counts[example.type] = counts.get(example.type, 0) + 1
    return [(name, counts.get(name, 0)) for name in ALL_TYPES if name not in validators]


def fail_on(problems: Iterable[Problem]) -> None:
    """Fail the current test with one line per problem and no traceback."""
    import pytest

    lines = [str(problem) for problem in problems]
    if lines:
        pytest.fail("\n".join(lines), pytrace=False)
