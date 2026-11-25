"""One supervised inference process, with fixed and verified artifact paths."""

from __future__ import annotations

import multiprocessing
import os
import re
import threading
from dataclasses import dataclass, replace
from functools import partial
from hashlib import sha256
from multiprocessing.connection import Connection, wait
from multiprocessing.process import BaseProcess
from pathlib import Path
from time import monotonic

from haynes_studio.store import canonical_json

from .files import create_file, open_directory, read_file
from .opencv import Fsrcnn
from .pixels import decode_png, describe, encode_png, fits, lanczos
from .profile import (
    BUSY, COMMAND_FAILED, MAX_INPUT, MAX_OUTPUT, NOT_FOUND, PIN_MISMATCH, PROFILE_ID,
    PROVIDER, REQUEST_INVALID, REQUEST_SECONDS, RESPONSE_INVALID, SETTINGS, STARTUP_SECONDS,
    TARGETS, TIMEOUT, Profile, UpscaleError,
)

REQUEST_SCHEMA = "studio.upscale-frame-request/v1"
RESULT_SCHEMA = "studio.upscale-frame-result/v1"
ATTEMPT_ID = re.compile("[a-f0-9]{32}")
DIGEST = re.compile("[a-f0-9]{64}")
# Fixture and production callers serialize child launches. The spawn lock also
# keeps smoke-only GLIBC_TUNABLES changes from leaking into another child.
_SPAWN_LOCK = threading.Lock()


def _digest(value) -> bool:
    return isinstance(value, str) and DIGEST.fullmatch(value) is not None


def envelope(value: object) -> tuple[str, dict]:
    if (not isinstance(value, dict) or set(value) != {"attempt_id", "request"}
            or not isinstance(value["attempt_id"], str) or not ATTEMPT_ID.fullmatch(value["attempt_id"])):
        raise UpscaleError(REQUEST_INVALID)
    request = value["request"]
    if (not isinstance(request, dict) or set(request) != {"schema", "source", "target", "profile_id", "profile_sha256"}
            or request["schema"] != REQUEST_SCHEMA or not _digest(request["profile_sha256"])
            or not isinstance(request["profile_id"], str)):
        raise UpscaleError(REQUEST_INVALID)
    source, target = request["source"], request["target"]
    if (not isinstance(source, dict) or set(source) != {"sha256", "bytes", "media_type", "width", "height"}
            or not isinstance(target, dict) or set(target) != {"width", "height"}
            or not _digest(source["sha256"]) or source["media_type"] != "image/png"
            or any(type(container[key]) is not int for container, key in (
                (source, "width"), (source, "height"), (source, "bytes"), (target, "width"), (target, "height"),
            ))
            or not 0 < source["bytes"] <= MAX_INPUT):
        raise UpscaleError(REQUEST_INVALID)
    size = (target["width"], target["height"])
    if size not in TARGETS or not fits((source["width"], source["height"]), size):
        raise UpscaleError(REQUEST_INVALID)
    return value["attempt_id"], request


def _receipt(request: dict, profile: Profile, output: dict) -> dict:
    return {
        "schema": RESULT_SCHEMA, "request_sha256": sha256(canonical_json(request)).hexdigest(),
        "source": request["source"], "target": request["target"], "output": output,
        "provenance": {"manifest": profile.document(), "profile_sha256": request["profile_sha256"]},
    }


def verify_result(request: dict, receipt: dict, data: bytes, profile: Profile) -> None:
    size = request["target"]["width"], request["target"]["height"]
    if (not 0 < len(data) <= MAX_OUTPUT
            or request["profile_id"] != PROFILE_ID
            or request["profile_sha256"] != sha256(profile.manifest()).hexdigest()
            or canonical_json(receipt) != canonical_json(_receipt(request, profile, describe(data, size)))):
        raise UpscaleError(RESPONSE_INVALID)
    decode_png(data, size, RESPONSE_INVALID)


def _infer(root: Path, attempt: str, request: dict, profile: Profile, upscale) -> dict:
    source = request["source"]
    source_size = source["width"], source["height"]
    target = request["target"]["width"], request["target"]["height"]
    with open_directory(root) as scratch:
        try:
            with open_directory(attempt, dir_fd=scratch) as directory:
                if set(os.listdir(directory)) != {"input.png"}:
                    raise UpscaleError(REQUEST_INVALID)
                data = read_file(directory, "input.png", MAX_INPUT, REQUEST_INVALID)
                if describe(data, source_size) != source:
                    raise UpscaleError(PIN_MISMATCH)
                rgb = decode_png(data, source_size, REQUEST_INVALID)
                enlarged = upscale(rgb)
                if enlarged.mode != "RGB" or enlarged.size != (rgb.width * 2, rgb.height * 2):
                    raise UpscaleError(RESPONSE_INVALID)
                png = encode_png(lanczos(enlarged, target))
                receipt = _receipt(request, profile, describe(png, target))
                if len(png) > MAX_OUTPUT:
                    raise UpscaleError(RESPONSE_INVALID)
                # The caller owns the attempt and input; the backend reserves the
                # result directory itself and never opens an existing destination for write.
                os.mkdir("result", mode=0o770, dir_fd=directory)
                with open_directory("result", dir_fd=directory) as output:
                    os.fchmod(output, 0o2770)
                    create_file(output, "output.png", png)
                    verify_result(request, receipt, read_file(output, "output.png", MAX_OUTPUT, RESPONSE_INVALID), profile)
                return receipt
        except OSError as error:
            raise UpscaleError(REQUEST_INVALID) from error


def worker_rss() -> dict[str, int] | None:
    try:
        fields = {}
        for line in Path("/proc/self/status").read_text().splitlines():
            key, _, value = line.partition(":")
            if key in ("VmHWM", "VmRSS"):
                fields[key] = int(value.split()[0]) * 1024
        return {"peak_rss_bytes": fields["VmHWM"], "rss_after_bytes": fields["VmRSS"]}
    except (OSError, ValueError, KeyError):
        return None


def reset_worker_peak() -> bool:
    try:
        Path("/proc/self/clear_refs").write_text("5")
        return True
    except OSError:
        return False


def _worker(channel, scratch: Path, weights: Path, profile: Profile, pinned: Profile, factory,
            measure_memory: bool) -> None:
    with channel:
        try:
            digest, graph = pinned.verify(weights)
            if profile != pinned:
                digest = sha256(profile.manifest()).hexdigest()
            model = factory(graph)
        except UpscaleError as error:
            channel.send((False, error.code, worker_rss() if measure_memory else None))
            return
        except Exception:
            channel.send((False, COMMAND_FAILED, worker_rss() if measure_memory else None))
            return
        channel.send((True, digest, worker_rss() if measure_memory else None))
        while True:
            try:
                attempt, request = channel.recv()
            except EOFError:
                return
            measuring = measure_memory and reset_worker_peak()
            try:
                receipt = _infer(scratch, attempt, request, profile, model)
            except UpscaleError as error:
                channel.send((False, error.code, worker_rss() if measuring else None))
            except Exception:
                channel.send((False, COMMAND_FAILED, worker_rss() if measuring else None))
            else:
                channel.send((True, receipt, worker_rss() if measuring else None))


@dataclass
class _Child:
    process: BaseProcess
    channel: Connection

    def read(self, deadline: float):
        ready = wait([self.channel, self.process.sentinel], max(0, deadline - monotonic()))
        if not ready or monotonic() >= deadline:
            raise UpscaleError(TIMEOUT)
        if self.channel not in ready:
            raise UpscaleError(COMMAND_FAILED)
        try:
            result = self.channel.recv()
        except (EOFError, OSError) as error:
            raise UpscaleError(COMMAND_FAILED) from error
        if monotonic() >= deadline:
            raise UpscaleError(TIMEOUT)
        return result

    def close(self) -> None:
        self.channel.close()
        if self.process.is_alive():
            self.process.kill()
        self.process.join()
        self.process.close()


class Engine:
    """Admit one request and reap a dead or timed-out child before recovery."""

    def __init__(self, scratch: Path, weights: Path, profile: Profile, *, factory=None,
                 request_seconds=REQUEST_SECONDS, startup_seconds=STARTUP_SECONDS,
                 smoke_settings="default", memory: dict | None = None):
        self._scratch = scratch
        self._weights = weights
        self._pinned = profile
        self.profile = replace(profile, settings=smoke_settings)
        self._factory = factory if factory is not None else partial(
            Fsrcnn, identity=profile.identity, settings=smoke_settings,
        )
        self.memory = memory
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
        digest, child = self._digest, self._child
        if digest is None or child is None:
            return None
        try:
            if not child.process.is_alive():
                return None
        except ValueError:  # A concurrent timeout closed the child.
            return None
        return {"profile_id": PROFILE_ID, "profile_sha256": digest, "provider": PROVIDER}

    def _start(self) -> None:
        deadline = monotonic() + self._startup_seconds
        ctx = multiprocessing.get_context("spawn")
        parent, peer = ctx.Pipe()
        process = ctx.Process(target=_worker, args=(
            peer, self._scratch, self._weights, self.profile, self._pinned, self._factory, self.memory is not None,
        ), daemon=True)
        try:
            with _SPAWN_LOCK:
                old = os.environ.get("GLIBC_TUNABLES")
                os.environ["GLIBC_TUNABLES"] = SETTINGS[self.profile.settings]
                try:
                    process.start()
                finally:
                    if old is None:
                        os.environ.pop("GLIBC_TUNABLES", None)
                    else:
                        os.environ["GLIBC_TUNABLES"] = old
        except (OSError, RuntimeError) as error:
            parent.close()
            raise UpscaleError(COMMAND_FAILED) from error
        finally:
            peer.close()
        child = _Child(process, parent)
        try:
            success, result, memory = child.read(deadline)
            if self.memory is not None:
                self.memory.setdefault("startup", []).append(memory)
            if not success:
                raise UpscaleError(result)
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
                except (UpscaleError, OSError):
                    return

    def run(self, value: object) -> dict:
        attempt, request = envelope(value)
        if not self._lock.acquire(blocking=False):
            raise UpscaleError(BUSY if self._digest is not None else NOT_FOUND)
        try:
            if self._child is None:
                raise UpscaleError(NOT_FOUND)
            if request["profile_sha256"] != self._digest or request["profile_id"] != PROFILE_ID:
                raise UpscaleError(PIN_MISMATCH)
            deadline = monotonic() + self._request_seconds
            try:
                self._child.channel.send((attempt, request))
                success, result, memory = self._child.read(deadline)
                if self.memory is not None:
                    self.memory.setdefault("requests", {})[attempt] = memory
            except (UpscaleError, OSError) as error:
                self._stop()
                self._recovery = threading.Thread(target=self._recover, name="upscaling-recovery")
                self._recovery.start()
                if isinstance(error, UpscaleError):
                    raise
                raise UpscaleError(COMMAND_FAILED) from error
            if not success:
                raise UpscaleError(result)
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
