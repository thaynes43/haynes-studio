"""Fixed artifact I/O and a single supervised subprocess that owns inference."""

from __future__ import annotations

import hashlib
import multiprocessing
import os
import re
import stat
import threading
from dataclasses import dataclass
from multiprocessing.connection import Connection, wait
from multiprocessing.process import BaseProcess
from pathlib import Path
from time import monotonic

import numpy as np

from haynes_studio.schemas import validator_for
from haynes_studio.store import canonical_json

from .ort import OnnxMatte
from .pixels import MAX_SOURCE_BYTES, MODES, decode_source, describe_png, encode_png, matte_pixels, measure_shape
from .profile import (
    BUSY, COMMAND_FAILED, NOT_FOUND, PIN_MISMATCH, PROFILE_ID, PROVIDER, REQUEST_INVALID,
    REQUEST_SECONDS, RESPONSE_INVALID, STARTUP_SECONDS, TIMEOUT, MatteError, Profile,
)

REQUEST_SCHEMA = "studio.matte-request.v1.schema.json"
RESULT_SCHEMA = "studio.matte-result.v1.schema.json"
ATTEMPT_ID = re.compile("[a-f0-9]{32}")
DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
CREATE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
MAX_PNG_BYTES = MAX_SOURCE_BYTES


def envelope(value: object) -> tuple[str, dict]:
    if (not isinstance(value, dict) or set(value) != {"attempt_id", "request"}
            or not isinstance(value["attempt_id"], str) or not ATTEMPT_ID.fullmatch(value["attempt_id"])):
        raise MatteError(REQUEST_INVALID)
    attempt, request = value["attempt_id"], value["request"]
    if not validator_for(REQUEST_SCHEMA).is_valid(request):
        raise MatteError(REQUEST_INVALID)
    # JSON Schema integers are mathematical. The frozen Studio document requires
    # integer tokens, so 64 and 64.0 must not be different valid signatures.
    source, parameters = request["source"], request["parameters"]
    integers = [source["width"], source["height"], source["bytes"]]
    if parameters["target_height_px"] is not None:
        integers.append(parameters["target_height_px"])
    integers.extend(parameters["chroma_rgb"] or [])
    if any(type(value) is not int for value in integers):
        raise MatteError(REQUEST_INVALID)
    return attempt, request


def _read_file(directory: int, name: str, limit: int, code: str) -> bytes:
    with os.fdopen(os.open(name, READ, dir_fd=directory), "rb") as source:
        facts = os.fstat(source.fileno())
        if not stat.S_ISREG(facts.st_mode) or facts.st_nlink != 1 or facts.st_size > limit:
            raise MatteError(code)
        data = source.read(limit + 1)
        if len(data) > limit:
            raise MatteError(code)
        return data


def _write_png(directory: int, name: str, data: bytes) -> None:
    with os.fdopen(os.open(name, CREATE, 0o640, dir_fd=directory), "wb") as output:
        output.write(data)


def verify_result(request: dict, receipt: dict, artifacts: dict[str, bytes], profile: Profile) -> None:
    if not validator_for(RESULT_SCHEMA).is_valid(receipt):
        raise MatteError(RESPONSE_INVALID)
    if any(receipt[key] != request[key] for key in request if key != "schema"):
        raise MatteError(RESPONSE_INVALID)
    if (receipt["input_signature"] != input_signature(request)
            or receipt["provenance"] != profile.provenance()):
        raise MatteError(RESPONSE_INVALID)

    size = request["source"]["width"], request["source"]["height"]
    decoded = {}
    for key, mode in MODES.items():
        descriptor, decoded[key] = describe_png(artifacts[key], mode, size)
        if descriptor != receipt["artifacts"][key]:
            raise MatteError(RESPONSE_INVALID)
    mask = decoded["mask"]
    if (not np.array_equal(decoded["cutout"][..., 3], mask)
            or np.any(decoded["cutout"][..., :3][mask == 0])
            or measure_shape(mask, request["parameters"]["target_height_px"]) != receipt["shape"]):
        raise MatteError(RESPONSE_INVALID)


def input_signature(request: dict) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(request)).hexdigest()


def _attempt(directory: int, request: dict, profile: Profile, matte) -> dict:
    try:
        if set(os.listdir(directory)) != {"input"}:
            raise MatteError(REQUEST_INVALID)
        data = _read_file(directory, "input", MAX_SOURCE_BYTES, REQUEST_INVALID)
    except OSError as error:
        raise MatteError(REQUEST_INVALID) from error
    image = decode_source(data, request["source"])
    parameters = request["parameters"]
    rgba = matte_pixels(image, matte(image), parameters["chroma_rgb"])
    shape = measure_shape(rgba[..., 3], parameters["target_height_px"])

    artifacts = {"cutout": encode_png(rgba), "mask": encode_png(rgba[..., 3])}
    receipt = {
        **request, "schema": "studio.matte-result/v1",
        "input_signature": input_signature(request),
        "shape": shape, "provenance": profile.provenance(),
        "artifacts": {
            key: {
                "sha256": hashlib.sha256(png).hexdigest(), "bytes": len(png),
                "media_type": "image/png", "width": image.width, "height": image.height,
            }
            for key, png in artifacts.items()
        },
    }
    for key, data in artifacts.items():
        _write_png(directory, key + ".png", data)
    readback = {
        key: _read_file(directory, key + ".png", MAX_PNG_BYTES, RESPONSE_INVALID)
        for key in artifacts
    }
    verify_result(request, receipt, readback, profile)
    return receipt


def _infer(scratch: Path, attempt: str, request: dict, profile: Profile, matte) -> dict:
    # Open both directories by descriptor and refuse links on every caller-
    # controlled entry. All file operations stay relative to the held directory.
    root = os.open(scratch, DIRECTORY)
    try:
        try:
            directory = os.open(attempt, DIRECTORY, dir_fd=root)
        except OSError as error:
            raise MatteError(REQUEST_INVALID) from error
        try:
            return _attempt(directory, request, profile, matte)
        finally:
            os.close(directory)
    finally:
        os.close(root)


def _worker(channel, scratch: Path, weights: Path, profile: Profile, factory) -> None:
    with channel:
        try:
            digest, graph = profile.verify(weights)
            matte = factory(graph)
            del graph
        except MatteError as error:
            channel.send((False, error.code))
            return
        except Exception:
            channel.send((False, COMMAND_FAILED))
            return
        channel.send((True, digest))
        while True:
            try:
                attempt, request = channel.recv()
            except EOFError:
                return
            try:
                receipt = _infer(scratch, attempt, request, profile, matte)
            except MatteError as error:
                channel.send((False, error.code))
            except Exception:
                channel.send((False, COMMAND_FAILED))
            else:
                channel.send((True, receipt))


@dataclass
class _Child:
    process: BaseProcess
    channel: Connection

    def read(self, deadline: float):
        ready = wait([self.channel, self.process.sentinel], max(0, deadline - monotonic()))
        if not ready or monotonic() >= deadline:
            raise MatteError(TIMEOUT)
        if self.channel not in ready:
            raise MatteError(COMMAND_FAILED)
        try:
            result = self.channel.recv()
        except (EOFError, OSError) as error:
            raise MatteError(COMMAND_FAILED) from error
        if monotonic() >= deadline:
            raise MatteError(TIMEOUT)
        return result

    def close(self):
        self.channel.close()
        if self.process.is_alive():
            self.process.kill()
        self.process.join()
        self.process.close()


class Engine:
    """One request at a time. A killed worker is joined before replacement starts."""

    def __init__(self, scratch: Path, weights: Path, profile: Profile, *, factory=OnnxMatte,
                 request_seconds=REQUEST_SECONDS, startup_seconds=STARTUP_SECONDS):
        self._scratch = scratch
        self._weights = weights
        self._profile = profile
        self._factory = factory
        self._request_seconds = request_seconds
        self._startup_seconds = startup_seconds
        self._lock = threading.Lock()
        self._child: _Child | None = None
        self._digest: str | None = None
        self._recovery: threading.Thread | None = None
        self._closed = False
        self._start()

    @property
    def readiness(self) -> dict | None:
        digest = self._digest
        child = self._child
        if digest is None or child is None:
            return None
        try:
            if not child.process.is_alive():
                return None
        except ValueError:  # A concurrent timeout closed this child's handle.
            return None
        return {"profile_id": PROFILE_ID, "profile_sha256": digest, "provider": PROVIDER}

    def _start(self) -> None:
        deadline = monotonic() + self._startup_seconds
        ctx = multiprocessing.get_context("spawn")
        parent, peer = ctx.Pipe()
        process = ctx.Process(target=_worker, args=(
            peer, self._scratch, self._weights, self._profile, self._factory,
        ), daemon=True)
        try:
            process.start()
        except (OSError, RuntimeError) as error:
            parent.close()
            raise MatteError(COMMAND_FAILED) from error
        finally:
            peer.close()
        child = _Child(process, parent)
        try:
            success, result = child.read(deadline)
            if not success:
                raise MatteError(result)
        except BaseException:
            child.close()
            raise
        self._child, self._digest = child, result

    def _stop(self) -> None:
        self._digest = None
        child, self._child = self._child, None
        if child is not None:
            child.close()

    def _recover(self) -> None:
        with self._lock:
            if not self._closed:
                try:
                    self._start()
                except (MatteError, OSError):
                    # Remain unready. The serving workload's liveness probe
                    # allows a full restart after the separately bounded load.
                    return

    def run(self, value: object) -> dict:
        attempt, request = envelope(value)
        if not self._lock.acquire(blocking=False):
            raise MatteError(BUSY if self._digest is not None else NOT_FOUND)
        try:
            if self._child is None:
                raise MatteError(NOT_FOUND)
            if request["profile_sha256"] != self._digest or request["profile_id"] != PROFILE_ID:
                raise MatteError(PIN_MISMATCH)
            deadline = monotonic() + self._request_seconds
            try:
                self._child.channel.send((attempt, request))
                success, result = self._child.read(deadline)
            except (MatteError, OSError) as error:
                self._stop()
                self._recovery = threading.Thread(target=self._recover, name="matting-recovery")
                self._recovery.start()
                if isinstance(error, MatteError):
                    raise
                raise MatteError(COMMAND_FAILED) from error
            if not success:
                raise MatteError(result)
            return result
        finally:
            self._lock.release()

    def __enter__(self) -> Engine:
        return self

    def __exit__(self, *_):
        with self._lock:
            self._closed = True
            self._stop()
        if self._recovery is not None:
            self._recovery.join()
