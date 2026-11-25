"""Private artifact I/O and a single supervised inference process."""

from __future__ import annotations

import multiprocessing
import os
import re
import stat
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from multiprocessing.connection import Connection, wait
from multiprocessing.process import BaseProcess
from pathlib import Path
from time import monotonic

from haynes_studio.store import canonical_json

from .inference import Observation, observe, validate_request
from .memory import Phases
from .pixels import decode_source, describe_mask, encode_mask, tight_box
from .profile import (
    MAX_SOURCE_BYTES, PROFILE_ID, REQUEST_SECONDS, SERVING_PROFILE_ID, STARTUP_SECONDS, WEIGHT_LOAD,
    Profile, SegmentationError, digest,
)
from .runtime import load_models

DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
CREATE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
ATTEMPT_ID = re.compile(r"[a-f0-9]{32}")


def envelope(value: object) -> tuple[str, dict]:
    if (not isinstance(value, dict) or set(value) != {"attempt_id", "request"}
            or not isinstance(value["attempt_id"], str) or not ATTEMPT_ID.fullmatch(value["attempt_id"])):
        raise SegmentationError("invalid_input")
    validate_request(value["request"])
    return value["attempt_id"], value["request"]


@contextmanager
def attempt_dir(scratch: Path, attempt: str):
    root = os.open(scratch, DIRECTORY)
    try:
        directory = os.open(attempt, DIRECTORY, dir_fd=root)
        try:
            yield directory
        finally:
            os.close(directory)
    finally:
        os.close(root)


def _read_file(directory: int, name: str, reason: str) -> bytes:
    with os.fdopen(os.open(name, READ, dir_fd=directory), "rb") as source:
        facts = os.fstat(source.fileno())
        if not stat.S_ISREG(facts.st_mode) or facts.st_nlink != 1 or facts.st_size > MAX_SOURCE_BYTES:
            raise SegmentationError(reason)
        data = source.read(MAX_SOURCE_BYTES + 1)
        if len(data) > MAX_SOURCE_BYTES:
            raise SegmentationError(reason)
        return data


def _create_file(directory: int, name: str, data: bytes):
    with os.fdopen(os.open(name, CREATE, 0o640, dir_fd=directory), "wb") as output:
        output.write(data)


def _identity(directory: int) -> tuple[int, int]:
    facts = os.fstat(directory)
    return facts.st_dev, facts.st_ino


def _prepare(directory, request, profile, detector, segmenter, phase, load_strategy):
    observation = Observation(applied={"weight_load": load_strategy})
    try:
        with phase("source_validation"):
            source = _read_file(directory, "input", "invalid_input")
            image, alpha = decode_source(source, request["input"])
        reason, pixels = observe(image, alpha, request, detector, segmenter, observation, phase)
        if pixels is None:
            return observation.receipt(request, profile, "needs_hint", reason)

        with phase("mask_publication"):
            png = encode_mask(pixels)
            descriptor, decoded = describe_mask(png, image.size)
            box = tight_box(decoded)
            try:
                _create_file(directory, "mask.png", png)
                readback = _read_file(directory, "mask.png", "store_failed")
            except OSError as error:
                raise SegmentationError("store_failed") from error
            if readback != png:
                raise SegmentationError("store_failed")
        return observation.receipt(request, profile, "ready", mask=descriptor, box=box)
    except SegmentationError as error:
        reason = error.reason
    except FileNotFoundError:
        reason = "input_unavailable"
    except OSError:
        reason = "invalid_input"
    except Exception:
        reason = "inference_failed"
    return observation.receipt(request, profile, "failed", reason)


def _worker(channel, scratch, weights, profile, factory, measure, load_strategy):
    with channel:
        phase = Phases(measure)
        try:
            with phase("verify_profile_and_files"):
                pin = profile.verify(weights)
            detector, segmenter = factory(weights, phase, load_strategy)
        except Exception:
            channel.send((False, None, phase.samples))
            return
        channel.send((True, pin, phase.samples))

        while True:
            try:
                attempt, identity, request = channel.recv()
            except EOFError:
                return
            phase = Phases(measure)
            try:
                with attempt_dir(scratch, attempt) as directory:
                    if _identity(directory) != identity or set(os.listdir(directory)) != {"input"}:
                        raise SegmentationError("invalid_input")
                    receipt = _prepare(directory, request, profile, detector, segmenter, phase, load_strategy)
            except (OSError, SegmentationError):
                receipt = Observation().receipt(request, profile, "failed", "invalid_input")
            channel.send((True, receipt, phase.samples))


@dataclass
class _Child:
    process: BaseProcess
    channel: Connection

    def read(self, deadline: float):
        ready = wait([self.channel, self.process.sentinel], max(0, deadline - monotonic()))
        if not ready or monotonic() >= deadline:
            raise SegmentationError("timeout")
        if self.channel not in ready:
            raise SegmentationError("inference_failed")
        try:
            received = self.channel.recv()
        except (EOFError, OSError) as error:
            raise SegmentationError("inference_failed") from error
        if monotonic() >= deadline:
            raise SegmentationError("timeout")
        return received

    def close(self, *, graceful=False):
        self.channel.close()
        if graceful:
            # The idle worker sees EOF and runs its finalizers, including
            # unregistering resources owned by the model runtime.
            self.process.join(timeout=3)
        if self.process.is_alive():
            self.process.kill()
        self.process.join()
        exitcode = self.process.exitcode
        self.process.close()
        if graceful and exitcode != 0:
            raise SegmentationError("worker_shutdown_failed")


class Engine:
    def __init__(self, scratch: Path, weights: Path, profile: Profile, *, factory=load_models,
                 request_seconds=REQUEST_SECONDS, startup_seconds=STARTUP_SECONDS,
                 memory: dict | None = None, load_strategy=WEIGHT_LOAD):
        self.scratch, self.weights, self.profile = scratch, weights, profile
        self.factory, self.memory, self.load_strategy = factory, memory, load_strategy
        self.request_seconds, self.startup_seconds = request_seconds, startup_seconds
        self._lock = threading.Lock()
        self._child: _Child | None = None
        self._pin: str | None = None
        self._recovery: threading.Thread | None = None
        self._closed = False
        self._start()

    @property
    def readiness(self) -> dict | None:
        pin, child = self._pin, self._child
        if pin is None or child is None:
            return None
        try:
            if not child.process.is_alive():
                return None
        except ValueError:
            return None
        return {"profile_id": SERVING_PROFILE_ID, "profile_sha256": pin, "device": "cpu"}

    def _start(self):
        deadline = monotonic() + self.startup_seconds
        context = multiprocessing.get_context("spawn")
        parent, peer = context.Pipe()
        process = context.Process(target=_worker, args=(
            peer, self.scratch, self.weights, self.profile, self.factory,
            self.memory is not None, self.load_strategy,
        ), daemon=True)
        try:
            process.start()
        except (OSError, RuntimeError) as error:
            parent.close()
            raise SegmentationError("profile_unavailable") from error
        finally:
            peer.close()
        child = _Child(process, parent)
        try:
            success, pin, phases = child.read(deadline)
            if self.memory is not None:
                self.memory["startup"] = phases
            if not success or pin != digest(self.profile.manifest()):
                raise SegmentationError("profile_unavailable")
        except BaseException:
            child.close()
            raise
        self._child, self._pin = child, pin

    def _stop(self, *, graceful=False):
        self._pin = None
        child, self._child = self._child, None
        if child is not None:
            child.close(graceful=graceful)

    def _recover(self):
        with self._lock:
            if not self._closed:
                try:
                    self._start()
                except (SegmentationError, OSError):
                    # A bounded failed restart leaves the service unready.
                    pass

    def _dispatch(self, attempt, directory, request, deadline):
        if request["profile"] != PROFILE_ID or self._child is None:
            return Observation().receipt(request, self.profile, "failed", "profile_unavailable")
        try:
            self._child.channel.send((attempt, _identity(directory), request))
            _, receipt, samples = self._child.read(deadline)
            if self.memory is not None:
                self.memory.setdefault("requests", []).append(samples)
            return receipt
        except (OSError, SegmentationError) as error:
            self._stop()
            if self.memory is None:
                # Reap the failed worker before starting a replacement.
                self._recovery = threading.Thread(target=self._recover, name="segmentation-recovery")
                self._recovery.start()
            return Observation().receipt(
                request, self.profile, "failed", getattr(error, "reason", "inference_failed"),
            )

    def run(self, value: object) -> dict:
        attempt, request = envelope(value)
        if not self._lock.acquire(blocking=False):
            raise SegmentationError("busy" if self._pin is not None else "profile_unavailable")
        try:
            return self._run(attempt, request)
        finally:
            self._lock.release()

    def _run(self, attempt, request):
        deadline = monotonic() + self.request_seconds
        try:
            with attempt_dir(self.scratch, attempt) as directory:
                names = set(os.listdir(directory))
                if names != {"input"}:
                    reason = "input_unavailable" if not names else "invalid_input"
                    return Observation().receipt(request, self.profile, "failed", reason)
                receipt = self._dispatch(attempt, directory, request, deadline)
                if monotonic() >= deadline and receipt["status"] != "failed":
                    receipt = Observation().receipt(request, self.profile, "failed", "timeout")
                try:
                    _create_file(directory, "result.json", canonical_json(receipt))
                except OSError:
                    # A caller must receive a committed receipt before using
                    # any mask. A partial write stays inside this attempt.
                    return Observation().receipt(request, self.profile, "failed", "store_failed")
                if monotonic() >= deadline and receipt["status"] != "failed":
                    # A slow close can consume the remaining budget. An
                    # attempt is usable only with the matching successful reply.
                    return Observation().receipt(request, self.profile, "failed", "timeout")
                return receipt
        except FileNotFoundError:
            return Observation().receipt(request, self.profile, "failed", "input_unavailable")
        except OSError:
            return Observation().receipt(request, self.profile, "failed", "invalid_input")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        try:
            with self._lock:
                self._closed = True
                self._stop(graceful=True)
        finally:
            if self._recovery is not None:
                self._recovery.join()
