"""The method capability matrix (contract section 5, D38, P-08) as code.

A method is one layer and one motion. Three cells are buildable; whole-frame +
speech-to-video is ``unavailable``: a valid design that saves with a warning and is
refused at ``queue_run`` (``method.unavailable``). The machine form with evidence and
profiles is the contract's ``method-capabilities.json``; a test keeps the two equal.
"""

from __future__ import annotations

from types import MappingProxyType

LAYERS = ("layered", "whole_frame")
MOTIONS = ("s2v", "i2v")
BUILDABLE, UNAVAILABLE = "buildable", "unavailable"

MATRIX = MappingProxyType({
    ("layered", "s2v"): BUILDABLE,
    ("layered", "i2v"): BUILDABLE,
    ("whole_frame", "i2v"): BUILDABLE,
    ("whole_frame", "s2v"): UNAVAILABLE,
})


def status(layer: str, motion: str) -> str | None:
    """``buildable``, ``unavailable``, or None for a layer or motion outside the
    lists (``method.unknown``)."""
    return MATRIX.get((layer, motion))


def default_method(spoken: bool, format_layer: str | None = None) -> tuple[str, str]:
    """D38: lines get ``s2v``, no lines ``i2v``. The layer comes from the format; with
    none, ``layered`` (P-08)."""
    return (format_layer or "layered", "s2v" if spoken else "i2v")
