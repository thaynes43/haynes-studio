"""The motion records a story's layered boards play, pinned before planning (story 426).

:func:`pin_story` calls story 457's resolver (:mod:`haynes_studio.motion.resolve`) once
per layered board, as if the board were layered I2V, so every cast entry gets its loop:
an idle doll plays it (TIME-8a) and a speaker takes her speech-to-video start image and
her keying inputs from it (**proposal**: ``source.image_sha256`` and ``keying`` of the
cast still's loop; the E0 records agree on the start image, see the reference). The set
gets the story's pinned set loop, the one promoted loop of the set still, or none (a
static plate). Build generates no loop (Q-457-1): a cast still without one is
``motion.clip_absent``, and the plan stops on it.

The result is the plan's :class:`~haynes_studio.cache.plan.LayeredMotion`. Its
``timed`` answers a speaker's library timed clip for the drive track the plan computed
(``resolve_timed``), so an existing clip made from the board's own drive track is used
and never made again. Nothing here reads media; ``verify`` is the store's
``Store.verify``.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from haynes_studio.cache.errors import CacheError
from haynes_studio.cache.plan import LayeredMotion
from haynes_studio.errors import blocking, pointer
from haynes_studio.library.library import Library
from haynes_studio.motion.resolve import (
    CLIP_ABSENT,
    BoardMotion,
    PinnedClip,
    Verify,
    remembered,
    resolve_board,
    resolve_timed,
)

DECAL_MIN_ECC = 0.8  # poc/decal.py MIN_ECC: the gate of a clip the build makes


def _as_layered_i2v(board: Mapping[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(dict(board))
    out["method"] = {"layer": "layered", "motion": "i2v"}
    return out


def pin_board(board: Mapping[str, Any], library: Library, verify: Verify, *,
              story: Mapping[str, Any], production_id: str | None = None,
              prefix: str = "") -> BoardMotion:
    """Every loop a layered board needs: one per cast entry and the set's."""
    return resolve_board(_as_layered_i2v(board), library, verify, story=story,
                         production_id=production_id, prefix=prefix)


def pin_story(story: Mapping[str, Any], library: Library, verify: Verify, *,
              production_id: str | None = None,
              decal_min_ecc: float = DECAL_MIN_ECC) -> LayeredMotion:
    """The plan's ``motion`` for a ``studio.story/v1`` document with embedded boards.
    Every layered board is resolved (problems stay on its ``BoardMotion``, and the plan
    stops on the first blocking one); whole-frame boards need none."""
    verify = remembered(verify)
    production = production_id or story.get("production_id")
    boards = {}
    for index, board in enumerate(story.get("boards") or []):
        if isinstance(board, Mapping) and (board.get("method") or {}).get("layer") == "layered":
            boards[board["id"]] = pin_board(board, library, verify, story=story,
                                            production_id=production,
                                            prefix=pointer("boards", index))

    def timed(slot: str, still_sha256: str, drive_track_sha256: str,
              board_frames: int) -> PinnedClip | None:
        clip, problems = resolve_timed(library, verify, still_sha256=still_sha256,
                                       drive_track_sha256=drive_track_sha256,
                                       board_frames=board_frames, slot=slot,
                                       production_id=production)
        stop = [v for v in blocking(problems) if v.rule != CLIP_ABSENT]
        if stop:  # an existing clip that cannot be played is never silently remade
            raise CacheError(stop[0].rule, stop[0].message, where=f"timed/{slot}")
        return clip

    return LayeredMotion(boards=boards, timed=timed, decal_min_ecc=decal_min_ecc)


__all__ = ["DECAL_MIN_ECC", "pin_board", "pin_story"]
