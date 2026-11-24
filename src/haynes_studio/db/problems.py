"""Domain failures shared by the service and its persistence layer."""

from haynes_studio.errors import ContractError, blocking


class NotFound(Exception):
    """No visible record matches the requested identity."""


class StaleRevision(Exception):
    def __init__(self, current: int):
        self.current = current


def require_revision(current: int, expected: int) -> None:
    if current != expected:
        raise StaleRevision(current)


def require_valid(violations) -> None:
    problems = blocking(violations)
    if problems:
        raise ContractError("<studio>", problems)
