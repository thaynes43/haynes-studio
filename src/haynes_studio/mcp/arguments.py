"""Tool input schemas. The API validates the canonical fields and their references."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from haynes_studio.canonical.ids import ULID_PATTERN
from haynes_studio.drafting.declaration import (
    DraftDeclaration, PersonEditAcknowledgment, RedraftDeclaration,
)

ProductionID = Annotated[str, StringConstraints(pattern=rf"^prd_{ULID_PATTERN}$")]
StoryID = Annotated[str, StringConstraints(pattern=rf"^sty_{ULID_PATTERN}$")]
BoardID = Annotated[str, StringConstraints(pattern=rf"^brd_{ULID_PATTERN}$")]
AssetID = Annotated[str, StringConstraints(pattern=rf"^ast_{ULID_PATTERN}$")]
RunID = Annotated[str, StringConstraints(pattern=rf"^run_{ULID_PATTERN}$")]
FormatID = Annotated[str, StringConstraints(
    max_length=64, pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$",
)]
FormatVersionID = Annotated[str, StringConstraints(pattern=rf"^fmv_{ULID_PATTERN}$")]
VersionCursor = Annotated[str, StringConstraints(pattern=rf"^asv_{ULID_PATTERN}$")]
BoardCursor = Annotated[str, StringConstraints(pattern=rf"^[1-9][0-9]{{0,18}}:brd_{ULID_PATTERN}$")]
Revision = Annotated[int, Field(ge=1, lt=2**63 - 1)]
Limit = Annotated[int, Field(ge=1, le=20)]
MediaKind = Literal["short", "video"]
Title = Annotated[str, StringConstraints(min_length=1, max_length=100)]
StoryTitle = Annotated[str, StringConstraints(min_length=1, max_length=80)]
Label = Annotated[str, StringConstraints(min_length=1, max_length=64)]

STORY_EDIT_FIELDS = Literal[
    "title", "format_version_id", "cast", "narrator_voice_version_id", "set", "layouts",
    "motion_style", "mix", "checks", "beds",
]
BOARD_EDIT_FIELDS = Literal[
    "title", "lines", "timing", "voice", "photo", "cast", "layout", "method", "seeds",
    "cues", "notes",
]


class Arguments(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", defer_build=True)


class StoryFields(Arguments):
    title: StoryTitle | None = None
    format_version_id: FormatVersionID | None = None
    cast: list[dict] | None = None
    narrator_voice_version_id: str | None = None
    set: dict | None = None
    layouts: dict | None = None
    motion_style: dict | None = None
    mix: dict | None = None
    checks: dict | None = None
    beds: list[dict] | None = None


class NewStoryFields(StoryFields):
    title: StoryTitle


class _BaseBoardFields(Arguments):
    title: Title | None = None
    lines: list[dict] | None = None
    timing: dict | None = None
    voice: dict | None = None
    photo: dict | None = None
    cast: list[dict] | None = None
    layout: dict | None = None
    method: dict | None = None
    seeds: dict | None = None
    cues: list[dict] | None = None
    notes: list[dict] | None = None


class NewBoardFields(_BaseBoardFields):
    draft_application: DraftDeclaration | None = None


class BoardFields(_BaseBoardFields):
    draft_application: RedraftDeclaration | None = None
    acknowledge_person_edit: PersonEditAcknowledgment | None = None


class Production(Arguments):
    production_id: ProductionID


class ListProductions(Arguments):
    cursor: ProductionID | None = None
    limit: Limit = 10


class ProductionMedia(Production):
    kind: MediaKind


class ListStories(ProductionMedia):
    publication: Literal["published", "unpublished"] | None = None
    approved: bool | None = None
    cursor: StoryID | None = None
    limit: Limit = 10


class CreateStory(ProductionMedia):
    fields: NewStoryFields


class Story(Arguments):
    story_id: StoryID


class StoryPage(Story):
    cursor: BoardCursor | None = None
    limit: Limit = 10


class StorySummary(StoryPage):
    fields: Annotated[list[STORY_EDIT_FIELDS], Field(max_length=10)] | None = None


class PatchStory(Story):
    revision: Revision
    patch: StoryFields


class AddBoard(Story):
    revision: Revision
    fields: NewBoardFields


class Board(Arguments):
    board_id: BoardID


class GetBoard(Board):
    fields: Annotated[list[BOARD_EDIT_FIELDS], Field(max_length=11)] | None = None


class BoardWrite(Board):
    revision: Revision


class PatchBoard(BoardWrite):
    patch: BoardFields


class RemoveBoard(BoardWrite):
    acknowledge_person_edit: PersonEditAcknowledgment | None = None


class ReorderBoards(Story):
    revision: Revision
    board_order: list[BoardID]
    acknowledge_person_edit: dict[BoardID, PersonEditAcknowledgment] | None = None


class SearchAssets(Arguments):
    kind: Annotated[str, StringConstraints(min_length=1, max_length=40)] | None = None
    label: Annotated[list[Label], Field(max_length=20)] | None = None
    production: ProductionID | None = None
    board: BoardID | None = None
    cursor: VersionCursor | None = None
    limit: Limit = 10


class Asset(Arguments):
    asset_id: AssetID
    cursor: VersionCursor | None = None
    limit: Limit = 10


class Delivery(Arguments):
    run_id: RunID


class ListFormats(Arguments):
    cursor: FormatID | None = None
    limit: Limit = 10


class ListFormatVersions(Arguments):
    format_id: FormatID
    cursor: FormatVersionID | None = None
    limit: Limit = 10


class FormatVersion(Arguments):
    version_id: FormatVersionID
