"""HTTP transport types. Canonical document fields are validated by stories 404/382."""

from functools import cache
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints
from pydantic.root_model import RootModel

from haynes_studio.drafting.declaration import PersonEditAcknowledgment

MediaKind = Literal["short", "video"]
Identifier = Annotated[str, StringConstraints(min_length=30, max_length=30)]
Title = Annotated[str, StringConstraints(min_length=1, max_length=80)]
Nonempty = Annotated[str, StringConstraints(min_length=1, max_length=200)]
JsonObject = dict[str, JsonValue]
T = TypeVar("T")


class TransportModel(BaseModel):
    # Model validators load Pydantic plugins. Build them only when composing the
    # app or using a model, keeping the package safe to import.
    model_config = ConfigDict(defer_build=True)


class Document(RootModel):
    model_config = ConfigDict(defer_build=True)
    root: dict[str, Any]


class Body(TransportModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Page(TransportModel, Generic[T]):
    items: list[T]
    next_cursor: str | None


class ProductionCreate(Body):
    name: Title
    labels: list[Nonempty] = Field(default_factory=list, max_length=100)


class StoryCreate(Document):
    pass


class StoryPatch(Document):
    pass


class BoardCreate(Document):
    pass


class BoardPatch(Document):
    pass


class BoardRemoval(Body):
    acknowledge_person_edit: PersonEditAcknowledgment | None = None


class BoardOrder(Body):
    board_order: list[Identifier]
    acknowledge_person_edit: dict[Identifier, PersonEditAcknowledgment] | None = None


class SelectionWrite(Body):
    values: JsonObject


class Selections(SelectionWrite):
    revision: int


class Me(TransportModel):
    principal: dict[str, str]
    display_name: str | None = None
    csrf_token: str | None = None
    production_scopes: dict[str, list[str]] | None = None


class ExternalPhotoDeclaration(Body):
    """D42 client-declared provenance for the upload transport in story 430."""

    model: Nonempty
    prompt: Annotated[str, StringConstraints(min_length=1, max_length=1800)]
    source_asset_version_ids: list[Annotated[str, StringConstraints(
        pattern=r"^asv_[0-7][0-9A-HJKMNP-TV-Z]{25}$",
    )]] = Field(default_factory=list, max_length=256)
    session: Nonempty
    harness: Nonempty


class Production(Document):
    pass


class Story(Document):
    pass


class Board(Document):
    pass


class Timing(Document):
    pass


class AssetVersion(Document):
    pass


class Delivery(Document):
    pass


class AssetDetail(TransportModel):
    asset: dict[str, Any]
    versions: list[AssetVersion]
    next_cursor: str | None


@cache
def build_models(*additional: type[BaseModel]) -> None:
    """Build the deferred models before FastAPI attaches route-specific field metadata."""
    for model in (
        ProductionCreate, StoryCreate, StoryPatch, BoardCreate, BoardPatch, BoardRemoval, BoardOrder, SelectionWrite,
        Selections, Me, ExternalPhotoDeclaration, Production, Story, Board, Timing,
        AssetVersion, Delivery, AssetDetail, Page[Production], Page[Story], Page[AssetVersion],
        *additional,
    ):
        model.model_config["defer_build"] = False
        model.model_rebuild(force=True)
