"""The asset library records of contract v1 (story 382): assets, immutable asset
versions, their validators, the library operations and the resolver.

- :mod:`.model`: read-only records, the kind and capability tables, and
  :func:`~.model.pin`, the one place that says what a version is.
- :mod:`.validate`: ``validate_asset`` and ``validate_asset_version`` with story
  404's contexts.
- :mod:`.library`: the library as a value; import, promotion and labels as pure
  functions; lookups, filters and the ``Facts`` story 404 takes.
- :mod:`.resolve`: every asset version a story names, to its record, pin and locator
  or a named problem; bytes are asked of an injected function.
- :mod:`.winter_menu`: the Winter Menu library from public files only.

Nothing here reads media, writes files, or calls a service or database; the store
adapter (story 379) and the API (story 409) own persistence.
"""

from __future__ import annotations

from haynes_studio.library.library import (
    EMPTY,
    Library,
    Outcome,
    VersionRequest,
    import_all,
    import_version,
    promote,
    set_labels,
)
from haynes_studio.library.model import (
    Asset,
    AssetVersion,
    BoardVoice,
    Content,
    Licence,
    Scope,
    Take,
    pin,
    version_document,
)
from haynes_studio.library.resolve import Resolution, Resolved, resolve
from haynes_studio.library.validate import validate_asset, validate_asset_version

__all__ = [
    "EMPTY", "Asset", "AssetVersion", "BoardVoice", "Content", "Library", "Licence", "Outcome",
    "Resolution", "Resolved", "Scope", "Take", "VersionRequest", "import_all", "import_version",
    "pin", "promote", "resolve", "set_labels", "validate_asset", "validate_asset_version",
    "version_document",
]
