"""Offline validation and board selection for versioned format recipes."""

from collections.abc import Mapping
from hashlib import sha256
import re

from haynes_studio.canonical import FormatLength
from haynes_studio.canonical.methods import BUILDABLE, UNAVAILABLE, status
from haynes_studio.errors import Violation, pointer
from haynes_studio.schemas import schema_violations
from haynes_studio.store import canonical_json

RECIPE_FILE = "studio.format-recipe.v1.schema.json"
SLUG_PATTERN = r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*"
PIN_PATH = "/format_version_id"


def valid_slug(slug: str) -> bool:
    return len(slug) <= 64 and re.fullmatch(SLUG_PATTERN, slug) is not None


def validate_recipe(recipe: Mapping) -> list[Violation]:
    found = schema_violations(RECIPE_FILE, recipe, default_rule="schema.invalid")
    if found:
        return found
    length = recipe["length"]
    if length["min_ms"] > length["max_ms"]:
        found.append(Violation("format.length_invalid", "/length/max_ms",
                               "The upper bound must be at least the lower bound"))
    for shot, methods in recipe["shot_types"].items():
        for index, method in enumerate(methods):
            path = pointer("shot_types", shot, index)
            if status(method["layer"], method["motion"]) != BUILDABLE:
                found.append(Violation("method.unavailable", path,
                                       "A format recipe may use only buildable methods", UNAVAILABLE))
            elif shot != "speaking" and method["motion"] == "s2v":
                found.append(Violation("method.s2v_needs_onscreen_speaker", path,
                                       "S2V requires an on-screen speaker"))
            elif shot == "ambient" and method["layer"] == "layered":
                found.append(Violation("method.layered_needs_cast", path,
                                       "A layered shot requires visible cast"))
    seen = set()
    for index, target in enumerate(recipe["targets"]):
        if target["id"] in seen:
            found.append(Violation("ref.duplicate", pointer("targets", index, "id"),
                                   "A target ID appears twice in the recipe"))
        seen.add(target["id"])
        if (target["state"] == "placeholder") != (target["account_id"] is None):
            found.append(Violation("format.target_invalid", pointer("targets", index, "account_id"),
                                   "A placeholder has a null account ID and an existing target has an ID"))
    return found


def recipe_hash(recipe: Mapping) -> str:
    return sha256(canonical_json(recipe)).hexdigest()


def format_length(version: dict | None) -> FormatLength | None:
    if version is None:
        return None
    return FormatLength(format_version_id=version["id"], **version["recipe"]["length"])


def shot_type(board: Mapping) -> str:
    """Classify from the visible cast and whether a line belongs to a placed speaker."""
    # Defaults also use this on incoming boards before draft validation.
    cast = [entry.get("slot") for entry in board["cast"] if isinstance(entry, dict) and "slot" in entry]
    if any(line.get("speaker") in cast for line in board["lines"] if isinstance(line, dict)):
        return "speaking"
    return "reaction" if cast else "ambient"


def allowed_methods(recipe: dict, board: Mapping) -> list[dict]:
    return recipe["shot_types"].get(shot_type(board), [])


def method_violation(recipe: dict, board: Mapping) -> Violation | None:
    method = board["method"]
    # The global capability validator already reports a matrix-level refusal.
    if status(method["layer"], method["motion"]) == BUILDABLE and method not in allowed_methods(recipe, board):
        return Violation("method.unavailable", "/method",
                         f"The pinned recipe has no {method['layer']}/{method['motion']} "
                         f"method for {shot_type(board)} shots", UNAVAILABLE)
    return None
