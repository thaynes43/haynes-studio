"""What the private input import reads, from public records only (story 846).

:func:`plan_import` walks every row of the recovery map (story 425) and every line of
the E0 clip records (story 457) and groups them by SHA-256: each distinct hash is one
:class:`Item`, read at most once, from the first of its sources that answers with the
right bytes. Nothing here reads a file, the store or a service.

Sources, in the order they are tried (the rows' order, each source once):

- ``ledger_asset``: a ``wan_pvc`` locator, read with ``LedgerReader.fetch_asset`` (the
  stills, the set, the effects and the takes, delivered by ``poc/deliver.py``);
- ``job_output``: an E0 clip record's ``job_id``, read with
  ``VolumeReader.fetch_job_output`` (the doll loops, the set loop and the timed clips);
- ``upload``: a ``wan_upload`` locator, an E0 clip's start image or a timed clip's drive
  track, read with ``VolumeReader.fetch_upload`` (the keyframes, the doll-on-green start
  images and, **proposal**, the speech-to-video drive tracks, which ``poc/s2v.py``
  uploaded as ``studio-e0/<16 hex>.wav``: no record outside the volume keeps them).

Rows with no source are planned as not read, with the reason: the fire bed (never
delivered to the Wan volume), the ComfyUI renders (another service, out of this story's
scope; render ``set-left-s221`` has the set's bytes, so it is verified with the set),
and the whole-frame E0 clips (not motion clips). ``job_dir`` locators (an earlier
session's home) are never read.

Each item is published into the scope of every library version with that hash (the
version's own locator), or, when no version has it, into the production's folder
(**proposal**: the bytes are kept for a later regeneration).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from haynes_studio.adapters.wan_volume import UPLOAD_FOLDER, upload_name
from haynes_studio.library.library import Library

# Roles: the recovery map's (story 425) and the E0 lines' (story 457).
RECOVERY_ROLES = ("render", "still", "set", "sfx", "bed", "take", "keyframe")
E0_ROLES = ("doll_loop", "set_loop", "timed_clip", "start_image", "drive_track", "not_motion")
ROLES = RECOVERY_ROLES + E0_ROLES
E0_OUTCOMES = {"doll loop": "doll_loop", "set loop": "set_loop", "timed clip": "timed_clip",
               "not a motion clip": "not_motion"}

LEDGER_ASSET, JOB_OUTPUT, UPLOAD = "ledger_asset", "job_output", "upload"
MEDIA_TYPES = {".png": "image/png", ".wav": "audio/wav", ".mp4": "video/mp4"}
LIBRARY = "library"

# Why a row has no source (the report's ``reason`` for a row that is not read).
NEVER_DELIVERED = ("never_delivered: poc/deliver.py copied no bed to the Wan volume; its only "
                   "recorded copies were in earlier sessions' job folders, which this import does "
                   "not read. Its replacement is a new sound version (story 428, D54), never a "
                   "repointed old one")
NOT_READ_RENDER = ("not_read: a ComfyUI render; this import reads only the Wan volume (story 846 "
                   "scope); a layered build does not need it")
NOT_READ_WHOLE_FRAME = ("not_read: not a motion clip (a whole-frame E0 clip, story 427's, or the "
                        "whole-frame speech-to-video test); a layered build does not need it")
NO_LOCATOR = "not_read: no locator this import may read"


class PlanError(ValueError):
    """The public records disagree with each other or with the library (a media type,
    an upload path, a role); nothing is read."""


@dataclass(frozen=True, order=True)
class Source:
    kind: str  # ledger_asset, job_output or upload
    name: str  # the ledger ID, the job ID, or the upload's file name
    path: str | None = None  # the pod path the public records give (ledger assets, uploads)

    def to_document(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind}
        out["ledger_id" if self.kind == LEDGER_ASSET else
            "job_id" if self.kind == JOB_OUTPUT else "name"] = self.name
        if self.path is not None:
            out["path"] = self.path
        return out


@dataclass(frozen=True)
class Row:
    """One recovery map row or one E0 line (or one distinct E0 start image)."""

    key: str
    role: str
    sha256: str
    unread: str | None = None  # why this row adds no source, when it adds none


@dataclass(frozen=True)
class Item:
    """One distinct hash: its rows, where it may be read, and where it goes."""

    sha256: str
    media_type: str
    rows: tuple[str, ...]
    sources: tuple[Source, ...]
    scopes: tuple[str, ...]  # "library" or production IDs, sorted
    versions: tuple[str, ...]  # library versions whose content has this hash
    unread: str | None = None  # why there is no source, when there is none

    def to_document(self) -> dict[str, Any]:
        return {"sha256": self.sha256, "media_type": self.media_type, "rows": list(self.rows),
                "sources": [s.to_document() for s in self.sources], "scopes": list(self.scopes),
                "versions": list(self.versions), "unread": self.unread}


@dataclass(frozen=True)
class E0Line:
    """One line of an E0 clip record file, with what story 457 made of it."""

    file: str
    line: int
    outcome: str  # E0Row.outcome
    record: Mapping[str, Any] = field(repr=False)


@dataclass(frozen=True)
class Plan:
    production_id: str
    rows: tuple[Row, ...]
    items: tuple[Item, ...]

    def item(self, sha256: str) -> Item:
        return next(item for item in self.items if item.sha256 == sha256)

    def to_document(self) -> dict[str, Any]:
        return {"production_id": self.production_id,
                "rows": [{"key": r.key, "role": r.role, "sha256": r.sha256, "unread": r.unread}
                         for r in self.rows],
                "items": [item.to_document() for item in self.items]}


def _media_type(file: str, where: str) -> str:
    suffix = PurePosixPath(file).suffix
    if suffix not in MEDIA_TYPES:
        raise PlanError(f"{where}: no media type for {file!r}")
    return MEDIA_TYPES[suffix]


def _scope_of(locator: str) -> str:
    parts = locator.split("/")
    return LIBRARY if parts[0] == LIBRARY else parts[1]


def _recovery_rows(recovery_map: Mapping[str, Any]) -> Iterable[tuple[Row, str, list[Source]]]:
    for row in recovery_map["rows"]:
        key, role, sha = row["key"], row["role"], row["sha256"]
        if role not in RECOVERY_ROLES:
            raise PlanError(f"{key}: unknown role {role!r}")
        media = _media_type(row["file"], key)
        sources = []
        for locator in row["locators"]:
            if locator["kind"] == "wan_pvc":
                sources.append(Source(LEDGER_ASSET, locator["ledger_id"], locator["path"]))
            elif locator["kind"] == "wan_upload":
                name = upload_name(sha, PurePosixPath(row["file"]).suffix)
                if locator["path"] != UPLOAD_FOLDER + name:
                    raise PlanError(f"{key}: the upload path is not {UPLOAD_FOLDER}{name}")
                sources.append(Source(UPLOAD, name, locator["path"]))
        unread = None
        if not sources:
            unread = NEVER_DELIVERED if role == "bed" else NOT_READ_RENDER if role == "render" \
                else NO_LOCATOR
        yield Row(key, role, sha, unread), media, sources


def _e0_rows(lines: Sequence[E0Line]) -> Iterable[tuple[Row, str, list[Source]]]:
    images: dict[str, list[str]] = {}
    drives: dict[str, list[str]] = {}
    for line in lines:
        record = line.record
        if line.outcome not in E0_OUTCOMES:
            raise PlanError(f"{line.file}:{line.line}: unknown outcome {line.outcome!r}")
        role = E0_OUTCOMES[line.outcome]
        key = f"e0:{line.file}:{line.line}:{record['name']}"
        if role == "not_motion":
            yield Row(key, role, record["clip_sha256"], NOT_READ_WHOLE_FRAME), "video/mp4", []
            continue
        yield Row(key, role, record["clip_sha256"]), "video/mp4", \
            [Source(JOB_OUTPUT, record["job_id"])]
        label = record.get("image") or f"{record['name']}-start.png"
        images.setdefault(record["image_sha256"], []).append(label)
        if role == "timed_clip":  # poc/s2v.py uploaded the drive track beside the image
            drives.setdefault(record["audio_sha256"], []).append(f"{record['name']}-drive.wav")
    for role, found, suffix, media in (("start_image", images, ".png", "image/png"),
                                       ("drive_track", drives, ".wav", "audio/wav")):
        for sha, labels in found.items():
            name = upload_name(sha, suffix)
            yield Row(f"e0:{role}:{sorted(set(labels))[0]}", role, sha), media, \
                [Source(UPLOAD, name, UPLOAD_FOLDER + name)]


def plan_import(recovery_map: Mapping[str, Any], e0_lines: Sequence[E0Line], library: Library, *,
                production_id: str) -> Plan:
    """The rows and the distinct hashes to read, in the records' order."""
    rows: list[Row] = []
    keys: set[str] = set()
    found: dict[str, dict[str, Any]] = {}
    for row, media, sources in [*_recovery_rows(recovery_map), *_e0_rows(e0_lines)]:
        if row.key in keys:
            raise PlanError(f"{row.key}: two rows have this key")
        keys.add(row.key)
        rows.append(row)
        item = found.setdefault(row.sha256, {"media": media, "rows": [], "sources": [],
                                             "unread": []})
        if item["media"] != media:
            raise PlanError(f"{row.key}: {row.sha256[:16]} is {item['media']} in another row")
        item["rows"].append(row.key)
        item["sources"] += [s for s in sources if s not in item["sources"]]
        if row.unread and row.unread not in item["unread"]:
            item["unread"].append(row.unread)
    by_hash: dict[str, list[Any]] = {}
    for version in library.versions.values():
        if version.content is not None and version.content.sha256 in found:
            by_hash.setdefault(version.content.sha256, []).append(version)
    items = []
    for sha, item in found.items():
        versions = sorted(by_hash.get(sha, []), key=lambda v: v.id)
        for version in versions:
            if version.content.media_type != item["media"]:
                raise PlanError(f"{version.id}: {sha[:16]} is {version.content.media_type}, the "
                                f"records say {item['media']}")
        scopes = sorted({_scope_of(v.content.locator) for v in versions}) or [production_id]
        unread = None if item["sources"] else "; ".join(item["unread"]) or NO_LOCATOR
        items.append(Item(sha, item["media"], tuple(item["rows"]), tuple(item["sources"]),
                          tuple(scopes), tuple(v.id for v in versions), unread))
    return Plan(production_id, tuple(rows), tuple(items))


__all__ = ["E0Line", "E0_ROLES", "Item", "JOB_OUTPUT", "LEDGER_ASSET", "LIBRARY", "NEVER_DELIVERED",
           "NOT_READ_RENDER", "NOT_READ_WHOLE_FRAME", "Plan", "PlanError", "RECOVERY_ROLES",
           "ROLES", "Row", "Source", "UPLOAD", "plan_import"]
