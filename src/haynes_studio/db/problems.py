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
    """The board no longer matches the agent draft's baseline."""


def require_valid(violations) -> None:
    problems = blocking(violations)
    if problems:
        raise ContractError("<studio>", problems)
