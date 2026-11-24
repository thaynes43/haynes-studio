"""Durable reconciliation of one Wan product request through the Studio worker API."""

from fractions import Fraction
from hashlib import sha256
from time import monotonic, sleep

import httpx

from haynes_studio.adapters import pinned, wan
from haynes_studio.build.errors import BuildError, BuildInterrupted, RunHeld
from haynes_studio.store import is_sha256

from .protocol import API_VERSION, PROFILES

MAX_CLIP_BYTES = 512 * 1024 * 1024
MAX_UPLOAD_BYTES = 19_999_999
POLL_SECONDS = 5
POLL_LIMIT_SECONDS = 1260
RESTART_ERROR = "Worker restarted; job was not replayed"
FOREIGN_ENGINE_QUEUE = "RuntimeError: ComfyUI already has a job; refusing a competing request"
GPU_REFUSALS = (
    "RuntimeError: Rack GPUs are busy; refusing to start a competing job",
    "RuntimeError: Rack GPUs must be below 62 C for a product job",
)
EXPECTED_PROFILES = {
    "i2v": {"fps": 24, "steps": 20, "max_frames": 121, "timeout_seconds": 1200},
    "s2v": {"fps": 16, "steps": 4, "cfg": 1, "chunk_frames": 77,
            "max_chunks": 3, "timeout_seconds": 1200},
}


class LanePaused(RunHeld):
    def __init__(self, code, message, *, job_id=None, wait_reason=None, admission_busy=False):
        self.wait_reason = wait_reason
        self.admission_busy = admission_busy
        super().__init__(code, message, job_id=job_id, detail={},
                         check="Reconcile the recorded job and check Wan readiness", stage="wan")


class BuildCancelled(BuildInterrupted):
    def __init__(self, job_id=None):
        self.job_id = job_id
        super().__init__()


class AttemptFailed(BuildInterrupted):
    """Definite failure to persist with the attempt and run in one transaction."""

    def __init__(self, job_id, error):
        self.job_id, self.error = job_id, error
        super().__init__(str(error))


def _mismatch(code, message, job_id, *, expected, actual):
    return BuildError(code, message, stage="wan", problems=(
        {"rule": code, "job_id": job_id, "expected": expected, "actual": actual},
    ))


def _path(attempt):
    return f'/v1/jobs/{attempt["kind"]}/{attempt["job_id"]}'


def _error(response):
    try:
        body = response.json()
    except ValueError:
        return None
    return body.get("code") if isinstance(body, dict) else None


class ProductWan:
    """Typed HTTP only. The installed service owns GPU admission and its lease."""

    def __init__(self, client):
        self.client = client

    def _json(self, response, code, *, job_id=None):
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise LanePaused(code, "Wan returned invalid JSON", job_id=job_id)
        return body

    def ready(self, kind=None):
        try:
            response = self.client.get("/v1/ready")
            if _error(response) == "worker_held":
                raise LanePaused("wan.held", "Wan requires inspection")
            if response.status_code != 200:
                raise LanePaused("wan.unavailable", "Wan is unavailable", wait_reason="gpu_unavailable")
            body = self._json(response, "wan.ready_invalid")
            if (body.get("api_version") != API_VERSION or type(body.get("ready")) is not bool or
                    not {"active_video_job", "active_foley_job"} <= body.keys()):
                raise LanePaused("wan.ready_invalid", "Wan returned an incompatible readiness record")
            if not body["ready"]:
                raise LanePaused("wan.unavailable", "Wan is not ready", wait_reason="gpu_unavailable")
            if (body["active_video_job"] is not None or
                    body["active_foley_job"] is not None):
                raise LanePaused("wan.busy", "The shared Wan lease is busy", wait_reason="lease_busy")
            if kind is None:
                return
            profiles = self.client.get("/v1/profiles")
        except httpx.RequestError as error:
            raise LanePaused("wan.unavailable", "Wan is unreachable", wait_reason="gpu_unavailable") from error
        if profiles.status_code != 200:
            raise LanePaused("wan.profile_unavailable", "Wan's profile matrix is unavailable")
        body = self._json(profiles, "wan.profile_invalid")
        matrix = body.get("profiles")
        profile = matrix.get(kind) if isinstance(matrix, dict) else None
        expected = {"profile": PROFILES[kind], **EXPECTED_PROFILES[kind]}
        if (body.get("api_version") != API_VERSION or not isinstance(profile, dict) or
                any(profile.get(key) != value for key, value in expected.items())):
            raise LanePaused("wan.profile_invalid", "Wan advertises another profile")

    def stage(self, data, digest, suffix):
        if not 0 < len(data) <= MAX_UPLOAD_BYTES or sha256(data).hexdigest() != digest:
            raise BuildError("wan.input_invalid", "The staging bytes do not match the Wan input pin")
        try:
            response = self.client.put(f"/v1/inputs/{digest}.{suffix}", content=data)
        except httpx.RequestError as error:
            raise LanePaused("wan.upload_unavailable", "Wan input staging is unavailable",
                             wait_reason="gpu_unavailable") from error
        if response.status_code not in (200, 201):
            if _error(response) == "upload_busy":
                raise LanePaused("wan.upload_busy", "A Wan upload is active", wait_reason="lease_busy")
            raise LanePaused("wan.upload_refused", "Wan refused input staging")
        body = self._json(response, "wan.upload_invalid")
        if body.get("sha256") != digest or body.get("bytes") != len(data):
            raise LanePaused("wan.upload_invalid", "Wan did not confirm the uploaded bytes")

    def submit(self, attempt):
        """Send only the persisted job ID and body. Ambiguous responses require a read."""
        job_id = attempt["job_id"]
        try:
            response = self.client.put(_path(attempt), json=attempt["request"])
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as error:
            raise LanePaused("wan.submit_not_sent", "The connection failed before the request was sent",
                             job_id=job_id) from error
        except httpx.RequestError:
            return
        code = _error(response)
        if response.status_code == 409 and code == "worker_busy":
            raise LanePaused("wan.busy", "Wan refused admission to the shared lease",
                             job_id=job_id, admission_busy=True)
        if 400 <= response.status_code < 500:
            failure = "wan.id_conflict" if code == "id_conflict" else "wan.submit_rejected"
            raise BuildError(failure, f"Wan rejected the job PUT with HTTP {response.status_code}",
                             stage="wan", problems=(
                                 {"rule": failure, "job_id": job_id, "http_status": response.status_code,
                                  "wan_code": code[:100] if isinstance(code, str) else None},
                             ))

    def status(self, attempt):
        response = self.client.get(_path(attempt))
        if response.status_code == 404 and _error(response) == "job_not_found":
            return None
        if response.status_code in (401, 403):
            raise LanePaused("wan.status_refused", "Wan refused access to the recorded job",
                             job_id=attempt["job_id"])
        if response.status_code != 200:
            # Let the caller apply the bounded slow-poll policy.
            raise httpx.ReadError("Wan job read failed")
        body = self._json(response, "wan.job_invalid", job_id=attempt["job_id"])
        expected = {"api_version": API_VERSION, "type": attempt["kind"], "id": attempt["job_id"],
                    "request_sha256": attempt["request_sha256"],
                    "profile": attempt["request"]["profile"]}
        if (any(body.get(key) != value for key, value in expected.items()) or
                body.get("state") not in ("queued", "running", "succeeded", "failed")):
            raise LanePaused("wan.job_invalid", "Wan returned another job or request",
                             job_id=attempt["job_id"])
        return body

    def download(self, attempt, body):
        job_id = attempt["job_id"]
        result = body.get("result")
        path = _path(attempt) + "/file"
        if (not isinstance(result, dict) or result.get("file_url") != path or
                result.get("media_type") != "video/mp4" or not is_sha256(result.get("sha256")) or
                type(result.get("bytes")) is not int or not 0 < result["bytes"] <= MAX_CLIP_BYTES):
            raise _mismatch("wan.result_invalid", "Wan reported invalid result metadata", job_id,
                            expected={"file_url": path, "media_type": "video/mp4",
                                      "sha256": "SHA-256", "max_bytes": MAX_CLIP_BYTES}, actual=result)
        expected = {"bytes": result["bytes"], "sha256": result["sha256"]}
        try:
            with self.client.stream("GET", path) as response:
                if 400 <= response.status_code < 500:
                    raise _mismatch("wan.result_invalid", "Wan refused the terminal job's result", job_id,
                                    expected={"http_status": 200}, actual={"http_status": response.status_code})
                if response.status_code != 200:
                    raise LanePaused("wan.download_failed", "Wan could not serve the result", job_id=job_id)
                data = bytearray()
                digest = sha256()
                for chunk in response.iter_bytes(chunk_size=1 << 20):
                    if len(data) + len(chunk) > result["bytes"]:
                        raise _mismatch("wan.result_invalid", "Wan returned more bytes than recorded", job_id,
                                        expected=expected, actual={"bytes_at_least": len(data) + len(chunk)})
                    data.extend(chunk)
                    digest.update(chunk)
        except httpx.RequestError as error:
            raise LanePaused("wan.download_failed", "Wan result download was interrupted",
                             job_id=job_id) from error
        if len(data) != result["bytes"] or digest.hexdigest() != result["sha256"]:
            raise _mismatch("wan.result_invalid", "Wan result byte count or SHA-256 differs", job_id,
                            expected=expected, actual={"bytes": len(data), "sha256": digest.hexdigest()})
        return bytes(data)


def product_request(request):
    body = {"profile": PROFILES[request.kind], "prompt": request.prompt.strip(),
            "negative_prompt": request.negative, "seed": request.seed, "story": request.story,
            "width": request.width, "height": request.height, "image_sha256": request.image_sha256}
    if isinstance(request, wan.SpeechToVideo):
        body.update(board_frames=request.board_frames, audio_sha256=sha256(request.drive_wav).hexdigest())
    else:
        body["frames"] = request.length
    return body


def expected_graph(attempt):
    """Reconstruct the pinned graph only to attest Wan's returned digest."""
    request = attempt["request"]
    job_id = attempt["job_id"]
    fields = {key: request[key] for key in ("prompt", "width", "height", "seed")}
    image = f'studio-v1/{request["image_sha256"]}.png'
    if attempt["kind"] == "i2v":
        template = pinned.load(wan.I2V_GRAPH)
        graph = wan.i2v_graph(template.data, negative=request["negative_prompt"], length=request["frames"],
                              steps=20, job_id=job_id, up_name="unused.png", **fields)
        graph["13"]["inputs"]["image"] = image
        return graph
    return wan.s2v_graph(negative=request["negative_prompt"], image=image,
                         audio=f'studio-v1/{request["audio_sha256"]}.wav',
                         length=wan.s2v_length(request["board_frames"]), prefix=f"video/{job_id}",
                         lightning=True, **fields)


def _result_clip(attempt, body, transport):
    request = attempt["request"]
    job_id = attempt["job_id"]
    graph = expected_graph(attempt)
    graph_digest = wan.graph_sha256(graph)
    if graph_digest != body.get("graph_sha256"):
        raise _mismatch("wan.graph_mismatch", "Wan reported a graph outside the Studio profile pins", job_id,
                        expected=graph_digest, actual=body.get("graph_sha256"))
    data = transport.download(attempt, body)
    frames = request["frames"] if attempt["kind"] == "i2v" else wan.s2v_length(request["board_frames"])
    fps = wan.I2V_FPS if attempt["kind"] == "i2v" else wan.FPS
    try:
        measured = wan.measure_clip(data)
        rate = Fraction(measured.fps)
    except (ValueError, OSError, ZeroDivisionError) as error:
        raise _mismatch("wan.clip_invalid", "The downloaded clip could not be decoded", job_id,
                        expected="decodable MP4", actual=type(error).__name__) from error
    expected_frames = frames
    if attempt["kind"] == "s2v":
        chunks = (frames + wan.CHUNK - 1) // wan.CHUNK
        expected_frames = wan.s2v_frames_delivered([min(frames, wan.CHUNK)] + [wan.CHUNK] * (chunks - 1))
    expected = {"width": request["width"], "height": request["height"],
                "frames": expected_frames, "fps": str(fps)}
    actual = {"width": measured.width, "height": measured.height,
              "frames": measured.frames, "fps": str(rate)}
    if expected != actual:
        raise _mismatch("wan.clip_invalid", "The decoded clip dimensions, length or rate differ", job_id,
                        expected=expected, actual=actual)
    return wan.WanClip(data, {
        "api_version": API_VERSION, "job_id": job_id, "graph_sha256": body["graph_sha256"],
        "engine": wan.I2V_ENGINE if attempt["kind"] == "i2v" else wan.S2V_ENGINE,
        "profile": request["profile"], "fps": fps, "seed": request["seed"],
        "frames_requested": frames, "frames_delivered": measured.frames,
        "clip_sha256": body["result"]["sha256"], "clip_bytes": len(data),
        "model_files_sha256": wan.model_files(graph),
        "model_files_source": "Pinned model licence register matched to Wan's graph SHA-256",
        "inputs": {"image": {"sha256": request["image_sha256"]},
                   **({"audio": {"sha256": request["audio_sha256"]}} if attempt["kind"] == "s2v" else {})},
    })


class ProductClips:
    """Clip source used by the existing I2V chains and layered S2V renderer."""

    def __init__(self, claim, transport, *, story, progress, clock=monotonic, pause=sleep):
        self.claim, self.transport, self.story = claim, transport, story
        self.progress, self.clock, self.pause = progress, clock, pause
        self.stopped = None
        self.downloaded = {}
        self.foreign_work_recorded = (claim.body["run"].get("error") or {}).get("code") == "wan.foreign_work"

    def reconcile(self):
        attempt = self.claim.body["pending"]
        if attempt is None:
            return
        if attempt["state"] == "reserved":
            try:
                status = self.transport.status(attempt)
            except httpx.RequestError as error:
                raise LanePaused("wan.poll_unavailable", "Cannot confirm a reserved job is absent",
                                 job_id=attempt["job_id"]) from error
            if status is not None:
                raise AttemptFailed(attempt["job_id"], BuildError(
                    "wan.id_conflict", "Wan already knows a locally reserved job ID", stage="wan"))
        else:
            clip = self._poll(attempt)
            if clip is not None:
                self.downloaded[attempt["job_id"]] = clip

    def _send(self, attempt):
        # Inputs were staged before the fenced sent marker. A takeover can use
        # the same request even if the previous worker's PUT is still in flight.
        try:
            self.transport.ready()
        except LanePaused as error:
            error.wait_reason = None
            raise
        if self.progress("wan_submitting", drain=True):
            return
        try:
            self.transport.submit(attempt)
        except LanePaused:
            raise
        except BuildError as error:
            raise AttemptFailed(attempt["job_id"], error) from error

    def _poll(self, attempt):
        job_id = attempt["job_id"]
        deadline = self.clock() + POLL_LIMIT_SECONDS
        first_miss = None
        misses = 0
        replayed = False
        while self.clock() < deadline:
            cancelling = self.progress("wan_poll", drain=True)
            try:
                body = self.transport.status(attempt)
            except httpx.RequestError:
                now = self.clock()
                first_miss = now if first_miss is None else first_miss
                misses += 1
                if misses >= 12 or now - first_miss >= 90:
                    raise LanePaused("wan.poll_unavailable", "Wan job status was repeatedly unavailable",
                                     job_id=job_id)
                self.pause(POLL_SECONDS)
                continue
            first_miss, misses = None, 0
            state = None if body is None else body["state"]
            if cancelling and state in (None, "succeeded", "failed"):
                raise BuildCancelled(job_id if attempt["state"] == "sent" else None)
            if body is None:
                if attempt["state"] == "succeeded":
                    raise BuildError("wan.result_changed", "Wan no longer reports a verified result", stage="wan")
                if replayed:
                    raise LanePaused("wan.ambiguous_submit", "Wan has no record yet for the sent ID",
                                     job_id=job_id)
                self._send(attempt)
                replayed = True
                continue
            if state == "failed" and attempt["state"] == "sent":
                error = body.get("error")
                if error == FOREIGN_ENGINE_QUEUE or error in GPU_REFUSALS:
                    self.claim.attempt(job_id, "busy")
                    code = "wan.foreign_engine_queue" if error == FOREIGN_ENGINE_QUEUE else "wan.busy"
                    raise LanePaused(code, "Wan refused admission without starting engine work",
                                     job_id=job_id, wait_reason="lease_busy")

            if cancelling:
                self.pause(POLL_SECONDS)
                continue
            foreign = body.get("unexpected_work_seen", [])
            if not isinstance(foreign, list) or not all(isinstance(item, str) for item in foreign):
                raise LanePaused("wan.job_invalid", "Wan returned invalid foreign-work evidence", job_id=job_id)
            if foreign:
                if not self.foreign_work_recorded or body["state"] not in ("succeeded", "failed"):
                    raise LanePaused("wan.foreign_work", "Wan observed foreign engine work", job_id=job_id)
                try:
                    self.transport.ready()
                except LanePaused as error:
                    raise LanePaused("wan.foreign_work", "Wan has yet to clear the reported foreign work",
                                     job_id=job_id) from error
            if state == "succeeded":
                try:
                    clip = _result_clip(attempt, body, self.transport)
                except LanePaused:
                    raise
                except BuildError as error:
                    if attempt["state"] == "succeeded":
                        raise
                    raise AttemptFailed(job_id, error) from error
                result = {"bytes": len(clip.data), "sha256": clip.sha256,
                          "graph_sha256": body["graph_sha256"]}
                if attempt["state"] == "succeeded":
                    if result != attempt["outcome"]:
                        raise BuildError("wan.result_changed", "Wan changed a verified result", stage="wan")
                else:
                    self.claim.attempt(job_id, "succeeded", result)
                return clip
            if attempt["state"] == "succeeded":
                raise BuildError("wan.result_changed", "Wan no longer reports a verified result", stage="wan")
            if state == "failed":
                if body.get("error") == RESTART_ERROR:
                    self.claim.attempt(job_id, "restart_failed")
                    return None
                raise AttemptFailed(job_id, BuildError(
                    "wan.job_failed", f"Wan job {job_id} failed", stage="wan"))
            self.pause(POLL_SECONDS)
        raise LanePaused("wan.poll_timeout", "Wan did not reach a terminal state within its budget",
                         job_id=job_id)

    def _make(self, request):
        body = product_request(request)
        self.progress("wan_preparing")
        restarts = 0
        while True:
            attempt = self.claim.reserve(request.kind, body)
            state, job_id = attempt["state"], attempt["job_id"]
            if state == "failed":
                raise BuildError("wan.job_failed", f"Wan job {job_id} failed", stage="wan")
            if state == "reserved":
                # Stage before the fenced sent marker so a takeover can replay it.
                self.transport.ready(request.kind)
                self.transport.stage(request.image_png, body["image_sha256"], "png")
                if isinstance(request, wan.SpeechToVideo):
                    self.transport.stage(request.drive_wav, body["audio_sha256"], "wav")
                self.progress("wan_submitting")
                self.claim.attempt(job_id, "sent")
                attempt = {**attempt, "state": "sent"}
                self._send(attempt)
            if job_id in self.downloaded:
                return self.downloaded.pop(job_id)
            clip = self._poll(attempt)
            if clip is not None:
                return clip
            restarts += 1
            if restarts > 1:
                raise LanePaused("wan.restarting", "Wan restarted again during this claim",
                                 job_id=job_id, wait_reason="gpu_unavailable")

    def make(self, request, *, stage, collected=(), keepable=False):
        try:
            clip = self._make(request)
            self.progress("rendering")
            return clip
        except LanePaused as error:
            self.stopped = error
            raise
