"""Studio-side client for the released Unix-socket matting service."""

import hashlib
import http.client
import os
from collections.abc import Callable
from pathlib import Path
from time import sleep
from uuid import uuid4

from haynes_studio.adapters.errors import (
    BUSY, COMMAND_FAILED, NOT_FOUND, PIN_MISMATCH, RESPONSE_INVALID, TIMEOUT, AdapterError,
)
from haynes_studio.matting.backend import DIRECTORY, MAX_PNG_BYTES, _read_file, envelope, verify_result
from haynes_studio.matting.profile import PROFILE_ID, PROVIDER, MatteError, Profile
from haynes_studio.matting.service import STATUS, local_call

BUSY_RETRIES = 7
BUSY_INTERVAL = 5


def failure(code: str, message: str = "The matting service could not complete the request") -> AdapterError:
    return AdapterError(code, "matting", message)


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

    def _call(self, method: str, route: str, payload: dict | None = None) -> dict:
        try:
            status, body = local_call(self.socket, method, route, payload, timeout=self.timeout)
        except TimeoutError:
            raise failure(TIMEOUT) from None
        except (MatteError, http.client.HTTPException, ValueError, RecursionError):
            raise failure(RESPONSE_INVALID) from None
        except OSError:
            raise failure(NOT_FOUND) from None
        if not isinstance(body, dict):
            raise failure(RESPONSE_INVALID)
        if status != 200:
            code = body.get("code")
            if (isinstance(code, str) and set(body) == {"code"}
                    and STATUS.get(code) == status):
                raise failure(code)
            raise failure(RESPONSE_INVALID)
        return body

    def ready(self) -> None:
        expected = {"profile_id": PROFILE_ID, "profile_sha256": self.profile_sha256,
                    "provider": PROVIDER}
        answer = self._call("GET", "/v1/ready")
        if answer != expected:
            raise failure(PIN_MISMATCH if set(answer) == set(expected) else RESPONSE_INVALID)

    def run(self, request: dict, data: bytes, *, check_fence: Callable[[], None]) -> tuple[dict, dict]:
        self.ready()
        for retry in range(BUSY_RETRIES + 1):
            try:
                return self._attempt(request, data, check_fence)
            except AdapterError as error:
                if error.code != BUSY or retry == BUSY_RETRIES:
                    raise
            self.pause(BUSY_INTERVAL)
        raise AssertionError("unreachable")

    def _attempt(self, request: dict, data: bytes, check_fence: Callable[[], None]) -> tuple[dict, dict]:
        attempt = uuid4().hex
        payload = {"attempt_id": attempt, "request": request}
        try:
            envelope(payload)
            directory_path = self.scratch / attempt
            directory_path.mkdir(mode=0o770)
            try:
                directory_path.chmod(0o2770)
                source = directory_path / "input"
                with source.open("xb") as output:
                    output.write(data)
                source.chmod(0o640)
                check_fence()
                receipt = self._call("POST", "/v1/matte", payload)
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
                # If a timeout raced a write, the service still owns the
                # bounded request. This attempt is never sent again.
                for name in ("input", "cutout.png", "mask.png"):
                    (directory_path / name).unlink(missing_ok=True)
                try:
                    directory_path.rmdir()
                except OSError:
                    pass
        except MatteError as error:
            raise failure(error.code) from None
        except OSError:
            raise failure(COMMAND_FAILED, "Matting scratch could not be staged or read") from None
