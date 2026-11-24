"""Deterministic evidence for wardrobe and decal checks."""

from ._evidence import ColorRange, as_run_check
from .decal import DecalRegions, check_decal
from .wardrobe import AttributeObserver, Observation, SleeveRegions, check_wardrobe

__all__ = [
    "AttributeObserver", "ColorRange", "DecalRegions", "Observation", "SleeveRegions",
    "as_run_check", "check_decal", "check_wardrobe",
]
