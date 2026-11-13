"""Facts for the contract examples, built from public text fixtures only.

The board and story examples name voice, photo and cast versions that live in the
asset library (story 382). Their facts come from the r4 evidence the examples were
computed from: each board's voice version holds the r4 takes of its legacy shot
(``speech.json``), each named photo version is current, and the asset-version
examples give capabilities.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from haynes_studio.canonical import Board, Facts, PhotoVersionFacts, Story
from haynes_studio.canonical.legacy_import import voice_facts
from haynes_studio.legacy import load, load_speech
from tests.support.policy import REPO_ROOT

EXAMPLES = REPO_ROOT / "docs" / "contracts" / "examples"
TITLE = REPO_ROOT / "titles" / "the-winter-menu"
REVISIONS = {1: ("manifest.json", "evidence", 662), 2: ("manifest-r2.json", "evidence-r2", 823),
             3: ("manifest-r3.json", "evidence-r3", 1094),
             4: ("manifest-r4.json", "evidence-r4", 1087)}
STORY_R4 = EXAMPLES / "valid" / "story-winter-menu-r4.json"
IMPORT_MAP = EXAMPLES / "valid" / "legacy-import-map.json"
OPERATOR = {"kind": "human",
            "iss": "https://authentik.example.invalid/application/o/haynes-studio/",
            "sub": "example-subject-tom"}
NOW = "2026-11-13T07:00:00Z"


def example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def manifest_path(revision: int) -> Path:
    return TITLE / REVISIONS[revision][0]


def speech_path(revision: int) -> Path:
    return TITLE / REVISIONS[revision][1] / "speech.json"


@dataclass(frozen=True)
class ExampleContext:
    stories: dict[str, Story]
    facts: Facts


@cache
def example_context() -> ExampleContext:
    story = Story.from_document(example("valid/story-winter-menu-r4.json"))
    boards = story.ordered_boards()
    facts = voice_facts(boards, load(manifest_path(4)), load_speech(speech_path(4)))
    capabilities = {}
    for path in sorted((EXAMPLES / "valid").glob("asset-version-*.json")):
        version = json.loads(path.read_text(encoding="utf-8"))
        capabilities[version["id"]] = version.get("capabilities", [])
    photos = [PhotoVersionFacts(board.photo.current_version_id) for board in boards
              if board.photo.current_version_id]
    return ExampleContext(stories={story.id: story},
                          facts=facts.merged(Facts.build(photos=photos, capabilities=capabilities)))


def board_context(document) -> dict:
    """Keyword arguments for validate_board: the example story's cast and layouts."""
    context = example_context()
    story_id = document.get("story_id") if isinstance(document, dict) else None
    story = context.stories.get(story_id)
    return {"facts": context.facts,
            "story_cast": story.slots if story else None,
            "story_layouts": tuple(story.layouts) if story else None}


def ordered(story: Story) -> tuple[Board, ...]:
    return story.ordered_boards()
