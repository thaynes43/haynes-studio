"""Wan clips on the studio's two RTX 3090s (story 842): image-to-video with Wan2.2
TI2V-5B and speech-to-video with Wan2.2 S2V-14B on the lightning profile.

Ported from ``poc/wan.py`` and ``poc/s2v.py``, the sanctioned E0 route: inside the Wan
API container (``ai/deploy/wan-video``, container ``api``) the pinned snippet
``wan_run.py`` imports the installed ``api`` module and runs its own ``generate()`` with
the client's graph, so the job holds the same ``/workspace/compute.lock`` as the HTTP
API, uses its watchdog, ledger and telemetry, and refuses unknown or competing work.
Nothing is deployed or changed. Reference: docs/reference/legacy-adapters.md.

:meth:`WanClipClient.render` is the only supported way to submit. Its guards run in the
PoC's order, and each one stops before anything is submitted:

0. Every pinned snippet and the template are checked before any command runs
   (``adapter.pin_mismatch``), and the graph is built from them.
1. One job per process (``adapter.busy``), and the client's :class:`Journal` held for the
   whole call (a second process on it is ``adapter.busy``, before anything runs) and read
   once (``adapter.journal_failed`` when it cannot be read exactly), so a job or halt an
   earlier process left blocks this one too. None after foreign engine work was seen
   (``adapter.competing_work``, until :meth:`WanClipClient.clear_halt`), none while an
   earlier job may still be running (``adapter.busy``, until that job's ledger reads
   ``failed`` and, if its prompt was accepted, a probe shows the engine queue empty; or
   :meth:`WanClipClient.clear_in_flight`), and none while an earlier job succeeded but
   its clip has not been collected (``adapter.busy``, until :meth:`WanClipClient.recover`
   fetches and checks it, or ``clear_in_flight``). The clears wait for no call: they
   refuse while one runs. The new job is journalled as in flight here, before the first
   probe.
2. Cool idle (``poc/wan.py`` ``wait_cool``): the API accepting with no active job and
   an empty engine queue, else a refusal at once; then exactly the two approved GPUs
   (``pinned.WAN_GPU_UUIDS``), each under 62 C and at most 5 % busy, read every 10 s for
   up to 1800 s, else a refusal. It only reads. An answer without both queue lists, ``accepting_jobs`` or the ``active_job``
   key is an error, never idle.
3. Inputs uploaded create-only under ``/workspace/input/studio-e0/``, named by hash; an
   existing name must hold the same bytes; the pod's read-back hash must match.
4. Cool idle again, right before the run: at once when still cool, else the same wait
   (reading only) or refusal.
5. ``wan_run.py``, byte for byte: the admission readback of ``/health`` just before
   submission, then ``api.generate()``, which takes the compute lease (a busy lease is
   a failed job, never a wait), checks the GPUs and the engine queue itself, submits
   once, and records foreign engine work seen during the job; engine reads that time
   out are retried read-only (writes never). The job sent is the PoC's plus one key,
   ``graph_sha256``, which :meth:`WanClipClient.recover` checks.
6. A job that did not succeed is an error. The job stays in flight until its finished
   ledger has been read; a lost, timed-out or non-zero-exit run leaves it so. Only these
   are known to have submitted nothing, and settle it: a refusal or failure before the
   run (either cool check, an upload), the runner could not start the command, or the
   admission readback refused. A failed job whose prompt was accepted stays until a
   probe shows the engine queue empty. A job whose ledger reads ``succeeded`` stays
   (``uncollected``) until its clip has been fetched and checked: a lost answer or a
   failed fetch or check is collected with :meth:`WanClipClient.recover`, never rendered
   again.
7. The clip is fetched read-only from ``/videos/<id>/file``, hash-checked against the
   pod's own read and the ledger's size, and decoded: a clip that does not decode, or
   whose size, frame count or measured rate is not exactly what the request's graph
   makes, is an error, never a clip.
8. Foreign engine work seen during the job: the clip is kept (on the error) and no
   further job is submitted, by this process or one using the same journal, until the
   halt is cleared.

The client never deletes, cancels, interrupts, moves or overwrites anything on the Wan
service or its volume, never changes GPU settings, and never retries a submission.
(``api.generate()`` itself, the installed code the PoC ran, removes or interrupts
*its own* prompt when its job fails; that is the API's behaviour, kept as it is.)

    client = WanClipClient(runner, journal=FileJournal(run_dir / "wan-journal.jsonl"))
    clip = client.render(ImageToVideo(image_png=png, prompt=text, seed=101, story=URL))
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import hashlib
import io
import json
import math
import os
import re
import threading
import time
import uuid
import wave
from dataclasses import dataclass, field, replace
from fractions import Fraction
from pathlib import Path
from typing import Any

from haynes_studio.adapters import pinned
from haynes_studio.adapters.errors import (
    BUSY,
    COMMAND_FAILED,
    COMPETING_WORK,
    JOB_FAILED,
    JOURNAL_FAILED,
    RESPONSE_INVALID,
    AdapterError,
    RequestInvalid,
    WanError,
    redact,
)
from haynes_studio.adapters.runner import (
    WAN_API,
    Command,
    Completed,
    ExecTarget,
    Runner,
    failure,
    run_checked,
)
from haynes_studio.jsonio import parse_strict

LABEL = "wan.render"
PROBE_LABEL = "wan.probe"
UPLOAD_LABEL = "wan.upload"
FETCH_LABEL = "wan.fetch"
READ_LABEL = "wan.read_job"
JOURNAL_LABEL = "wan.journal"

PROBE_SNIPPET = "wan_probe.py"
UPLOAD_SNIPPET = "wan_upload.py"
RUN_SNIPPET = "wan_run.py"
FETCH_SNIPPET = "wan_clip_fetch.py"
READ_SNIPPET = "wan_ledger_read.py"  # poc/deliver.py READ: GET /videos/<id>
I2V_GRAPH = "wan_ti2v_workflow.json"

# Timeouts, from poc/wan.py: remote(PROBE, timeout=30), the upload's timeout=30,
# remote(RUN, ..., timeout=1500), remote(fetch, timeout=90).
PROBE_TIMEOUT_S = 30
UPLOAD_TIMEOUT_S = 30
RUN_TIMEOUT_S = 1500
FETCH_TIMEOUT_S = 90
READ_TIMEOUT_S = 30  # wan_ledger.READ_TIMEOUT_S, poc/deliver.py's read-back

# poc/wan.py wait_cool(max_s=1800): a probe every 10 s; cool is every GPU under 62 C
# and at most 5 % busy.
COOL_MAX_S = 1800
COOL_POLL_S = 10
COOL_TEMP_C = 62
COOL_UTIL_PERCENT = 5
EXPECTED_GPUS = 2  # the studio's two RTX 3090s; api.gpu_sample() itself requires both

UPLOAD_FOLDER = "studio-e0"  # wan_upload.py writes /workspace/input/studio-e0/<name>
MAX_UPLOAD_BYTES = 20000000 - 1  # wan_upload.py asserts len(b) < 20000000
MAX_ANSWER_BYTES = 16 * 1024 * 1024  # a job ledger with its telemetry
MAX_CLIP_BYTES = 256 * 1024 * 1024  # proposal; the largest E0 clip is 5 204 854 bytes
MAX_PROMPT = 4096  # proposal: the Wan API's own prompt limit on POST /videos
MAX_SEED = 2 ** 53 - 1  # the Wan API's own seed limit on POST /videos
MIN_SIDE, MAX_SIDE, SIDE_STEP = 64, 1280, 32  # proposal; E0 ran 576x1024

# poc/wan.py: the negative prompt of every E0 clip, image and speech alike.
NEGATIVE = ('changing doll identity, changing faces, new faces, extra people, extra dolls, human hands, text, '
            'subtitles, watermark, camera shake, fast motion, cuts, scene change, blurry, distorted, melting')

# Image to video (poc/wan.py render()): the template's nodes that the filler edits,
# with the class each must have, and the settings E0 ran.
I2V_NODES = {'4': 'CLIPTextEncode', '5': 'CLIPTextEncode', '8': 'Wan22ImageToVideoLatent', '9': 'KSampler', '12': 'SaveVideo'}
I2V_STEPS = 20
I2V_FPS = 24  # the template's CreateVideo node
I2V_MAX_LENGTH = 121  # proposal: what E0 ran (5.04 s at 24 fps), 4k + 1 frames
I2V_STORY = "https://work.haynesnetwork.com/work_packages/387"  # what poc/wan.py recorded

# Speech to video (poc/s2v.py), lightning profile only.
FPS = 16
CHUNK = 77  # frames per S2V chunk, as in ComfyUI's template; longer clips chain Extend chunks
LORA = 'wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors'
S2V_MAX_CHUNKS = 3  # proposal: the longest E0 ran (231 frames, 716 s of the API's 1200 s)
S2V_STORY = "https://work.haynesnetwork.com/work_packages/394"  # what poc/s2v.py recorded

# Engine names for the clip-source interfaces (wholeframe.source.SourceClip.engine).
I2V_ENGINE = "wan-api/ti2v-5b"
S2V_ENGINE = "wan-api/s2v-14b-lightning"

# Model files the two graphs load, with their SHA-256 as the model licence register
# records them (docs/reference/model-licences.json, story 809). The client does not
# hash the files on the Wan volume; these are the register's values.
MODEL_FILES_SHA256 = {
    "wan2.2_ti2v_5B_fp16.safetensors": "456f901338bd9eadbded3828b819109a9b68e8a525ca5cf8d0049a69fcfeca1e",
    "umt5_xxl_fp8_e4m3fn_scaled.safetensors": "c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68",
    "wan2.2_vae.safetensors": "e40321bd36b9709991dae2530eb4ac303dd168276980d3e9bc4b6e2b75fed156",
    "wan2.2_s2v_14B_fp8_scaled.safetensors": "140e75af5534ac3d91e710d9df756f7032addd64b341ba2c1c70e3e6da9aa216",
    "wav2vec2_large_english_fp16.safetensors": "f0017a43ea57ef6b3d4866be607844bbd8cada6d30966f7d70044ed0d63d3f9e",
    "wan_2.1_vae.safetensors": "2fc39d31359a4b0a64f55876d8ff7fa8d780956ae2cb13463b0223e15148976b",
    LORA: "698321cb86bd30c4af06c9b84e656a1048c8cb54e06d50694536fb5de37fde41",
}
MODEL_INPUTS = ("unet_name", "clip_name", "vae_name", "lora_name", "audio_encoder_name")

JOB_ID = re.compile(r"[0-9a-f]{32}")  # the Wan API's JOB_ID
SHA256 = re.compile(r"[0-9a-f]{64}")
STORY = re.compile(r"https://work\.haynesnetwork\.com/work_packages/[1-9][0-9]{0,7}")
TERMINAL = ("succeeded", "failed")
# A job that blocks further renders is in one of two states: it may still be running
# (its finished ledger has not been read), or its ledger reads succeeded but its clip has
# not been fetched and checked.
IN_FLIGHT = "in_flight"
UNCOLLECTED = "uncollected"
# How a job stops blocking: its clip was fetched and checked (render or recover); its
# ledger reads failed; the run certainly submitted nothing (it never started, or the
# admission readback refused); a person cleared it.
OUTCOMES = ("collected", "failed", "no_submission", "cleared")
# The one non-zero exit of wan_run.py that certainly submitted nothing: its admission
# readback refused before api.save() and api.generate().
NO_SUBMISSION = "RuntimeError: Live API busy or hold; no submission"
UPLOAD_CONFLICT = "different file already uploaded"  # wan_upload.py's assertion
LEASE_BUSY = "Compute is reserved by another video/audio job"  # api.generate()'s refusal
CLIP_LINE = re.compile(r"^CLIP_SHA256 ([0-9a-f]{64}) ([0-9]{1,12})$", re.MULTILINE)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


# Requests -------------------------------------------------------------------------------

def _int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_common(prompt: Any, negative: Any, seed: Any, story: Any, width: Any, height: Any,
                  image_png: Any, spare_seeds: int = 0) -> None:
    for name, text in (("prompt", prompt), ("negative", negative)):
        if not isinstance(text, str) or not text.strip():
            raise RequestInvalid(LABEL, f"{name} must be non-empty text")
        if len(text) > MAX_PROMPT:
            raise RequestInvalid(LABEL, f"{name} is over {MAX_PROMPT} characters")
    if not _int(seed) or not 0 <= seed <= MAX_SEED - spare_seeds:
        raise RequestInvalid(LABEL, f"seed must be an integer from 0 to {MAX_SEED - spare_seeds}")
    if not isinstance(story, str) or not STORY.fullmatch(story):
        raise RequestInvalid(LABEL, "story must be a full https://work.haynesnetwork.com/work_packages/<id> URL")
    for side in (width, height):
        if not _int(side) or not MIN_SIDE <= side <= MAX_SIDE or side % SIDE_STEP:
            raise RequestInvalid(LABEL, f"width and height must be multiples of {SIDE_STEP} "
                                        f"from {MIN_SIDE} to {MAX_SIDE}")
    if not isinstance(image_png, bytes) or not image_png.startswith(PNG_SIGNATURE):
        raise RequestInvalid(LABEL, "image_png must be PNG bytes")
    if len(image_png) > MAX_UPLOAD_BYTES:
        raise RequestInvalid(LABEL, f"image_png is over {MAX_UPLOAD_BYTES} bytes")


def upload_name(data: bytes, suffix: str) -> str:
    """The name ``poc/wan.py`` uploads an input under: 16 hex digits of its SHA-256."""
    return f'{hashlib.sha256(data).hexdigest()[:16]}{suffix}'


@dataclass(frozen=True)
class ImageToVideo:
    """``poc/wan.py render()``: one TI2V-5B clip of ``length`` frames at 24 fps from a
    start image. ``story`` is the work package the Wan ledger records the job under."""

    image_png: bytes = field(repr=False)
    prompt: str
    seed: int
    story: str
    width: int = 576
    height: int = 1024
    length: int = 121
    negative: str = NEGATIVE

    def __post_init__(self):
        _check_common(self.prompt, self.negative, self.seed, self.story, self.width, self.height,
                      self.image_png)
        if not _int(self.length) or not 5 <= self.length <= I2V_MAX_LENGTH or self.length % 4 != 1:
            raise RequestInvalid(LABEL, f"length must be 4k + 1 frames from 5 to {I2V_MAX_LENGTH}")

    kind = "i2v"
    engine = I2V_ENGINE
    fps = I2V_FPS

    @property
    def frames_requested(self) -> int:
        return self.length

    @property
    def frames_expected(self) -> int:
        """The frames the graph delivers: exactly ``length``, as every E0 clip had."""
        return self.length

    @property
    def image_sha256(self) -> str:
        return hashlib.sha256(self.image_png).hexdigest()


def s2v_length(board_frames: int) -> int:
    """TIME-9: the requested length for a board of ``board_frames`` delivery frames,
    ``4 * ceil(F / 6) + 1``, then whole 77-frame chunks when over 77. In integers."""
    if not _int(board_frames) or board_frames < 1:
        raise ValueError("a board has at least one frame")
    length = 4 * ((board_frames + 5) // 6) + 1
    if length > CHUNK:  # Extend chunks are whole CHUNKs
        length = CHUNK * ((length + CHUNK - 1) // CHUNK)
    return length


def s2v_frames_needed(board_frames: int) -> int:
    """TIME-8: the source frames a board of ``board_frames`` frames shows at 16 fps."""
    return (board_frames - 1) * FPS // 24 + 1


def s2v_frames_delivered(chunk_lengths) -> int:
    """The frames an S2V graph delivers, as every E0 clip did: each chunk's latent frames
    (``(length - 1) // 4 + 1``) plus the doubled first one, decoded (4 frames per latent
    after the first), less the 3 that ``ImageFromBatch`` drops. 65 asked: 66; 154: 158."""
    latents = sum((length - 1) // 4 + 1 for length in chunk_lengths) + 1
    return 4 * (latents - 1) + 1 - 3


def _wav(data: Any) -> tuple[int, int]:
    """``(frames, rate)`` of a PCM WAV, or :class:`RequestInvalid`."""
    if not isinstance(data, bytes) or len(data) > MAX_UPLOAD_BYTES:
        raise RequestInvalid(LABEL, f"drive_wav must be WAV bytes, at most {MAX_UPLOAD_BYTES}")
    try:
        with wave.open(io.BytesIO(data)) as reader:
            frames, rate = reader.getnframes(), reader.getframerate()
    except (wave.Error, EOFError, ValueError):
        raise RequestInvalid(LABEL, "drive_wav is not a PCM WAV") from None
    if frames < 1 or rate < 1:
        raise RequestInvalid(LABEL, "drive_wav has no audio")
    return frames, rate


@dataclass(frozen=True)
class SpeechToVideo:
    """``poc/s2v.py --lightning`` for one board: the start image and the board's drive
    track (exactly ``board_frames / 24`` seconds, TIME-9) in, a 16 fps clip of
    :attr:`length` frames (TIME-9) out. Lightning profile only: the 4-step LoRA at cfg 1
    on one GPU, as every layered S2V clip of E0."""

    image_png: bytes = field(repr=False)
    drive_wav: bytes = field(repr=False)
    board_frames: int
    prompt: str
    seed: int
    story: str
    width: int = 576
    height: int = 1024
    negative: str = NEGATIVE

    kind = "s2v"
    engine = S2V_ENGINE
    fps = FPS
    lightning = True

    def __post_init__(self):
        if not _int(self.board_frames) or self.board_frames < 1:
            raise RequestInvalid(LABEL, "board_frames must be a positive integer")
        length = s2v_length(self.board_frames)
        if length > CHUNK * S2V_MAX_CHUNKS:
            raise RequestInvalid(LABEL, f"a board of {self.board_frames} frames needs "
                                        f"{length // CHUNK} chunks; at most {S2V_MAX_CHUNKS}")
        _check_common(self.prompt, self.negative, self.seed, self.story, self.width, self.height,
                      self.image_png, spare_seeds=S2V_MAX_CHUNKS - 1)
        frames, rate = _wav(self.drive_wav)
        exact = self.board_frames * rate  # TIME-9: the drive lasts F / 24 s, to one sample
        if not exact // 24 <= frames <= -(-exact // 24):
            raise RequestInvalid(LABEL, f"drive_wav is {frames} samples at {rate} Hz; a board of "
                                        f"{self.board_frames} frames needs {exact / 24:g}")
        if length < s2v_frames_needed(self.board_frames):  # TIME-9; true by the formula
            raise RequestInvalid(LABEL, "length is shorter than the board needs")

    @property
    def length(self) -> int:
        return s2v_length(self.board_frames)

    @property
    def chunks(self) -> int:
        return max(1, math.ceil(self.length / CHUNK))

    @property
    def frames_requested(self) -> int:
        return self.length

    @property
    def frames_expected(self) -> int:
        """The frames the graph delivers (:func:`s2v_frames_delivered` for its chunks)."""
        return s2v_frames_delivered([min(self.length, CHUNK)] + [CHUNK] * (self.chunks - 1))

    @property
    def image_sha256(self) -> str:
        return hashlib.sha256(self.image_png).hexdigest()

    @property
    def drive(self) -> tuple[int, int]:
        """``(samples, rate)`` of the drive track."""
        return _wav(self.drive_wav)


WanRequest = ImageToVideo | SpeechToVideo


# Graphs and jobs, as the PoC builds them ---------------------------------------------------

def i2v_graph(template: bytes, *, prompt: str, negative: str, width: int, height: int, length: int,
              seed: int, steps: int, job_id: str, up_name: str) -> dict:
    """The graph ``poc/wan.py render()`` submits: the template with the same edits, in the
    same order. The ``graph[...]`` lines are the PoC's lines (a test compares them)."""
    graph = json.loads(template)
    for node, cls in I2V_NODES.items():
        if graph.get(node, {}).get('class_type') != cls:
            raise RequestInvalid(LABEL, f"{I2V_GRAPH} node {node} is not {cls}")
    job = {'id': job_id}
    graph['4']['inputs']['text'] = prompt
    graph['5']['inputs']['text'] = negative
    graph['8']['inputs'].update(width=width, height=height, length=length, start_image=['13', 0])
    graph['9']['inputs'].update(seed=seed, steps=steps)
    graph['12']['inputs']['filename_prefix'] = 'video/' + job['id']
    graph['13'] = {'class_type': 'LoadImage', 'inputs': {'image': 'studio-e0/' + up_name}}
    return graph


def i2v_job(*, job_id: str, width: int, height: int, length: int, seed: int, created_at: float,
            up_name: str, digest: str, story: str) -> dict:
    """The job ledger ``poc/wan.py render()`` hands to ``api.generate()``."""
    return {'id': job_id, 'state': 'queued', 'preset': f'studio-e0-i2v-{width}x{height}-{length}f',
            'seed': seed, 'created_at': created_at, 'telemetry': [], 'kind': 'reference_conditioned_render',
            'reference_image': 'studio-e0/' + up_name, 'reference_sha256': digest,
            'story': story}


# poc/s2v.py graph(), byte for byte apart from its name (a test compares the two functions).
def s2v_graph(prompt, negative, image, audio, width, height, length, seed, prefix, lightning=False):
    """`length` frames: one WanSoundImageToVideo chunk, plus Extend chunks when longer than
    CHUNK (the template's structure). `lightning` uses the template's fast path: the 4-step
    LoRA at cfg 1 on one GPU; otherwise 20 steps at cfg 6 with the CFG split over both GPUs."""
    chunks = max(1, math.ceil(length / CHUNK)); first = min(length, CHUNK)
    steps, cfg = (4, 1.0) if lightning else (20, 6.0)
    g = {
        '1': {'class_type': 'UNETLoader', 'inputs': {'unet_name': 'wan2.2_s2v_14B_fp8_scaled.safetensors', 'weight_dtype': 'default'}},
        '2': {'class_type': 'CLIPLoader', 'inputs': {'clip_name': 'umt5_xxl_fp8_e4m3fn_scaled.safetensors', 'type': 'wan', 'device': 'default'}},
        '3': {'class_type': 'VAELoader', 'inputs': {'vae_name': 'wan_2.1_vae.safetensors'}},
        '4': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['2', 0], 'text': prompt}},
        '5': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['2', 0], 'text': negative}},
        '7': {'class_type': 'AudioEncoderLoader', 'inputs': {'audio_encoder_name': 'wav2vec2_large_english_fp16.safetensors'}},
        '8': {'class_type': 'LoadAudio', 'inputs': {'audio': audio}},
        '9': {'class_type': 'AudioEncoderEncode', 'inputs': {'audio_encoder': ['7', 0], 'audio': ['8', 0]}},
        '10': {'class_type': 'LoadImage', 'inputs': {'image': image}},
        '11': {'class_type': 'WanSoundImageToVideo', 'inputs': {'positive': ['4', 0], 'negative': ['5', 0], 'vae': ['3', 0],
               'width': width, 'height': height, 'length': first, 'batch_size': 1,
               'audio_encoder_output': ['9', 0], 'ref_image': ['10', 0]}},
    }
    if lightning:
        g['17'] = {'class_type': 'LoraLoaderModelOnly', 'inputs': {'model': ['1', 0], 'lora_name': LORA, 'strength_model': 1.0}}
        g['6'] = {'class_type': 'ModelSamplingSD3', 'inputs': {'model': ['17', 0], 'shift': 8.0}}
        model = ['6', 0]
    else:
        g['6'] = {'class_type': 'ModelSamplingSD3', 'inputs': {'model': ['1', 0], 'shift': 8.0}}
        # Both 3090s: the CFG passes split across two model copies, as in the Wan workflow.json.
        g['16'] = {'class_type': 'MultiGPU_WorkUnits', 'inputs': {'model': ['6', 0], 'max_gpus': 2}}
        model = ['16', 0]
    sampler = {'steps': steps, 'cfg': cfg, 'sampler_name': 'uni_pc', 'scheduler': 'simple', 'denoise': 1.0}
    g['12'] = {'class_type': 'KSampler', 'inputs': {'model': model, 'positive': ['11', 0], 'negative': ['11', 1],
               'latent_image': ['11', 2], 'seed': seed, **sampler}}
    latent = ['12', 0]
    for k in range(1, chunks):
        n = 100 + 10 * k
        g[str(n)] = {'class_type': 'WanSoundImageToVideoExtend', 'inputs': {'positive': ['4', 0], 'negative': ['5', 0],
                     'vae': ['3', 0], 'length': CHUNK, 'video_latent': latent, 'audio_encoder_output': ['9', 0], 'ref_image': ['10', 0]}}
        g[str(n + 1)] = {'class_type': 'KSampler', 'inputs': {'model': model, 'positive': [str(n), 0], 'negative': [str(n), 1],
                         'latent_image': [str(n), 2], 'seed': seed + k, **sampler}}
        g[str(n + 2)] = {'class_type': 'LatentConcat', 'inputs': {'samples1': latent, 'samples2': [str(n + 1), 0], 'dim': 't'}}
        latent = [str(n + 2), 0]
    # The template's fix for an overbaked first frame: double the first latent frame, decode,
    # then drop the frames it produced.
    g['18'] = {'class_type': 'LatentCut', 'inputs': {'samples': latent, 'dim': 't', 'index': 0, 'amount': 1}}
    g['19'] = {'class_type': 'LatentConcat', 'inputs': {'samples1': ['18', 0], 'samples2': latent, 'dim': 't'}}
    g['13'] = {'class_type': 'VAEDecode', 'inputs': {'samples': ['19', 0], 'vae': ['3', 0]}}
    g['20'] = {'class_type': 'ImageFromBatch', 'inputs': {'image': ['13', 0], 'batch_index': 3, 'length': 4096}}
    g['14'] = {'class_type': 'CreateVideo', 'inputs': {'images': ['20', 0], 'fps': float(FPS), 'audio': ['8', 0]}}
    g['15'] = {'class_type': 'SaveVideo', 'inputs': {'video': ['14', 0], 'filename_prefix': prefix, 'format': 'mp4', 'codec': 'h264'}}
    return g



def s2v_job(*, job_id: str, width: int, height: int, length: int, seed: int, created_at: float,
            image: str, image_sha: str, audio: str, audio_sha: str, story: str,
            lightning: bool = True) -> dict:
    """The job ledger ``poc/s2v.py main()`` hands to ``api.generate()``."""
    return {'id': job_id, 'state': 'queued', 'preset': f"studio-e0-s2v{'-lightning' if lightning else ''}-{width}x{height}-{length}f", 'seed': seed,
            'created_at': created_at, 'telemetry': [], 'kind': 'reference_conditioned_render', 'reference_image': image,
            'reference_sha256': image_sha, 'audio': audio, 'audio_sha256': audio_sha,
            'story': story}


def graph_sha256(g: dict) -> str:
    """SHA-256 of ``json.dumps(graph, sort_keys=True)``, as the ComfyUI client records."""
    return hashlib.sha256(json.dumps(g, sort_keys=True).encode()).hexdigest()


def model_files(g: dict) -> dict[str, str]:
    """The model files a graph loads, with the register's SHA-256 for each."""
    names = sorted({node['inputs'][key] for node in g.values() for key in MODEL_INPUTS
                    if isinstance(node.get('inputs', {}).get(key), str)})
    unknown = [n for n in names if n not in MODEL_FILES_SHA256]
    if unknown:
        raise RequestInvalid(LABEL, f"graph loads a model file the register does not list: {unknown[0]}")
    return {name: MODEL_FILES_SHA256[name] for name in names}


# Answers ------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Probe:
    """One ``wan_probe.py`` answer: the API's ``/health``, ``api.gpu_sample()`` and the
    engine's ``/queue``."""

    health: dict
    gpus: tuple[dict, ...]
    queue: dict

    @property
    def cool(self) -> bool:
        """``poc/wan.py wait_cool``'s test: every GPU under 62 C and at most 5 % busy."""
        return all(g['temperature_c'] < COOL_TEMP_C and g['utilization_percent'] <= COOL_UTIL_PERCENT
                   for g in self.gpus)


@dataclass(frozen=True)
class Upload:
    ref: str  # the name the graph loads: studio-e0/<16 hex digits><suffix>
    sha256: str
    bytes: int


@dataclass(frozen=True)
class InFlightJob:
    """A Wan job that blocks further renders: its ID; the error code of the call that
    left it (``unknown`` before the run's outcome is known, ``journal`` when loaded from
    an earlier process's journal); its state, ``in_flight`` (it may still be running)
    or ``uncollected`` (its ledger reads succeeded, its clip has not been fetched and
    checked); and the SHA-256 of the graph it was sent with."""

    job_id: str
    code: str
    state: str
    graph_sha256: str


@dataclass(frozen=True)
class Halt:
    """Why this process submits no more Wan jobs: the job during which foreign engine
    work was seen, and the prompt IDs seen."""

    job_id: str
    unexpected_work_seen: tuple[str, ...]


# The journal -------------------------------------------------------------------------------

def _journal_error(message: str) -> WanError:
    return WanError(JOURNAL_FAILED, JOURNAL_LABEL, f"{message}; nothing is submitted until a "
                    "person has inspected the journal and the Wan service (its engine queue and "
                    "the ledger of every job the journal names); replacing the file discards the "
                    "only record of a job the engine queue may not show yet")


def _journal_busy(name: Any) -> WanError:
    return WanError(BUSY, JOURNAL_LABEL, f"journal {name} is held by another process (one process "
                    "at a time on a journal); nothing was probed, uploaded or submitted")


# Each event's keys besides "v", "event" and "at".
_EVENT_KEYS = {"created": set(), "remember": {"job_id", "state", "graph_sha256"},
               "settle": {"job_id", "outcome"}, "halt": {"job_id", "unexpected_work_seen"},
               "clear_halt": {"job_id"}}


def _event_problem(event: Any) -> str | None:
    """What is wrong with one journal event, or None."""
    if not isinstance(event, dict) or event.get("v") != 1 or event.get("event") not in _EVENT_KEYS:
        return "not a version 1 event"
    if set(event) != _EVENT_KEYS[event["event"]] | {"v", "event", "at"} or not isinstance(event["at"], str):
        return f"{event['event']} has other keys than {sorted(_EVENT_KEYS[event['event']])} and at"
    if event["event"] == "created":
        return None
    if not isinstance(event["job_id"], str) or not JOB_ID.fullmatch(event["job_id"]):
        return "job_id is not a Wan job ID"
    if event["event"] == "remember" and (event["state"] not in (IN_FLIGHT, UNCOLLECTED)
                                         or not isinstance(event["graph_sha256"], str)
                                         or not SHA256.fullmatch(event["graph_sha256"])):
        return "remember needs a state and a graph SHA-256"
    if event["event"] == "settle" and event["outcome"] not in OUTCOMES:
        return f"settle outcome is not one of {list(OUTCOMES)}"
    seen = event.get("unexpected_work_seen")
    if event["event"] == "halt" and (not isinstance(seen, list) or not seen
                                     or not all(isinstance(s, str) for s in seen)):
        return "halt needs the prompt IDs seen"
    return None


@dataclass(frozen=True)
class JournalState:
    """One read of a journal: the job that blocks (or None), the halt (or None), and every
    job ID any line names (a job this process holds that the journal does not name means
    the file was replaced or cut)."""

    job: InFlightJob | None
    halt: Halt | None
    named: frozenset[str]


class Journal:
    """Where a :class:`WanClipClient` keeps the job that blocks further renders and the
    halt, so both outlive the process. A :class:`WanClipClient` needs one.

    Each event is one JSON line, appended and never rewritten: ``remember`` (a job, before
    its first probe, and again when its state changes to ``uncollected``), ``settle`` (it
    no longer blocks; ``outcome`` is ``collected``, ``failed``, ``no_submission`` or
    ``cleared``), ``halt`` and ``clear_halt``. :meth:`read_state` replays the lines in one
    read; anything it cannot read exactly (a line that is not one of these events, an
    incomplete last line, a second unsettled job, a settle or clear of something not set)
    is ``adapter.journal_failed``, and nothing is submitted. Every call that may submit,
    collect or clear holds the journal for its whole length (:meth:`hold`,
    :meth:`release`); a second holder is ``adapter.busy``. Subclasses keep the lines:
    :class:`FileJournal` for real runs, :class:`MemoryJournal` for tests."""

    def __init__(self, *, wall=time.time):
        self.wall = wall

    def _read(self) -> bytes | None:
        raise NotImplementedError

    def _append(self, line: bytes) -> None:
        raise NotImplementedError

    def hold(self) -> None:
        """Take the journal for one call, or ``adapter.busy`` when another holds it."""
        raise NotImplementedError

    def release(self) -> None:
        raise NotImplementedError

    def same(self, other: Journal | None) -> bool:
        """Whether ``other`` keeps the same lines as this journal."""
        return other is self

    def check(self) -> None:
        """While held: ``adapter.journal_failed`` if the journal was removed or replaced
        since the hold. A call checks before each step that sends a command."""

    def load(self) -> InFlightJob | None:
        """The job that blocks further renders (code ``journal``), or None."""
        return self.read_state().job

    def load_halt(self) -> Halt | None:
        """The halt after foreign engine work, or None."""
        return self.read_state().halt

    def remember(self, job_id: str, state: str, graph_sha256: str) -> None:
        self._write({"event": "remember", "job_id": job_id, "state": state, "graph_sha256": graph_sha256})

    def settle(self, job_id: str, outcome: str) -> None:
        self._write({"event": "settle", "job_id": job_id, "outcome": outcome})

    def halt(self, job_id: str, unexpected_work_seen) -> None:
        self._write({"event": "halt", "job_id": job_id, "unexpected_work_seen": list(unexpected_work_seen)})

    def clear_halt(self, job_id: str) -> None:
        self._write({"event": "clear_halt", "job_id": job_id})

    def _created_line(self) -> bytes:
        """The first line of every journal file, written when it is created."""
        event = {"v": 1, "event": "created", "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.wall()))}
        assert _event_problem(event) is None
        return (json.dumps(event) + "\n").encode()

    def _write(self, event: dict) -> None:
        event = {"v": 1, **event, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.wall()))}
        problem = _event_problem(event)
        if problem:  # never write a line read_state() would refuse
            raise ValueError(f"not a journal event: {problem}")
        line = (json.dumps(event) + "\n").encode()
        try:
            self._append(line)
        except OSError as error:
            raise _journal_error(f"the journal could not be written ({type(error).__name__})") from None

    def read_state(self) -> JournalState:
        """One read of the journal, replayed. A journal not created yet is empty; one that
        exists must start with its ``created`` line."""
        try:
            data = self._read()
        except OSError as error:
            raise _journal_error(f"the journal could not be read ({type(error).__name__})") from None
        if data is None:  # first use: nothing created yet
            return JournalState(None, None, frozenset())
        if not data:
            raise _journal_error(_EMPTIED)
        if data and not data.endswith(b"\n"):
            raise _journal_error("the journal's last line is incomplete")
        try:
            lines = data.decode("utf-8").split("\n")[:-1]
        except UnicodeDecodeError:
            raise _journal_error("the journal is not UTF-8 text") from None
        job: InFlightJob | None = None
        halt: Halt | None = None
        named: set[str] = set()
        for number, line in enumerate(lines, 1):
            try:
                event = parse_strict(line)
            except (ValueError, RecursionError):
                raise _journal_error(f"journal line {number} is not JSON") from None
            problem = _event_problem(event)
            if problem:
                raise _journal_error(f"journal line {number}: {problem}")
            if (event["event"] == "created") != (number == 1):  # the first line, and only it
                raise _journal_error(_EMPTIED if number == 1 else
                                     f"journal line {number} is a second created line")
            if event["event"] == "created":
                continue
            kind, job_id = event["event"], event["job_id"]
            if kind == "remember":
                if job is not None and (job.job_id != job_id or job.graph_sha256 != event["graph_sha256"]):
                    raise _journal_error(f"journal line {number} remembers job {job_id} while job "
                                         f"{job.job_id} is unsettled")
                job = InFlightJob(job_id, "journal", event["state"], event["graph_sha256"])
            elif kind == "settle":
                if job is None or job.job_id != job_id:
                    raise _journal_error(f"journal line {number} settles job {job_id}, which is not unsettled")
                job = None
            elif kind == "halt":  # a later line for the same job extends it; it never moves
                if halt is not None and halt.job_id != job_id:
                    raise _journal_error(f"journal line {number} sets a halt for job {job_id} while "
                                         f"the halt of job {halt.job_id} is set")
                halt = Halt(job_id, tuple(event["unexpected_work_seen"]))
            else:
                if halt is None or halt.job_id != job_id:
                    raise _journal_error(f"journal line {number} clears a halt that is not set")
                halt = None
            named.add(job_id)
        return JournalState(job, halt, frozenset(named))


class MemoryJournal(Journal):
    """A journal in memory, lost with the process: for tests only. ``data`` holds the
    lines exactly as :class:`FileJournal` writes them, its ``created`` line first
    (``None``: not created yet, or removed once used); ``held`` models the lock file,
    ``used`` that the lock file exists. It keeps
    a :class:`FileJournal`'s rules: an append outside a call holds it for that append; a
    journal removed or replaced (:meth:`replace`) while held is
    ``adapter.journal_failed`` at the next read, append or :meth:`check`; and one removed
    after it was used is ``adapter.journal_failed`` until a person starts it afresh."""

    def __init__(self, data: bytes | None = None, *, wall=time.time):
        super().__init__(wall=wall)
        self.data = data  # None: not created yet (or removed, once used)
        self.held = False
        self.used = False
        self._generation = 0
        self._held_generation: int | None = None

    def replace(self, data: bytes | None) -> None:
        """Test hook: the journal removed (``None``) or replaced by other lines, as a
        person or another program could do to the file."""
        self.data = data
        self._generation += 1

    def check(self) -> None:
        if self.held and self._generation != self._held_generation:
            raise _journal_error(_moved("in memory"))

    def _read(self) -> bytes | None:
        self.check()
        if self.data is None:
            if self.used:
                raise _journal_error(_missing_after_use("in memory"))
            return None
        return self.data

    def _append(self, line: bytes) -> None:
        if not self.held:
            self.hold()
            try:
                self._append(line)
            finally:
                self.release()
            return
        self.check()
        self.data += line

    def hold(self) -> None:
        if self.held:
            raise _journal_busy("in memory")
        if self.data is None and self.used:
            raise _journal_error(_missing_after_use("in memory"))
        if self.data is None:
            self.data = self._created_line()  # first use
        self.held, self.used, self._held_generation = True, True, self._generation

    def release(self) -> None:
        self.held, self._held_generation = False, None


def _sync_directory(path: Path) -> None:
    """``fsync`` a directory, so a file just created in it survives a crash."""
    directory = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    except OSError as error:
        if error.errno != errno.EINVAL:  # a file system that cannot sync a directory
            raise
    finally:
        os.close(directory)


def _create_or_open(path: Path, flags: int) -> tuple[int, bool]:
    """A descriptor on ``path``, and whether this call created the file (then its
    directory is synced, so the new name survives a crash)."""
    flags |= os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags | os.O_EXCL, 0o600)
    except FileExistsError:
        return os.open(path, flags, 0o600), False
    try:
        _sync_directory(path.parent)
    except BaseException:
        os.close(fd)
        raise
    return fd, True


def _same_file(path: Path, fd: int) -> bool:
    """Whether ``path`` still names the file ``fd`` has open (same device and inode)."""
    try:
        named = os.stat(path)
    except FileNotFoundError:
        return False
    held = os.fstat(fd)
    return (named.st_dev, named.st_ino) == (held.st_dev, held.st_ino)


class FileJournal(Journal):
    """The journal for real runs: an append-only JSON-lines file on a local file system,
    with a lock file beside it (``<journal>.lock``).

    :meth:`hold` takes an exclusive ``flock`` on the lock file without waiting, so a
    second process (or a second ``FileJournal`` on the same path) is refused while one
    call holds it, whether or not the journal file still exists; then one on the journal
    file itself, so a second name for it (a symlink, a hard link: another lock file) is
    refused too, before it reads anything. The lock file is
    created if missing and is never written, replaced or deleted by the client. While
    held, the journal is read and appended only through one descriptor on the journal
    file, and before each read, append and :meth:`check` the path of the journal and of
    the lock file must still name the files those descriptors hold; a journal removed or
    replaced while in use is ``adapter.journal_failed``. Each event is one ``os.write``
    to that descriptor (opened ``O_APPEND``), then ``fsync``; a new file's directory is
    synced too. The journal is never rewritten, truncated or deleted. Its first line,
    written when the file is created and before any job, is ``created``; a journal file
    that is empty or does not start with it was emptied or replaced, and is
    ``adapter.journal_failed``. A missing journal is an empty one on first use only: with
    its lock file present it was removed between runs, and that is
    ``adapter.journal_failed`` too. An append outside a call
    holds the journal for that append. Keep both files under the store root, the same
    path for every run."""

    def __init__(self, path, *, wall=time.time):
        super().__init__(wall=wall)
        self.path = Path(path)
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self._lock_fd: int | None = None
        self._fd: int | None = None

    def same(self, other: Journal | None) -> bool:
        return isinstance(other, FileJournal) and os.path.realpath(self.path) == os.path.realpath(other.path)

    def check(self) -> None:
        """While held: the journal and its lock file are still the files this call holds."""
        if self._fd is None:
            return
        if not _same_file(self.path, self._fd) or not _same_file(self.lock_path, self._lock_fd):
            raise _journal_error(_moved(self.path))

    def _read(self) -> bytes | None:
        if self._fd is not None:
            self.check()
            size, chunks, offset = os.fstat(self._fd).st_size, [], 0
            while offset < size:
                chunk = os.pread(self._fd, size - offset, offset)
                if not chunk:
                    break
                chunks.append(chunk)
                offset += len(chunk)
            return b"".join(chunks)
        try:
            return self.path.read_bytes()
        except FileNotFoundError:
            if self.lock_path.exists():
                raise _journal_error(_missing_after_use(self.path)) from None
            return None  # first use

    def _append(self, line: bytes) -> None:
        if self._fd is None:  # outside a call: hold the journal for this one append
            self.hold()
            try:
                self._append(line)
            finally:
                self.release()
            return
        self.check()
        if os.write(self._fd, line) != len(line):
            raise OSError(errno.EIO, "short write to the journal")
        os.fsync(self._fd)

    def hold(self) -> None:
        if self._lock_fd is not None:
            raise _journal_busy(self.path)
        try:
            lock_fd, first_use = _create_or_open(self.lock_path, os.O_RDONLY)
        except OSError as error:
            raise _journal_error(f"the journal's lock file could not be opened to hold it "
                                 f"({type(error).__name__})") from None
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(lock_fd)
            raise _journal_busy(self.path) from None
        except OSError as error:
            os.close(lock_fd)
            raise _journal_error(f"the journal could not be locked ({type(error).__name__}); it must be "
                                 "on a local file system") from None
        try:
            try:
                fd, created = os.open(self.path, os.O_RDWR | os.O_APPEND | getattr(os, "O_CLOEXEC", 0)), False
            except FileNotFoundError:
                if not first_use:  # the lock file shows it was used: it was removed since
                    raise _journal_error(_missing_after_use(self.path)) from None
                fd, made = _create_or_open(self.path, os.O_RDWR | os.O_APPEND)
                created = True  # it did not exist a moment ago, and the lock file is held
                if not made:  # created through a symlink (O_EXCL refuses one): sync its directory
                    _sync_directory(Path(os.path.realpath(self.path)).parent)
        except OSError as error:
            _unlock(lock_fd)
            raise _journal_error(f"the journal could not be opened ({type(error).__name__})") from None
        except BaseException:
            _unlock(lock_fd)
            raise
        try:
            # The journal file itself too: another name for it (a symlink, a hard link) has
            # another lock file, but not another file.
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if created:  # its first line, before any job can be remembered
                line = self._created_line()
                if os.write(fd, line) != len(line):
                    raise OSError(errno.EIO, "short write to the journal")
                os.fsync(fd)
        except BlockingIOError:
            os.close(fd)
            _unlock(lock_fd)
            raise _journal_busy(self.path) from None
        except OSError as error:
            os.close(fd)
            _unlock(lock_fd)
            raise _journal_error(f"the journal could not be locked or started ({type(error).__name__})") from None
        except BaseException:
            os.close(fd)
            _unlock(lock_fd)
            raise
        self._lock_fd, self._fd = lock_fd, fd

    def release(self) -> None:
        fd, self._fd = self._fd, None
        lock_fd, self._lock_fd = self._lock_fd, None
        try:
            if fd is not None:
                os.close(fd)
        finally:
            if lock_fd is not None:
                _unlock(lock_fd)


def _unlock(lock_fd: int) -> None:
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
    finally:
        os.close(lock_fd)


_EMPTIED = ("the journal is empty or does not start with its created line: it was emptied or "
            "replaced, or the call that created it stopped before writing that line (that call "
            "submitted nothing: the created line is written before any job is remembered, and a "
            "job is remembered before the first probe). A person inspects the Wan service, then "
            "removes the journal and its lock file to start afresh")


def _moved(name: Any) -> str:
    return (f"journal {name} was removed or replaced while this call held it; nothing more is "
            "probed, uploaded or submitted, and its job stays unsettled in this process")


def _missing_after_use(name: Any) -> str:
    return (f"journal {name} is missing but its lock file shows it was used: it was removed "
            "between runs. After checking the Wan service a person may delete the lock file "
            "too, to start afresh")


@dataclass(frozen=True)
class Measured:
    frames: int
    width: int
    height: int
    fps: str  # the stream's average rate as a fraction, as read


@dataclass(frozen=True)
class WanClip:
    """One delivered clip and its provenance record (plain JSON, see
    :meth:`WanClipClient.render`). For a clip-source interface: ``engine``,
    ``job_id``, ``files_sha256`` and ``start_image_sha256`` are its fields."""

    data: bytes = field(repr=False)
    record: dict = field(repr=False)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    @property
    def job_id(self) -> str:
        return self.record["job_id"]

    @property
    def engine(self) -> str:
        return self.record["engine"]

    @property
    def files_sha256(self) -> dict[str, str]:
        return dict(self.record["model_files_sha256"])

    @property
    def start_image_sha256(self) -> str:
        return self.record["inputs"]["image"]["sha256"]

    @property
    def frames(self) -> int:
        return self.record["frames_delivered"]


def measure_clip(data: bytes) -> Measured:
    """Decode every frame (two threads, as ``poc/wan.py``) and read the picture size.
    Raises ``ValueError`` for anything that does not decode as one video stream."""
    import av  # noqa: PLC0415 - only a render decodes; importing the package stays light

    problem, frames, width, height, rate = None, 0, None, None, None
    try:
        with av.open(io.BytesIO(data)) as container:
            if container.streams.video:
                stream = container.streams.video[0]
                stream.codec_context.thread_count = 2
                for frame in container.decode(stream):
                    width, height = frame.width, frame.height
                    frames += 1
                rate = stream.average_rate
            else:
                problem = "no video stream"
    except Exception as error:  # PyAV's FFmpegError family, and anything a bad file raises
        problem = type(error).__name__
    if problem is None and frames == 0:
        problem = "no frame decodes"
    if problem is not None:
        raise ValueError(problem)
    return Measured(frames, width, height, str(rate) if rate is not None else "")


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _ids(value: Any) -> list[str] | None:
    if not value:
        return None
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return sorted(set(value))
    return ["<unreadable>"]


def _new_job_id() -> str:
    return uuid.uuid4().hex


# The client ---------------------------------------------------------------------------------

class WanClipClient:
    """Image-to-video and speech-to-video clips through the E0 route. See the module
    notes for the guards, in order. ``journal`` is required: a :class:`FileJournal`
    under the run's own directory (tests: :class:`MemoryJournal`); construction loads it,
    so a job or halt an earlier process left there blocks this process as if it had
    made it, and every call that may submit, collect or clear holds it. ``clock``
    (monotonic seconds), ``wall`` (epoch seconds) and ``sleep`` are injectable for
    tests; nothing here sleeps except the cool-idle wait between probes."""

    # Per process, shared by every WanClipClient: one job at a time, the job that blocks
    # further renders and the halt after foreign engine work, each with the journal that
    # records it.
    _lock = threading.Lock()
    _unsettled: InFlightJob | None = None
    _unsettled_journal: Journal | None = None
    _halt: Halt | None = None
    _halt_journal: Journal | None = None

    def __init__(self, runner: Runner, *, journal: Journal, target: ExecTarget = WAN_API,
                 probe_snippet: pinned.PinnedInput | None = None,
                 upload_snippet: pinned.PinnedInput | None = None,
                 run_snippet: pinned.PinnedInput | None = None,
                 fetch_snippet: pinned.PinnedInput | None = None,
                 read_snippet: pinned.PinnedInput | None = None,
                 i2v_template: pinned.PinnedInput | None = None,
                 clock=time.monotonic, wall=time.time, sleep=time.sleep, new_job_id=_new_job_id):
        def take(item, name):
            return pinned.check(item, name) if item else pinned.load(name)
        if not isinstance(journal, Journal):
            raise TypeError("WanClipClient needs a journal: FileJournal(<the run's directory>/"
                            "wan-journal.jsonl), or MemoryJournal() in tests")
        self.runner = runner
        self.target = target
        self.probe_snippet = take(probe_snippet, PROBE_SNIPPET)
        self.upload_snippet = take(upload_snippet, UPLOAD_SNIPPET)
        self.run_snippet = take(run_snippet, RUN_SNIPPET)
        self.fetch_snippet = take(fetch_snippet, FETCH_SNIPPET)
        self.read_snippet = take(read_snippet, READ_SNIPPET)
        self.i2v_template = take(i2v_template, I2V_GRAPH)
        self.clock = clock
        self.wall = wall
        self.sleep = sleep
        self.new_job_id = new_job_id
        self.journal = journal
        self._adopt()

    # Building (pure) ----------------------------------------------------------------------

    def graph(self, request: WanRequest, job_id: str) -> dict:
        """The graph :meth:`render` submits for ``request`` as job ``job_id``."""
        _job_id(job_id)
        if isinstance(request, ImageToVideo):
            pinned.check(self.i2v_template, I2V_GRAPH)
            return i2v_graph(self.i2v_template.data, prompt=request.prompt, negative=request.negative,
                             width=request.width, height=request.height, length=request.length,
                             seed=request.seed, steps=I2V_STEPS, job_id=job_id,
                             up_name=upload_name(request.image_png, '.png'))
        if isinstance(request, SpeechToVideo):
            return s2v_graph(request.prompt, request.negative,
                             f'{UPLOAD_FOLDER}/' + upload_name(request.image_png, '.png'),
                             f'{UPLOAD_FOLDER}/' + upload_name(request.drive_wav, '.wav'),
                             request.width, request.height, request.length, request.seed,
                             'video/' + job_id, request.lightning)
        raise RequestInvalid(LABEL, "request must be ImageToVideo or SpeechToVideo")

    def job(self, request: WanRequest, job_id: str, created_at: float) -> dict:
        """The job ledger :meth:`render` hands to ``api.generate()``: the PoC's job plus
        one key, ``graph_sha256`` (of the graph sent with it, which holds the prompt, the
        negative, seed, size, length, input names and the job's own output prefix), so
        :meth:`recover` can prove a ledger is this request's job."""
        _job_id(job_id)
        if isinstance(request, ImageToVideo):
            job = i2v_job(job_id=job_id, width=request.width, height=request.height,
                          length=request.length, seed=request.seed, created_at=created_at,
                          up_name=upload_name(request.image_png, '.png'),
                          digest=request.image_sha256, story=request.story)
        elif isinstance(request, SpeechToVideo):
            job = s2v_job(job_id=job_id, width=request.width, height=request.height,
                          length=request.length, seed=request.seed, created_at=created_at,
                          image=f'{UPLOAD_FOLDER}/' + upload_name(request.image_png, '.png'),
                          image_sha=request.image_sha256,
                          audio=f'{UPLOAD_FOLDER}/' + upload_name(request.drive_wav, '.wav'),
                          audio_sha=hashlib.sha256(request.drive_wav).hexdigest(),
                          story=request.story, lightning=request.lightning)
        else:
            raise RequestInvalid(LABEL, "request must be ImageToVideo or SpeechToVideo")
        job['graph_sha256'] = graph_sha256(self.graph(request, job_id))
        return job

    def command(self, request: WanRequest, job_id: str, created_at: float) -> Command:
        """The ``wan_run.py`` command :meth:`render` runs. For inspection and tests only:
        it takes no lock and makes no check. Submit with :meth:`render`."""
        return self._run_command(self.job(request, job_id, created_at), self.graph(request, job_id),
                                 request.prompt)

    def _run_command(self, job: dict, g: dict, prompt: str) -> Command:
        pinned.check(self.run_snippet, RUN_SNIPPET)
        stdin = json.dumps({'job': job, 'graph': g, 'prompt': prompt}).encode()
        return Command(LABEL, self.target.argv(self.run_snippet.text), stdin, RUN_TIMEOUT_S,
                       self.target.describe())

    def probe_command(self) -> Command:
        pinned.check(self.probe_snippet, PROBE_SNIPPET)
        return Command(PROBE_LABEL, self.target.argv(self.probe_snippet.text), b"", PROBE_TIMEOUT_S,
                       self.target.describe())

    def upload_command(self, data: bytes, suffix: str) -> Command:
        pinned.check(self.upload_snippet, UPLOAD_SNIPPET)
        digest = hashlib.sha256(data).hexdigest()
        return Command(UPLOAD_LABEL, self.target.argv(self.upload_snippet.text, upload_name(data, suffix),
                                                      digest), data, UPLOAD_TIMEOUT_S,
                       self.target.describe())

    def fetch_command(self, job_id: str) -> Command:
        pinned.check(self.fetch_snippet, FETCH_SNIPPET)
        return Command(FETCH_LABEL, self.target.argv(self.fetch_snippet.text, _job_id(job_id)), b"",
                       FETCH_TIMEOUT_S, self.target.describe())

    def read_command(self, job_id: str) -> Command:
        pinned.check(self.read_snippet, READ_SNIPPET)
        return Command(READ_LABEL, self.target.argv(self.read_snippet.text, _job_id(job_id)), b"",
                       READ_TIMEOUT_S, self.target.describe())

    # Process state ------------------------------------------------------------------------

    @classmethod
    def in_flight(cls) -> InFlightJob | None:
        """The job that blocks further renders in this process (one a failed call may have
        left running, one whose clip is uncollected, or one loaded from the journal), or
        None."""
        return WanClipClient._unsettled

    @classmethod
    def clear_in_flight(cls) -> InFlightJob | None:
        """Forget the blocking job, once a person has checked it: that it is not running
        (for example: its ledger is missing and no snippet process is left in the ``api``
        container), or that its uncollected clip has been inspected. Refused
        (``adapter.busy``, nothing changed) while a :meth:`render` or :meth:`recover` runs
        in this process or another process holds its journal. Appends a ``settle`` line
        with outcome ``cleared`` to its journal first (unless another process already
        settled it there); if that write fails, the job stays. Returns what it forgot.
        Touches nothing on the Wan service."""
        with _process_lock("a Wan job is running in this process; clear after it returns"):
            cleared, journal = WanClipClient._unsettled, WanClipClient._unsettled_journal
            if cleared is not None and journal is not None:
                journal.hold()
                try:
                    state = journal.read_state()
                    if state.job is not None and state.job.job_id == cleared.job_id:
                        journal.settle(cleared.job_id, "cleared")
                    elif cleared.job_id not in state.named:
                        raise _journal_error(_unnamed(cleared.job_id))
                finally:
                    journal.release()
            WanClipClient._unsettled = WanClipClient._unsettled_journal = None
            return cleared

    @classmethod
    def halted(cls) -> Halt | None:
        """Why this process submits no more jobs (foreign engine work seen), or None."""
        return WanClipClient._halt

    @classmethod
    def clear_halt(cls) -> Halt | None:
        """Allow submissions again after a person has inspected the foreign work. Refused
        (``adapter.busy``, nothing changed) while a :meth:`render` or :meth:`recover` runs
        in this process or another process holds its journal. Appends a ``clear_halt``
        line to the halt's journal first (unless the journal no longer has that halt); if
        that write fails, the halt stays."""
        with _process_lock("a Wan job is running in this process; clear after it returns"):
            cleared, journal = WanClipClient._halt, WanClipClient._halt_journal
            if cleared is not None and journal is not None:
                journal.hold()
                try:
                    state = journal.read_state()
                    if state.halt is not None and state.halt.job_id == cleared.job_id:
                        journal.clear_halt(cleared.job_id)
                        cleared = _extended(cleared, state.halt.unexpected_work_seen)
                    elif cleared.job_id not in state.named:
                        raise _journal_error(_unnamed(cleared.job_id))
                finally:
                    journal.release()
            WanClipClient._halt = WanClipClient._halt_journal = None
            return cleared

    # Reads --------------------------------------------------------------------------------

    def probe(self) -> Probe:
        """One read of the API's health, the GPUs and the engine queue. Submits nothing.
        An answer without ``accepting_jobs`` or the ``active_job`` key in its health,
        without both queue lists, or whose GPUs are not exactly the two approved ones
        (``pinned.WAN_GPU_UUIDS``) is ``adapter.response_invalid``: missing evidence is
        never idle."""
        result = run_checked(self.runner, self.probe_command(), error=WanError)
        out = _json(result.stdout, PROBE_LABEL)
        health = out.get('health') if isinstance(out, dict) else None
        sample = out.get('sample') if isinstance(out, dict) else None
        queue = out.get('queue') if isinstance(out, dict) else None
        gpus = sample.get('gpus') if isinstance(sample, dict) else None
        if not isinstance(health, dict) or not isinstance(queue, dict) or not isinstance(gpus, list) \
                or not gpus:
            raise WanError(RESPONSE_INVALID, PROBE_LABEL, "answer lacks health, GPU sample or queue")
        if len(gpus) != EXPECTED_GPUS:
            raise WanError(RESPONSE_INVALID, PROBE_LABEL, f"the GPU sample shows {len(gpus)} GPUs; "
                                                          f"expected exactly {EXPECTED_GPUS}")
        for gpu in gpus:
            if not isinstance(gpu, dict) or _number(gpu.get('temperature_c')) is None \
                    or _number(gpu.get('utilization_percent')) is None:
                raise WanError(RESPONSE_INVALID, PROBE_LABEL, "a GPU sample lacks temperature or utilization")
        if {gpu.get('uuid') for gpu in gpus} != set(pinned.WAN_GPU_UUIDS):
            raise WanError(RESPONSE_INVALID, PROBE_LABEL, "the GPU sample is not the two approved GPUs "
                                                          "(pinned.WAN_GPU_UUIDS)")
        for key in ('accepting_jobs', 'active_job'):
            if key not in health:
                raise WanError(RESPONSE_INVALID, PROBE_LABEL, f"health lacks {key}")
        for key in ('queue_running', 'queue_pending'):
            if not isinstance(queue.get(key), list):
                raise WanError(RESPONSE_INVALID, PROBE_LABEL, f"queue {key} is not a list")
        return Probe(health, tuple(gpus), queue)

    def wait_cool(self) -> tuple[float, list[tuple[float, float]]]:
        """``poc/wan.py wait_cool``: refuse at once when the API is busy or holding, or
        when the engine has any work queued or running; otherwise wait (reading only)
        until both GPUs are cool and idle, up to 1800 s. Returns the seconds waited and
        each GPU's ``(temperature_c, utilization_percent)`` at the passing read."""
        t0 = self.clock()
        while True:
            s = self.probe()
            h, q = s.health, s.queue
            if h.get('accepting_jobs') is not True or h.get('active_job') is not None:
                raise WanError(BUSY, PROBE_LABEL, "Wan API busy or holding submissions "
                                                  f"(accepting_jobs={h.get('accepting_jobs')!r}, "
                                                  f"active_job={h.get('active_job')!r})")
            if q.get('queue_running') or q.get('queue_pending'):
                raise WanError(BUSY, PROBE_LABEL, "unknown engine work queued; preserving it and stopping")
            gpus = s.gpus
            if s.cool:
                return round(self.clock() - t0, 1), [(g['temperature_c'], g['utilization_percent']) for g in gpus]
            if self.clock() - t0 > COOL_MAX_S:
                raise WanError(BUSY, PROBE_LABEL, "GPUs did not return to cool idle within "
                                                  f"{COOL_MAX_S} s")
            self.sleep(COOL_POLL_S)

    def read_job(self, job_id: str) -> dict:
        """The Wan job's ledger (``GET /videos/<job_id>``). Read-only; a missing job is
        ``adapter.not_found``."""
        result = run_checked(self.runner, self.read_command(job_id), error=WanError)
        job = _json(result.stdout, READ_LABEL)
        if not isinstance(job, dict) or job.get('id') != job_id or not isinstance(job.get('state'), str):
            raise WanError(RESPONSE_INVALID, READ_LABEL, "answer is not this job's ledger", job_id=job_id)
        return job

    # Writes (create-only) -----------------------------------------------------------------

    def upload(self, data: bytes, suffix: str) -> Upload:
        """``poc/wan.py``'s upload: ``data`` written create-only as
        ``studio-e0/<16 hex digits of its SHA-256><suffix>``. An existing file of that name
        must hold the same bytes; the pod's read-back hash must match."""
        command = self.upload_command(data, suffix)
        digest = hashlib.sha256(data).hexdigest()
        result = self.runner.run(command)
        if not isinstance(result, Completed):
            raise TypeError("a runner must return Completed")
        if result.returncode != 0:
            if UPLOAD_CONFLICT in redact(result.stderr):
                raise WanError(COMMAND_FAILED, UPLOAD_LABEL,
                               f"{UPLOAD_FOLDER}/{upload_name(data, suffix)} already holds other "
                               "bytes; nothing was overwritten", returncode=result.returncode)
            raise failure(command, result, error=WanError)
        if result.stdout.decode('utf-8', 'replace').strip() != digest:
            raise WanError(RESPONSE_INVALID, UPLOAD_LABEL, "the pod read back another hash")
        return Upload(f'{UPLOAD_FOLDER}/' + upload_name(data, suffix), digest, len(data))

    # Render -------------------------------------------------------------------------------

    def render(self, request: WanRequest) -> WanClip:
        """Make one clip (see the module notes for the guards, in order). Returns the clip
        with its provenance record, or raises :class:`WanError`."""
        if not isinstance(request, ImageToVideo | SpeechToVideo):
            raise RequestInvalid(LABEL, "request must be ImageToVideo or SpeechToVideo")
        self._check_pins()  # every snippet and the template, before anything runs
        job_id = _job_id(self.new_job_id())
        g = self.graph(request, job_id)
        files = model_files(g)
        with self._exclusive():
            return self._render(request, job_id, g, files)

    def _render(self, request: WanRequest, job_id: str, g: dict, files: dict) -> WanClip:
        self._adopt()  # the journal, read exactly, before anything else
        self._check_halt()
        self._settle_in_flight()
        self._remember(job_id, graph_sha256(g))  # on record before the first probe
        try:
            t0 = self.clock()
            first_s, first_temps = self.wait_cool()
            self.journal.check()  # still the journal this call holds, before each step that sends
            uploads = {'image': self.upload(request.image_png, '.png')}
            if isinstance(request, SpeechToVideo):
                uploads['audio'] = self.upload(request.drive_wav, '.wav')
            created_at = self.wall()
            job = self.job(request, job_id, created_at)
            command = self._run_command(job, g, request.prompt)
            self.journal.check()
            cooled_s, temps = self.wait_cool()  # again, right before the run: the uploads took time
            self.journal.check()
        except BaseException:
            self._settle(job_id, "no_submission")  # the run command was never started
            raise
        t_submit = self.clock()
        result = self._submit(command, job_id)
        t_done = self.clock()
        foreign = _ids(result.get('unexpected_work_seen'))
        if foreign:  # latched before anything else can fail, as the PoC stops here too
            foreign = self._latch_halt(Halt(job_id, tuple(foreign))).unexpected_work_seen
        if result['state'] != 'succeeded':
            error = redact(str(result.get('error') or ''))[:200]
            if result.get('prompt_id'):  # accepted by the engine: it may still be there
                self._recode(job_id, JOB_FAILED)
                raise WanError(JOB_FAILED, LABEL, f"Wan job {job_id} ended {result['state']}: {error}; "
                               f"{_accepted(result.get('prompt_id'))}", job_id=job_id, in_flight=True)
            self._settle(job_id, "failed")  # its finished ledger has been read
            code = BUSY if LEASE_BUSY in error else JOB_FAILED
            raise WanError(code, LABEL, f"Wan job {job_id} ended {result['state']}: {error}; "
                                        "inspect before any further render", job_id=job_id)
        self._mark_uncollected(job_id)  # blocks further renders until its clip passes
        body, fetch_s = self._fetch(job_id, result.get('bytes'))
        measured = self._check_clip(request, job_id, body)
        timings = {'cooldown_s': cooled_s, 'start_temps': [list(t) for t in temps],
                   'cool_before_upload': {'cooldown_s': first_s,
                                          'start_temps': [list(t) for t in first_temps]},
                   'render_s': round(t_done - t_submit, 1), 'fetch_s': fetch_s,
                   'wall_s': round(self.clock() - t0, 1)}
        clip = WanClip(body, self._record(request, job_id, g, files, uploads, result, body,
                                          measured, timings))
        self._settle(job_id, "collected")
        if foreign:
            raise WanError(COMPETING_WORK, LABEL, f"competing engine work seen during job {job_id} "
                           f"({', '.join(foreign)}); output kept, no further submissions until "
                           "WanClipClient.clear_halt()", job_id=job_id, clip=clip)
        return clip

    def recover(self, request: WanRequest, job_id: str) -> WanClip:
        """The clip of an earlier job made for ``request``, without rendering again: for
        a job whose answer was lost or whose fetch or clip check failed, once its ledger
        reads ``succeeded``. Read-only: it reads the ledger and checks that it is this
        request's job (the ledger's ``graph_sha256`` must equal the graph rebuilt for
        ``request`` and ``job_id``, and its story, preset, seed and inputs must match; a
        ledger without ``graph_sha256``, as every E0 job, is refused), then fetches and
        checks the clip exactly as :meth:`render` does. Only a clip that passes settles
        the job. It submits nothing, so a halt does not block it; foreign work recorded on
        the job latches the halt and raises ``adapter.competing_work`` with the clip, as
        :meth:`render`. The record has ``recovered: true`` and no cool-down or render
        timings."""
        if not isinstance(request, ImageToVideo | SpeechToVideo):
            raise RequestInvalid(LABEL, "request must be ImageToVideo or SpeechToVideo")
        self._check_pins()
        g = self.graph(request, _job_id(job_id))
        files = model_files(g)
        with self._exclusive():
            return self._recover(request, job_id, g, files)

    def _recover(self, request: WanRequest, job_id: str, g: dict, files: dict) -> WanClip:
        self._adopt()
        ledger = self.read_job(job_id)
        expected = self.job(request, job_id, 0.0)
        if not isinstance(ledger.get('graph_sha256'), str):
            raise WanError(RESPONSE_INVALID, READ_LABEL, f"job {job_id}'s ledger has no graph_sha256 "
                           "(as every E0 job), so it cannot be shown to be this request's job; "
                           "recover collects only jobs this client made, older jobs are imported "
                           "another way", job_id=job_id)
        keys = ('preset', 'seed', 'reference_image', 'reference_sha256', 'audio', 'audio_sha256',
                'story', 'graph_sha256')
        if any(ledger.get(k) != expected.get(k) for k in keys):
            raise WanError(RESPONSE_INVALID, READ_LABEL, f"job {job_id} was not made for this request",
                           job_id=job_id)
        state = ledger['state']
        if state not in TERMINAL:
            raise WanError(BUSY, LABEL, f"Wan job {job_id} is {state}", job_id=job_id, in_flight=True)
        foreign = _ids(ledger.get('unexpected_work_seen'))
        if foreign:  # every prompt ID the halt now holds, an earlier halt's first
            foreign = self._latch_halt(Halt(job_id, tuple(foreign))).unexpected_work_seen
        if state != 'succeeded':
            error = redact(str(ledger.get('error') or ''))[:200]
            if ledger.get('prompt_id'):  # accepted by the engine: it may still be there
                raise WanError(JOB_FAILED, LABEL, f"Wan job {job_id} ended {state}: {error}; "
                               f"{_accepted(ledger.get('prompt_id'))}", job_id=job_id, in_flight=True)
            self._settle(job_id, "failed")
            raise WanError(JOB_FAILED, LABEL, f"Wan job {job_id} ended {state}: {error}", job_id=job_id)
        self._mark_uncollected(job_id)
        t0 = self.clock()
        body, fetch_s = self._fetch(job_id, ledger.get('bytes'))
        measured = self._check_clip(request, job_id, body)
        uploads = {'image': Upload(expected['reference_image'], request.image_sha256,
                                   len(request.image_png))}
        if isinstance(request, SpeechToVideo):
            uploads['audio'] = Upload(expected['audio'], expected['audio_sha256'], len(request.drive_wav))
        timings = {'cooldown_s': None, 'start_temps': None, 'cool_before_upload': None,
                   'render_s': None, 'fetch_s': fetch_s,
                   'wall_s': round(self.clock() - t0, 1), 'recovered': True}
        clip = WanClip(body, self._record(request, job_id, g, files, uploads, ledger, body,
                                          measured, timings))
        self._settle(job_id, "collected")
        if foreign:
            raise WanError(COMPETING_WORK, LABEL, f"competing engine work was seen during job {job_id} "
                           f"({', '.join(foreign)}); output kept, no further submissions until "
                           "WanClipClient.clear_halt()", job_id=job_id, clip=clip)
        return clip

    @contextlib.contextmanager
    def _exclusive(self):
        """The process's one-job lock, then this client's journal held, for one call."""
        with _process_lock("another Wan job is in flight in this process; one job at a time"):
            self.journal.hold()
            try:
                yield
            finally:
                self.journal.release()

    def _check_pins(self) -> None:
        for item, name in ((self.probe_snippet, PROBE_SNIPPET), (self.upload_snippet, UPLOAD_SNIPPET),
                           (self.run_snippet, RUN_SNIPPET), (self.fetch_snippet, FETCH_SNIPPET),
                           (self.read_snippet, READ_SNIPPET), (self.i2v_template, I2V_GRAPH)):
            pinned.check(item, name)

    def _check_halt(self) -> None:
        halt = WanClipClient._halt
        if halt is not None:
            raise WanError(COMPETING_WORK, LABEL, f"competing engine work was seen during job "
                           f"{halt.job_id} ({', '.join(halt.unexpected_work_seen)}); no further "
                           "submissions until WanClipClient.clear_halt()", job_id=halt.job_id)

    def _adopt(self) -> None:
        """One read of this client's journal (``adapter.journal_failed`` unless it reads
        exactly) brought into the process's memory, so a job or halt an earlier process
        left behaves as this process's own. What memory holds from the same journal
        follows the journal (another process may have settled it since); a held job or
        halt the journal does not name at all means the file was replaced or cut, and is
        ``adapter.journal_failed``. A journal job other than the one the process holds is
        ``adapter.busy``."""
        journal, state = self.journal, self.journal.read_state()
        held = WanClipClient._unsettled
        if held is not None and journal.same(WanClipClient._unsettled_journal):
            if state.job is not None and state.job.job_id == held.job_id:
                WanClipClient._unsettled = replace(held, state=state.job.state)
                WanClipClient._unsettled_journal = journal  # written through the held one
            elif held.job_id in state.named:  # settled in the journal since
                WanClipClient._unsettled = WanClipClient._unsettled_journal = None
            else:
                raise _journal_error(_unnamed(held.job_id))
        held = WanClipClient._unsettled
        if state.job is not None and held is None:
            WanClipClient._unsettled, WanClipClient._unsettled_journal = state.job, journal
        elif state.job is not None and held.job_id != state.job.job_id:
            raise WanError(BUSY, LABEL, f"this process holds Wan job {held.job_id} and the journal "
                                        f"holds Wan job {state.job.job_id}; settle {held.job_id} first",
                           job_id=state.job.job_id)
        halt = WanClipClient._halt
        if halt is not None and journal.same(WanClipClient._halt_journal) \
                and (state.halt is None or state.halt.job_id != halt.job_id):
            if halt.job_id not in state.named:
                raise _journal_error(_unnamed(halt.job_id))
            WanClipClient._halt = WanClipClient._halt_journal = None  # cleared or replaced since
        if state.halt is not None and WanClipClient._halt is None:
            WanClipClient._halt, WanClipClient._halt_journal = state.halt, journal

    def _settle_in_flight(self) -> None:
        """With a job that blocks, go ahead only once its ledger reads failed. An
        uncollected job, or one whose ledger now reads succeeded, refuses until
        :meth:`recover` collects its clip (or a person clears it)."""
        unsettled = WanClipClient._unsettled
        if unsettled is None:
            return
        if unsettled.state == UNCOLLECTED:
            raise WanError(BUSY, LABEL, _uncollected(unsettled.job_id), job_id=unsettled.job_id)
        try:
            job = self.read_job(unsettled.job_id)  # read-only; any failure keeps the state
        except AdapterError as error:
            hint = ("it has no ledger: it may never have started, or its process may still be "
                    "starting; check the api container, then WanClipClient.clear_in_flight()"
                    if error.code == "adapter.not_found" else f"its ledger could not be read ({error.code})")
            raise WanError(BUSY, LABEL, f"an earlier Wan job may still be running; {hint}",
                           job_id=unsettled.job_id, in_flight=True) from None
        state = job['state']
        if state not in TERMINAL:
            raise WanError(BUSY, LABEL, f"an earlier Wan job is {state}", job_id=unsettled.job_id,
                           in_flight=True)
        foreign = _ids(job.get('unexpected_work_seen'))
        if foreign:  # latched before the job is settled
            foreign = self._latch_halt(Halt(unsettled.job_id, tuple(foreign))).unexpected_work_seen
        if state == 'succeeded':  # its clip has not been collected: it keeps blocking
            self._mark_uncollected(unsettled.job_id)
            if foreign:
                raise WanError(COMPETING_WORK, LABEL, f"competing engine work was seen during the "
                               f"earlier job {unsettled.job_id} ({', '.join(foreign)}); no further "
                               f"submissions until WanClipClient.clear_halt(); "
                               f"{_uncollected(unsettled.job_id)}",
                               job_id=unsettled.job_id)
            raise WanError(BUSY, LABEL, _uncollected(unsettled.job_id), job_id=unsettled.job_id)
        if job.get('prompt_id') and not self._engine_idle():
            raise WanError(BUSY, LABEL, f"the earlier Wan job {unsettled.job_id} failed; "
                           f"{_accepted(job.get('prompt_id'))}", job_id=unsettled.job_id, in_flight=True)
        self._settle(unsettled.job_id, "failed")
        if foreign:
            raise WanError(COMPETING_WORK, LABEL, f"competing engine work was seen during the earlier "
                           f"job {unsettled.job_id} ({', '.join(foreign)}); its output stays on the Wan "
                           "API; no further submissions until WanClipClient.clear_halt()",
                           job_id=unsettled.job_id)

    # The process's memory and the journal: every change to a blocking job or the halt is
    # journalled. Remembering a job writes the journal first, so a job whose line could not
    # be written never runs; a change of state, a settle or a halt keeps the job (or sets
    # the halt) in memory if its journal write fails.

    def _engine_idle(self) -> bool:
        """One probe shows both engine queue lists present and empty. A probe that fails
        is not idle."""
        try:
            queue = self.probe().queue
        except AdapterError:
            return False
        return queue['queue_running'] == [] and queue['queue_pending'] == []

    def _remember(self, job_id: str, graph_sha: str) -> None:
        self.journal.remember(job_id, IN_FLIGHT, graph_sha)
        WanClipClient._unsettled = InFlightJob(job_id, "unknown", IN_FLIGHT, graph_sha)
        WanClipClient._unsettled_journal = self.journal

    def _recode(self, job_id: str, code: str) -> None:
        held = WanClipClient._unsettled
        if held is not None and held.job_id == job_id:
            WanClipClient._unsettled = replace(held, code=code)

    def _mark_uncollected(self, job_id: str) -> None:
        held, journal = WanClipClient._unsettled, WanClipClient._unsettled_journal
        if held is not None and held.job_id == job_id and held.state != UNCOLLECTED:
            WanClipClient._unsettled = replace(held, state=UNCOLLECTED)
            journal.remember(job_id, UNCOLLECTED, held.graph_sha256)

    def _settle(self, job_id: str, outcome: str) -> None:
        held, journal = WanClipClient._unsettled, WanClipClient._unsettled_journal
        if held is not None and held.job_id == job_id:
            journal.settle(job_id, outcome)
            WanClipClient._unsettled = WanClipClient._unsettled_journal = None

    def _latch_halt(self, halt: Halt) -> Halt:
        """Latch ``halt``, or extend the one already set: a halt is never replaced. It
        keeps the first job's ID and gains the new prompt IDs, first seen first, and the
        journal gets that whole halt (a replay keeps the last ``halt`` line). Returns the
        halt now set."""
        if WanClipClient._halt is not None:
            halt = _extended(WanClipClient._halt, halt.unexpected_work_seen)
        WanClipClient._halt, WanClipClient._halt_journal = halt, self.journal
        self.journal.halt(halt.job_id, halt.unexpected_work_seen)
        return halt

    def _submit(self, command: Command, job_id: str) -> dict:
        """Run ``wan_run.py`` once (lock and journal held). The job was journalled as in
        flight before the first probe, and stays so for every outcome but three: the
        runner could not start the command, the admission readback refused (both certainly
        submitted nothing), or the answer is this job's finished ledger, which
        :meth:`render` settles (failed, no prompt accepted), keeps (failed after its prompt
        was accepted) or marks uncollected (succeeded) once it has latched any halt."""
        try:
            result = self.runner.run(command)
        except AdapterError as error:
            in_flight = error.code != COMMAND_FAILED  # a runner's command_failed: it never started
            if in_flight:
                self._recode(job_id, error.code)
            else:
                self._settle(job_id, "no_submission")
            raise WanError(error.code, LABEL, error.message, job_id=job_id, in_flight=in_flight,
                           detail=error.detail, returncode=error.returncode,
                           redacted_stderr=error.redacted_stderr) from None
        if not isinstance(result, Completed):
            raise TypeError("a runner must return Completed")
        if result.returncode != 0:
            stderr = redact(result.stderr)
            if NO_SUBMISSION in (line.strip() for line in stderr.splitlines()):
                self._settle(job_id, "no_submission")
                raise WanError(BUSY, LABEL, "the Wan API was busy or holding at the admission "
                                            "readback; nothing was submitted", job_id=job_id,
                               returncode=result.returncode)
            error = failure(command, result, error=WanError, job_id=job_id, in_flight=True)
            self._recode(job_id, error.code)
            raise error
        try:
            answer = _json(result.stdout, LABEL)
        except WanError:
            answer = None
        if not isinstance(answer, dict) or answer.get('id') != job_id \
                or answer.get('state') not in TERMINAL:
            self._recode(job_id, RESPONSE_INVALID)
            raise WanError(RESPONSE_INVALID, LABEL, "the run's answer is not this job's finished "
                                                    "ledger", job_id=job_id, in_flight=True)
        return answer

    def _fetch(self, job_id: str, ledger_bytes: Any) -> tuple[bytes, float]:
        """The clip's bytes, read-only, checked against the pod's own hash and size and
        the ledger's size."""
        if not _int(ledger_bytes) or ledger_bytes <= 0:
            raise WanError(RESPONSE_INVALID, FETCH_LABEL, f"job {job_id}'s ledger has no clip size",
                           job_id=job_id)
        if ledger_bytes > MAX_CLIP_BYTES:
            raise WanError(RESPONSE_INVALID, FETCH_LABEL, f"job {job_id}'s clip is over "
                                                          f"{MAX_CLIP_BYTES} bytes", job_id=job_id)
        t0 = self.clock()
        try:
            result = run_checked(self.runner, self.fetch_command(job_id), error=WanError)
        except AdapterError as error:  # the job succeeded: its clip stays on the Wan API
            raise WanError(error.code, FETCH_LABEL, f"{error.message}; job {job_id} succeeded and its "
                           f"clip stays on the Wan API at /videos/{job_id}/file: collect it with "
                           "WanClipClient.recover(request, job_id), do not render it again",
                           job_id=job_id, detail=error.detail, returncode=error.returncode,
                           redacted_stderr=error.redacted_stderr) from None
        found = CLIP_LINE.search(result.stderr.decode('utf-8', 'replace'))
        body = result.stdout
        if found is None:
            raise WanError(RESPONSE_INVALID, FETCH_LABEL, "the pod stated no clip hash", job_id=job_id)
        if len(body) != int(found.group(2)) or hashlib.sha256(body).hexdigest() != found.group(1):
            raise WanError(RESPONSE_INVALID, FETCH_LABEL, f"clip of job {job_id} differs from what "
                                                          "the pod read (cut or changed in transfer)",
                           job_id=job_id)
        if len(body) != ledger_bytes:
            raise WanError(RESPONSE_INVALID, FETCH_LABEL, f"clip of job {job_id} is {len(body)} bytes; "
                                                          f"its ledger says {ledger_bytes}", job_id=job_id)
        return body, round(self.clock() - t0, 1)

    def _check_clip(self, request: WanRequest, job_id: str, body: bytes) -> Measured:
        """The clip decodes and has exactly the frames, the size and (as measured) the
        rate the request's graph makes: image-to-video ``length`` frames at 24 fps,
        speech-to-video :func:`s2v_frames_delivered` frames at 16 fps. Anything else is
        an error, and the job stays uncollected, its clip on the Wan API to inspect."""
        kept = (f"; job {job_id} stays uncollected and its clip stays on the Wan API at "
                f"/videos/{job_id}/file: inspect it, then WanClipClient.clear_in_flight()")
        try:
            measured = measure_clip(body)
        except ValueError as problem:
            raise WanError(RESPONSE_INVALID, FETCH_LABEL, f"clip of job {job_id} does not decode "
                                                          f"({problem}){kept}", job_id=job_id) from None
        if measured.frames < request.frames_requested:
            raise WanError(RESPONSE_INVALID, FETCH_LABEL, f"clip of job {job_id} is short: "
                           f"{measured.frames} frames, asked for {request.frames_requested}{kept}",
                           job_id=job_id)
        if measured.frames != request.frames_expected:
            raise WanError(RESPONSE_INVALID, FETCH_LABEL, f"clip of job {job_id} has {measured.frames} "
                           f"frames; its graph makes exactly {request.frames_expected}{kept}",
                           job_id=job_id)
        if (measured.width, measured.height) != (request.width, request.height):
            raise WanError(RESPONSE_INVALID, FETCH_LABEL, f"clip of job {job_id} is "
                           f"{measured.width}x{measured.height}, asked for "
                           f"{request.width}x{request.height}{kept}", job_id=job_id)
        if _rate(measured.fps) != request.fps:
            raise WanError(RESPONSE_INVALID, FETCH_LABEL, f"clip of job {job_id} plays at "
                           f"{measured.fps or 'no measured rate'} fps; its graph makes {request.fps}{kept}",
                           job_id=job_id)
        return measured

    def _record(self, request, job_id, g, files, uploads, result, body, measured, timings) -> dict:
        telemetry = result.get('telemetry') if isinstance(result.get('telemetry'), list) else []
        peak = max((_number(gpu.get('memory_mib')) or 0 for sample in telemetry if isinstance(sample, dict)
                    for gpu in (sample.get('gpus') or []) if isinstance(gpu, dict)), default=None)
        readback = result.get('live_admission_readback')
        record = {
            'kind': request.kind, 'engine': request.engine, 'job_id': job_id,
            'prompt_id': result.get('prompt_id') if isinstance(result.get('prompt_id'), str) else None,
            'preset': result.get('preset'), 'story': request.story,
            'graph_sha256': graph_sha256(g),
            'template_sha256': self.i2v_template.sha256 if request.kind == 'i2v' else None,
            'run_snippet_sha256': self.run_snippet.sha256,
            'model_files_sha256': files, 'model_files_source': 'docs/reference/model-licences.json',
            'seed': request.seed, 'width': request.width, 'height': request.height,
            'fps': int(_rate(measured.fps)),  # as measured; _check_clip made it the request's
            'frames_requested': request.frames_requested, 'frames_delivered': measured.frames,
            'measured': {'width': measured.width, 'height': measured.height, 'fps': measured.fps},
            'inputs': {name: {'ref': up.ref, 'sha256': up.sha256, 'bytes': up.bytes}
                       for name, up in uploads.items()},
            'prompt': request.prompt, 'negative': request.negative,
            'clip_sha256': hashlib.sha256(body).hexdigest(), 'clip_bytes': len(body),
            'cooldown_s': timings['cooldown_s'], 'start_temps': timings['start_temps'],
            'cool_before_upload': timings['cool_before_upload'],
            'render_s': timings['render_s'], 'fetch_s': timings['fetch_s'], 'wall_s': timings['wall_s'],
            'recovered': timings.get('recovered', False),
            'job_created_at': _number(result.get('created_at')),
            'job_started_at': _number(result.get('started_at')),
            'job_finished_at': _number(result.get('finished_at')),
            'admission_readback_at': _number(readback.get('time')) if isinstance(readback, dict) else None,
            'engine_read_retries': int(_number(result.get('engine_read_retries')) or 0),
            'poll_misses': int(_number(result.get('poll_misses')) or 0),
            'unexpected_work_seen': _ids(result.get('unexpected_work_seen')),
            'telemetry_tail': telemetry[-3:], 'peak_gpu_mib': peak,
            'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(self.wall())),
        }
        if isinstance(request, SpeechToVideo):
            samples, rate = request.drive
            record.update(method='s2v-lightning', chunks=request.chunks,
                          board_frames=request.board_frames,
                          frames_needed=s2v_frames_needed(request.board_frames),
                          drive_samples=samples, drive_rate=rate)
        return record


def _job_id(value: Any) -> str:
    if not isinstance(value, str) or not JOB_ID.fullmatch(value):
        raise RequestInvalid(LABEL, "a Wan job ID is 32 lower-case hex digits")
    return value


def _rate(text: str) -> Fraction | None:
    """A measured rate (``measure_clip``'s fraction text) as a number, or None."""
    try:
        return Fraction(text)
    except (ValueError, ZeroDivisionError):
        return None


@contextlib.contextmanager
def _process_lock(refusal: str):
    """``WanClipClient._lock`` without waiting: ``adapter.busy`` with ``refusal`` when it
    is taken (a render or recover runs in this process)."""
    if not WanClipClient._lock.acquire(blocking=False):
        raise WanError(BUSY, LABEL, refusal)
    try:
        yield
    finally:
        WanClipClient._lock.release()


def _extended(halt: Halt, seen) -> Halt:
    """``halt`` with the prompt IDs of ``seen`` it lacks added, first seen first."""
    return Halt(halt.job_id, halt.unexpected_work_seen
                + tuple(dict.fromkeys(p for p in seen if p not in halt.unexpected_work_seen)))


def _unnamed(job_id: str) -> str:
    return (f"the journal no longer names Wan job {job_id}, which this process holds: the file "
            "was replaced or cut")


def _accepted(prompt_id: Any) -> str:
    return (f"its prompt {str(prompt_id)[:64]} was accepted and may still be on the engine: it "
            "blocks further renders until a probe shows the engine queue empty")


def _uncollected(job_id: str) -> str:
    return (f"Wan job {job_id} succeeded but its clip has not been collected: call "
            f"WanClipClient.recover(request, {job_id!r}) with the request it was made for; no "
            "further render until its clip is fetched and checked, or until a person has "
            "inspected it and called WanClipClient.clear_in_flight()")


def _json(stdout: bytes, label: str) -> Any:
    if len(stdout) > MAX_ANSWER_BYTES:
        raise WanError(RESPONSE_INVALID, label, "answer is too long")
    try:
        return parse_strict(stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise WanError(RESPONSE_INVALID, label, "answer is not one JSON object") from None
