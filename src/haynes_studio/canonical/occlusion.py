"""Write defaults for the visibility declaration contract (CR-61)."""

from collections.abc import Mapping

from haynes_studio.errors import Violation

OCCLUSION_UNAVAILABLE = "occlusion.check_unavailable"
VISIBILITY_UNAVAILABLE = "The visibility check is not installed"


def unavailable(path: str) -> Violation:
    return Violation(OCCLUSION_UNAVAILABLE, path, VISIBILITY_UNAVAILABLE, "unavailable")


def board_write_document(board):
    """Omit an explicit null or empty pose list in a board write."""
    layout = board.get("layout") if isinstance(board, Mapping) else None
    if isinstance(layout, Mapping) and "check_poses" in layout and _empty_list(layout["check_poses"]):
        return {**board, "layout": {key: value for key, value in layout.items() if key != "check_poses"}}
    return board


def story_write_document(story):
    """Apply the board write defaults to the embedded documents."""
    boards = story.get("boards") if isinstance(story, Mapping) else None
    if isinstance(boards, (list, tuple)):
        cleaned = [board_write_document(board) for board in boards]
        if any(before is not after for before, after in zip(boards, cleaned)):
            return {**story, "boards": cleaned}
    return story


def _empty_list(value) -> bool:
    return value is None or (isinstance(value, (list, tuple)) and not value)
