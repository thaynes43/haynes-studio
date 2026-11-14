"""Pinned workflow inputs: the ComfyUI graphs and the in-pod snippets.

Each file lives in this package's ``pinned-inputs/`` folder (a hyphenated name, so no
snippet can be imported as a module) and has its SHA-256 recorded here with its source.
A client loads its inputs with :func:`load` and calls :func:`check` before every call,
so a graph or snippet whose bytes differ from the pin is refused, never sent. Nothing
here reads another checkout: the haynes-ops graph was copied once, and its path,
commit and blob are recorded below.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path

from haynes_studio.adapters.errors import PinMismatch

FOLDER = "pinned-inputs"
HAYNES_OPS_COMMIT = "7c7b2cf6cceecc782cb149a958635852ae162966"
# The commit that added the Wan worker's graph template (haynes-ops#4504); the file has
# not changed since (story 842 read it at haynes-ops main bab21e14 on 2026-11-13).
HAYNES_OPS_WAN_COMMIT = "3a3571c4016a57465b5e995077bb691037224705"
# The two GPUs the Wan worker may use: haynes-ops kubernetes/main/apps/ai/wan-video/app/api.py
# EXPECTED, which api.gpu_sample() requires (the same two IDs are in the public E0 clip
# records). A Wan probe must show exactly these (story 842).
WAN_GPU_UUIDS = ("GPU-d8a856f1-f955-f683-bc24-654561496774", "GPU-6ff9702a-1b2c-6094-5a85-00aa1924c55a")


@dataclass(frozen=True)
class Pin:
    """A pinned file's expected SHA-256 and where its bytes came from."""

    sha256: str
    kind: str  # "snippet" or "graph"
    source: str


PINS: dict[str, Pin] = {
    "kokoro_tts.py": Pin(
        "7fcf8605f9713f66a110516606f8c2493fe851b986842015a746e9ef1f11fadf", "snippet",
        "poc/studio.py TTS, byte for byte (lifted there from haynes-ops "
        "scripts/wan-video/butter_speech.py CODE)"),
    "whisper_asr.py": Pin(
        "6e2ce027609d4f1e071bccd5ff9d5b16fe8e19f2d303a651bb04687e415d0b57", "snippet",
        "poc/studio.py ASR, byte for byte (lifted there from haynes-ops "
        "scripts/wan-video/check_butter_dialogue.py CODE)"),
    "comfyui_prompt.py": Pin(
        "2b5f31d2bbe42d4532fee006423edc6d11d83371fc7acb9536d51146880abcdb", "snippet",
        "poc/comfy.py REMOTE, byte for byte: waits for an idle queue, submits one prompt, "
        "polls its history"),
    "comfyui_queue.py": Pin(
        "281325a754325867d53559a37057179005f6680695e5d21a6589894f0c267d6f", "snippet",
        "new in story 425: GET /queue, read-only; prints running and pending counts"),
    "wan_ledger_read.py": Pin(
        "ba9fa7aac19a20a54d52d6081323c008345bc74e243c359e7c35ea7005a96469", "snippet",
        "poc/deliver.py READ, byte for byte: GET /videos/<id> on the Wan API"),
    "wan_ledger_list.py": Pin(
        "e068145dfcb8a1b13e525d613e335c8c478ebf04f090e6ede6e1f5d8c248f424", "snippet",
        "new in story 425: lists edited_production ledgers in /workspace/jobs/, read-only "
        "(the Wan API has no list route); a ledger must resolve under /workspace/jobs and be "
        "a regular file opened with O_NOFOLLOW, else it is listed as unreadable"),
    "wan_ledger_fetch.py": Pin(
        "8aaa1c0f555bb907127863968db7087cf08d47aa94be760a2bf1464e4d9c4300", "snippet",
        "new in story 425: prints one ledger asset's bytes, read-only, after checking the "
        "ledger as wan_ledger_list.py does, that the asset path is under "
        "/workspace/output/productions/, and on its O_NOFOLLOW descriptor that it is a "
        "regular file with one link and at most 64 MiB whose sha256 matches"),
    "qwen_image_2_1_t2i_API.json": Pin(
        "f18a6e29a1f225467874d6c4d9fe16861982ad9ff6e274ca3d170245c43d226d", "graph",
        "poc/graphs/qwen_image_2_1_t2i_API.json, byte for byte (hand-converted from "
        "haynes-ops UI template image_qwen_image_2_1_t2i.json)"),
    "qwen_image_2_1_edit_API.json": Pin(
        "946f46812559426297191419e8e4ca614ac948698f8a5ae9d09cda6b0e2fdcb6", "graph",
        "haynes-ops kubernetes/main/apps/ai/stable-diffusion/comfyui/resources/api-workflows/"
        f"qwen_image_2_1_edit_API.json at {HAYNES_OPS_COMMIT} (git blob f520dcd4937c, last "
        "changed in 31b449445dc1), the commit prompts.json records; copied once"),
    # Story 842: the Wan clip clients (poc/wan.py and poc/s2v.py).
    "wan_probe.py": Pin(
        "cd73ebd733c48c1a40222fc7a1a39ad9788db09b2b145837c5db5839c0eb6716", "snippet",
        "poc/wan.py PROBE, byte for byte: the Wan API's /health, api.gpu_sample() and the "
        "engine's /queue, read-only"),
    "wan_upload.py": Pin(
        "636cb89c132f83ec40426e971df9ba48ddcb466fe16f78a3c896baa7052748a9", "snippet",
        "poc/wan.py UPLOAD, byte for byte: one input written create-only under "
        "/workspace/input/studio-e0/, hash checked; an existing name must hold the same bytes"),
    "wan_run.py": Pin(
        "b44fcef47d1b125c0f061fd6f4f6d69357969a34f298549e85d44645b90836ce", "snippet",
        "poc/wan.py RUN, byte for byte (from OP342): the admission readback, then the "
        "installed api.generate() under its compute lease, with read-only engine retries "
        "and the unknown-work observer"),
    "wan_clip_fetch.py": Pin(
        "3db29f979cb996dfe351f0e5c040f193670a65f292c926a49272110b4f1d5c56", "snippet",
        "poc/wan.py fetch with the job ID as an argument instead of inline, plus a "
        "CLIP_SHA256 line on stderr: GET /videos/<id>/file on the Wan API, read-only; a "
        "read redirected to any other URL exits non-zero having written nothing"),
    "wan_ti2v_workflow.json": Pin(
        "88fe79ad543a93febd6f72e0dc86eecdb27b70c73e54d4553917f72cb95a136b", "graph",
        "haynes-ops kubernetes/main/apps/ai/wan-video/app/workflow.json at "
        f"{HAYNES_OPS_WAN_COMMIT} (git blob 5f9e9f968176, its only commit; unchanged at "
        "haynes-ops main bab21e14 on 2026-11-13), the template_sha256 of every E0 layer "
        "record; copied once"),
    # Story 846: the private input import's read-only volume reads (wan_volume.py).
    "wan_upload_read.py": Pin(
        "6945c756d3e2d4d15307e26d6527758a5b14740b8c3f48e4b292026395dc38a9", "snippet",
        "new in story 846: prints one E0 upload, /workspace/input/studio-e0/<first 16 hex>.<png|wav>, "
        "read-only; every folder below /workspace and the file opened with O_NOFOLLOW after an "
        "lstat, the file a regular file with one link and at most 20 000 000 bytes, hash "
        "checked; refusals are REFUSED <reason> and exit status 3"),
    "wan_job_output_read.py": Pin(
        "5a16cec45659cc6879cd17d783c8d3a2d472590f19b75ba0fefd2721dad20129", "snippet",
        "new in story 846: prints one Wan job's output, read-only: its ledger "
        "/workspace/jobs/<job_id>.json a succeeded job of that id, its output a plain relative "
        ".mp4 path below /workspace/output; every folder and file opened with O_NOFOLLOW after "
        "an lstat, the clip a regular file with one link, at most 64 MiB and the size its "
        "ledger records, hash checked; refusals are REFUSED <reason> and exit status 3"),
}


@dataclass(frozen=True)
class PinnedInput:
    """The bytes of one pinned file. ``sha256`` is computed from ``data``."""

    name: str
    data: bytes = field(repr=False)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    @property
    def text(self) -> str:
        return self.data.decode("utf-8")


def check(item: PinnedInput, name: str | None = None) -> PinnedInput:
    """``item`` if it is the pinned file ``name`` (default: its own name) byte for byte;
    otherwise :class:`PinMismatch`. An unknown name is a mismatch too."""
    name = name or item.name
    pin = PINS.get(name)
    actual = item.sha256
    if pin is None or item.name != name or actual != pin.sha256:
        raise PinMismatch(name, pin.sha256 if pin else "(no pin)", actual)
    return item


def load(name: str, *, root: str | Path | None = None) -> PinnedInput:
    """Read a pinned file from the package (or from ``root``, for tests) and check it."""
    if name not in PINS:
        raise PinMismatch(name, "(no pin)", "(not read)")
    if root is None:
        data = files(__package__).joinpath(FOLDER).joinpath(name).read_bytes()
    else:
        data = Path(root, name).read_bytes()
    return check(PinnedInput(name, data))
