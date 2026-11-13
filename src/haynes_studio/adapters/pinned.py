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
        "32d6228e662fc4d793e0d037c5543c2f03eed3a968a0ebc243adb0f1de4f0ede", "snippet",
        "new in story 425: lists edited_production ledgers in /workspace/jobs/, read-only "
        "(the Wan API has no list route)"),
    "wan_ledger_fetch.py": Pin(
        "5682a9ea1f50c7724095008b3e5fdb426371e4302c62baf33df7fda76dcd9584", "snippet",
        "new in story 425: prints one ledger asset's bytes after checking its path is under "
        "/workspace/output/productions/ and its sha256 matches, read-only"),
    "qwen_image_2_1_t2i_API.json": Pin(
        "f18a6e29a1f225467874d6c4d9fe16861982ad9ff6e274ca3d170245c43d226d", "graph",
        "poc/graphs/qwen_image_2_1_t2i_API.json, byte for byte (hand-converted from "
        "haynes-ops UI template image_qwen_image_2_1_t2i.json)"),
    "qwen_image_2_1_edit_API.json": Pin(
        "946f46812559426297191419e8e4ca614ac948698f8a5ae9d09cda6b0e2fdcb6", "graph",
        "haynes-ops kubernetes/main/apps/ai/stable-diffusion/comfyui/resources/api-workflows/"
        f"qwen_image_2_1_edit_API.json at {HAYNES_OPS_COMMIT} (git blob f520dcd4937c, last "
        "changed in 31b449445dc1), the commit prompts.json records; copied once"),
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
