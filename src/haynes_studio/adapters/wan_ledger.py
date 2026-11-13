"""The legacy delivery ledger behind the Wan API (``ai/deploy/wan-video``, container
``api``, PVC ``ai/wan-video``), **read-only**.

Contract section 8: product code never writes the Wan volume or its ledger. This
reader has no write, publish, link, rename or delete path, and its three in-pod
snippets read files and one HTTP route only:

- :meth:`LedgerReader.get` is ``poc/deliver.py``'s read-back: ``GET
  /videos/<ledger_id>`` on the API (snippet ``wan_ledger_read.py``, 30 s).
- :meth:`LedgerReader.list` reads ``/workspace/jobs/*.json`` and keeps the
  ``edited_production`` ledgers (``wan_ledger_list.py``, 60 s; the API has no list
  route). A ledger it cannot parse is reported by file name, never fatal.
- :meth:`LedgerReader.find` lists, then matches a SHA-256 against each ledger's output
  and assets.
- :meth:`LedgerReader.fetch_asset` prints one asset's bytes after checking, in the pod,
  that the ledger lists it, that its path is under ``/workspace/output/productions/``
  and that its SHA-256 matches; the client checks the hash again
  (``wan_ledger_fetch.py``, 180 s, 64 MiB).

    reader = LedgerReader(runner)
    r4 = reader.get("032f1bb230794aaf84dce9001181a7d7")
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from haynes_studio.adapters import pinned
from haynes_studio.adapters.errors import RESPONSE_INVALID, AdapterError, RequestInvalid
from haynes_studio.adapters.runner import WAN_API, Command, ExecTarget, Runner, run_checked
from haynes_studio.jsonio import freeze, parse_strict

ADAPTER = "legacy_wan_ledger"  # the delivery adapter name in contract section 8
READ_SNIPPET = "wan_ledger_read.py"
LIST_SNIPPET = "wan_ledger_list.py"
FETCH_SNIPPET = "wan_ledger_fetch.py"
READ_TIMEOUT_S = 30  # poc/deliver.py read-back
LIST_TIMEOUT_S = 60  # proposal
FETCH_TIMEOUT_S = 180  # poc/deliver.py's per-file copy timeout
MAX_ASSET_BYTES = 64 * 1024 * 1024  # the largest Winter Menu delivery is 33 541 086 bytes
MAX_ANSWER_BYTES = 16 * 1024 * 1024
LEDGER_ID = re.compile(r"[0-9a-f]{32}")  # the Wan API's JOB_ID
SHA256 = re.compile(r"[0-9a-f]{64}")
KIND = "edited_production"
REQUIRED = ("id", "kind", "state", "output", "title", "story", "assets", "bytes", "sha256",
            "created_at", "finished_at", "telemetry", "preset", "provenance")


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


@dataclass(frozen=True)
class LedgerAsset:
    path: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class LedgerRecord:
    """One ``edited_production`` ledger as the API serves it. ``document`` is the whole
    ledger, read-only."""

    id: str
    title: str
    story: str
    state: str
    output: str
    bytes: int
    sha256: str
    created_at: float
    finished_at: float
    preset: str
    assets: tuple[LedgerAsset, ...]
    document: Any = field(repr=False, compare=False)

    def asset(self, sha256: str) -> LedgerAsset | None:
        return next((a for a in self.assets if a.sha256 == sha256), None)


@dataclass(frozen=True)
class LedgerSummary:
    id: str
    title: str | None
    state: str | None
    output: str | None
    bytes: int | None
    sha256: str | None
    created_at: float | None
    asset_sha256: tuple[str, ...]

    def holds(self, sha256: str) -> bool:
        return self.sha256 == sha256 or sha256 in self.asset_sha256


@dataclass(frozen=True)
class LedgerListing:
    ledgers: tuple[LedgerSummary, ...]
    # Ledger files the pod could not parse, and listed entries with a malformed field
    # (by file name, or "entry <n>" when even the ID is unusable).
    unreadable: tuple[str, ...]


@dataclass(frozen=True)
class AssetBytes:
    ledger_id: str
    path: str
    sha256: str
    data: bytes = field(repr=False)


def record_from_document(document: Any, label: str = "wan_ledger.get") -> LedgerRecord:
    """Check a ledger the way ``poc/deliver.py`` ``check_ledger`` does (the fields the
    Wan API relies on) and type it. Messages name fields, never values."""
    def bad(message):
        return AdapterError(RESPONSE_INVALID, label, message)
    if not isinstance(document, dict):
        raise bad("ledger is not an object")
    missing = [k for k in REQUIRED if k not in document]
    if missing:
        raise bad("ledger lacks " + ", ".join(missing))
    if not isinstance(document["id"], str) or not LEDGER_ID.fullmatch(document["id"]):
        raise bad("ledger id is not 32 hex digits")
    if document["kind"] != KIND:
        raise bad(f"ledger kind is not {KIND}")
    if document["state"] != "succeeded":
        raise bad("ledger state is not succeeded")
    output = document["output"]
    if not isinstance(output, str) or not output.endswith(".mp4") or output.startswith("/") \
            or ".." in output:
        raise bad("ledger output is not a relative .mp4 path")
    if not _is_count(document["bytes"]) or not isinstance(document["sha256"], str) \
            or not SHA256.fullmatch(document["sha256"]):
        raise bad("ledger bytes or sha256 is malformed")
    times = (document["created_at"], document["finished_at"])
    if not all(isinstance(t, int | float) and not isinstance(t, bool) for t in times):
        raise bad("ledger created_at or finished_at is not a number")
    assets = []
    if not isinstance(document["assets"], list):
        raise bad("ledger assets is not a list")
    for i, asset in enumerate(document["assets"]):
        if not isinstance(asset, dict) or not isinstance(asset.get("path"), str) \
                or not _is_count(asset.get("bytes")) or not isinstance(asset.get("sha256"), str) \
                or not SHA256.fullmatch(asset["sha256"]):
            raise bad(f"ledger asset {i} lacks path, bytes or sha256")
        assets.append(LedgerAsset(asset["path"], asset["bytes"], asset["sha256"]))
    for name in ("title", "story", "preset"):
        if not isinstance(document[name], str):
            raise bad(f"ledger {name} is not text")
    return LedgerRecord(document["id"], document["title"], document["story"], document["state"],
                        output, document["bytes"], document["sha256"], float(times[0]),
                        float(times[1]), document["preset"], tuple(assets), freeze(document))


def _json_answer(stdout: bytes, label: str) -> Any:
    if len(stdout) > MAX_ANSWER_BYTES:
        raise AdapterError(RESPONSE_INVALID, label, "answer is too long")
    try:
        return parse_strict(stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise AdapterError(RESPONSE_INVALID, label, "answer is not JSON") from None


def _ledger_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not LEDGER_ID.fullmatch(value):
        raise RequestInvalid(label, "ledger_id must be 32 lower-case hex digits")
    return value


def _sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise RequestInvalid(label, "sha256 must be 64 lower-case hex digits")
    return value


class LedgerReader:
    """Reads the legacy ledger. There is deliberately no method that writes."""

    def __init__(self, runner: Runner, *, target: ExecTarget = WAN_API,
                 read_snippet: pinned.PinnedInput | None = None,
                 list_snippet: pinned.PinnedInput | None = None,
                 fetch_snippet: pinned.PinnedInput | None = None):
        def take(item, name):
            return pinned.check(item, name) if item else pinned.load(name)
        self.runner = runner
        self.target = target
        self.read_snippet = take(read_snippet, READ_SNIPPET)
        self.list_snippet = take(list_snippet, LIST_SNIPPET)
        self.fetch_snippet = take(fetch_snippet, FETCH_SNIPPET)

    def get_command(self, ledger_id: str) -> Command:
        label = "wan_ledger.get"
        pinned.check(self.read_snippet, READ_SNIPPET)
        return Command(label, self.target.argv(self.read_snippet.text, _ledger_id(ledger_id, label)),
                       b"", READ_TIMEOUT_S, self.target.describe())

    def get(self, ledger_id: str) -> LedgerRecord:
        command = self.get_command(ledger_id)
        record = record_from_document(_json_answer(run_checked(self.runner, command).stdout,
                                                   command.label))
        if record.id != ledger_id:
            raise AdapterError(RESPONSE_INVALID, command.label, "the API answered with another ledger")
        return record

    def list_command(self) -> Command:
        pinned.check(self.list_snippet, LIST_SNIPPET)
        return Command("wan_ledger.list", self.target.argv(self.list_snippet.text), b"",
                       LIST_TIMEOUT_S, self.target.describe())

    def list(self) -> LedgerListing:
        command = self.list_command()
        answer = _json_answer(run_checked(self.runner, command).stdout, command.label)
        if not isinstance(answer, list):
            raise AdapterError(RESPONSE_INVALID, command.label, "answer is not a list")
        ledgers, unreadable = [], []
        for i, entry in enumerate(answer):
            if isinstance(entry, dict) and set(entry) == {"file", "error"}:
                unreadable.append(str(entry["file"]))
                continue
            try:
                ledgers.append(_summary(entry))
            except (KeyError, TypeError, ValueError):  # one odd ledger never hides the rest
                found = entry.get("id") if isinstance(entry, dict) else None
                unreadable.append(f"{found}.json" if isinstance(found, str)
                                  and LEDGER_ID.fullmatch(found) else f"entry {i}")
        return LedgerListing(tuple(ledgers), tuple(unreadable))

    def find(self, sha256: str) -> tuple[LedgerSummary, ...]:
        """Every listed ledger whose output or an asset has this SHA-256."""
        digest = _sha256(sha256, "wan_ledger.find")
        return tuple(s for s in self.list().ledgers if s.holds(digest))

    def fetch_command(self, ledger_id: str, sha256: str) -> Command:
        label = "wan_ledger.fetch_asset"
        pinned.check(self.fetch_snippet, FETCH_SNIPPET)
        argv = self.target.argv(self.fetch_snippet.text, _ledger_id(ledger_id, label),
                                _sha256(sha256, label))
        return Command(label, argv, b"", FETCH_TIMEOUT_S, self.target.describe())

    def fetch_asset(self, ledger_id: str, sha256: str, *, path: str = "") -> AssetBytes:
        """The bytes of the asset with this SHA-256 in ledger ``ledger_id``. ``path`` is
        only recorded on the result (from :meth:`get` or the recovery map)."""
        command = self.fetch_command(ledger_id, sha256)
        data = run_checked(self.runner, command).stdout
        if len(data) > MAX_ASSET_BYTES:
            raise AdapterError(RESPONSE_INVALID, command.label, "asset is over 64 MiB")
        if hashlib.sha256(data).hexdigest() != sha256:
            raise AdapterError(RESPONSE_INVALID, command.label, "asset bytes do not match the sha256")
        return AssetBytes(ledger_id, path, sha256, data)


def _summary(entry: Any) -> LedgerSummary:
    if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) \
            or not LEDGER_ID.fullmatch(entry["id"]):
        raise ValueError("id")
    hashes = entry.get("asset_sha256", [])
    if not isinstance(hashes, list) or not all(isinstance(h, str) and SHA256.fullmatch(h)
                                               for h in hashes):
        raise ValueError("asset_sha256")

    def optional(name, kinds):
        value = entry.get(name)
        if value is not None and (not isinstance(value, kinds) or isinstance(value, bool)):
            raise ValueError(name)
        return value
    return LedgerSummary(entry["id"], optional("title", str), optional("state", str),
                         optional("output", str), optional("bytes", int), optional("sha256", str),
                         optional("created_at", int | float), tuple(hashes))
