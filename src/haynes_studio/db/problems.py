"""Domain failures shared by the service and its persistence layer."""

from haynes_studio.errors import ContractError, blocking


class NotFound(Exception):
    """No visible record matches the requested identity."""


class StaleRevision(Exception):
    def __init__(self, current: int, path: str = "/revision"):
        self.current = current
        self.path = path


def require_revision(current: int, expected: int, path: str = "/revision") -> None:
    if current != expected:
        raise StaleRevision(current, path)


class DraftProtected(Exception):
    """An agent needs to acknowledge the current board before replacing it."""

    def __init__(self, board: dict):
        self.board_id = board["id"]
        self.current_revision = board["revision"]
        stamp = board.get("draft_application", {})
        self.person_edit = stamp.get("person_edit")
        self.person_edit_revision = stamp.get("person_edit_revision")


def require_valid(violations) -> None:
    problems = blocking(violations)
    if problems:
        raise ContractError("<studio>", problems)
