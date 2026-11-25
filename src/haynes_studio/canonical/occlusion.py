"""Write defaults for the visibility declaration contract (CR-61)."""

import re
from collections.abc import Mapping
from dataclasses import replace

from haynes_studio.canonical.jsonvalues import normalize, too_deep
from haynes_studio.errors import ContractError, Violation, pointer
from haynes_studio.schemas import schema_violations

OCCLUSION_UNAVAILABLE = "occlusion.check_unavailable"
VISIBILITY_UNAVAILABLE = "The visibility check is not installed"
POSE_PATH = "/layout/check_poses"
POSE_SCHEMA = ("properties", "layout", "properties", "check_poses")


def unavailable(path: str) -> Violation:
    return Violation(OCCLUSION_UNAVAILABLE, path, VISIBILITY_UNAVAILABLE, "unavailable")


def pose_problems(poses) -> list[Violation]:
    """Key rules for schema-valid poses, relative to the pose list."""
    found = []
    seen = set()
    for i, pose in enumerate(poses):
        key = pose["key"]
        path = pointer(i, "key")
        if key in seen:
            found.append(Violation("ref.duplicate", path, "the check pose key is already used"))
        seen.add(key)
        if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", key) is None:
            found.append(Violation("schema.invalid", path,
                                   "the pose key must match the segmentation target grammar"))
    return found


def board_write_document(board, *, prefix: str = ""):
    """Canonical board output (also accepts a draft's partial board fields).

    CR-61 is checked here for every representation of a board. Other board
    validation remains with the caller. Unchanged documents keep their bytes.
    """
    layout = board.get("layout") if isinstance(board, Mapping) else None
    if not isinstance(layout, Mapping) or "check_poses" not in layout:
        return board
    poses = layout["check_poses"]
    if poses is None or (isinstance(poses, (list, tuple)) and not poses):
        return {**board, "layout": {key: value for key, value in layout.items() if key != "check_poses"}}
    if too_deep(poses):
        problems = [Violation("schema.invalid", "", "the pose list is nested too deeply")]
    else:
        poses = normalize(poses)
        problems = schema_violations("studio.board.v1.schema.json", poses,
                                     default_rule="schema.invalid", fragment=POSE_SCHEMA)
        if not problems:
            problems = pose_problems(poses) or [unavailable("")]
    raise ContractError("<board>", [
        replace(v, path=prefix + POSE_PATH + v.path) for v in problems
    ])


def story_write_document(story, *, prefix: str = ""):
    """Apply the board write defaults to the embedded documents."""
    boards = story.get("boards") if isinstance(story, Mapping) else None
    if isinstance(boards, (list, tuple)):
        cleaned = [board_write_document(board, prefix=prefix + pointer("boards", i))
                   for i, board in enumerate(boards)]
        if any(before is not after for before, after in zip(boards, cleaned)):
            return {**story, "boards": cleaned}
    return story
