"""Studio-side client for the released Unix-socket matting service."""

import hashlib
import http.client
import os
import re
import stat
from collections.abc import Callable
from fcntl import LOCK_EX, LOCK_NB, flock
from pathlib import Path
from time import monotonic, sleep, time
from uuid import uuid4

from haynes_studio.adapters.errors import (
    BUSY, COMMAND_FAILED, NOT_FOUND, PIN_MISMATCH, RESPONSE_INVALID, TIMEOUT, AdapterError,
)
from haynes_studio.matting.backend import DIRECTORY, MAX_PNG_BYTES, _read_file, envelope, verify_result
from haynes_studio.matting.profile import (
    PROFILE_ID, PROVIDER, REQUEST_SECONDS, STARTUP_SECONDS, MatteError, Profile,
)
from haynes_studio.matting.service import STATUS, local_call

BUSY_RETRIES = 7
BUSY_INTERVAL = 5
# The HTTP handler allows three seconds for receiving the request. Readiness
# alone is insufficient: the backend can be ready while a request is active.
POST_QUIESCENCE_SECONDS = REQUEST_SECONDS + 3
PROBE_SECONDS = 1
ATTEMPT_MARKER = re.compile(r"\.studio-matting-([0-9a-f]{32})")


def failure(code: str, message: str = "The matting service could not complete the request") -> AdapterError:
    return AdapterError(code, "matting", message)


class _UnconfirmedReply(AdapterError):
    """The transport did not establish that the server finished the request."""


class MattingClient:
    """A worker-configured socket, scratch root and immutable backend pin."""

    def __init__(self, profile: Profile, profile_sha256: str, *,
                 scratch: Path = Path("/matting"), socket: Path | None = None,
                 pause: Callable[[float], None] = sleep,
                 timeout: float = 35):
        if hashlib.sha256(profile.manifest()).hexdigest() != profile_sha256:
            raise failure(PIN_MISMATCH, "The admitted profile differs from the expected manifest hash")
        self.profile = profile
        self.profile_sha256 = profile_sha256
        self.scratch = scratch
        self.socket = socket if socket is not None else scratch / "matte.sock"
        self.pause = pause
        self.timeout = timeout

    def _call(self, method: str, route: str, payload: dict | None = None,
              *, timeout: float | None = None) -> dict:
        message = "The matting service did not return a confirmed reply"
        try:
            status, body = local_call(self.socket, method, route, payload,
                                      timeout=self.timeout if timeout is None else timeout)
        except TimeoutError:
            raise _UnconfirmedReply(TIMEOUT, "matting", message) from None
        except (MatteError, http.client.HTTPException, ValueError, RecursionError):
            raise _UnconfirmedReply(RESPONSE_INVALID, "matting", message) from None
        except OSError:
            raise _UnconfirmedReply(NOT_FOUND, "matting", message) from None
        if not isinstance(body, dict):
            raise _UnconfirmedReply(RESPONSE_INVALID, "matting", message)
        if status != 200:
            code = body.get("code")
            if (isinstance(code, str) and set(body) == {"code"}
                    and STATUS.get(code) == status):
                raise failure(code)
            raise _UnconfirmedReply(RESPONSE_INVALID, "matting", message)
        return body

    def ready(self, *, timeout: float | None = None) -> None:
        expected = {"profile_id": PROFILE_ID, "profile_sha256": self.profile_sha256,
                    "provider": PROVIDER}
        answer = self._call("GET", "/v1/ready", timeout=timeout)
        if answer != expected:
            raise failure(PIN_MISMATCH if set(answer) == set(expected) else RESPONSE_INVALID)

    def run(self, request: dict, data: bytes, *, check_fence: Callable[[], None]) -> tuple[dict, dict]:
        self.ready()
        for retry in range(BUSY_RETRIES + 1):
            try:
                self._sweep()
                return self._attempt(request, data, check_fence)
            except AdapterError as error:
                if error.code != BUSY or retry == BUSY_RETRIES:
                    raise
            self.pause(BUSY_INTERVAL)
        raise AssertionError("unreachable")

    def _remove_attempt(self, directory: Path, marker: Path) -> None:
        try:
            try:
                fd = os.open(directory, DIRECTORY)
            except FileNotFoundError:
                pass
            else:
                try:
                    for name in ("input", "cutout.png", "mask.png"):
                        try:
                            os.unlink(name, dir_fd=fd)
                        except FileNotFoundError:
                            pass
                finally:
                    os.close(fd)
                directory.rmdir()
            marker.unlink(missing_ok=True)
        except OSError:
            # Keep the marker so the next dispatch can retry cleanup.
            pass

    def _sweep(self) -> None:
        for marker in self.scratch.glob(".studio-matting-*"):
            match = ATTEMPT_MARKER.fullmatch(marker.name)
            if match is None:
                continue
            try:
                fd = os.open(marker, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            except OSError:
                # Gone already, or not a marker this adapter wrote (a symlink, an
                # unreadable file). Leave it: a stray name must not stop matting.
                continue
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    continue
                try:
                    flock(fd, LOCK_EX | LOCK_NB)
                except BlockingIOError:
                    continue
                if time() - os.fstat(fd).st_mtime >= POST_QUIESCENCE_SECONDS:
                    self._remove_attempt(self.scratch / match[1], marker)
            finally:
                os.close(fd)

    def _ready_after_timeout(self, *, unconfirmed: bool) -> bool:
        if unconfirmed:
            # A client-side timeout may precede both the inference deadline
            # and any readiness change it triggers.
            self.pause(POST_QUIESCENCE_SECONDS)
        deadline = monotonic() + STARTUP_SECONDS + PROBE_SECONDS
        while (remaining := deadline - monotonic()) > 0:
            try:
                self.ready(timeout=min(PROBE_SECONDS, remaining))
                return True
            except AdapterError:
                self.pause(min(PROBE_SECONDS, max(0, deadline - monotonic())))
        return False

    def _attempt(self, request: dict, data: bytes, check_fence: Callable[[], None]) -> tuple[dict, dict]:
        attempt = uuid4().hex
        payload = {"attempt_id": attempt, "request": request}
        try:
            envelope(payload)
            directory_path = self.scratch / attempt
            marker = self.scratch / f".studio-matting-{attempt}"
            marker_fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            staged = False
            clean = True
            try:
                flock(marker_fd, LOCK_EX)
                directory_path.mkdir(mode=0o770)
                staged = True
                directory_path.chmod(0o2770)
                source = directory_path / "input"
                with source.open("xb") as output:
                    output.write(data)
                source.chmod(0o640)
                check_fence()
                os.utime(marker_fd)
                try:
                    receipt = self._call("POST", "/v1/matte", payload)
                except AdapterError as error:
                    unconfirmed = isinstance(error, _UnconfirmedReply)
                    if unconfirmed or error.code == TIMEOUT:
                        clean = False
                        os.utime(marker_fd)
                        clean = self._ready_after_timeout(unconfirmed=unconfirmed)
                    raise
                directory = os.open(directory_path, DIRECTORY)
                try:
                    artifacts = {name: _read_file(directory, name + ".png",
                                                  MAX_PNG_BYTES, RESPONSE_INVALID)
                                 for name in ("cutout", "mask")}
                except OSError:
                    raise failure(RESPONSE_INVALID) from None
                finally:
                    os.close(directory)
                verify_result(request, receipt, artifacts, self.profile)
                return receipt, artifacts
            finally:
                try:
                    if not staged:
                        marker.unlink(missing_ok=True)
                    elif clean:
                        self._remove_attempt(directory_path, marker)
                finally:
                    os.close(marker_fd)
        except MatteError as error:
            raise failure(error.code) from None
        except OSError:
            raise failure(COMMAND_FAILED, "Matting scratch could not be staged or read") from None
