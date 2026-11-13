"""The library and the motion block (story 457): a board's cast-entry motion pin is a
reference of kind ``motion``; a motion block exists only on a motion version; versions
without one keep their pins."""

from __future__ import annotations

import copy

from haynes_studio.library import resolve
from haynes_studio.library.resolve import board_references
from tests.library.fixtures import SyntheticStore, imported, winter_menu


def test_a_cast_entry_pin_is_a_motion_reference():
    board = copy.deepcopy(imported(4).story["boards"][0])
    still = board["cast"][0]["asset_version_id"]
    board["cast"][0]["motion_asset_version_id"] = still  # a cast version, not a motion
    refs = {ref.path: ref.kinds for ref in board_references(board)}
    assert refs["/cast/0/motion_asset_version_id"] == frozenset({"motion"})
    library = winter_menu(4).library
    result = resolve({**board, "schema": "studio.board/v1"}, library,
                     SyntheticStore.holding(library))
    assert [(v.rule, v.path) for v in result.problems] == [
        ("asset.kind_mismatch", "/cast/0/motion_asset_version_id")]


def test_boards_without_pins_resolve_as_before():
    story = imported(4).story
    library = winter_menu(4).library
    result = resolve(story, library, SyntheticStore.holding(library))
    assert result.complete
    assert not any(ref.path.endswith("motion_asset_version_id") and "/cast/" in ref.path
                   for ref in result.references)


def test_the_winter_menu_library_has_no_motion_blocks():
    library = winter_menu(4).library
    assert all(version.motion is None for version in library.versions.values())
    assert all("motion" not in document for document in library.documents())
