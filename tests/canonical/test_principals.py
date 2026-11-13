"""The agent-session principal (contract section 2, P-24; story 849): accepted wherever
a principal is, validated like the other kinds, and granting nothing."""

from __future__ import annotations

import copy

import pytest

from haynes_studio.canonical import validate_board, validate_production, validate_story
from haynes_studio.canonical.ids import Minter
from haynes_studio.canonical.model import Principal, to_document
from haynes_studio.errors import WARNING
from haynes_studio.library import validate_asset, validate_asset_version
from haynes_studio.voice import new_job, validate_job
from tests.canonical.fixtures import NOW, OPERATOR, board_context, example, example_context

SESSION = {"kind": "agent_session", "session": "haynes-studio-1113-141004",
           "harness": "Claude Code", "model": "claude-opus-5-5"}


def _write_form(document):
    out = {k: copy.deepcopy(v) for k, v in document.items() if k != "derived"}
    if "boards" in out:
        out["boards"] = [{k: v for k, v in b.items() if k != "derived"} for b in out["boards"]]
    return out


def _board():
    story = example("valid/story-winter-menu-r4.json")
    return _write_form(next(b for b in story["boards"] if b["number"] == 8))


def _job():
    minter = Minter(clock=lambda: 1_800_000_000_000, random_bits=lambda: 9)
    return new_job("photo", "brd_01M79V9FC00000000000000008", "sha256:" + "a" * 64,
                   by=Principal.from_document(SESSION), now=NOW, minter=minter).to_document()


def _story_check(document):
    return validate_story(document, context="write", facts=example_context().facts)


def _board_check(document):
    return validate_board(document, context="write", **board_context(document))


# (name, base document, the principal's path, validator)
PLACES = [
    ("production", lambda: example("valid/production.json"), ("created_by",),
     lambda d: validate_production(d, context="write")),
    ("story", lambda: _write_form(example("valid/story-winter-menu-r4.json")), ("created_by",),
     _story_check),
    ("board", _board, ("drafted_by",), _board_check),
    ("asset", lambda: example("valid/asset-cast.json"), ("created_by",),
     lambda d: validate_asset(d, context="write")),
    ("asset-version", lambda: example("valid/asset-version-cast.json"),
     ("provenance", "created_by"), lambda d: validate_asset_version(d, context="write")),
    ("licence", lambda: example("valid/asset-version-cast.json"), ("licence", "checked_by"),
     lambda d: validate_asset_version(d, context="write")),
    ("job", _job, ("created_by",), lambda d: validate_job(d, context="write")),
]


def _put(document, path, value):
    target = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return document


def _found(validate, document):
    return [(v.rule, v.path) for v in validate(document) if v.status != WARNING]


def _at(path) -> str:
    return "".join(f"/{key}" for key in path)


@pytest.mark.parametrize("name, base, path, validate", PLACES, ids=[p[0] for p in PLACES])
def test_an_agent_session_is_accepted_wherever_a_principal_is(name, base, path, validate):
    assert _found(validate, base()) == []
    assert _found(validate, _put(base(), path, dict(SESSION))) == []


MALFORMED = [
    (lambda p: p.pop("model"), "schema.invalid", ""),
    (lambda p: p.pop("session"), "schema.invalid", ""),
    (lambda p: p.update(harness=""), "schema.invalid", "/harness"),
    (lambda p: p.update(session=7), "schema.invalid", "/session"),
    (lambda p: p.update(key_id="key_01M79V9FC00000000000000001"), "schema.unknown_field",
     "/key_id"),
    (lambda p: p.update(kind="agent-session"), "schema.invalid", "/kind"),
]


@pytest.mark.parametrize("name, base, path, validate", PLACES, ids=[p[0] for p in PLACES])
@pytest.mark.parametrize("change, rule, tail", MALFORMED,
                         ids=["no-model", "no-session", "empty-harness", "session-not-text",
                              "key-id", "kind-spelling"])
def test_a_malformed_agent_session_is_refused(name, base, path, validate, change, rule, tail):
    principal = dict(SESSION)
    change(principal)
    if name == "licence":  # null or a principal (anyOf): reported at the field, as below
        rule, tail = "schema.invalid", ""
    assert _found(validate, _put(base(), path, principal)) == [(rule, _at(path) + tail)]


def test_a_nullable_principal_reports_any_malformed_kind_at_its_field():
    """``licence.checked_by`` is null or a principal; a malformed worker is reported at
    the field too, so the agent session is validated like the other kinds there."""
    worker = {"kind": "worker", "worker_id": "w", "key_id": "key_01M79V9FC00000000000000001"}
    document = _put(example("valid/asset-version-cast.json"), ("licence", "checked_by"), worker)
    assert _found(lambda d: validate_asset_version(d, context="write"), document) == [
        ("schema.invalid", "/licence/checked_by")]


def test_an_agent_session_grants_nothing():
    """It cannot stand in for the human a command line acts for, so it cannot reach
    anything a human principal is needed for (P-24)."""
    document = example("valid/asset-cast.json")
    document["created_by"]["operator"] = dict(SESSION)
    found = set(_found(lambda d: validate_asset(d, context="write"), document))
    assert found == {("schema.invalid", "/created_by/operator"),
                     ("schema.invalid", "/created_by/operator/kind"),
                     *(("schema.unknown_field", f"/created_by/operator/{key}")
                       for key in ("session", "harness", "model"))}


@pytest.mark.parametrize("document", [
    SESSION, OPERATOR, {"kind": "agent", "key_id": "key_01M79V9FC00000000000000001"},
    {"kind": "worker", "worker_id": "dev-env agent session haynes-studio-1113-141004"},
    {"kind": "cli", "command": "studio legacy import", "operator": OPERATOR},
], ids=["agent_session", "human", "agent", "worker", "cli"])
def test_every_kind_round_trips_through_the_model(document):
    assert to_document(Principal.from_document(document)) == document
