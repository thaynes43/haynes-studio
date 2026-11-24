"""The client-declared part of an agent board write. The API supplies the rest."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

DraftKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
SHA256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Label = Annotated[str, StringConstraints(min_length=1, max_length=200, pattern=r"^[^\x00-\x1f\x7f]+$")]


class DraftDeclaration(BaseModel):
    # Pydantic loads plugins on first use. Keep imports free of environment reads.
    model_config = ConfigDict(strict=True, extra="forbid", defer_build=True)

    board_key: DraftKey
    draft_sha256: SHA256
    model: Label
    session: Label


class RedraftDeclaration(DraftDeclaration):
    previous_draft_sha256: SHA256
    story_revision: Annotated[int, Field(ge=1, lt=2**63 - 1)]
