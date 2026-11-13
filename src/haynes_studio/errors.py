"""Rule violations and the error that carries them.

A violation names a rule code from the contract's rule index (section 15) or a
documented proposal, a JSON Pointer into the document, and a message. The contract
harness reads ``rule``, ``status`` and ``path``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

INVALID = "invalid"
WARNING = "warning"


def pointer(*parts: str | int) -> str:
    """A JSON Pointer from path parts: ``pointer("shots", 0, "line")`` is ``/shots/0/line``."""
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


@dataclass(frozen=True)
class Violation:
    """One broken rule. ``path`` is a JSON Pointer (``""`` is the whole document)."""

    rule: str
    path: str
    message: str
    status: str = INVALID

    def __str__(self) -> str:
        return f"rule {self.rule} at {self.path or '/'}: {self.message}"


def blocking(violations: Iterable[Violation]) -> list[Violation]:
    """The violations that make a document invalid (everything but warnings)."""
    return [violation for violation in violations if violation.status != WARNING]


class ContractError(ValueError):
    """A document failed one or more rules. ``source`` names the file (or ``<document>``)."""

    def __init__(self, source: str, violations: Iterable[Violation]):
        self.source = source
        self.violations = tuple(violations)
        super().__init__("\n".join(f"{source}: {violation}" for violation in self.violations))
