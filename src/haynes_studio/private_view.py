"""Create-only delivery to the legacy Wan private viewer (story 863).

This is an explicit CLI operation, separate from the read-only legacy adapter.
All remote code is fixed source, with data in argv/stdin and an injectable runner.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from haynes_studio import _private_view_remote as remote
from haynes_studio.adapters.runner import WAN_API, Command, Runner, run_checked
from haynes_studio.adapters.wan_ledger import LedgerReader, record_from_document
from haynes_studio.build.run import RUN_OUTPUT, RunRecords, version_stage
from haynes_studio.build.validate import validate_run
from haynes_studio.canonical.model import to_document
from haynes_studio.delivery.publish import read_delivery
from haynes_studio.errors import blocking
from haynes_studio.jsonio import parse_strict, thaw
from haynes_studio.stages import completed_stage
from haynes_studio.store import Blob, LocalStore, canonical_json

STORY = "https://work.haynesnetwork.com/work_packages/863"
ROOT = "/workspace"
CODE = Path(remote.__file__).read_text(encoding="utf-8")


class PrivateViewError(Exception):
    """Proposed codes: private_view.invalid, remote_failed, readback_failed,
    withdraw_failed. ``record`` describes this attempt's retained artifacts."""

    def __init__(self, code: str, message: str, record: dict | None = None):
        self.code, self.record = "private_view." + code, record
        super().__init__(self.code + ": " + message)


def _hash(data: bytes) -> dict:
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _blob_bytes(store: LocalStore, blob: Blob) -> bytes:
    with store.open(blob.locator) as source:
        data = source.read()
    if _hash(data) != {"bytes": blob.bytes, "sha256": blob.sha256}:
        raise PrivateViewError("invalid", "local blob changed while reading")
    return data


def _inputs(store: LocalStore, production_id: str, run_id: str):
    delivery = read_delivery(store, production_id=production_id, run_id=run_id)
    if delivery is None:
        raise PrivateViewError("invalid", "the run has no verified delivery")
    run = RunRecords(store, production_id).latest(run_id)
    if run is None or blocking(validate_run(run)):
        raise PrivateViewError("invalid", "the latest named run output is not a valid run")
    if (run["id"], run["delivery_id"], run["status"]) != (run_id, delivery.id, "succeeded"):
        raise PrivateViewError("invalid", "run and delivery identities or final state disagree")
    outputs = run["outputs"]
    if not outputs or (outputs.get("master_sha256"), outputs.get("proxy_sha256"),
                       outputs.get("frames"), outputs.get("fps")) != (
            delivery.master.sha256, delivery.proxy.sha256, delivery.master.frames, 24):
        raise PrivateViewError("invalid", "run outputs do not name the verified delivery")
    provenance = run["provenance"]
    if not provenance or not provenance.get("toolchain", {}).get("studio"):
        raise PrivateViewError("invalid", "the succeeded run lacks its studio provenance")
    # Match latest()'s contiguous numeric stages and named RUN_OUTPUT, never glob/sort
    # or the first JSON blob. Re-reading also detects a writer advancing the journal.
    latest = None
    for number in range(1, 10_000):
        record = completed_stage(store, production_id=production_id, run_id=run_id,
                                 stage=version_stage(number))
        if record is None:
            break
        latest = record
    run_data = _blob_bytes(store, latest.blobs[RUN_OUTPUT])
    if parse_strict(run_data.decode("utf-8")) != run:
        raise PrivateViewError("invalid", "run journal changed during preflight")
    stage = completed_stage(store, production_id=production_id, run_id=run_id, stage="delivery")
    files = {"final.mp4": _blob_bytes(store, stage.blobs["master"]),
             "proxy.mp4": _blob_bytes(store, stage.blobs["proxy"]),
             "run.json": run_data, "delivery.json": _blob_bytes(store, stage.blobs["delivery"])}
    for name, media in (("final.mp4", delivery.master), ("proxy.mp4", delivery.proxy)):
        if _hash(files[name]) != {"bytes": media.bytes, "sha256": media.sha256}:
            raise PrivateViewError("invalid", "delivery stage changed during preflight")
    if parse_strict(files["delivery.json"].decode("utf-8")) != to_document(delivery):
        raise PrivateViewError("invalid", "delivery document changed during preflight")
    return delivery, run, files


class Route:
    def __init__(self, runner: Runner):
        self.runner = runner

    def call(self, action: str, request: dict, data: bytes = b"") -> dict:
        command = Command("private_view." + action,
                          WAN_API.argv(CODE, action, ROOT, canonical_json(request).decode()),
                          data, 600 if action == "copy" else 300, WAN_API.describe())
        result = run_checked(self.runner, command)
        answer = parse_strict(result.stdout.decode("utf-8"))
        if not isinstance(answer, dict):
            raise ValueError("remote answer is not an object")
        return answer


def _record(out: Path, document: dict) -> None:
    # The final record is create-only, complete, and never a partial JSON document.
    temp = out / (".production-" + uuid.uuid4().hex + ".tmp")
    with temp.open("xb") as handle:
        handle.write(canonical_json(document) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.link(temp, out / "production.json", follow_symlinks=False)


def put_private_view(*, store: LocalStore, production_id: str, run_id: str, job: str,
                     out: Path, runner: Runner, title: str, master: bool = False,
                     check_only: bool = False) -> dict[str, Any]:
    """Put a verified run on private viewing; check-only stops before the first write.

    OUT must be a new folder outside the store. No retries and no delete path.
    On a failure after linking (including an uncertain link response), try to move
    only the ledger whose inode/hash the prepare step recorded, then report leftovers.
    """
    if not isinstance(job, str) or remote.JOB.fullmatch(job) is None:
        raise PrivateViewError("invalid", "JOB must match [a-z0-9][a-z0-9-]{2,63}")
    if not isinstance(title, str) or not title.strip():
        raise PrivateViewError("invalid", "a nonempty title is required")
    out = out.absolute()
    if out.resolve().is_relative_to(Path(store.root).resolve()):
        raise PrivateViewError("invalid", "OUT must be outside the input store")
    if os.path.lexists(out):
        raise PrivateViewError("invalid", "OUT must be a new folder")
    if not out.parent.is_dir():
        raise PrivateViewError("invalid", "OUT's parent must exist")
    try:
        delivery, run, data = _inputs(store, production_id, run_id)
    except (KeyError, TypeError, ValueError, UnicodeDecodeError) as error:
        raise PrivateViewError("invalid", "cannot read the named run/delivery outputs: "
                               + type(error).__name__) from None
    files = {name: _hash(value) for name, value in data.items()}
    ledger_id = uuid.uuid4().hex
    base = "/workspace/output/productions/" + job + "/"
    choice = "master" if master else "proxy"
    selected = "final.mp4" if master else "proxy.mp4"
    now = time.time()
    ledger = {
        "id": ledger_id, "kind": "edited_production", "state": "succeeded",
        "story": STORY, "title": title, "created_at": now, "finished_at": now,
        "telemetry": [], "preset": "studio-private-view",
        "output": "productions/" + job + "/" + selected, **files[selected],
        "assets": [{"path": base + name, **facts} for name, facts in files.items()],
        "provenance": {"production_id": production_id, "run_id": run_id,
                       "delivery_id": delivery.id, "story_id": run["story_id"],
                       "studio_commit": run["provenance"]["toolchain"]["studio"],
                       "plays": choice, "master_sha256": delivery.master.sha256,
                       "proxy_sha256": delivery.proxy.sha256,
                       "human_approval": "Pending: Tom; private viewing only."},
    }
    remote.check_ledger(ledger)
    record_from_document(ledger)
    request = {"job": job, "id": ledger_id, "need": sum(v["bytes"] for v in files.values()),
               "files": files, "ledger": ledger}
    route = Route(runner)
    try:
        preflight = route.call("preflight", request)
    except Exception as error:
        raise PrivateViewError("remote_failed", "read-only preflight failed: " + str(error)) from None
    request["identities"] = preflight["identities"]
    document = {"status": "check-only" if check_only else "preparing", "ledger": ledger,
                "files": ledger["assets"], "plays": choice, "production_id": production_id,
                "run_id": run_id, "delivery_id": delivery.id,
                "url": "https://video.haynesops.com/videos/" + ledger_id + "/file",
                "remote_folder": base.rstrip("/"), "free_bytes": preflight["free"],
                "recovery_folder": "/workspace/jobs/.private-view-" + ledger_id,
                "local_record": str(out / "production.json"),
                "plan": ["reserve folder", "copy four files create-only", "reopen and hash files",
                         "validate and link ledger create-only", "read ledger, file bytes and list",
                         "write production.json create-only"]}
    if check_only:
        return document
    out.mkdir()  # The first write. No remote mutation before all read-only checks.
    link_attempted = False
    phase = "remote_failed"
    try:
        document["remote_folder_may_exist"] = True
        reserved = route.call("reserve", request)
        request["identities"] = reserved["identities"]
        document["directory_identities"] = reserved["identities"]
        for name, content in data.items():
            route.call("copy", {**request, "name": name}, content)
        route.call("verify", request)
        ledger_data = canonical_json(ledger)
        request["ledger_file"] = _hash(ledger_data)
        # Both local validators run again against the exact document staged to link.
        remote.check_ledger(ledger)
        record_from_document(parse_strict(ledger_data.decode()))
        document["ledger_staging_may_exist"] = True
        request["receipt"] = route.call("prepare", request, ledger_data)
        document["receipt"] = request["receipt"]
        link_attempted = True
        route.call("link", request)
        phase = "readback_failed"
        reader = LedgerReader(runner)
        served = reader.get(ledger_id)
        if canonical_json(thaw(served.document)) != ledger_data:
            raise ValueError("the API served another ledger document")
        fetched = route.call("fetch", request)
        if fetched != {"status": 200, "content_type": "video/mp4", **files[selected]}:
            raise ValueError("GET /videos/<id>/file did not serve the selected file")
        listing = reader.list()
        if listing.unreadable or ledger_id not in {entry.id for entry in listing.ledgers}:
            raise ValueError("ledger listing is unreadable or lacks this attempt")
        route.call("verify", request)  # catches folder/file substitutions during read-back
        document.update(status="verified", served_file=fetched,
                        ledgers_listed=len(listing.ledgers), unreadable=[])
        _record(out, document)
    except Exception as error:
        document.update(status="failed", failure=str(error))
        if link_attempted:
            try:
                document["withdrawal"] = route.call("withdraw", request)
            except Exception as withdrawal:
                phase = "withdraw_failed"
                document["withdrawal"] = {"error": str(withdrawal),
                                          "served_name_may_remain": True}
        try:
            _record(out, document)
        except OSError as record_error:
            document["record_error"] = str(record_error)
        raise PrivateViewError(phase, str(error) + "; retained artifacts: "
                               + json.dumps(document, allow_nan=False), document) from None
    return document
