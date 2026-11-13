"""Deterministic fakes for the service clients, for this package's tests and later
stories'. Nothing here starts a process or opens a socket.

A :class:`FakeRunner` records every :class:`~haynes_studio.adapters.runner.Command` and
answers it from the fake service that owns the command's in-pod snippet, identified by
the snippet's pinned SHA-256 (an unpinned snippet is :class:`UnexpectedCommand`).
Answers are synthetic bytes (:func:`synthetic_wav`, :func:`synthetic_png`) or JSON in
the shape each snippet prints, so the same inputs always give the same bytes.

    kokoro = FakeKokoro()
    runner = FakeRunner(kokoro, FakeWhisper(kokoro.spoken))
    take = KokoroClient(runner).synthesize(SpeechRequest("bf_emma", "Aye."))
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import struct
import uuid
import wave
import zlib
from collections.abc import Iterable, Mapping

from haynes_studio.adapters.pinned import PINS
from haynes_studio.adapters.runner import Command, Completed

_BY_SHA = {pin.sha256: name for name, pin in PINS.items() if pin.kind == "snippet"}


class UnexpectedCommand(AssertionError):
    """A command no fake service answers: not ``kubectl exec ... -c <pinned snippet>``."""


def snippet_of(command: Command) -> tuple[str, tuple[str, ...]]:
    """The pinned snippet name a ``kubectl exec`` command runs, and its extra arguments."""
    argv = command.argv
    if argv[:2] != ("kubectl", "exec") or "--" not in argv:
        raise UnexpectedCommand(f"{command.label}: not a kubectl exec command")
    rest = argv[argv.index("--") + 1:]
    if len(rest) < 3 or rest[1] != "-c":
        raise UnexpectedCommand(f"{command.label}: expected <python> -c <code>")
    name = _BY_SHA.get(hashlib.sha256(rest[2].encode()).hexdigest())
    if name is None:
        raise UnexpectedCommand(f"{command.label}: the code is not a pinned snippet")
    return name, rest[3:]


class FakeRunner:
    """A runner that answers from fake services. ``calls`` holds every command run."""

    def __init__(self, *services):
        self.calls: list[Command] = []
        self._by_snippet = {}
        for service in services:
            for name in service.snippets:
                self._by_snippet[name] = service

    def run(self, command: Command) -> Completed:
        self.calls.append(command)
        name, args = snippet_of(command)
        service = self._by_snippet.get(name)
        if service is None:
            raise UnexpectedCommand(f"{command.label}: no fake answers {name}")
        return service.answer(name, command, args)


class FailingRunner:
    """Answers every command with one fixed result (an exit status and stderr)."""

    def __init__(self, returncode: int = 1, stderr: bytes = b"", stdout: bytes = b""):
        self.calls: list[Command] = []
        self.result = Completed(returncode, stdout, stderr)

    def run(self, command: Command) -> Completed:
        self.calls.append(command)
        return self.result


# Synthetic media -------------------------------------------------------------------


def synthetic_wav(frames: int, *, rate: int = 24000, channels: int = 1, seed: int = 0) -> bytes:
    """A 16-bit PCM WAV of ``frames`` frames: a quiet square wave whose period depends
    on ``seed``. 24 kHz mono is what Kokoro returned in OP345. At most 10 s."""
    if not 0 < frames <= rate * 10:
        raise ValueError("a synthetic WAV is 1 frame to 10 s long")
    period = 40 + seed % 80
    level = 2000
    sample = struct.Struct("<h")
    frame = [sample.pack(level if (i // (period // 2)) % 2 else -level) for i in range(period)]
    data = b"".join(frame[i % period] * channels for i in range(frames))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(data)
    return buffer.getvalue()


def _png_chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def synthetic_png(width: int = 8, height: int = 8, *, seed: int = 0) -> bytes:
    """A small RGB PNG whose colour depends on ``seed``. At most 360x640."""
    if not (0 < width <= 360 and 0 < height <= 640):
        raise ValueError("a synthetic PNG is at most 360x640")
    pixel = bytes(((seed * 37) % 256, (seed * 91) % 256, (seed * 53) % 256))
    rows = b"".join(b"\x00" + pixel * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", header)
            + _png_chunk(b"IDAT", zlib.compress(rows, 9)) + _png_chunk(b"IEND", b""))


def _seed(*parts: str) -> int:
    return int(hashlib.sha256("\x00".join(parts).encode()).hexdigest()[:8], 16)


# Services ----------------------------------------------------------------------------


class FakeKokoro:
    """Answers ``kokoro_tts.py`` with a synthetic WAV. ``frames`` maps ``(voice, text)``
    to a frame count (default: 2 400 frames per 10 characters, 0.2 to 3 s). ``spoken``
    maps each answer's SHA-256 to its text, for :class:`FakeWhisper`."""

    snippets = ("kokoro_tts.py",)

    def __init__(self, frames: Mapping[tuple[str, str], int] | None = None, *, rate: int = 24000):
        self.frames = dict(frames or {})
        self.rate = rate
        self.spoken: dict[str, str] = {}
        self.requests: list[dict] = []

    def answer(self, name: str, command: Command, args) -> Completed:
        request = json.loads(command.stdin)
        self.requests.append(request)
        voice, text = request["voice"], request["text"]
        frames = self.frames.get((voice, text))
        if frames is None:
            frames = min(max(240 * len(text), self.rate // 5), self.rate * 3)
        wav = synthetic_wav(frames, rate=self.rate, seed=_seed(voice, text))
        self.spoken[hashlib.sha256(wav).hexdigest()] = text
        return Completed(0, wav, b"")


class FakeWhisper:
    """Answers ``whisper_asr.py`` with ``{"transcript": ...}``: the text ``transcripts``
    maps the WAV's SHA-256 to, else ``default``; with neither, the snippet's error."""

    snippets = ("whisper_asr.py",)

    def __init__(self, transcripts: Mapping[str, str] | None = None, *, default: str | None = None):
        self.transcripts = transcripts if transcripts is not None else {}
        self.default = default
        self.heard: list[str] = []

    def answer(self, name: str, command: Command, args) -> Completed:
        text = self.transcripts.get(hashlib.sha256(command.stdin).hexdigest(), self.default)
        if text is None:
            return Completed(1, b"", b"RuntimeError: STT error\n")
        self.heard.append(text)
        return Completed(0, (json.dumps({'transcript': text}) + "\n").encode(), b"")


class FakeComfyUI:
    """Answers ``comfyui_prompt.py`` with one synthetic PNG per prompt, and
    ``comfyui_queue.py`` with ``running`` and ``pending``. The prompt ID is a UUID
    derived from the graph's hash, as stable as the graph."""

    snippets = ("comfyui_prompt.py", "comfyui_queue.py")

    def __init__(self, *, running: int = 0, pending: int = 0, waited_s: float = 0,
                 render_s: float = 1.5):
        self.running = running
        self.pending = pending
        self.waited_s = waited_s
        self.render_s = render_s
        self.payloads: list[dict] = []

    def answer(self, name: str, command: Command, args) -> Completed:
        if name == "comfyui_queue.py":
            body = {'running': self.running, 'pending': self.pending}
            return Completed(0, (json.dumps(body) + "\n").encode(), b"")
        job = json.loads(command.stdin)
        self.payloads.append(job)
        graph_hash = hashlib.sha256(json.dumps(job["graph"], sort_keys=True).encode()).hexdigest()
        prompt_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "fake-comfyui:" + graph_hash))
        prefix = next(node["inputs"]["filename_prefix"] for node in job["graph"].values()
                      if node.get("class_type") == "SaveImage")
        subfolder, _, stem = prefix.rpartition("/")
        png = synthetic_png(seed=int(graph_hash[:8], 16))
        image = {'filename': f'{stem}_00001_.png', 'subfolder': subfolder, 'type': 'output',
                 'b64': base64.b64encode(png).decode()}
        stderr = b""
        if job.get("upload"):
            stderr += b"uploaded {'name': '%s', 'subfolder': '', 'type': 'input'}\n" % (
                job["upload"]["name"].encode())
        stderr += f"PROMPT_ID {prompt_id}\n".encode()
        body = {'prompt_id': prompt_id, 'waited_s': self.waited_s, 'render_s': self.render_s,
                'images': [image]}
        return Completed(0, (json.dumps(body) + "\n").encode(), stderr)


_LEDGER_FILE = re.compile(r"[0-9a-f]{32}")


class FakeWanLedger:
    """Answers the three read-only ledger snippets from ``ledgers`` (documents such as
    the committed ``titles/<slug>/evidence*/production.json``) and ``files`` (absolute
    PVC path to bytes). ``unreadable`` names ledger files the pod could not parse."""

    snippets = ("wan_ledger_read.py", "wan_ledger_list.py", "wan_ledger_fetch.py")

    def __init__(self, ledgers: Iterable[Mapping] = (), *, files: Mapping[str, bytes] | None = None,
                 unreadable: Iterable[str] = ()):
        self.ledgers = {ledger["id"]: dict(ledger) for ledger in ledgers}
        self.files = dict(files or {})
        self.unreadable = tuple(unreadable)

    def answer(self, name: str, command: Command, args) -> Completed:
        if name == "wan_ledger_read.py":
            ledger = self.ledgers.get(args[0]) if args else None
            if ledger is None:
                return Completed(1, b"", b"urllib.error.HTTPError: HTTP Error 404: Not Found\n")
            return Completed(0, (json.dumps(ledger) + "\n").encode(), b"")
        if name == "wan_ledger_list.py":
            out = [{'file': f, 'error': 'unreadable'} for f in self.unreadable]
            for ledger_id in sorted(self.ledgers):
                j = self.ledgers[ledger_id]
                if j.get('kind') != 'edited_production':
                    continue
                assets = j.get('assets') if isinstance(j.get('assets'), list) else []
                out.append({'id': j.get('id'), 'title': j.get('title'), 'state': j.get('state'),
                            'output': j.get('output'), 'bytes': j.get('bytes'),
                            'sha256': j.get('sha256'), 'created_at': j.get('created_at'),
                            'asset_sha256': sorted({a['sha256'] for a in assets
                                                    if isinstance(a.get('sha256'), str)})})
            return Completed(0, (json.dumps(out) + "\n").encode(), b"")
        ledger_id, digest = args
        ledger = self.ledgers.get(ledger_id)
        if ledger is None:
            return Completed(1, b"", b"FileNotFoundError: [Errno 2] No such file or directory\n")
        match = [a for a in ledger.get("assets", []) if a.get("sha256") == digest]
        if not match:
            return Completed(1, b"", b"no asset with that sha256 in the ledger\n")
        data = self.files.get(match[0]["path"])
        if data is None:
            return Completed(1, b"", b"FileNotFoundError: [Errno 2] No such file or directory\n")
        if hashlib.sha256(data).hexdigest() != digest:
            return Completed(1, b"", b"asset bytes do not match the ledger sha256\n")
        return Completed(0, data, b"")
