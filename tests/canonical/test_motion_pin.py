"""The optional ``motion_asset_version_id`` on a board's cast entry (story 457): additive,
so every board that was valid stays valid and keeps its document; a pin is an asset
version ID, round-trips, and a pin whose version is no doll clip is a capability
mismatch."""

from __future__ import annotations

import copy

import pytest

from haynes_studio.canonical import Board, Facts, to_document, validate_board, validate_story
from tests.canonical.fixtures import board_context, example, example_context

PIN = "asv_01M79V9FC00000000000000099"


def story():
    return example("valid/story-winter-menu-r4.json")


def board(pin=PIN):
    document = copy.deepcopy(story()["boards"][0])
    if pin is not None:
        document["cast"][0]["motion_asset_version_id"] = pin
    return document


def rules(document, facts=None):
    context = board_context(document)
    if facts is not None:
        context["facts"] = facts
    return [(v.rule, v.path) for v in validate_board(document, context="read", **context)]


def test_existing_boards_and_stories_are_unchanged():
    document = story()
    assert [(v.rule, v.path) for v in validate_story(document, context="read",
                                                     facts=example_context().facts)] == []
    for board_doc in document["boards"]:
        assert to_document(Board.from_document(board_doc))["cast"] == board_doc["cast"]
        assert all("motion_asset_version_id" not in entry for entry in board_doc["cast"])


def test_a_pinned_cast_entry_is_valid_and_round_trips():
    document = board()
    assert rules(document) == []
    model = Board.from_document(document)
    assert model.cast[0].motion_asset_version_id == PIN
    assert to_document(model)["cast"] == document["cast"]


@pytest.mark.parametrize(("value", "rule"), [
    ("not-an-id", "id.malformed"),
    ("ast_01M79V9FC00000000000000099", "id.type_mismatch"),
    (None, "schema.invalid"),
])
def test_a_pin_is_an_asset_version_id(value, rule):
    document = board()
    document["cast"][0]["motion_asset_version_id"] = value
    assert rules(document) == [(rule, "/cast/0/motion_asset_version_id")]


def test_a_pin_whose_version_is_no_doll_clip_is_a_capability_mismatch():
    facts = example_context().facts.merged(Facts.build(capabilities={PIN: ["set_loop"]}))
    assert rules(board(), facts) == [("asset.capability_mismatch",
                                      "/cast/0/motion_asset_version_id")]
    clip = example_context().facts.merged(Facts.build(capabilities={PIN: ["motion_clip"]}))
    assert rules(board(), clip) == []
