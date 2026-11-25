"""Direct worker transports to the configured ComfyUI and Kokoro services."""

import asyncio
import io
import re
import wave
from hashlib import sha256
from time import monotonic, sleep

import httpx

from haynes_studio.adapters import pinned
from haynes_studio.adapters.comfyui import (
    EDIT_GRAPH, PNG_SIGNATURE, T2I_GRAPH, ImageEdit, ImageResult, QueueState, graph_sha256, image_graph,
)
from haynes_studio.adapters.errors import AdapterError
from haynes_studio.adapters.kokoro import MAX_WAV_BYTES, SpeechTake, parse_wav
from haynes_studio.jsonio import parse_strict

from .asr import _send
from .media_worker import ImageQueueBusy
from .progress import ProgressFile

MAX_CONTROL_BYTES = 8 * 1024 * 1024
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_PCM_BYTES = 2_000_000
PROMPT_ID = re.compile(r"[0-9a-fA-F-]{1,64}")


class ComfyHTTP:
    def __init__(self, http, *, clock=monotonic, pause=sleep, progress=None):
        self.http, self.clock, self.pause = http, clock, pause
        self.progress = progress or ProgressFile()
        # Reuse the pinned graphs and their deterministic request filling.
        self.t2i_graph = pinned.load(T2I_GRAPH)
        self.edit_graph = pinned.load(EDIT_GRAPH)

    def _read(self, method, path, limit, **kwargs):
        self.progress()
        data = bytearray()
        with self.http.stream(method, path, **kwargs) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                if len(data) + len(chunk) > limit:
                    raise ValueError("ComfyUI response too large")
                data.extend(chunk)
        return bytes(data)

    def _json(self, method, path, **kwargs):
        result = parse_strict(self._read(method, path, MAX_CONTROL_BYTES, **kwargs).decode("utf-8"))
        if not isinstance(result, dict):
            raise ValueError("Expected a ComfyUI response object")
        return result

    def queue(self):
        try:
            queue = self._json("GET", "/queue")
            return QueueState(len(_array(queue["queue_running"])), len(_array(queue["queue_pending"])))
        except (httpx.HTTPError, KeyError, TypeError, ValueError, RecursionError):
            raise AdapterError("adapter.response_invalid", "comfyui", "The shared image queue is unknown") from None

    def render(self, request, *, before_submit):
        graph = image_graph(request, t2i_graph=self.t2i_graph, edit_graph=self.edit_graph)
        try:
            if isinstance(request, ImageEdit):
                answer = self._json("POST", "/upload/image", files={
                    "image": (request.upload_name, request.source_png, "image/png"),
                }, data={"overwrite": "true"})
                if answer.get("name") != request.upload_name or answer.get("subfolder", "") != "":
                    raise ValueError("ComfyUI renamed the upload")
            if not self.queue().idle:
                raise ImageQueueBusy()
            started = self.clock()
            before_submit()
            answer = self._json("POST", "/prompt", json={
                "prompt": graph, "client_id": f"studio-{request.job}",
            })
            prompt_id = answer["prompt_id"]
            if not isinstance(prompt_id, str) or not PROMPT_ID.fullmatch(prompt_id):
                raise ValueError("Invalid prompt ID")
            while self.clock() - started < 1200:
                history = self._json("GET", f"/history/{prompt_id}").get(prompt_id, {})
                status = history.get("status", {})
                if status.get("status_str") == "error":
                    raise AdapterError("adapter.command_failed", "comfyui", "The image prompt failed")
                if status.get("completed") is True:
                    return self._image(request, graph, prompt_id, history, started)
                self.pause(3)
        except (httpx.HTTPError, AttributeError, KeyError, StopIteration, TypeError, ValueError, RecursionError):
            raise AdapterError("adapter.response_invalid", "comfyui", "ComfyUI did not return a verified image") from None
        raise AdapterError("adapter.timeout", "comfyui", "The image prompt exceeded its time limit")

    def _image(self, request, graph, prompt_id, history, started):
        image = next(item for node in history["outputs"].values()
                     for item in node.get("images", []) if item.get("type") == "output")
        name, folder = image["filename"], image["subfolder"]
        if (not isinstance(name, str) or not name.endswith(".png") or "/" in name or "\\" in name
                or not name.startswith(request.name + "_") or folder != f"studio/{request.job}"):
            raise ValueError("Unexpected ComfyUI output locator")
        data = self._read("GET", "/view", MAX_IMAGE_BYTES, params={
            "filename": name, "subfolder": folder, "type": "output",
        })
        if not data.startswith(PNG_SIGNATURE):
            raise ValueError("ComfyUI did not return PNG")
        return ImageResult(data, sha256(data).hexdigest(), prompt_id, name, folder, 0.0,
                           round(self.clock() - started, 1), graph_sha256(graph))


def _array(value):
    if not isinstance(value, list):
        raise ValueError("Expected an array")
    return value


class WyomingKokoro:
    def __init__(self, host, port=10210):
        self.host, self.port = host, port

    def synthesize(self, request):
        try:
            data = asyncio.run(asyncio.wait_for(self._voice(request), timeout=45))
        except (OSError, ValueError, EOFError) as error:
            code = "adapter.timeout" if isinstance(error, TimeoutError) else "adapter.response_invalid"
            raise AdapterError(code, "kokoro", "Wyoming did not return speech") from error
        if len(data) > MAX_WAV_BYTES:
            raise AdapterError("adapter.response_invalid", "kokoro", "The returned WAV is too large")
        return SpeechTake(data, sha256(data).hexdigest(), *parse_wav(data, "kokoro"))

    async def _voice(self, request):
        reader, writer = await asyncio.open_connection(self.host, self.port, limit=8192)
        try:
            await _send(writer, "synthesize", {"text": request.text, "voice": {"name": request.voice}})
            audio, format_ = bytearray(), None
            while header := await reader.readline():
                event = parse_strict(header.decode("utf-8"))
                if not isinstance(event, dict):
                    break
                data_size, payload_size = event.get("data_length", 0), event.get("payload_length", 0)
                if (type(data_size) is not int or not 0 <= data_size <= 8192 or type(payload_size) is not int
                        or not 0 <= payload_size <= MAX_PCM_BYTES - len(audio)):
                    break
                data = (parse_strict((await reader.readexactly(data_size)).decode("utf-8"))
                        if data_size else event.get("data", {}))
                payload = await reader.readexactly(payload_size)
                tag = event.get("type")
                if tag == "audio-start":
                    if not isinstance(data, dict) or format_ is not None:
                        break
                    format_ = tuple(data.get(key) for key in ("channels", "width", "rate"))
                    if (any(type(value) is not int for value in format_) or format_[:2] != (1, 2)
                            or not 8000 <= format_[2] <= 48000):
                        break
                elif tag == "audio-chunk" and format_ is not None:
                    if not isinstance(data, dict) or tuple(data.get(key) for key in ("channels", "width", "rate")) != format_:
                        break
                    audio.extend(payload)
                elif tag == "audio-stop" and format_ is not None and audio and len(audio) % 2 == 0:
                    output = io.BytesIO()
                    with wave.open(output, "wb") as wav:
                        wav.setparams((*format_, 0, "NONE", "not compressed"))
                        wav.writeframes(audio)
                    return output.getvalue()
                elif tag == "error":
                    break
            raise ValueError("Missing Wyoming speech")
        finally:
            writer.close()
            await writer.wait_closed()
