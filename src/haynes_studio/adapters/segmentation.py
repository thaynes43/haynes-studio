"""Client for the pinned segmentation service on the worker's scratch volume."""

from __future__ import annotations

import http.client
import os
import re
import stat
from collections.abc import Callable
from contextlib import contextmanager, nullcontext
from errno import EEXIST, EISDIR, ELOOP, ENOTDIR, ENOTEMPTY, ENXIO
from fcntl import LOCK_EX, LOCK_NB, flock
from pathlib import Path
from time import sleep, time
from uuid import uuid4

from PIL import Image

from haynes_studio.schemas import validator_for
from haynes_studio.segmentation.backend import DIRECTORY, _create_file, _read_file, envelope
from haynes_studio.segmentation.inference import RESULT_SCHEMA, Candidate, Grounding, Observation, _prompt, observe
from haynes_studio.segmentation.pixels import describe_mask, tight_box
from haynes_studio.segmentation.profile import (
    MASK_FLOOR,
    MIN_MODEL_PIXELS,
    PROFILE_ID,
    REQUEST_SECONDS,
    Profile,
    SegmentationError,
    digest,
)
from haynes_studio.segmentation.service import MAX_REPLY, MAX_REQUEST, STATUS, local_call
from haynes_studio.store import canonical_json

BUSY_INTERVAL = 5
BUSY_WAITS = 13
# Leave an unconfirmed attempt alone until the request and socket input deadlines
# have passed. Its files alone can never be used as a successful response.
SCRATCH_GRACE = REQUEST_SECONDS + 6
MARKER = re.compile(r"\.studio-segment-([a-f0-9]{32})")
PATH_DIRECTORY = os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW
GROUNDING_FACTS = {"prompt", "detector_resize_wh", "detector_canvas_wh"}
OPERATION_FACTS = GROUNDING_FACTS | {"sam_hint"}


def _check_parameters(request, applied, direct, result):
    status, reason = result["status"], result["reason"]
    uses_sam = status == "ready" or reason in {"mask_uncertain", "foreground_depth_ambiguous"}
    if status != "failed":
        required = set() if direct else set(GROUNDING_FACTS)
        if uses_sam:
            required.add("sam_hint")
        if applied.keys() != required:
            raise SegmentationError("invalid_output")
    if direct and applied.keys() - {"sam_hint"}:
        raise SegmentationError("invalid_output")
    if "prompt" in applied and applied["prompt"] != _prompt(request):
        raise SegmentationError("invalid_output")
    resize, canvas = applied.get("detector_resize_wh"), applied.get("detector_canvas_wh")
    if applied.keys() & {"detector_resize_wh", "detector_canvas_wh"}:
        if (not all(isinstance(pair, list) and len(pair) == 2 for pair in (resize, canvas))
                or not all(type(n) is int and n > 0 for n in (*resize, *canvas))
                or not all(inner <= outer for inner, outer in zip(resize, canvas))):
            raise SegmentationError("invalid_output")
    if "sam_hint" in applied:
        box = result["detector_box_xyxy"]
        expected = request["hint"] if direct else {"kind": "box", "xyxy": box}
        if (not direct and box is None) or canonical_json(applied["sam_hint"]) != canonical_json(expected):
            raise SegmentationError("invalid_output")


def _check_grounded_foreground(request, pixels, score):
    # The depth prior lives inside observe. Replay the decoded mask with one
    # eligible grounding candidate and one SAM result to reach it without models.
    side = MIN_MODEL_PIXELS
    grounding = Grounding([Candidate((0, 0, side, side), 1.0, "foreground")], (side, side), (side, side))
    reason, _ = observe(
        Image.fromarray(pixels), None, request, lambda _image, _query: grounding,
        lambda _image, _hint: (pixels[None, :, :], [score]), Observation(), lambda _phase: nullcontext(),
    )
    if reason is not None:
        raise SegmentationError("invalid_output")


def verify_result(request: dict, result: object, mask: bytes | None, profile: Profile):
    """Verify the closed receipt, frozen provenance and the backend's pixel contract."""
    if (not isinstance(result, dict) or not validator_for(RESULT_SCHEMA).is_valid(result)
            or canonical_json(result["input"]) != canonical_json(request["input"])
            or result["target"] != request["target"]
            or result["request_sha256"] != digest(canonical_json(request))):
        raise SegmentationError("invalid_output")
    provenance = result["provenance"]
    hint = request["hint"]
    direct = hint is not None and hint["kind"] in ("point", "box")
    status, reason = result["status"], result["reason"]
    if status == "failed":
        executions = [[], ["sam"]] if direct else [[], ["dino"], ["dino", "sam"]]
    elif status == "ready" or reason in {"mask_uncertain", "foreground_depth_ambiguous"}:
        executions = [["sam"] if direct else ["dino", "sam"]]
    else:
        executions = [] if direct else [["dino"]]
    # The serving manifest fixes mmap. Only operation-specific facts may extend
    # its parameters, and the frozen runtime, image and model identities must match.
    applied = {key: value for key, value in provenance["parameters"].items() if key in OPERATION_FACTS}
    recorded = canonical_json(provenance)
    if not any(recorded == canonical_json(profile.provenance(models, applied)) for models in executions):
        raise SegmentationError("profile_unavailable")
    source = request["input"]
    size = source["width"], source["height"]
    box = result["detector_box_xyxy"]
    if (direct and (box is not None or result["scores"]["detector"] is not None)
            or box is not None and (any(type(n) is not int for n in box)
                                    or not (0 <= box[0] < box[2] <= size[0]
                                            and 0 <= box[1] < box[3] <= size[1]))):
        raise SegmentationError("invalid_output")
    _check_parameters(request, applied, direct, result)
    if status == "ready" and mask is not None:
        score = result["scores"]["mask_iou"]
        if score is None or not score >= MASK_FLOOR:
            raise SegmentationError("invalid_output")
        descriptor, pixels = describe_mask(mask, size)
        if (canonical_json(result["mask"]) != canonical_json(descriptor)
                or canonical_json(result["box_xyxy"]) != canonical_json(tight_box(pixels))):
            raise SegmentationError("invalid_output")
        if not direct and request["target"]["kind"] == "foreground":
            _check_grounded_foreground(request, pixels, score)
        return pixels
    if status == "ready" or mask is not None:
        raise SegmentationError("invalid_output")
    return None


@contextmanager
def _scratch_directory(path: Path):
    # Reject symlinks at each step and require read permission only on the root.
    anchor = path.anchor
    parts = path.parts[1:] if anchor else path.parts
    current = os.open(anchor or ".", PATH_DIRECTORY if parts else DIRECTORY)
    try:
        for depth, part in enumerate(parts, start=1):
            flags = DIRECTORY if depth == len(parts) else PATH_DIRECTORY
            try:
                child = os.open(part, flags, dir_fd=current)
            except OSError as error:
                if error.errno in (ELOOP, ENOTDIR):
                    raise SegmentationError("lock_path_invalid") from None
                raise
            os.close(current)
            current = child
        yield current
    finally:
        os.close(current)


class SegmentationClient:
    """One trusted caller at a time across processes sharing the scratch root."""

    def __init__(self, profile: Profile, profile_sha256: str, *,
                 scratch: Path = Path("/segmentation"), socket: Path | None = None,
                 pause: Callable[[float], None] = sleep, timeout: float = REQUEST_SECONDS + 5):
        if digest(profile.manifest()) != profile_sha256:
            raise SegmentationError("profile_unavailable")
        self.profile = profile
        self.profile_sha256 = profile_sha256
        self.scratch = scratch
        self.socket = socket if socket is not None else scratch / "segment.sock"
        self.pause = pause
        self.timeout = timeout

    @contextmanager
    def serial(self, check_fence: Callable[[], None]):
        """Hold the scratch descriptor and local gate through completion."""
        with _scratch_directory(self.scratch) as scratch:
            try:
                fd = os.open(".studio-segmentation.lock",
                             os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o660, dir_fd=scratch)
            except OSError as error:
                if error.errno in (ELOOP, EISDIR, ENXIO):
                    raise SegmentationError("lock_path_invalid") from None
                raise
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise SegmentationError("lock_path_invalid")
                for wait in range(BUSY_WAITS + 1):
                    check_fence()
                    try:
                        flock(fd, LOCK_EX | LOCK_NB)
                    except BlockingIOError:
                        if wait == BUSY_WAITS:
                            raise SegmentationError("busy") from None
                        self.pause(BUSY_INTERVAL)
                    else:
                        yield scratch
                        return
            finally:
                os.close(fd)

    def _call(self, method: str, route: str, payload: dict | None = None):
        try:
            return local_call(self.socket, method, route, payload, timeout=self.timeout)
        except TimeoutError:
            raise SegmentationError("timeout") from None
        except (http.client.HTTPException, ValueError, RecursionError):
            raise SegmentationError("invalid_output") from None
        except OSError:
            raise SegmentationError("profile_unavailable") from None

    def _ready(self) -> None:
        status, body = self._call("GET", "/v1/ready")
        if status != 200 or body != {
            "profile_id": PROFILE_ID, "profile_sha256": self.profile_sha256, "device": "cpu",
        }:
            raise SegmentationError("profile_unavailable")

    def run_locked(self, request: dict, data: bytes, check_fence: Callable[[], None], scratch: int):
        """Fetch one verified receipt under the caller's serial context."""
        self._sweep(scratch)
        for wait in range(BUSY_WAITS + 1):
            check_fence()
            self._ready()
            try:
                return self._attempt(request, data, check_fence, scratch)
            except SegmentationError as error:
                if error.reason != "busy" or wait == BUSY_WAITS:
                    raise
            self.pause(BUSY_INTERVAL)

    def _attempt(self, request, data, check_fence, scratch):
        attempt = uuid4().hex
        payload = {"attempt_id": attempt, "request": request}
        envelope(payload)
        if len(canonical_json(payload)) > MAX_REQUEST:
            raise SegmentationError("invalid_input")
        marker = f".studio-segment-{attempt}"
        marker_fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=scratch)
        staged, finished = False, True
        try:
            os.mkdir(attempt, mode=0o770, dir_fd=scratch)
            staged = True
            path_fd = os.open(attempt, PATH_DIRECTORY, dir_fd=scratch)
            try:
                # O_PATH pins the directory even when umask masked owner read.
                # procfs lets chmod address that descriptor before a readable open.
                os.chmod(f"/proc/self/fd/{path_fd}", 0o2770)
                fd = os.open(".", DIRECTORY, dir_fd=path_fd)
            finally:
                os.close(path_fd)
            try:
                _create_file(fd, "input", data)
                os.chmod("input", 0o640, dir_fd=fd)
                check_fence()
                os.utime(marker_fd)
                finished = False
                status, reply = self._call("POST", "/v1/segment", payload)
                # A parsed HTTP reply confirms the handler returned. A transport
                # failure above must leave the directory undisturbed for the server.
                finished = True
                return self._read_reply(fd, request, status, reply)
            finally:
                os.close(fd)
        finally:
            try:
                if not finished:
                    os.utime(marker_fd)
                elif staged:
                    self._remove(scratch, attempt, marker)
                else:
                    os.unlink(marker, dir_fd=scratch)
            finally:
                os.close(marker_fd)

    def _read_reply(self, fd, request, status, reply):
        if not isinstance(reply, dict):
            raise SegmentationError("invalid_output")
        if set(reply) == {"code"} and isinstance(reply["code"], str) and STATUS.get(reply["code"]) == status:
            raise SegmentationError(reply["code"])
        if set(reply) != {"result", "result_sha256"} or not isinstance(reply["result"], dict):
            raise SegmentationError("invalid_output")
        result = reply["result"]
        reason = result.get("reason")
        failed = result.get("status") == "failed"
        expected_status = STATUS.get(reason) if isinstance(reason, str) else None
        if status != (expected_status if failed else 200):
            raise SegmentationError("invalid_output")
        try:
            result_bytes = canonical_json(result)
        except (ValueError, RecursionError):
            raise SegmentationError("invalid_output") from None
        if digest(result_bytes) != reply["result_sha256"] or len(result_bytes) > MAX_REPLY:
            raise SegmentationError("invalid_output")
        try:
            on_disk = _read_file(fd, "result.json", "invalid_output")
        except OSError:
            on_disk = None
        if on_disk != result_bytes:
            # An engine timeout or store failure can legitimately supersede the
            # staged bytes. It still proves no completion.
            if failed:
                verify_result(request, result, None, self.profile)
            raise SegmentationError(reason if failed else "invalid_output")
        mask = None
        if result.get("status") == "ready":
            try:
                mask = _read_file(fd, "mask.png", "invalid_output")
            except OSError:
                raise SegmentationError("invalid_output") from None
        elif not failed and "mask.png" in os.listdir(fd):
            raise SegmentationError("invalid_output")
        pixels = verify_result(request, result, mask, self.profile)
        return result, mask, pixels

    def _remove(self, scratch: int, attempt: str, marker: str):
        try:
            try:
                try:
                    # An empty attempt can be removed even if chmod never ran.
                    os.rmdir(attempt, dir_fd=scratch)
                except OSError as error:
                    if error.errno not in (ENOTEMPTY, EEXIST):
                        raise
                    fd = os.open(attempt, PATH_DIRECTORY, dir_fd=scratch)
                    try:
                        for name in ("input", "mask.png", "result.json"):
                            try:
                                os.unlink(name, dir_fd=fd)
                            except FileNotFoundError:
                                pass
                    finally:
                        os.close(fd)
                    os.rmdir(attempt, dir_fd=scratch)
            except FileNotFoundError:
                pass
            try:
                os.unlink(marker, dir_fd=scratch)
            except FileNotFoundError:
                pass
        except OSError:
            # An interrupted cleanup can be resumed by the next caller.
            pass

    def _sweep(self, scratch: int):
        for marker in os.listdir(scratch):
            match = MARKER.fullmatch(marker)
            if match is None:
                continue
            try:
                facts = os.stat(marker, dir_fd=scratch, follow_symlinks=False)
            except FileNotFoundError:
                continue
            if stat.S_ISREG(facts.st_mode) and time() - facts.st_mtime >= SCRATCH_GRACE:
                self._remove(scratch, match[1], marker)
