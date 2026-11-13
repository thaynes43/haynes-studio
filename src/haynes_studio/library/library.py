"""The library as a value: assets and their versions, and the operations on them as
pure functions that return a new :class:`Library` (contract section 9).

- **Import** (:func:`import_version`): the same bytes (the same :func:`~.model.pin`)
  under the same ``source_key`` return the existing version; changed bytes make the
  next ``number`` on the same asset. Nothing is overwritten and no ID is reused.
- **Promotion** (:func:`promote`) is explicit and idempotent: a candidate becomes
  ``promoted``; a board photo gets a library version with ``origin: derived`` that
  points at it.
- **Labels** (:func:`set_labels`) are mutable metadata on the asset; no version's
  content, pin or ID changes.
- **Lookups**: by version ID (pinning), by asset, by source key, the pickers'
  "latest", the section 9 filters, capabilities and board voice takes, and the
  :class:`~haynes_studio.canonical.facts.Facts` story 404's validators take.

Nothing is ever deleted (D17). Nothing here reads files, bytes or services; the
caller owns persistence.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any

from haynes_studio.canonical.facts import Facts, PhotoVersionFacts, VoiceVersionFacts
from haynes_studio.canonical.ids import Minter, is_id
from haynes_studio.canonical.jsonvalues import normalize
from haynes_studio.canonical.model import Principal, to_document
from haynes_studio.errors import ContractError, Violation, blocking, pointer
from haynes_studio.library.model import (
    BOARD,
    CANDIDATE,
    PROMOTED,
    Asset,
    AssetVersion,
    Content,
    Licence,
    Scope,
    Take,
    content_fields,
    pin,
    version_document,
)
from haynes_studio.library.validate import validate_asset, validate_asset_version
from haynes_studio.jsonio import freeze

# Rule codes beyond the contract's rule index are proposals of story 382.
REF_UNKNOWN = "ref.unknown"  # story 404's proposal
REF_DUPLICATE = "ref.duplicate"  # story 404's proposal
IDEMPOTENCY_MISMATCH = "idempotency.mismatch"  # section 12, applied to re-imports
CONFLICT_REVISION = "conflict.revision"  # section 12, applied to label edits
NOT_PROMOTABLE = "asset.not_promotable"  # proposal
SOURCE_KEY_REQUIRED = "asset.source_key_required"  # proposal

PROMOTE_PREFIX = "promote:"  # source key of a board photo's library version (proposal)


def _error(rule: str, path: str, message: str, source: str = "<library>",
           status: str = "invalid") -> ContractError:
    return ContractError(source, [Violation(rule, path, message, status)])


@dataclass(frozen=True)
class Library:
    """Assets and versions by ID. Build one with :meth:`build` (which checks that the
    records fit together) or :data:`EMPTY`; every operation returns a new value. A
    library may hold a slice of the records (version 2 without version 1), so a new
    version takes the highest number plus one, and numbers are never reused."""

    assets: Mapping[str, Asset] = field(default_factory=lambda: MappingProxyType({}))
    versions: Mapping[str, AssetVersion] = field(default_factory=lambda: MappingProxyType({}))

    @classmethod
    def build(cls, assets: Iterable[Asset], versions: Iterable[AssetVersion]) -> Library:
        assets, versions = list(assets), list(versions)
        problems = []
        problems += _repeated(((pointer("assets", i), a.id) for i, a in enumerate(assets)),
                              "asset ID")
        problems += _repeated(((pointer("versions", i), v.id) for i, v in enumerate(versions)),
                              "version ID")
        by_asset = {a.id: a for a in assets}
        numbers: dict[str, list[int]] = {}
        keys: dict[str, str] = {}
        for i, version in enumerate(versions):
            at = pointer("versions", i)
            asset = by_asset.get(version.asset_id)
            if asset is None:
                problems.append(Violation(REF_UNKNOWN, at + "/asset_id", "no such asset"))
                continue
            if asset.kind != version.kind:
                problems.append(Violation(
                    "schema.invalid", at + "/kind",
                    f"the asset is a {asset.kind}, the version a {version.kind}"))
            numbers.setdefault(asset.id, []).append(version.number)
            key = version.source_key
            if key is not None and keys.setdefault(key, asset.id) != asset.id:
                problems.append(Violation(REF_DUPLICATE, at + "/provenance/source_key",
                                          f"source key {key!r} already names asset {keys[key]}"))
        for asset_id, seen in numbers.items():
            if len(set(seen)) != len(seen):
                problems.append(Violation(
                    REF_DUPLICATE, pointer("assets", asset_id),
                    f"asset {asset_id} has repeated version numbers {sorted(seen)}"))
        if problems:
            raise ContractError("<library>", problems)
        return cls(assets=MappingProxyType(by_asset),
                   versions=MappingProxyType({v.id: v for v in versions}))

    @classmethod
    def from_version_documents(cls, documents: Iterable[Mapping[str, Any]]) -> Library:
        """A library from ``studio.asset-version/v1`` documents alone (each asset from its
        versions' joined fields; they must agree). Every document must validate."""
        assets: dict[str, Asset] = {}
        versions = []
        for i, document in enumerate(documents):
            problems = blocking(validate_asset_version(document))
            if problems:
                raise ContractError(f"<version {i}>", problems)
            asset = Asset.from_version_document(document)
            if assets.setdefault(asset.id, asset) != asset:
                raise _error("schema.invalid", pointer(i, "asset_id"),
                             "versions of one asset disagree on its kind, name, scope, labels "
                             "or attributes")
            versions.append(AssetVersion.from_document(document))
        return cls.build(assets.values(), versions)

    # Lookups --------------------------------------------------------------------------

    def version(self, version_id: str) -> AssetVersion:
        """The version a pinned ID names; :class:`KeyError` if there is none."""
        return self.versions[version_id]

    def get(self, version_id: str) -> AssetVersion | None:
        return self.versions.get(version_id)

    def asset(self, asset_id: str) -> Asset:
        return self.assets[asset_id]

    def asset_of(self, version_id: str) -> Asset:
        return self.assets[self.versions[version_id].asset_id]

    def versions_of(self, asset_id: str) -> tuple[AssetVersion, ...]:
        """Every version of an asset, by number."""
        return tuple(sorted((v for v in self.versions.values() if v.asset_id == asset_id),
                            key=lambda v: v.number))

    def by_source_key(self, source_key: str) -> Asset | None:
        for version in self.versions.values():
            if version.source_key == source_key:
                return self.assets[version.asset_id]
        return None

    def latest(self, asset_id: str, *, include_candidates: bool = False) -> AssetVersion | None:
        """The highest-numbered visible version: for pickers only. Boards and snapshots
        name version IDs, never "latest" (section 9)."""
        visible = [v for v in self.versions_of(asset_id)
                   if include_candidates or v.state != CANDIDATE]
        return visible[-1] if visible else None

    def search(self, *, kind: str | None = None, labels: Iterable[str] = (),
               production_id: str | None = None, board: Mapping[str, Any] | None = None,
               include_candidates: bool = False) -> tuple[AssetVersion, ...]:
        """The section 9 filters, combined: kind; every label in ``labels``; a
        production (its own versions and the global library's); a board document (the
        versions it references, D32 and D34). Candidates stay hidden unless asked for.
        Sorted by asset, then number."""
        from haynes_studio.library.resolve import board_references

        wanted = set(labels)
        named = None if board is None else {ref.version_id for ref in board_references(board, "")}
        out = []
        for version in self.versions.values():
            asset = self.assets[version.asset_id]
            if version.state == CANDIDATE and not include_candidates:
                continue
            if kind is not None and version.kind != kind:
                continue
            if not wanted <= set(asset.labels):
                continue
            if production_id is not None and asset.scope.production_id not in (production_id, None):
                continue
            if named is not None and version.id not in named:
                continue
            out.append(version)
        return tuple(sorted(out, key=lambda v: (v.asset_id, v.number)))

    def capabilities(self, version_id: str) -> frozenset[str]:
        return frozenset(self.versions[version_id].capabilities)

    def has_capability(self, version_id: str, capability: str) -> bool:
        """Does this version have this capability? False for an unknown version."""
        version = self.versions.get(version_id)
        return version is not None and capability in version.capabilities

    def takes(self, version_id: str) -> tuple[Take, ...]:
        """A board voice version's takes, in line order (VOICE-2)."""
        version = self.versions[version_id]
        if version.voice is None:
            raise _error("schema.invalid", "/kind",
                         f"{version_id} is a {version.kind}, not a board_voice")
        return version.voice.takes

    def pin(self, version_id: str) -> str:
        version = self.versions[version_id]
        return pin(version, self.assets[version.asset_id])

    def document(self, version_id: str) -> dict[str, Any]:
        """The ``studio.asset-version/v1`` document a read returns."""
        version = self.versions[version_id]
        return version_document(version, self.assets[version.asset_id])

    def documents(self) -> list[dict[str, Any]]:
        return [self.document(v.id) for v in sorted(self.versions.values(),
                                                     key=lambda v: (v.asset_id, v.number))]

    def facts(self, story: Mapping[str, Any] | None = None) -> Facts:
        """What story 404's validators and derived values take from the library: each
        version's capabilities, each board voice's measured takes and each photo.

        With ``story`` (boards embedded), a board's current voice version is stale
        (``matches_board: false``, so the board is untimed and ``queue_run`` reports
        ``voice.stale``) unless its takes are the board's lines in order (line ID,
        speaker, NFC text), each from the voice the story casts for that speaker, with
        the board's lead and gaps (VOICE-3, VOICE-4). Without a story every voice is
        taken as current. Photos are always current here: a photo's inputs signature is
        story 407's."""
        current = {} if story is None else _voice_currency(self, story)
        voices, photos = [], []
        for version in self.versions.values():
            if version.voice is not None:
                voices.append(VoiceVersionFacts(id=version.id, takes_ms=version.voice.takes_ms,
                                                matches_board=current.get(version.id, True)))
            if version.kind == "photo":
                photos.append(PhotoVersionFacts(id=version.id))
        return Facts.build(voices=voices, photos=photos,
                           capabilities={v.id: v.capabilities for v in self.versions.values()})

    # Internal -------------------------------------------------------------------------

    def _with(self, *, asset: Asset | None = None,
              version: AssetVersion | None = None) -> Library:
        assets, versions = dict(self.assets), dict(self.versions)
        if asset is not None:
            assets[asset.id] = asset
        if version is not None:
            versions[version.id] = version
        return Library(assets=MappingProxyType(assets), versions=MappingProxyType(versions))


EMPTY = Library()


def _voice_currency(library: Library, story: Mapping[str, Any]) -> dict[str, bool]:
    """Board voice version ID to whether it still matches every board naming it."""
    cast = {member.get("slot"): member.get("voice_version_id")
            for member in story.get("cast") or [] if isinstance(member, Mapping)}
    cast["narrator"] = story.get("narrator_voice_version_id")
    out: dict[str, bool] = {}
    for board in story.get("boards") or []:
        if not isinstance(board, Mapping):
            continue
        version_id = (board.get("voice") or {}).get("current_version_id")
        version = library.get(version_id) if isinstance(version_id, str) else None
        if version is None or version.voice is None:
            continue
        voice, lines = version.voice, board.get("lines") or []
        same = (len(voice.takes) == len(lines)
                and voice.lead_ms == (board.get("timing") or {}).get("lead_ms")
                and list(voice.gaps_ms) == [line.get("gap_before_ms") for line in lines[1:]]
                and all(take.line_id == line.get("id") and take.speaker == line.get("speaker")
                        and unicodedata.normalize("NFC", take.text)
                        == unicodedata.normalize("NFC", line.get("text") or "")
                        and take.voice_version_id == cast.get(line.get("speaker"))
                        for take, line in zip(voice.takes, lines)))
        out[version_id] = out.get(version_id, True) and same
    return out


def _repeated(items: Iterable[tuple[str, str]], what: str) -> list[Violation]:
    seen: dict[str, str] = {}
    out = []
    for path, value in items:
        if value in seen:
            out.append(Violation(REF_DUPLICATE, path,
                                 f"{what} {value!r} is already used at {seen[value]}"))
        seen.setdefault(value, path)
    return out


# Import ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class VersionRequest:
    """One version to import. The asset fields (``kind`` to ``attributes``) are used
    only when the source key is new; a known source key's asset keeps its own, and
    its labels change only through :func:`set_labels`. ``version_id`` and
    ``asset_id`` are IDs another record already uses (the legacy import's
    ``story_records``); otherwise they are minted. ``provenance`` must hold a
    ``source_key``; ``created_by`` and ``created_at`` come from the caller."""

    kind: str
    name: str
    scope: Scope
    capabilities: tuple[str, ...]
    content: Content | None
    provenance: Mapping[str, Any]
    licence: Licence
    state: str = PROMOTED
    labels: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    legacy: Mapping[str, Any] | None = None
    voice: Any = None  # BoardVoice
    motion: Mapping[str, Any] | None = None  # a motion version's clip record (story 457)
    version_id: str | None = None
    asset_id: str | None = None


@dataclass(frozen=True)
class Outcome:
    library: Library
    version: AssetVersion
    created: bool  # False: the existing version was returned (idempotent)


def import_version(library: Library, request: VersionRequest, *, by: Principal, now: str,
                   minter: Minter | None = None) -> Outcome:
    """Import one version by source key (section 9). Raises :class:`ContractError` for
    a request without a source key, a source key that names an asset of another kind
    or other attributes, the same bytes with other immutable fields
    (``idempotency.mismatch``), a given ID already in use (``ref.duplicate``), or a
    version that breaks a ``studio.asset-version/v1`` rule."""
    minter = minter or Minter()
    source_key = request.provenance.get("source_key")
    if not source_key:
        raise _error(SOURCE_KEY_REQUIRED, "/provenance/source_key",
                     "an import is keyed by its source key (section 9); other versions come "
                     "from jobs and uploads")
    provenance = normalize({**request.provenance, "created_by": to_document(by),
                            "created_at": now})
    asset = library.by_source_key(source_key)
    if asset is None:
        asset_id = _fresh(library, request.asset_id, "ast", minter, "/asset_id")
        asset = Asset(id=asset_id, kind=request.kind, name=request.name, scope=request.scope,
                      labels=tuple(request.labels),
                      attributes=freeze(normalize(dict(request.attributes))),
                      revision=1, created_at=now, updated_at=now, created_by=by)
        number = 1
    else:
        _same_asset(asset, request)
        if request.asset_id is not None and request.asset_id != asset.id:
            raise _error(IDEMPOTENCY_MISMATCH, "/asset_id",
                         f"source key {source_key!r} names asset {asset.id}")
        numbers = sorted(v.number for v in library.versions_of(asset.id))
        if numbers != list(range(1, len(numbers) + 1)):
            raise _error(REF_UNKNOWN, "/asset_id",
                         f"the library holds versions {numbers} of {asset.id}, a slice; import "
                         "into the whole library so no number is reused")
        number = len(numbers) + 1
    candidate = AssetVersion(
        id=request.version_id or "asv_00000000000000000000000000", asset_id=asset.id,
        number=number, kind=request.kind, state=request.state,
        capabilities=tuple(request.capabilities), content=request.content,
        provenance=freeze(provenance), licence=request.licence,
        legacy=None if request.legacy is None else freeze(normalize(request.legacy)),
        voice=request.voice,
        motion=None if request.motion is None else freeze(normalize(dict(request.motion))))
    wanted = pin(candidate, asset)
    for existing in library.versions_of(asset.id):
        if pin(existing, asset) != wanted:
            continue
        if not _same_content(existing, candidate):
            raise _error(IDEMPOTENCY_MISMATCH, pointer("versions", existing.id),
                         f"{existing.id} already holds these bytes under {source_key!r} with "
                         "other capabilities, provenance or takes; versions never change (D15)")
        if request.version_id is not None and request.version_id != existing.id:
            raise _error(IDEMPOTENCY_MISMATCH, "/version_id",
                         f"these bytes were imported as {existing.id}; an ID never names other "
                         "content")
        return Outcome(library=library, version=existing, created=False)
    version_id = _fresh(library, request.version_id, "asv", minter, "/version_id")
    version = replace(candidate, id=version_id)
    _check(version, asset)
    return Outcome(library=library._with(asset=asset, version=version), version=version,
                   created=True)


MEASURED = ("bytes", "width", "height")  # what the store measures from the bytes


def _same_content(existing: AssetVersion, candidate: AssetVersion) -> bool:
    """The immutable fields agree. A measurement the existing version does not record
    (``bytes: null`` or no ``width`` and ``height``: a legacy import from public
    evidence) matches any value for the same hash; the existing version is returned
    unchanged."""
    ours, theirs = content_fields(existing), content_fields(candidate)
    if ours["content"] is not None and theirs["content"] is not None:
        for name in MEASURED:
            if ours["content"].get(name) is None:
                ours["content"].pop(name, None)
                theirs["content"].pop(name, None)
    return ours == theirs


def _fresh(library: Library, given: str | None, prefix: str, minter: Minter, path: str) -> str:
    if given is None:
        return minter.mint(prefix)
    if not is_id(given, prefix):
        raise _error("id.malformed", path, f"must be a {prefix}_ ID")
    if given in library.assets or given in library.versions:
        raise _error(REF_DUPLICATE, path, f"{given} is already in the library")
    return given


def _same_asset(asset: Asset, request: VersionRequest) -> None:
    if asset.kind != request.kind:
        raise _error(IDEMPOTENCY_MISMATCH, "/kind", f"the source key names a {asset.kind} asset")
    if asset.scope != request.scope:
        raise _error(IDEMPOTENCY_MISMATCH, "/scope",
                     "the source key names an asset in another scope")
    if dict(asset.attributes) != normalize(dict(request.attributes)):
        raise _error(IDEMPOTENCY_MISMATCH, "/attributes",
                     "the source key names an asset with other attributes")


def _check(version: AssetVersion, asset: Asset) -> None:
    problems = blocking(validate_asset_version(version_document(version, asset), context="write"))
    if problems:
        raise ContractError(version.id, problems)


# Promotion and labels ---------------------------------------------------------------------


def promote(library: Library, version_id: str, *, by: Principal, now: str,
            minter: Minter | None = None) -> Outcome:
    """Explicit and idempotent promotion (section 9). A promoted version is returned
    unchanged; a candidate becomes promoted (its content, pin and ID stay); a board
    photo gets one library version with ``origin: derived`` that points at it, under
    the source key ``promote:<board version ID>`` (proposal), so a second promotion
    returns the same version. A board voice is board-scoped only
    (``asset.not_promotable``, proposal)."""
    version = library.versions.get(version_id)
    if version is None:
        raise _error(REF_UNKNOWN, "/id", f"no asset version {version_id}")
    if version.state == PROMOTED:
        return Outcome(library=library, version=version, created=False)
    if version.state == CANDIDATE:
        promoted = version.with_state(PROMOTED)
        return Outcome(library=library._with(version=promoted), version=promoted, created=True)
    if version.kind != "photo":
        raise _error(NOT_PROMOTABLE, "/kind", f"a {version.kind} stays on its board")
    board_asset = library.asset_of(version_id)
    generator = version.provenance.get("generator") or {}
    request = VersionRequest(
        kind="photo", name=board_asset.name, scope=Scope(board_asset.scope.production_id),
        capabilities=version.capabilities, content=version.content, licence=version.licence,
        provenance={"origin": "derived",
                    "generator": {"role": generator.get("role", "image"),
                                  "source_asset_version_ids": [version.id]},
                    "external": version.provenance.get("external"),
                    "source_key": PROMOTE_PREFIX + version.id},
        state=PROMOTED)
    return import_version(library, request, by=by, now=now, minter=minter)


def set_labels(library: Library, asset_id: str, labels: Iterable[str], *, now: str,
               revision: int | None = None) -> Library:
    """Replace an asset's labels (P-21). ``revision``, when given, must be the asset's
    current one (``conflict.revision``). No version changes."""
    asset = library.assets.get(asset_id)
    if asset is None:
        raise _error(REF_UNKNOWN, "/id", f"no asset {asset_id}")
    if isinstance(labels, str):
        raise _error("schema.invalid", "/labels", "labels are a list of strings, not one string")
    if revision is not None and revision != asset.revision:
        raise _error(CONFLICT_REVISION, "/revision",
                     f"the asset is at revision {asset.revision}, not {revision}",
                     status="conflict")
    changed = replace(asset, labels=tuple(labels), revision=asset.revision + 1, updated_at=now)
    problems = blocking(validate_asset(changed.to_document(), context="write"))
    if problems:
        raise ContractError(asset_id, problems)
    return library._with(asset=changed)


def import_all(library: Library, requests: Iterable[VersionRequest], *, by: Principal, now: str,
               minter: Minter | None = None) -> tuple[Library, list[Outcome]]:
    """:func:`import_version` for each request in order."""
    minter = minter or Minter()
    outcomes = []
    for request in requests:
        outcome = import_version(library, request, by=by, now=now, minter=minter)
        library = outcome.library
        outcomes.append(outcome)
    return library, outcomes


Exists = Callable[[str, str], bool]
"""``exists(locator, sha256)``: whether the store holds those bytes (story 379)."""

__all__ = [
    "BOARD", "CONFLICT_REVISION", "EMPTY", "IDEMPOTENCY_MISMATCH", "NOT_PROMOTABLE",
    "PROMOTE_PREFIX", "REF_DUPLICATE", "REF_UNKNOWN", "SOURCE_KEY_REQUIRED", "Exists", "Library",
    "Outcome", "VersionRequest", "import_all", "import_version", "promote", "set_labels",
]
