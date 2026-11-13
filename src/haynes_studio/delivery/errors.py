"""Delivery errors and their codes (proposals of story 381; ``store.collision`` is the
contract's, section 8)."""

from __future__ import annotations

from haynes_studio.delivery.media import Problem

MASTER_INVALID = "delivery.master_invalid"  # the master failed a check: nothing written
PROXY_INVALID = "delivery.proxy_invalid"  # the proxy made from it failed a check
MASTER_CHANGED = "delivery.master_changed"  # the master file changed while it was read
NOT_VERIFIED = "delivery.not_verified"  # a published file did not re-hash to its hash
RECORD_INVALID = "delivery.record_invalid"  # a completed stage that is not a delivery
LEGACY_MISMATCH = "delivery.legacy_mismatch"  # a ledger and its evidence disagree


class DeliveryError(Exception):
    """A delivery refused or failed. ``code`` names why; ``problems`` lists each failed
    media check (what was expected and what was found)."""

    def __init__(self, code: str, message: str, problems: tuple[Problem, ...] = ()):
        self.code, self.problems = code, tuple(problems)
        lines = [f"{code}: {message}", *(f"  {problem}" for problem in self.problems)]
        super().__init__("\n".join(lines))


__all__ = ["DeliveryError", "LEGACY_MISMATCH", "MASTER_CHANGED", "MASTER_INVALID",
           "NOT_VERIFIED", "PROXY_INVALID", "RECORD_INVALID"]
