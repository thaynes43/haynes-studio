"""The D39 store layout (contract section 8): where a blob or a stage record lives.

```
<root>/library/sha256/<h[0:2]>/<h>.<ext>
<root>/productions/<production_id>/sha256/<h[0:2]>/<h>.<ext>
<root>/productions/<production_id>/records/<run_id>/<stage>.json   (local adapter only)
<root>/.staging/<random>.part
<root>/.probe/
```

A **locator** is the relative path of a blob, exactly as above. Anything else (an
absolute path, ``..``, a backslash, a doubled or trailing slash, upper-case hex, a hash
folder that is not the hash's first two characters, an extension outside the list, a
records path) fails ``store.locator_invalid``. Pure functions: nothing here touches
the file system.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from haynes_studio.canonical.ids import ULID_PATTERN, is_id
from haynes_studio.store.errors import (
    ID_MALFORMED,
    ID_TYPE_MISMATCH,
    LOCATOR_INVALID,
    MEDIA_TYPE_UNSUPPORTED,
    RECORD_INVALID,
    StoreError,
)

LIBRARY = "library"
PRODUCTIONS = "productions"
SHA256_DIR = "sha256"
RECORDS = "records"
STAGING = ".staging"
PROBE = ".probe"
PART = ".part"
RECORD_EXT = ".json"
# Files another writer keeps at the store root (proposal, story 860): the Wan clip
# client's one journal of the store (``build.live.journal_path``, story 851) and the lock
# file the client keeps beside it (``adapters.wan.FileJournal``). The store only reports
# them; it never opens, locks, moves or rewrites them. The build imports the store, so
# the store cannot import those names; a test holds them equal.
WAN_JOURNAL = "wan-journal.jsonl"
WAN_JOURNAL_LOCK = WAN_JOURNAL + ".lock"
ROOT_FILES = (WAN_JOURNAL, WAN_JOURNAL_LOCK)

# Contract section 8: "ext is one of mp4, wav, png, jpg, webp, json, chosen from the
# validated media type". The media type is the caller's, already validated (for an
# upload, P-16); the store does not sniff bytes.
EXTENSIONS = {
    "video/mp4": "mp4",
    "audio/wav": "wav",
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "application/json": "json",
}
MEDIA_TYPES = {ext: media_type for media_type, ext in EXTENSIONS.items()}

_HEX64 = re.compile(r"[0-9a-f]{64}")
_EXT = "|".join(sorted(MEDIA_TYPES))
_LOCATOR = re.compile(
    rf"(?:{LIBRARY}|{PRODUCTIONS}/(?P<production>prd_{ULID_PATTERN}))"
    rf"/{SHA256_DIR}/(?P<fan>[0-9a-f]{{2}})/(?P<sha256>(?P=fan)[0-9a-f]{{62}})\.(?P<ext>{_EXT})")
# Proposal: a stage name is a path component, so it is a short, plain word (letters,
# digits, "_" and "-"; no dot, so never "." or ".."); stories 380, 381 and 406 name
# their stages (for example "voice", "segment-brd_<ULID>", "mix", "master").
_STAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
_RECORD = re.compile(
    rf"{PRODUCTIONS}/(?P<production>prd_{ULID_PATTERN})/{RECORDS}/(?P<run>run_{ULID_PATTERN})"
    rf"/(?P<stage>{_STAGE.pattern}){re.escape(RECORD_EXT)}")


def is_sha256(value: object) -> bool:
    """A lower-case hex SHA-256 (contract section 2: a field named ``sha256``)."""
    return isinstance(value, str) and _HEX64.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class Locator:
    """A parsed, valid locator. ``production_id`` is ``None`` for the library."""

    text: str
    production_id: str | None
    sha256: str
    ext: str

    @property
    def media_type(self) -> str:
        return MEDIA_TYPES[self.ext]

    @property
    def scope(self) -> str:
        return self.production_id or LIBRARY

    def __str__(self) -> str:
        return self.text


def parse_locator(locator: object) -> Locator:
    """The parsed locator, or ``store.locator_invalid``. The whole string must match
    the layout; nothing is normalized first (``a/./b`` and ``a//b`` are refused)."""
    if not isinstance(locator, str):
        raise StoreError(LOCATOR_INVALID, f"a locator is a relative path string, got {type(locator).__name__}")
    match = _LOCATOR.fullmatch(locator)
    if match is None:
        raise StoreError(LOCATOR_INVALID, _why(locator), locator=locator)
    return Locator(text=locator, production_id=match["production"], sha256=match["sha256"],
                   ext=match["ext"])


def _why(locator: str) -> str:
    """A short reason for a refused locator (the message only; the rule is one)."""
    if locator.startswith("/") or (len(locator) > 1 and locator[1] == ":"):
        return "an absolute path is not a locator"
    if "\\" in locator or "\x00" in locator:
        return "a locator has no backslash or NUL"
    parts = locator.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return "a locator has no empty, '.' or '..' component"
    return ("not a blob path of the D39 layout: library/sha256/<h[0:2]>/<h>.<ext> or "
            "productions/<production_id>/sha256/<h[0:2]>/<h>.<ext>")


def is_locator(locator: object) -> bool:
    try:
        parse_locator(locator)
    except StoreError:
        return False
    return True


def check_production_id(value: object) -> str:
    """``value`` if it is a ``prd_`` ID; else ``id.malformed`` or ``id.type_mismatch``."""
    return _check_id(value, "prd")


def check_run_id(value: object) -> str:
    return _check_id(value, "run")


def _check_id(value: object, prefix: str) -> str:
    if not is_id(value):
        raise StoreError(ID_MALFORMED, f"expected a {prefix}_ ID, got {value!r}")
    if not is_id(value, prefix):
        raise StoreError(ID_TYPE_MISMATCH, f"expected a {prefix}_ ID, got {value!r}")
    return value  # type: ignore[return-value]


def check_stage(stage: object) -> str:
    if not isinstance(stage, str) or _STAGE.fullmatch(stage) is None:
        raise StoreError(RECORD_INVALID,
                         f"a stage name is 1 to 128 of A-Z, a-z, 0-9, '_' and '-', got {stage!r}")
    return stage


def extension(media_type: object) -> str:
    """The file extension for a media type, or ``store.media_type_unsupported``."""
    ext = EXTENSIONS.get(media_type) if isinstance(media_type, str) else None
    if ext is None:
        raise StoreError(MEDIA_TYPE_UNSUPPORTED,
                         f"media type {media_type!r} is not one of {', '.join(EXTENSIONS)}")
    return ext


def scope_prefix(scope: object) -> str:
    """``library`` or ``productions/<production_id>`` for a scope (``"library"`` or a
    production ID)."""
    if scope == LIBRARY:
        return LIBRARY
    return f"{PRODUCTIONS}/{check_production_id(scope)}"


def blob_locator(scope: object, sha256: object, media_type: object) -> str:
    """The locator of a blob with this hash and media type in ``scope``."""
    if not is_sha256(sha256):
        raise StoreError(LOCATOR_INVALID, f"sha256 must be 64 lower-case hex digits, got {sha256!r}")
    text = f"{scope_prefix(scope)}/{SHA256_DIR}/{sha256[:2]}/{sha256}.{extension(media_type)}"  # type: ignore[index]
    return parse_locator(text).text


def record_path(production_id: object, run_id: object, stage: object) -> str:
    """The relative path of a stage's completion record (local adapter only). Not a
    locator: records are addressed by production, run and stage."""
    return (f"{PRODUCTIONS}/{check_production_id(production_id)}/{RECORDS}/"
            f"{check_run_id(run_id)}/{check_stage(stage)}{RECORD_EXT}")


def parse_record_path(path: str) -> tuple[str, str, str] | None:
    """``(production_id, run_id, stage)`` for a record path of the layout, else ``None``."""
    match = _RECORD.fullmatch(path)
    return None if match is None else (match["production"], match["run"], match["stage"])
