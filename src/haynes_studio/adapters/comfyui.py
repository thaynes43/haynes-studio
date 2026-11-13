"""Images: Qwen-Image 2.1 (int8) on the shared ComfyUI in ``ai/comfyui-0``.

Ported from ``poc/comfy.py``. The pinned snippet ``comfyui_prompt.py`` runs inside the
pod: it waits while anyone else's work is queued or running (up to 30 min, then gives
up without submitting), submits one prompt, polls its history (20 min limit) and
prints the images as base64. It never cancels or interrupts other work. The command
timeout is the PoC's 3300 s.

One prompt in flight: this process runs at most one :meth:`ImageClient.render` at a
time (a second concurrent call fails with ``adapter.busy``), and the snippet's queue
check covers everyone else. :meth:`ImageClient.queue` reads the queue without
submitting anything.

Graphs are the pinned ``qwen_image_2_1_t2i_API.json`` and
``qwen_image_2_1_edit_API.json``; the filled graph's hash is ``graph_sha256`` exactly as
``prompts.json`` records it (SHA-256 of ``json.dumps(graph, sort_keys=True)``).

    client = ImageClient(runner)
    image = client.render(TextToImage(job="the-winter-menu-r1", name="a-base-s101",
                                      prompt=text, seed=101))
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import threading
from dataclasses import dataclass, field
from typing import Any

from haynes_studio.adapters import pinned
from haynes_studio.adapters.errors import (
    BUSY,
    RESPONSE_INVALID,
    AdapterError,
    ImageError,
    RequestInvalid,
)
from haynes_studio.adapters.runner import COMFYUI, Command, ExecTarget, Runner, failure, run_checked
from haynes_studio.jsonio import parse_strict

LABEL = "comfyui.render"
QUEUE_LABEL = "comfyui.queue"
PROMPT_SNIPPET = "comfyui_prompt.py"
QUEUE_SNIPPET = "comfyui_queue.py"
T2I_GRAPH = "qwen_image_2_1_t2i_API.json"
EDIT_GRAPH = "qwen_image_2_1_edit_API.json"
TIMEOUT_S = 3300  # poc/comfy.py run(): 30 min queue wait + 20 min render + transfer
QUEUE_TIMEOUT_S = 45  # proposal; the snippet's HTTP timeout is 30 s
MAX_ANSWER_BYTES = 64 * 1024 * 1024
MAX_PROMPT = 10000  # proposal
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# The nodes each filler edits, with the class they must have (poc/comfy.py asserts
# the edit graph's two; this client checks all eight).
T2I_NODES = {"4": "TextEncodeQwenImage21", "5": "EmptyLatentImage", "6": "KSampler",
             "8": "SaveImage"}
EDIT_NODES = {"1": "LoadImage", "6": "TextEncodeQwenImage21", "7": "KSampler", "9": "SaveImage"}

NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,79}")
UPLOAD_NAME = re.compile(r"studio-[0-9a-f]{12}\.png")
PROMPT_ID = re.compile(r"PROMPT_ID ([0-9A-Za-z-]{1,64})")


def _check_common(job: Any, name: Any, prompt: Any, seed: Any) -> None:
    if not isinstance(job, str) or not NAME.fullmatch(job):
        raise RequestInvalid(LABEL, "job must be a folder name: lower-case letters, digits, hyphens")
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise RequestInvalid(LABEL, "name must be lower-case letters, digits and hyphens")
    if not isinstance(prompt, str) or not prompt.strip():
        raise RequestInvalid(LABEL, "prompt must be non-empty")
    if len(prompt) > MAX_PROMPT:
        raise RequestInvalid(LABEL, f"prompt is over {MAX_PROMPT} characters")
    if not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed < 2 ** 64:
        raise RequestInvalid(LABEL, "seed must be an integer from 0 to 2**64 - 1")


@dataclass(frozen=True)
class TextToImage:
    """``poc/comfy.py t2i``. ``job`` is the job folder's name: the output prefix is
    ``studio/<job>/<name>`` and the client ID ``studio-<job>``."""

    job: str
    name: str
    prompt: str
    seed: int
    width: int = 1104
    height: int = 1472

    def __post_init__(self):
        _check_common(self.job, self.name, self.prompt, self.seed)
        for side in (self.width, self.height):
            if not isinstance(side, int) or isinstance(side, bool) or not 64 <= side <= 4096 \
                    or side % 8:
                raise RequestInvalid(LABEL, "width and height must be multiples of 8 from 64 to 4096")


def upload_name_for(source_png: bytes) -> str:
    """A content-derived upload name in the PoC's form (proposal: the PoC used 12 random
    hex digits, which made a recorded edit graph impossible to rebuild)."""
    return f"studio-{hashlib.sha256(source_png).hexdigest()[:12]}.png"


@dataclass(frozen=True)
class ImageEdit:
    """``poc/comfy.py edit``: ``source_png`` is uploaded as ``upload_name`` (ComfyUI's
    ``/upload/image`` with ``overwrite=true``, as the PoC does), then edited."""

    job: str
    name: str
    prompt: str
    seed: int
    source_png: bytes = field(repr=False)
    upload_name: str

    def __post_init__(self):
        _check_common(self.job, self.name, self.prompt, self.seed)
        if not isinstance(self.source_png, bytes) or not self.source_png.startswith(PNG_SIGNATURE):
            raise RequestInvalid(LABEL, "source_png must be PNG bytes")
        if not isinstance(self.upload_name, str) or not UPLOAD_NAME.fullmatch(self.upload_name):
            raise RequestInvalid(LABEL, "upload_name must look like studio-<12 hex>.png")


@dataclass(frozen=True)
class ImageResult:
    png: bytes = field(repr=False)
    sha256: str
    prompt_id: str
    comfy_file: str
    comfy_subfolder: str
    waited_s: float
    render_s: float
    graph_sha256: str

    @property
    def bytes(self) -> int:
        return len(self.png)


@dataclass(frozen=True)
class QueueState:
    running: int
    pending: int

    @property
    def idle(self) -> bool:
        return self.running == 0 and self.pending == 0


def graph_sha256(graph: dict) -> str:
    """The ``graph_sha256`` ``poc/comfy.py`` records for a filled graph."""
    return hashlib.sha256(json.dumps(graph, sort_keys=True).encode()).hexdigest()


def _template(item: pinned.PinnedInput, name: str, nodes: dict[str, str]) -> dict:
    pinned.check(item, name)
    graph = json.loads(item.text)
    for node, class_type in nodes.items():
        if graph.get(node, {}).get("class_type") != class_type:
            raise RequestInvalid(LABEL, f"graph {name} node {node} is not {class_type}")
    return graph


class ImageClient:
    _in_flight = threading.Lock()  # one render per process; the snippet waits for others

    def __init__(self, runner: Runner, *, target: ExecTarget = COMFYUI,
                 prompt_snippet: pinned.PinnedInput | None = None,
                 queue_snippet: pinned.PinnedInput | None = None,
                 t2i_graph: pinned.PinnedInput | None = None,
                 edit_graph: pinned.PinnedInput | None = None):
        def take(item, name):
            return pinned.check(item, name) if item else pinned.load(name)
        self.runner = runner
        self.target = target
        self.prompt_snippet = take(prompt_snippet, PROMPT_SNIPPET)
        self.queue_snippet = take(queue_snippet, QUEUE_SNIPPET)
        self.t2i_graph = take(t2i_graph, T2I_GRAPH)
        self.edit_graph = take(edit_graph, EDIT_GRAPH)

    def graph(self, request: TextToImage | ImageEdit) -> dict:
        """The filled graph, built the way ``poc/comfy.py`` builds it."""
        prefix = f'studio/{request.job}/{request.name}'
        if isinstance(request, TextToImage):
            g = _template(self.t2i_graph, T2I_GRAPH, T2I_NODES)
            g['4']['inputs']['prompt'] = request.prompt
            g['5']['inputs'].update(width=request.width, height=request.height)
            g['6']['inputs']['seed'] = request.seed
            g['8']['inputs']['filename_prefix'] = prefix
            return g
        if isinstance(request, ImageEdit):
            g = _template(self.edit_graph, EDIT_GRAPH, EDIT_NODES)
            g['6']['inputs']['prompt'] = request.prompt
            g['7']['inputs']['seed'] = request.seed
            g['1']['inputs']['image'] = request.upload_name
            g['9']['inputs']['filename_prefix'] = prefix
            return g
        raise RequestInvalid(LABEL, "request must be TextToImage or ImageEdit")

    def payload(self, request: TextToImage | ImageEdit, graph: dict | None = None) -> bytes:
        """The stdin bytes, exactly as ``poc/comfy.py`` ``run()`` writes them."""
        payload = {'graph': graph if graph is not None else self.graph(request),
                   'client_id': f'studio-{request.job}'}
        if isinstance(request, ImageEdit):
            payload['upload'] = {'name': request.upload_name,
                                 'b64': base64.b64encode(request.source_png).decode()}
        return json.dumps(payload).encode()

    def command(self, request: TextToImage | ImageEdit, graph: dict | None = None) -> Command:
        pinned.check(self.prompt_snippet, PROMPT_SNIPPET)
        return Command(LABEL, self.target.argv(self.prompt_snippet.text),
                       self.payload(request, graph), TIMEOUT_S, self.target.describe())

    def render(self, request: TextToImage | ImageEdit) -> ImageResult:
        graph = self.graph(request)
        command = self.command(request, graph)
        if not ImageClient._in_flight.acquire(blocking=False):
            raise ImageError(BUSY, LABEL, "another render is in flight in this process; "
                                          "one prompt at a time on the shared GPU")
        try:
            result = self.runner.run(command)
        except ImageError:
            raise
        except AdapterError as error:  # a timeout: the prompt may be running on the GPU
            raise ImageError(error.code, LABEL, error.message, prompt_id=_prompt_id(error.detail),
                             detail=error.detail) from None
        finally:
            ImageClient._in_flight.release()
        prompt_id = _prompt_id(result.stderr.decode("utf-8", "replace"))
        if result.returncode != 0:
            raise failure(command, result, error=ImageError, prompt_id=prompt_id)
        return self._parse(result.stdout, graph, prompt_id)

    def _parse(self, stdout: bytes, graph: dict, prompt_id: str | None) -> ImageResult:
        def bad(message):
            return ImageError(RESPONSE_INVALID, LABEL, message, prompt_id=prompt_id)
        if len(stdout) > MAX_ANSWER_BYTES:
            raise bad("answer is too long")
        try:
            out = parse_strict(stdout.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise bad("answer is not one JSON object") from None
        if not isinstance(out, dict) or not isinstance(out.get("prompt_id"), str) \
                or not isinstance(out.get("images"), list) or not out["images"]:
            raise bad("answer has no prompt_id or no images")
        prompt_id = out["prompt_id"]
        image = out["images"][0]
        if not isinstance(image, dict) or not all(isinstance(image.get(k), str)
                                                  for k in ("b64", "filename", "subfolder")):
            raise bad("first image lacks b64, filename or subfolder")
        try:
            data = base64.b64decode(image["b64"], validate=True)
        except (binascii.Error, ValueError):
            raise bad("first image is not base64") from None
        if not data.startswith(PNG_SIGNATURE):
            raise bad("first image is not a PNG")
        timings = [out.get("waited_s"), out.get("render_s")]
        if not all(isinstance(t, int | float) and not isinstance(t, bool) for t in timings):
            raise bad("answer lacks waited_s or render_s")
        return ImageResult(data, hashlib.sha256(data).hexdigest(), prompt_id, image["filename"],
                           image["subfolder"], float(timings[0]), float(timings[1]),
                           graph_sha256(graph))

    def queue_command(self) -> Command:
        pinned.check(self.queue_snippet, QUEUE_SNIPPET)
        return Command(QUEUE_LABEL, self.target.argv(self.queue_snippet.text), b"",
                       QUEUE_TIMEOUT_S, self.target.describe())

    def queue(self) -> QueueState:
        """ComfyUI's running and pending counts. Submits nothing."""
        result = run_checked(self.runner, self.queue_command(), error=ImageError)
        try:
            out = parse_strict(result.stdout.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise ImageError(RESPONSE_INVALID, QUEUE_LABEL, "answer is not one JSON object") from None
        counts = [out.get(k) if isinstance(out, dict) else None for k in ("running", "pending")]
        if not all(isinstance(c, int) and not isinstance(c, bool) and c >= 0 for c in counts):
            raise ImageError(RESPONSE_INVALID, QUEUE_LABEL, "answer lacks running or pending counts")
        return QueueState(*counts)


def _prompt_id(stderr: str) -> str | None:
    """The ``PROMPT_ID`` line the snippet prints once ComfyUI accepts a prompt."""
    found = PROMPT_ID.search(stderr or "")
    return found.group(1) if found else None
