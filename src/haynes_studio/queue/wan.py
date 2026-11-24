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
EXPECTED_PROFILES = {
    "i2v": {"fps": 24, "steps": 20, "max_frames": 121, "timeout_seconds": 1200},
    "s2v": {"fps": 16, "steps": 4, "cfg": 1, "chunk_frames": 77,
            "max_chunks": 3, "timeout_seconds": 1200},
}


class LanePaused(RunHeld):
    def __init__(self, code, message, *, job_id=None, wait_reason=None):
        self.wait_reason = wait_reason
        super().__init__(code, message, job_id=job_id, detail={},
                         check="Reconcile the recorded job and check Wan readiness", stage="wan")


class BuildCancelled(BuildInterrupted):
    pass


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
            if (body.get("api_version") != API_VERSION or body.get("ready") is not True or
                    not {"active_video_job", "active_foley_job"} <= body.keys()):
                raise LanePaused("wan.ready_invalid", "Wan returned an incompatible readiness record")
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
        """A lost or malformed reply is resolved by GET, never by a second PUT."""
        try:
            response = self.client.put(_path(attempt), json=attempt["request"])
        except httpx.RequestError:
            return None
        if response.status_code == 409 and _error(response) == "worker_busy":
            return "busy"
        # Error replies other than the documented pre-admission refusal may
        # have been produced after Wan committed the job. Read its record.
        return None

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
            raise LanePaused("wan.result_invalid", "Wan reported invalid result metadata", job_id=job_id)
        try:
            with self.client.stream("GET", path) as response:
                if response.status_code != 200:
                    raise LanePaused("wan.download_failed", "Wan could not serve the result", job_id=job_id)
                data = bytearray()
                digest = sha256()
                for chunk in response.iter_bytes(chunk_size=1 << 20):
                    if len(data) + len(chunk) > result["bytes"]:
                        raise LanePaused("wan.result_invalid", "Wan returned more bytes than recorded", job_id=job_id)
                    data.extend(chunk)
                    digest.update(chunk)
        except httpx.RequestError as error:
            raise LanePaused("wan.download_failed", "Wan result download was interrupted",
                             job_id=job_id) from error
        if len(data) != result["bytes"] or digest.hexdigest() != result["sha256"]:
            raise LanePaused("wan.result_invalid", "Wan result byte count or SHA-256 differs", job_id=job_id)
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
    if wan.graph_sha256(graph) != body.get("graph_sha256"):
        raise LanePaused("wan.graph_mismatch", "Wan reported a graph outside the Studio profile pins",
                         job_id=job_id)
    data = transport.download(attempt, body)
    frames = request["frames"] if attempt["kind"] == "i2v" else wan.s2v_length(request["board_frames"])
    fps = wan.I2V_FPS if attempt["kind"] == "i2v" else wan.FPS
    try:
        measured = wan.measure_clip(data)
        rate = Fraction(measured.fps)
    except (ValueError, OSError, ZeroDivisionError) as error:
        raise LanePaused("wan.clip_invalid", "The downloaded clip could not be decoded", job_id=job_id) from error
    expected_frames = frames
    if attempt["kind"] == "s2v":
        chunks = (frames + wan.CHUNK - 1) // wan.CHUNK
        expected_frames = wan.s2v_frames_delivered([min(frames, wan.CHUNK)] + [wan.CHUNK] * (chunks - 1))
    if ((measured.width, measured.height) != (request["width"], request["height"]) or
            measured.frames != expected_frames or rate != fps):
        raise LanePaused("wan.clip_invalid", "The decoded clip dimensions, length or rate differ",
                         job_id=job_id)
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
                raise LanePaused("wan.job_conflict", "Wan already knows an unsubmitted ID",
                                 job_id=attempt["job_id"])
        else:
            clip, _ = self._poll(attempt)
            if clip is not None:
                self.downloaded[attempt["job_id"]] = clip

    def _poll(self, attempt):
        job_id = attempt["job_id"]
        deadline = self.clock() + POLL_LIMIT_SECONDS
        first_miss = None
        misses = 0
        while self.clock() < deadline:
            self.progress("wan_poll", drain=True)
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
            if body is None:
                raise LanePaused("wan.ambiguous_submit", "Wan has no record yet for the sent ID",
                                 job_id=job_id)
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
            state = body["state"]
            if state == "succeeded":
                clip = _result_clip(attempt, body, self.transport)
                result = {"bytes": len(clip.data), "sha256": clip.sha256,
                          "graph_sha256": body["graph_sha256"]}
                if attempt["state"] == "succeeded":
                    if result != attempt["outcome"]:
                        raise LanePaused("wan.result_changed", "Wan changed a verified result", job_id=job_id)
                else:
                    self.claim.attempt(job_id, "succeeded", result)
                return clip, False
            if attempt["state"] == "succeeded":
                raise LanePaused("wan.result_changed", "Wan no longer reports a verified result", job_id=job_id)
            if state == "failed":
                error = body.get("error")
                if error == "RuntimeError: ComfyUI already has a job; refusing a competing request":
                    raise LanePaused("wan.foreign_engine_queue", "Wan refused unknown ComfyUI work",
                                     job_id=job_id)
                if error in ("RuntimeError: Rack GPUs are busy; refusing to start a competing job",
                             "RuntimeError: Rack GPUs must be below 62 C for a product job"):
                    self.claim.attempt(job_id, "busy")
                    raise LanePaused("wan.busy", "Wan refused GPU admission",
                                     job_id=job_id, wait_reason="lease_busy")
                restarted = error == RESTART_ERROR
                self.claim.attempt(job_id, "restart_failed" if restarted else "failed")
                return None, restarted
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
                # Persisting a reservation and consuming its send permission are separate.
                # A lost acknowledgement of consuming permission must never trigger a PUT.
                self.transport.ready(request.kind)
                self.transport.stage(request.image_png, body["image_sha256"], "png")
                if isinstance(request, wan.SpeechToVideo):
                    self.transport.stage(request.drive_wav, body["audio_sha256"], "wav")
                self.progress("wan_submitting")
                self.claim.attempt(job_id, "sent")
                attempt = {**attempt, "state": "sent"}
                if self.transport.submit(attempt) == "busy":
                    self.claim.attempt(job_id, "busy")
                    raise LanePaused("wan.busy", "Wan refused admission to the shared lease",
                                     job_id=job_id, wait_reason="lease_busy")
            if job_id in self.downloaded:
                return self.downloaded.pop(job_id)
            clip, restarted = self._poll(attempt)
            if clip is not None:
                return clip
            if not restarted:
                raise BuildError("wan.job_failed", f"Wan job {job_id} failed", stage="wan")
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
