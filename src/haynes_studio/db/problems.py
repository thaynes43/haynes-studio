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
        protection = board.get("draft_application", board)
        self.path = "/person_edit" if "person_edit" in board else "/draft_application"
        self.person_edit = protection.get("person_edit")
        self.person_edit_revision = protection.get("person_edit_revision")


def require_valid(violations) -> None:
    problems = blocking(violations)
    if problems:
        raise ContractError("<studio>", problems)
