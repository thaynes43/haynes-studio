"""Read and validate a finished production archive before opening the destination."""

from collections.abc import Iterator, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
from typing import BinaryIO

import av

from haynes_studio.adapters.errors import AdapterError
from haynes_studio.adapters.wan_ledger import record_from_document
from haynes_studio.build.validate import validate_run, validate_run_snapshot
from haynes_studio.delivery.model import (
    AAC, DELIVERY_SCHEMA, FPS, H264, MASTER_SIZES, MP4, PROXY_SIZES, proxy_byte_limit,
)
from haynes_studio.delivery.validate import validate_delivery
from haynes_studio.errors import ContractError, blocking
from haynes_studio.jsonio import parse_strict
from haynes_studio.library import Library
from haynes_studio.store import StageRecord, StoreError, blob_locator, canonical_json, is_sha256, parse_locator

MEDIA = {"master": "final.mp4", "proxy": "proxy.mp4"}
COMMON = {*MEDIA.values(), "run.json", "delivery.json"}
CANONICAL = COMMON | {"snapshot.json", "asset-versions.json", "delivery-stage.json"}
RECOVERED = COMMON | {"ledger.json"}
ARCHIVE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
JSON_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,122}\.json")
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_FILES = 64


class ImportProblem(Exception):
    """An operator-facing code and, optionally, a checked archive member name."""

    def __init__(self, code: str, member: str | None = None):
        super().__init__(f"import_production.{code}" + (f" {member}" if member else ""))


@dataclass(frozen=True)
class Archive:
    directory: Path
    receipt: dict
    members: dict[str, BinaryIO]
    run: dict
    delivery: dict
    production_id: str
    story: dict
    snapshot: dict | None
    versions: list[dict]

    @property
    def marker(self) -> dict:
        return {
            "source_directory": self.directory.name,
            "receipt_sha256": hashlib.sha256(canonical_json(self.receipt)).hexdigest(),
            "source_kind": "canonical" if self.snapshot is not None else "recovered",
        }

    @property
    def publications(self) -> dict[str, tuple[str, str]]:
        """The archive member mapped to its destination locator and MIME type."""
        items = {file: (self.delivery[role]["locator"], MP4) for role, file in MEDIA.items()}
        if self.snapshot is not None:
            items["snapshot.json"] = (self.run["snapshot"]["locator"], "application/json")
        return items


def _receipt(path: Path, recovered: bool) -> dict:
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_JSON_BYTES + 1)
        if len(raw) > MAX_JSON_BYTES:
            raise ValueError
        receipt = parse_strict(raw.decode("utf-8"))
    except (OSError, ValueError, RecursionError):
        raise ImportProblem("receipt_invalid") from None
    required = RECOVERED if recovered else CANONICAL
    if (not isinstance(receipt, dict) or len(receipt) > MAX_FILES or not required <= receipt.keys()
            or (recovered and receipt.keys() != RECOVERED)):
        raise ImportProblem("receipt_invalid")
    for name, facts in receipt.items():
        if ((name not in MEDIA.values() and JSON_NAME.fullmatch(name) is None)
                or not isinstance(facts, dict) or facts.keys() != {"bytes", "sha256"}
                or type(facts["bytes"]) is not int or facts["bytes"] < 1
                or not is_sha256(facts["sha256"])
                or (name.endswith(".json") and facts["bytes"] > MAX_JSON_BYTES)):
            raise ImportProblem("receipt_invalid")
    if sum(facts["bytes"] for name, facts in receipt.items() if name.endswith(".json")) > MAX_JSON_BYTES:
        raise ImportProblem("receipt_invalid")
    return receipt


def _directory(stack: ExitStack, path: Path) -> int:
    """Pin the archive and refuse symlinks at every depth, including its root."""
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY
    fd = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
    except OSError:
        os.close(fd)
        raise ImportProblem("archive_directory") from None
    stack.callback(os.close, fd)
    return fd


def _read_member(stack: ExitStack, folder: int, name: str, facts: dict) -> tuple[BinaryIO, object]:
    def opener(path: str, flags: int) -> int:
        return os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder)

    try:
        handle = stack.enter_context(open(name, "rb", opener=opener))
        fd = handle.fileno()
        before = os.fstat(fd)
    except OSError:
        raise ImportProblem("archive_member", name) from None
    if not stat.S_ISREG(before.st_mode):
        raise ImportProblem("archive_member", name)
    if before.st_size != facts["bytes"]:
        raise ImportProblem("archive_size", name)
    # JSON is small and parsed from the exact bytes just hashed. Keep media descriptors
    # pinned for publication, which hashes the stream again against the same receipt.
    if name.endswith(".json"):
        raw = handle.read(facts["bytes"] + 1)
        digest = hashlib.sha256(raw).hexdigest()
    else:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    after = os.fstat(fd)
    if (digest != facts["sha256"] or after.st_size != before.st_size
            or after.st_mtime_ns != before.st_mtime_ns or after.st_ctime_ns != before.st_ctime_ns):
        raise ImportProblem("archive_hash", name)
    handle.seek(0)
    if not name.endswith(".json"):
        return handle, None
    try:
        return handle, parse_strict(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        raise ImportProblem("archive_json", name) from None


def _matches(facts: dict, document: object) -> bool:
    return (isinstance(document, dict) and type(document.get("bytes")) is int
            and all(document.get(k) == v for k, v in facts.items()))


def _pins(snapshot: dict, value: object) -> list[dict]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ImportProblem("asset_versions", "asset-versions.json")
    try:
        library = Library.from_version_documents(value)
    except ContractError:
        raise ImportProblem("asset_versions", "asset-versions.json") from None
    by_id = {item["id"]: item for item in value}
    pinned = []
    for entry in snapshot["resolved_asset_versions"]:
        version = library.get(entry["id"])
        if version is None:
            raise ImportProblem("asset_pin", "asset-versions.json")
        asset = library.asset_of(version.id)
        expected = {"id": version.id, "kind": version.kind, "sha256": None}
        if version.kind == "voice":
            expected["definition_signature"] = library.pin(version.id)
        elif version.kind == "board_voice" and version.voice is not None:
            expected["input_signature"] = version.voice.input_signature
            expected["take_sha256"] = [take.sha256 for take in version.voice.takes]
        elif version.content is not None:
            expected["sha256"] = version.content.sha256
        if (entry != expected or asset.scope.production_id not in (None, snapshot["story"]["production_id"])
                or asset.scope.story_id not in (None, snapshot["story"]["id"])
                or asset.scope.board_id not in (None, *snapshot["story"]["board_order"])
                or version.state == "candidate"):
            raise ImportProblem("asset_pin", "asset-versions.json")
        pinned.append(by_id[version.id])
    return pinned


def _canonical(docs: dict, receipt: dict, run: dict, production_id: str, kind: str):
    snapshot = docs["snapshot.json"]
    if blocking(validate_run_snapshot(snapshot)):
        raise ImportProblem("snapshot_invalid", "snapshot.json")
    story = snapshot["story"]
    held_snapshot = run["snapshot"]
    if (receipt["snapshot.json"]["sha256"] != held_snapshot["sha256"]
            or hashlib.sha256(canonical_json(snapshot)).hexdigest() != held_snapshot["sha256"]
            or (story["id"], story["production_id"], story["media_kind"], story["revision"],
                len(story["boards"])) !=
            (run["story_id"], production_id, kind, held_snapshot["story_revision"],
             held_snapshot["board_count"])):
        raise ImportProblem("snapshot_mismatch", "snapshot.json")
    delivery = docs["delivery.json"]
    if blocking(validate_delivery(delivery)):
        raise ImportProblem("delivery_invalid", "delivery.json")
    if delivery["id"] != run["delivery_id"] or delivery["run_id"] != run["id"]:
        raise ImportProblem("delivery_identity", "delivery.json")
    try:
        stage = StageRecord.decode(canonical_json(docs["delivery-stage.json"]),
                                   source="delivery-stage.json")
    except StoreError:
        raise ImportProblem("delivery_stage", "delivery-stage.json") from None
    if ((stage.production_id, stage.run_id, stage.stage) != (production_id, run["id"], "delivery")
            or stage.blobs.keys() != {"master", "proxy", "delivery"}):
        raise ImportProblem("delivery_stage", "delivery-stage.json")
    for role, name in {**MEDIA, "delivery": "delivery.json"}.items():
        if not _matches(receipt[name], stage.blobs[role].to_document()):
            raise ImportProblem("delivery_stage", "delivery-stage.json")
    for name in docs.keys() - CANONICAL:
        if not isinstance(docs[name], dict):
            raise ImportProblem("archive_json", name)
    return story, snapshot, _pins(snapshot, docs["asset-versions.json"]), delivery


def _check_recovered_media(handle: BinaryIO, size: tuple[int, int], frames: int, name: str) -> None:
    """The original frame-count check is archived. Check the recovered MP4's profile."""
    try:
        if handle.read(8)[4:] != b"ftyp":
            raise ImportProblem("recovered_profile", name)
        handle.seek(0)
        with av.open(handle, "r", format="mp4") as mp4:
            if len(mp4.streams) != 2 or len(mp4.streams.video) != 1 or len(mp4.streams.audio) != 1:
                raise ImportProblem("recovered_profile", name)
            video, audio = mp4.streams.video[0], mp4.streams.audio[0]
            if ((video.width, video.height) != size or video.average_rate != FPS
                    or video.frames != frames or video.codec_context.name != H264
                    or audio.codec_context.name != AAC):
                raise ImportProblem("recovered_profile", name)
    except (av.FFmpegError, OSError, ValueError):
        raise ImportProblem("recovered_profile", name) from None
    finally:
        handle.seek(0)


def _recovered(docs: dict, receipt: dict, members: dict, run: dict, production_id: str,
               kind: str, name: str):
    delivery = docs["delivery.json"]
    outputs = run["outputs"]
    frames = outputs["frames"]
    if (not isinstance(delivery, dict)
            or delivery.get("schema") != "studio.recovered-delivery/proposal"
            or delivery.get("is_original_delivery_document") is not False
            or (delivery.get("run_id"), delivery.get("delivery_id"), delivery.get("frames"),
                delivery.get("fps")) != (run["id"], run["delivery_id"], frames, FPS)
            or not any(check.get("check") == "frame_count" and check.get("result") == "pass"
                       and check.get("actual") == check.get("expected") == frames
                       for check in run["checks"] or [])):
        raise ImportProblem("recovered_delivery", "delivery.json")
    try:
        ledger = record_from_document(docs["ledger.json"], label="ledger.json")
    except AdapterError:
        raise ImportProblem("recovered_ledger", "ledger.json") from None
    provenance = ledger.document.get("provenance")
    expected = {"production_id": production_id, "story_id": run["story_id"], "run_id": run["id"],
                "delivery_id": run["delivery_id"], "plays": "proxy",
                "master_sha256": outputs["master_sha256"], "proxy_sha256": outputs["proxy_sha256"]}
    if (not isinstance(provenance, Mapping)
            or any(provenance.get(key) != value for key, value in expected.items())
            or not _matches(receipt["proxy.mp4"], {"bytes": ledger.bytes, "sha256": ledger.sha256})):
        raise ImportProblem("recovered_ledger", "ledger.json")
    published = {}
    for role, size in (("master", MASTER_SIZES[kind]), ("proxy", PROXY_SIZES[kind])):
        member = MEDIA[role]
        facts = receipt[member]
        if not _matches(facts, delivery.get(role)):
            raise ImportProblem("media_mismatch", member)
        _check_recovered_media(members[member], size, frames, member)
        width, height = size
        published[role] = {
            **facts, "media_type": MP4, "width": width, "height": height, "fps": FPS,
            "frames": frames, "video_codec": H264, "audio_codec": AAC, "legacy_path": None,
            "locator": blob_locator(production_id, facts["sha256"], MP4),
        }
    # The reference is still on the original run. This is a catalog entry for
    # playback, without a claim to know the lost draft, boards or asset versions.
    story = {
        "schema": "studio.story/v1", "id": run["story_id"], "production_id": production_id,
        "media_kind": kind, "title": name, "revision": 1, "format_version_id": None,
        "cast": [], "narrator_voice_version_id": None, "set": None, "layouts": {"default": {}},
        "motion_style": None, "mix": {"line_rms_dbfs": -22, "master_lufs": -20, "true_peak_dbtp": -3.5},
        "checks": {}, "beds": [], "board_order": [], "boards": [], "origin": None,
        "created_at": run["queued_at"], "updated_at": run["queued_at"], "created_by": run["queued_by"],
    }
    return story, None, [], {
        "schema": DELIVERY_SCHEMA, "id": run["delivery_id"], "run_id": run["id"],
        "created_at": run["finished_at"], "store": {"adapter": "local", "writable": True},
        **published, "legacy": None, "verification": {
            "decoded_frames": frames, "expected_frames": frames, "sha256_verified": True,
            "proxy_under_bytes": proxy_byte_limit(frames),
        },
    }


@contextmanager
def verify_archive(directory: Path, receipt_path: Path, *, name: str, kind: str,
                   recovered: bool) -> Iterator[Archive]:
    """Verify the complete flat inventory and cross-check canonical identities."""
    if ".." in directory.parts:
        raise ImportProblem("archive_directory")
    directory = directory.absolute()
    if ARCHIVE_NAME.fullmatch(directory.name) is None:
        raise ImportProblem("archive_directory")
    receipt = _receipt(receipt_path, recovered)
    with ExitStack() as stack:
        folder = _directory(stack, directory)
        actual = set(os.listdir(folder))
        if missing := receipt.keys() - actual:
            raise ImportProblem("archive_missing", min(missing))
        if actual - receipt.keys():
            raise ImportProblem("archive_extra")
        members, docs = {}, {}
        for member, facts in sorted(receipt.items()):
            handle, document = _read_member(stack, folder, member, facts)
            members[member] = handle
            if member.endswith(".json"):
                docs[member] = document
        run = docs["run.json"]
        if (blocking(validate_run(run)) or run["status"] != "succeeded" or run["delivery_id"] is None
                or not isinstance(run["provenance"], dict) or "archive_import" in run["provenance"]
                or run["finished_at"] is None or not isinstance(run["outputs"], dict)
                or run["progress"]["stage"] != "delivered"
                or run["outputs"].get("fps") != FPS
                or type(run["outputs"].get("frames")) is not int or run["outputs"]["frames"] < 1):
            raise ImportProblem("run_invalid", "run.json")
        try:
            production_id = parse_locator(run["snapshot"]["locator"]).production_id
            expected = blob_locator(production_id, run["snapshot"]["sha256"], "application/json")
        except StoreError:
            raise ImportProblem("snapshot_locator", "run.json") from None
        if run["snapshot"]["locator"] != expected or production_id is None:
            raise ImportProblem("snapshot_locator", "run.json")
        for role, member in MEDIA.items():
            if receipt[member]["sha256"] != run["outputs"].get(f"{role}_sha256"):
                raise ImportProblem("media_mismatch", member)
        if recovered:
            story, snapshot, versions, delivery = _recovered(
                docs, receipt, members, run, production_id, kind, name)
        else:
            story, snapshot, versions, delivery = _canonical(docs, receipt, run, production_id, kind)
        if blocking(validate_delivery(delivery)):
            raise ImportProblem("delivery_invalid", "delivery.json")
        for role, member in MEDIA.items():
            media = delivery[role]
            facts = receipt[member]
            if (not _matches(facts, media) or media["locator"] !=
                    blob_locator(production_id, facts["sha256"], MP4)
                    or media["frames"] != run["outputs"]["frames"]):
                raise ImportProblem("media_mismatch", member)
        if (delivery["master"]["width"], delivery["master"]["height"]) != MASTER_SIZES[kind]:
            raise ImportProblem("media_kind", "delivery.json")
        yield Archive(directory, receipt, members, run, delivery, production_id, story, snapshot, versions)
