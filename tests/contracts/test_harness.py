"""The harness's own tests: broken examples fail loudly, by path and rule, and nothing else leaks."""

from __future__ import annotations

import json
import textwrap

import pytest

from tests.contracts import harness
from tests.contracts.harness import Violation

RULES = harness.load_rule_index()
BOARD = {"schema": "studio.board/v1", "id": "brd_01M79V9FC00000000000000002"}


def case(**overrides):
    wrapper = {
        "schema": "studio.invalid-case/v1",
        "rule": "time.negative",
        "expect": "invalid",
        "context": "write",
        "path": "/lines/2/gap_before_ms",
        "why": "A negative gap breaks TIME-2.",
        "document": BOARD,
    }
    wrapper.update(overrides)
    return {key: value for key, value in wrapper.items() if value is not ...}


class ExampleDir:
    """A scratch examples/ folder under tmp_path; labels are relative to tmp_path."""

    def __init__(self, root):
        self.root = root
        self.folder = root / "examples"

    def write(self, relative, data):
        path = self.folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        text = data if isinstance(data, str) else json.dumps(data)
        path.write_text(text, encoding="utf-8")
        return path

    def check(self, relative, data):
        path = self.write(relative, data)
        found = harness.check_example(path, RULES, examples_dir=self.folder, root=self.root)
        return [str(problem) for problem in found]

    def load(self, relative, data):
        path = self.write(relative, data)
        example, problems = harness.load(path, examples_dir=self.folder, root=self.root)
        assert not problems, problems
        return example


@pytest.fixture
def examples(tmp_path):
    return ExampleDir(tmp_path)


def test_good_case_and_valid_example_have_no_problems(examples):
    assert examples.check("invalid/ok.json", case()) == []
    assert examples.check("valid/ok.json", BOARD) == []
    assert examples.check("valid/legacy.json", {"shots": [], "frame": {}, "job": "x"}) == []
    assert examples.check("valid/error.json", {"error": {"code": "method.unavailable"}}) == []


@pytest.mark.parametrize(("relative", "data", "expected"), [
    ("invalid/syntax.json", "{", "examples/invalid/syntax.json: example.json: not JSON"),
    ("loose.json", BOARD, "examples/loose.json: example.location"),
    ("valid/notes.txt", "plain text", "examples/valid/notes.txt: example.json: not JSON"),
    ("valid/case.json", case(), "examples/valid/case.json: example.location"),
    ("valid/list.json", [], "examples/valid/list.json: example.type: is a JSON array"),
    ("valid/v9.json", {"schema": "studio.film/v1"}, "example.type: schema type 'film'"),
    ("valid/shape.json", {"id": "x"}, "example.type: has no schema field"),
    ("invalid/typo.json", case(rule="time.negativ"),
     "examples/invalid/typo.json: rule time.negativ: case.rule_unknown"),
    ("invalid/expect.json", case(expect="forbidden"),
     "examples/invalid/expect.json: rule time.negative: case.expect_mismatch"),
    ("invalid/why.json", case(why=...),
     "examples/invalid/why.json: rule time.negative: case.wrapper: missing field(s): why"),
    ("invalid/extra.json", case(colour="red"),
     "examples/invalid/extra.json: rule time.negative: case.wrapper: unknown field(s): colour"),
    ("invalid/context.json", case(context="read"),
     "rule time.negative: case.wrapper: context must be one of write, queue_run"),
    ("invalid/pointer.json", case(path="lines/2"),
     "rule time.negative: case.wrapper: path must be a JSON Pointer"),
    ("invalid/wrapper.json", case(schema="studio.board/v1"),
     "rule time.negative: case.wrapper: schema must be 'studio.invalid-case/v1'"),
    ("invalid/document.json", case(document=...),
     "rule time.negative: case.wrapper: missing field(s): document"),
    ("valid/dupe.json", '{"schema": "studio.board/v1", "id": "a", "id": "b"}',
     "examples/valid/dupe.json: example.json: not JSON: duplicate key 'id'"),
    ("valid/nan.json", '{"schema": "studio.board/v1", "number": NaN}',
     "examples/valid/nan.json: example.json: not JSON: NaN is not JSON"),
    ("valid/v2.json", {"schema": "studio.board/v2"},
     "examples/valid/v2.json: example.version: a valid v1 example has schema 'studio.board/v2'"),
    ("invalid/queue.json", case(rule="method.unavailable", expect="unavailable"),
     "rule method.unavailable: case.context_mismatch: context 'write'"),
    ("invalid/null.json", case(document=None),
     "rule time.negative: example.type: document is a JSON null, not an object"),
])
def test_broken_example_names_its_path_and_rule(examples, relative, data, expected):
    problems = examples.check(relative, data)
    assert any(expected in problem for problem in problems), problems


def test_validator_must_report_exactly_the_rule_with_its_status(examples):
    example = examples.load("invalid/case.json", case())

    def wrong_rule(document, *, context):
        return [Violation("schema.unknown_field", "invalid", "/colour")]

    def right_rule_and_warning(document, *, context):
        return [("time.negative", "invalid", "/lines/2/gap_before_ms"),
                ("format.length_exceeded", "warning", "")]

    def wrong_status(document, *, context):
        return [Violation("time.negative", "forbidden", "/lines/2/gap_before_ms")]

    problems = [str(p) for p in harness.check_with_validator(example, wrong_rule)]
    assert problems == [
        "examples/invalid/case.json: rule time.negative: validator.mismatch: expected exactly "
        "time.negative in context write, got schema.unknown_field (invalid) at /colour"
    ]
    assert harness.check_with_validator(example, right_rule_and_warning) == []
    assert "validator.status" in str(harness.check_with_validator(example, wrong_status)[0])


def test_queue_run_case_must_save_and_then_fail_at_queue(examples):
    example = examples.load("invalid/queue.json", case(
        rule="method.unavailable", expect="unavailable", context="queue_run", path="/method",
    ))
    contexts = []

    def at_queue_only(document, *, context):
        contexts.append(context)
        return [("method.unavailable", "unavailable", "/method")] if context == "queue_run" else []

    def always(document, *, context):
        return [("method.unavailable", "unavailable", "/method")]

    assert harness.check_with_validator(example, at_queue_only) == []
    assert contexts == ["write", "queue_run"]
    assert "validator.write_rejects" in str(harness.check_with_validator(example, always)[0])


def test_valid_example_is_checked_in_read_context(examples):
    example = examples.load("valid/board.json", BOARD)
    seen = []

    def rejects(document, *, context):
        seen.append(context)
        return [("id.malformed", "invalid", "/id")]

    problems = [str(p) for p in harness.check_with_validator(example, rejects)]
    assert seen == ["read"]
    assert problems == ["examples/valid/board.json: validator.rejects_valid: expected valid, "
                        "got id.malformed (invalid) at /id"]


def test_validator_exception_is_labelled_with_the_example(examples):
    example = examples.load("valid/board.json", BOARD)

    def broken(document, *, context):
        raise KeyError("timing")

    with pytest.raises(KeyError) as raised:
        harness.check_with_validator(example, broken)
    assert "examples/valid/board.json: validator for 'board' raised" in raised.value.__notes__[0]


def test_pending_lists_every_unregistered_type_by_name(examples):
    board = examples.load("valid/board.json", BOARD)
    pending = harness.pending_types({}, [board, board])
    assert [name for name, _ in pending] == list(harness.ALL_TYPES)
    assert ("board", 2) in pending and ("job", 0) in pending
    registered = harness.pending_types({"board": lambda document, *, context: []}, [board])
    assert "board" not in [name for name, _ in registered]


def test_index_link_to_a_missing_or_mismatched_case_fails(examples):
    examples.write("invalid/time-negative.json", case(rule="time.tail_too_short"))
    rules = {
        "time.negative": harness.Rule("time.negative", "invalid", ("time.negative",),
                                      ("time-negative.json",)),
        "cue.out_of_range": harness.Rule("cue.out_of_range", "invalid", ("cue.out_of_range",),
                                         ("cue-out-of-range.json",)),
    }
    problems = [str(p) for p in harness.check_index_links(rules, examples.folder,
                                                          root=examples.root)]
    assert problems == [
        "examples/invalid/time-negative.json: rule time.negative: index.link: section 15 links "
        "it for time.negative, it declares time.tail_too_short",
        "examples/invalid/cue-out-of-range.json: rule cue.out_of_range: index.link: linked "
        "from section 15 but missing",
    ]


def test_failing_run_prints_path_and_rule_but_no_environment(pytester, monkeypatch):
    """End to end: a broken example fails the pytest run; the log holds no env or token."""
    canary = "canary-7f3a9c1e-token"
    monkeypatch.setenv("STUDIO_FAKE_TOKEN", canary)
    monkeypatch.setenv("STUDIO_TEST_DATABASE_URL", "postgresql://u:pw-canary-91@h/studio_test")
    (pytester.path / "examples" / "invalid").mkdir(parents=True)
    (pytester.path / "examples" / "invalid" / "broken.json").write_text(
        json.dumps(case(rule="time.negativ")), encoding="utf-8")
    (pytester.path / "examples" / "invalid" / "mismatch.json").write_text(
        json.dumps(case()), encoding="utf-8")
    pytester.makepyfile(test_inner=textwrap.dedent("""
        import os
        from pathlib import Path
        from tests.contracts import harness

        HERE = Path(__file__).parent
        FOLDER = HERE / "examples"
        RULES = harness.load_rule_index()

        def test_shape():
            token = os.environ["STUDIO_FAKE_TOKEN"]
            problems = []
            for path in harness.discover(FOLDER):
                problems += harness.check_example(path, RULES, examples_dir=FOLDER, root=HERE)
            harness.fail_on(problems)

        def test_validator():
            env = dict(os.environ)
            example, _ = harness.load(FOLDER / "invalid" / "mismatch.json",
                                      examples_dir=FOLDER, root=HERE)
            wrong = lambda document, *, context: [("schema.unknown_field", "invalid", "/x")]
            harness.fail_on(harness.check_with_validator(example, wrong))
    """))
    result = pytester.runpytest("-p", "tests.support.plugin", "--showlocals", "-rA")
    result.assert_outcomes(failed=2)
    output = result.stdout.str() + result.stderr.str()
    assert "examples/invalid/broken.json: rule time.negativ: case.rule_unknown" in output
    assert ("examples/invalid/mismatch.json: rule time.negative: validator.mismatch: "
            "expected exactly time.negative") in output
    for leaked in (canary, "pw-canary-91", "STUDIO_FAKE_TOKEN", "environ("):
        assert leaked not in output
