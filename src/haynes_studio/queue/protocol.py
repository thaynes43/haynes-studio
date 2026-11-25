"""JSON payloads shared by Studio's API and the queue worker."""

from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from haynes_studio.canonical.ids import is_id

API_VERSION = "1.0.0"
PROFILES = {"i2v": "wan2.2-ti2v-5b", "s2v": "wan2.2-s2v-14b-lightning"}
STORY_PATTERN = r"^https://work\.haynesnetwork\.com/work_packages/[1-9][0-9]*$"
SHA256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
JobId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500,
                                          pattern=r"^[^\x00-\x1f\x7f-\x9f]+$")]
JobKind = Literal["i2v", "s2v"]


class Payload(BaseModel):
    model_config = ConfigDict(defer_build=True, extra="forbid", strict=True)


class Reservation(Payload):
    kind: JobKind
    profile: str
    prompt: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4096)]
    negative_prompt: Annotated[str, StringConstraints(min_length=1, max_length=4096, pattern=r"\S")]
    seed: Annotated[int, Field(ge=0, le=2**53 - 1)]
    story: Annotated[str, StringConstraints(max_length=255, pattern=STORY_PATTERN)]
    width: Annotated[int, Field(ge=64, le=1280, multiple_of=32)]
    height: Annotated[int, Field(ge=64, le=1280, multiple_of=32)]
    image_sha256: SHA256
    frames: Annotated[int, Field(ge=5, le=121)] | None = None
    audio_sha256: SHA256 | None = None
    board_frames: Annotated[int, Field(ge=1, le=342)] | None = None

    def product_request(self):
        return self.model_dump(exclude={"kind"}, exclude_none=True)

    def supported(self):
        if self.profile != PROFILES[self.kind]:
            return False
        if self.kind == "i2v":
            return (self.frames is not None and self.frames % 4 == 1 and
                    self.audio_sha256 is None and self.board_frames is None)
        return (self.frames is None and self.audio_sha256 is not None and
                self.board_frames is not None and self.seed <= 2**53 - 3)


class WanResult(Payload):
    sha256: SHA256
    bytes: Annotated[int, Field(gt=0, le=512 * 1024 * 1024)]
    graph_sha256: SHA256


class AttemptChange(Payload):
    state: Literal["sent", "succeeded", "failed", "restart_failed", "busy"]
    result: WanResult | None = None


class ClaimFence(Payload):
    run_id: str
    fence: Annotated[int, Field(ge=1, lt=2**63)]

    def valid_run(self):
        return is_id(self.run_id, "run")


class Progress(Payload):
    percent: Annotated[int, Field(ge=0, le=99)]
    stage: Reason


class Heartbeat(ClaimFence):
    progress: Progress | None = None


class WorkReserve(ClaimFence):
    proposal: Reservation


class WorkAttempt(ClaimFence, AttemptChange):
    pass


class WorkCompletion(ClaimFence):
    stages: list[dict]
    outputs: dict
    checks: list[dict]
    provenance: dict
    delivery_id: str


class WorkFailure(ClaimFence):
    status: Literal["failed", "held", "queued", "cancelled"]
    wait_reason: Literal["lease_busy", "gpu_unavailable"] | None = None
    reason: Reason
    stages: list[dict] | None = None
    checks: list[dict] | None = None
    error: dict | None = None
    wan_job_id: JobId | None = None
    admission_busy: bool = False


WorkLane = Literal["run", "image", "voice", "matte"]
WORK_LANES = get_args(WorkLane)
MEDIA_LANES = tuple(lane for lane in WORK_LANES if lane != "run")


class WorkClaim(Payload):
    lane: WorkLane = "run"
    settle_only: bool = False


class MediaFence(Payload):
    job_id: str
    fence: Annotated[int, Field(ge=1, lt=2**63)]


class MatteRelease(MediaFence):
    reason: Literal["connect", "busy"] | None = None


class MediaHeartbeat(MediaFence):
    pass


class ImageEvidence(Payload):
    sha256: SHA256
    generator: dict
    licence: dict


class VoiceEvidence(Payload):
    version: dict


class MatteEvidence(Payload):
    matte_version: dict


class MediaCompletion(MediaFence):
    result: VoiceEvidence | ImageEvidence | MatteEvidence | None


class MediaFailure(MediaFence):
    code: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]{0,95}$")]
    message: Reason
