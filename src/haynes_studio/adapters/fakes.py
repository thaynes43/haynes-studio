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
import builtins
import hashlib
import io
import json
import re
import struct
import uuid
import wave
import zlib
from collections.abc import Iterable, Mapping

from haynes_studio.adapters.pinned import PINS, WAN_GPU_UUIDS
from haynes_studio.adapters.runner import Command, Completed
from haynes_studio.adapters.wan import s2v_frames_delivered  # E0's S2V frame counts (test_wan_compat)

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


# The Wan pod (story 842) -------------------------------------------------------------------

class FakeHTTPError(Exception):
    """What ``urllib.request.urlopen`` raises for an HTTP error status, as the pod's
    traceback names it."""

    shown_as = "urllib.error.HTTPError"

    def __init__(self, status: int, reason: str):
        super().__init__(f"HTTP Error {status}: {reason}")


class _Response(io.BytesIO):
    """What ``urllib.request.urlopen`` returns: the body, and the URL it was read from
    (another one when the read was redirected)."""

    def __init__(self, data: bytes, url: str):
        super().__init__(data)
        self._url = url

    def geturl(self) -> str:
        return self._url


class _PodOut:
    """A pod process's stdout or stderr: text and ``.buffer`` bytes into one stream."""

    def __init__(self):
        self.buffer = io.BytesIO()

    def write(self, text):
        self.buffer.write(text.encode("utf-8"))
        return len(text)

    def flush(self):
        pass

    def value(self) -> bytes:
        return self.buffer.getvalue()


class _PodIn:
    def __init__(self, data: bytes):
        self.buffer = io.BytesIO(data)

    def read(self, *args):
        return self.buffer.read(*args).decode("utf-8")


class _PodPath:
    """The few ``pathlib.Path`` calls ``wan_upload.py`` makes, on the fake volume."""

    def __init__(self, pod: FakeWan, path: str):
        self._pod, self._path = pod, path

    def __truediv__(self, name: str) -> _PodPath:
        return _PodPath(self._pod, self._path.rstrip("/") + "/" + name)

    @property
    def parent(self) -> _PodPath:
        return _PodPath(self._pod, self._path.rsplit("/", 1)[0])

    def mkdir(self, parents=False, exist_ok=False):
        self._pod.folders.add(self._path)

    def exists(self) -> bool:
        return self._path in self._pod.files

    def read_bytes(self) -> bytes:
        return self._pod.files[self._path]

    def open(self, mode: str):
        if mode != "xb":
            raise AssertionError(f"the fake volume opens files create-only, not {mode!r}")
        if self._path in self._pod.files:
            raise FileExistsError(f"[Errno 17] File exists: {self._path!r}")
        return _PodCreate(self._pod, self._path)


class _PodCreate:
    def __init__(self, pod: FakeWan, path: str):
        self._pod, self._path, self._data = pod, path, io.BytesIO()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._pod.files[self._path] = self._data.getvalue()
        self._pod.writes.append(("create", self._path))
        return False

    def write(self, data: bytes):
        return self._data.write(data)


class _Namespace:
    def __init__(self, **members):
        self.__dict__.update(members)


class FakeWan:
    """The Wan API container (``ai/deploy/wan-video``, container ``api``) for the Wan clip
    client's tests. It **runs the pinned snippets themselves** (``wan_probe.py``,
    ``wan_upload.py``, ``wan_run.py``, ``wan_clip_fetch.py``, ``wan_ledger_read.py``),
    each in a namespace whose ``sys``, ``time``, ``pathlib``, ``urllib.request`` and
    ``api`` are this pod's and whose builtins have no ``open``, ``exec``, ``eval`` or
    ``compile``: nothing reaches the host's files, clock or network.

    The ``api`` module is a port of the installed ``api.py`` (haynes-ops
    ``kubernetes/main/apps/ai/wan-video/app/api.py``): ``generate()`` takes the compute
    lease, checks the GPUs and the engine queue, submits once, polls the history with the
    API's own miss tolerance, and records the job's ledger with ``save()``. ComfyUI is a
    small engine that answers ``/queue``, ``/prompt`` and ``/history/<id>`` and makes a
    synthetic MP4 of the frames the graph asks for (S2V: as many as E0's clips had).

    Behaviours, all off by default: ``accepting=False`` or ``active_job`` (an API hold or
    busy job); ``hold_at_admission`` (the hold starts after the last probe, so only the
    run's admission readback sees it); ``lease_held`` (another job holds the compute
    lease); ``gpu_trace`` (per probe: each GPU's ``(temperature_c, utilization_percent)``,
    the last repeating; hot or busy GPUs); ``busy_at_generate``; ``queue_running`` /
    ``queue_pending`` (foreign work queued before the job); ``foreign_during_job``
    (foreign prompt IDs in the queue while the job runs); ``slow_reads`` (that many
    engine history reads time out first); ``slow_prompt`` (the ``/prompt`` write times
    out); ``outcome`` (``"success"``, ``"error"``, ``"no_mp4"``); ``deliver_frames``; ``deliver_size``;
    ``deliver_fps`` (the clip is encoded at another rate than the graph's);
    ``null_queue_in_run`` (inside ``wan_run.py`` the engine's ``/queue`` answers null lists,
    which ``api.generate()``'s truthiness check reads as idle); ``redirect_fetch`` (the
    clip read is redirected, so ``geturl()`` names another URL); ``corrupt_clip``; ``lose`` (``"timeout"``, ``"empty"``, ``"exit"``: the run's answer is
    lost after the job ran, and ``lost_state`` is what its ledger then reads, ``None`` for
    no ledger; ``"no_start"``: the command fails before the snippet starts);
    ``mangle_fetch`` (the clip is cut in transfer).

    Each snippet run gets a fresh ``api`` module, as each ``kubectl exec`` is a new
    process in the real pod. ``payloads`` holds every run's stdin, ``submitted`` every
    graph sent to ``/prompt``,
    ``engine_calls`` every engine call (path, whether it had a body), ``files`` the
    volume, ``writes`` every write to it and ``jobs`` the saved ledgers."""

    snippets = ("wan_probe.py", "wan_upload.py", "wan_run.py", "wan_clip_fetch.py",
                "wan_ledger_read.py")

    def __init__(self, *, accepting: bool = True, active_job: str | None = None,
                 hold_at_admission: bool = False, lease_held: bool = False,
                 gpu_trace: Iterable[Iterable[tuple[float, float]]] = (((45.0, 0.0), (44.0, 0.0)),),
                 busy_at_generate: bool = False,
                 queue_running: Iterable[str] = (), queue_pending: Iterable[str] = (),
                 foreign_during_job: Iterable[str] = (), slow_reads: int = 0,
                 slow_prompt: bool = False, history_polls: int = 2, outcome: str = "success",
                 deliver_frames: int | None = None, deliver_size: tuple[int, int] | None = None,
                 deliver_fps: int | None = None, corrupt_clip: bool = False,
                 null_queue_in_run: bool = False, redirect_fetch: bool = False,
                 lose: str | None = None, lost_state: str | None = "running",
                 mangle_fetch: bool = False, files: Mapping[str, bytes] | None = None):
        self.health = {'api': 'ok', 'accepting_jobs': accepting, 'active_job': active_job}
        self.hold_at_admission = hold_at_admission
        self.lease_held = lease_held
        self.gpu_trace = [tuple(probe) for probe in gpu_trace]
        self.busy_at_generate = busy_at_generate
        self.queue_running = list(queue_running)
        self.queue_pending = list(queue_pending)
        self.foreign_during_job = list(foreign_during_job)
        self.slow_reads = slow_reads
        self.slow_prompt = slow_prompt
        self.history_polls = history_polls
        self.outcome = outcome
        self.deliver_frames = deliver_frames
        self.deliver_size = deliver_size
        self.deliver_fps = deliver_fps
        self.null_queue_in_run = null_queue_in_run
        self.redirect_fetch = redirect_fetch
        self.corrupt_clip = corrupt_clip
        self.lose = lose
        self.lost_state = lost_state
        self.mangle_fetch = mangle_fetch
        self.files: dict[str, bytes] = dict(files or {})
        self.folders: set[str] = set()
        self.writes: list[tuple[str, str]] = []
        self.jobs: dict[str, dict] = {}
        self.payloads: list[dict] = []
        self.submitted: list[dict] = []
        self.engine_calls: list[tuple[str, bool]] = []
        self.probes = 0
        self.unsafe = False  # what api.py sets when its cleanup meets work it cannot account for
        self.now = 1_800_000_000.0
        self.slept: list[float] = []
        self._snippet = None
        self._running_prompt = None
        self._client_id = None
        self._polls = 0
        self._api = self._make_api()

    # The runner's view -------------------------------------------------------------------

    def answer(self, name: str, command: Command, args) -> Completed:
        if name == "wan_run.py":
            self.payloads.append(json.loads(command.stdin))
            if self.lose == "no_start":
                return Completed(1, b"", b"error: unable to upgrade connection: container not found\n")
        code = command.argv[command.argv.index("--") + 3]  # <python> -c <code>
        result = self.run_snippet(name, code, args, command.stdin)
        if name == "wan_run.py" and self.lose:
            job_id = self.payloads[-1]["job"]["id"]
            if self.lost_state is None:
                self.jobs.pop(job_id, None)
            elif job_id in self.jobs:
                self.jobs[job_id]["state"] = self.lost_state
            if self.lose == "timeout":
                from haynes_studio.adapters.errors import TIMEOUT, AdapterError  # noqa: PLC0415
                raise AdapterError(TIMEOUT, command.label, f"no answer within {command.timeout_s:g} s")
            if self.lose == "empty":
                return Completed(0, b"", b"")
            return Completed(1, b"", b"error: lost connection to pod\n")
        if name == "wan_clip_fetch.py" and self.mangle_fetch and result.returncode == 0:
            return Completed(0, result.stdout[: len(result.stdout) // 2], result.stderr)
        return result

    def run_snippet(self, name: str, code: str, args, stdin: bytes = b"") -> Completed:
        """Run one snippet's code in the fake pod: exit status, stdout, stderr."""
        out, err = _PodOut(), _PodOut()
        self._api = self._make_api()  # each kubectl exec is a new process with a fresh api module
        pod_sys = _Namespace(argv=["-c", *args], path=[], stdin=_PodIn(stdin), stdout=out, stderr=err)
        urllib = _Namespace(request=_Namespace(urlopen=self._urlopen))
        modules = {"sys": pod_sys, "json": json, "hashlib": hashlib, "api": self._api,
                   "time": _Namespace(time=lambda: self.now, sleep=self._sleep),
                   "pathlib": _Namespace(Path=lambda path: _PodPath(self, path)),
                   "urllib": urllib, "urllib.request": urllib}

        def pod_import(module, globals=None, locals=None, fromlist=(), level=0):
            if module not in modules:
                raise ImportError(f"the fake pod has no module {module}")
            return modules[module]

        def pod_print(*values, sep=" ", end="\n", file=None, flush=False):
            (file or out).write(sep.join(str(v) for v in values) + end)

        namespace = {k: v for k, v in vars(builtins).items()
                     if k not in ("open", "exec", "eval", "compile", "input", "breakpoint", "__loader__")}
        namespace.update(__import__=pod_import, print=pod_print)
        self._snippet = name
        if name == "wan_probe.py":
            self.probes += 1
        try:
            exec(compile(code, name, "exec"), {"__builtins__": namespace, "__name__": "__main__"})
        except Exception as error:  # in the pod: a traceback and exit status 1
            shown = getattr(error, "shown_as", type(error).__name__)
            err.write(f"Traceback (most recent call last):\n  File \"<string>\", line 1, in <module>\n"
                      f"{shown}: {error}\n")
            return Completed(1, out.value(), err.value())
        finally:
            self._snippet = None
        return Completed(0, out.value(), err.value())

    # The pod -----------------------------------------------------------------------------

    def _sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds

    def _urlopen(self, url, timeout=None):
        base = "http://127.0.0.1:8080"
        if not url.startswith(base):
            raise AssertionError(f"the fake pod serves only the Wan API, not {url}")
        path = url[len(base):]
        if path == "/health":
            health = dict(self.health)
            if self.hold_at_admission and self._snippet == "wan_run.py":
                health["accepting_jobs"] = False
            return _Response(json.dumps(health).encode(), url)
        parts = path.strip("/").split("/")
        if len(parts) in (2, 3) and parts[0] == "videos":
            job = self.jobs.get(parts[1])
            if job is None:
                raise FakeHTTPError(404, "Not Found")
            if len(parts) == 2:
                return _Response(json.dumps(job).encode(), url)
            if parts[2] == "file" and job["state"] == "succeeded":
                return _Response(self.files["/workspace/output/" + job["output"]],
                                 base + "/redirected/elsewhere" if self.redirect_fetch else url)
            raise FakeHTTPError(409, "Conflict")
        raise FakeHTTPError(404, "Not Found")

    def _gpu_sample(self):
        # Each probe reads the next entry of the trace (the last repeats); the job sees
        # the state of the last probe.
        state = self.gpu_trace[max(0, min(self.probes, len(self.gpu_trace)) - 1)]
        busy = self._running_prompt is not None or (self.busy_at_generate and self._snippet == "wan_run.py")
        gpus = [{'uuid': uuid_, 'memory_mib': 20500.0 if busy else 300.0,
                 'utilization_percent': 100.0 if busy else util, 'power_w': 30.0,
                 'temperature_c': temp} for uuid_, (temp, util) in zip(WAN_GPU_UUIDS, state)]
        return {'time': self.now, 'gpus': gpus}

    def _engine(self, path, body=None):
        self.engine_calls.append((path, body is not None))
        if path == "/queue" and body is None and self.null_queue_in_run and self._snippet == "wan_run.py":
            return {'queue_running': None, 'queue_pending': None}
        if path == "/queue" and body is None:
            running = [[0, p, {}, {'client_id': 'other'}] for p in self.queue_running]
            if self._running_prompt is not None:
                running.append([1, self._running_prompt, {}, {'client_id': self._client_id}])
                running += [[2, p, {}, {'client_id': 'other'}] for p in self.foreign_during_job]
            return {'queue_running': running,
                    'queue_pending': [[3, p, {}, {'client_id': 'other'}] for p in self.queue_pending]}
        if path == "/prompt":
            if self.slow_prompt:
                self.now += 20  # api.engine's urlopen timeout
                raise TimeoutError("timed out")
            self.submitted.append(body)
            graph_hash = hashlib.sha256(json.dumps(body["prompt"], sort_keys=True).encode()).hexdigest()
            self._running_prompt = str(uuid.uuid5(uuid.NAMESPACE_URL, "fake-wan:" + graph_hash))
            self._client_id = body["client_id"]
            self._polls = 0
            return {'prompt_id': self._running_prompt, 'number': 1}
        if path.startswith("/history/") and body is None:
            if self.slow_reads > 0:
                self.slow_reads -= 1
                self.now += 20  # api.engine's urlopen timeout
                raise TimeoutError("timed out")
            prompt_id = path[len("/history/"):]
            if prompt_id != self._running_prompt:
                return {}
            self._polls += 1
            if self._polls < self.history_polls:
                return {}
            self._running_prompt = None
            if self.outcome == "error":
                return {prompt_id: {'status': {'status_str': 'error'}, 'outputs': {}}}
            if self.outcome == "no_mp4":
                return {prompt_id: {'status': {'status_str': 'success'}, 'outputs': {}}}
            graph = self.submitted[-1]["prompt"]
            save = next(n for n in graph.values() if n.get("class_type") == "SaveVideo")
            subfolder, _, stem = save["inputs"]["filename_prefix"].rpartition("/")
            filename = f"{stem}_00001_.mp4"
            self.files[f"/workspace/output/{subfolder}/{filename}"] = self._clip(graph)
            self.writes.append(("engine-output", f"/workspace/output/{subfolder}/{filename}"))
            return {prompt_id: {'status': {'status_str': 'success', 'completed': True},
                                'outputs': {'save': {'images': [{'filename': filename, 'subfolder': subfolder,
                                                                 'type': 'output'}],
                                                     'animated': [True]}}}}
        if path == "/interrupt" and body is not None:  # api.py interrupts only its own prompt
            self._running_prompt = None
            return {}
        if path == "/queue" and body is not None:  # api.py deletes only its own pending prompts
            self.queue_pending = [p for p in self.queue_pending if p not in body.get("delete", [])]
            return {}
        raise AssertionError(f"the fake engine does not answer {path}")

    def _clip(self, graph) -> bytes:
        """A synthetic MP4 of the frames, size and rate the graph asks for. S2V delivers
        what E0's clips did: every chunk's latents plus the doubled first one, decoded,
        less the 3 frames ``ImageFromBatch`` drops (65 asked, 66 delivered)."""
        import numpy as np  # noqa: PLC0415 - only a fake render encodes

        from haynes_studio.render.encode import EncoderSettings, encode_segment  # noqa: PLC0415

        if self.corrupt_clip:
            return b"\x00\x00\x00\x18ftypmp42" + bytes(range(256)) * 4
        nodes = {n.get("class_type"): n["inputs"] for n in graph.values()}
        if "Wan22ImageToVideoLatent" in nodes:
            latent = nodes["Wan22ImageToVideoLatent"]
            width, height, frames = latent["width"], latent["height"], latent["length"]
        else:
            first = nodes["WanSoundImageToVideo"]
            width, height = first["width"], first["height"]
            chunks = [first["length"]] + [n["inputs"]["length"] for n in graph.values()
                                          if n.get("class_type") == "WanSoundImageToVideoExtend"]
            frames = s2v_frames_delivered(chunks)
        if self.deliver_frames is not None:
            frames = self.deliver_frames
        if self.deliver_size is not None:
            width, height = self.deliver_size
        fps = int(nodes["CreateVideo"]["fps"]) if self.deliver_fps is None else self.deliver_fps
        pictures = (np.full((height, width, 3), (i * 7) % 256, dtype=np.uint8) for i in range(frames))
        return encode_segment(pictures, frames_expected=frames, width=width, height=height, fps=fps,
                              settings=EncoderSettings())

    def _make_api(self):
        pod = self
        api = _Namespace()

        def save(job):
            pod.jobs[job["id"]] = json.loads(json.dumps(job))
            pod.writes.append(("ledger", f"/workspace/jobs/{job['id']}.json"))

        def make_graph(*args):
            raise AssertionError("wan_run.py replaces api.make_graph before generate()")

        def generate(job, prompt, lease=None):
            # A port of api.py generate() (haynes-ops main, lines 149-241): the same checks,
            # polls and cleanup in the same order, on the pod's clock. It calls api.engine
            # through the module, so the snippet's wrapper is what runs.
            started = False
            submission_attempted = False
            try:
                if pod.lease_held:
                    raise RuntimeError("Compute is reserved by another video/audio job")
                sample = api.gpu_sample()
                if any(s["utilization_percent"] > 5 or s["memory_mib"] > 22000 for s in sample["gpus"]):
                    raise RuntimeError("Rack GPUs are busy; refusing to start a competing job")
                queue = api.engine("/queue")
                if queue.get("queue_running") or queue.get("queue_pending"):
                    raise RuntimeError("ComfyUI already has a job; refusing a competing request")
                graph = api.make_graph(prompt, job["preset"], job["seed"], job["id"])
                submission_attempted = True
                reply = api.engine("/prompt", {"prompt": graph, "client_id": job["id"]})
                prompt_id = reply["prompt_id"]
                started = True
                job.update(state="running", started_at=pod.now, prompt_id=prompt_id)
                save(job)
                deadline = pod.now + 1200
                misses, first_miss = 0, None
                while pod.now < deadline:
                    job["telemetry"].append(api.gpu_sample())
                    try:
                        history = api.engine("/history/" + prompt_id).get(prompt_id)
                        misses, first_miss = 0, None
                    except (TimeoutError, OSError):
                        misses += 1
                        first_miss = first_miss or pod.now
                        job["poll_misses"] = job.get("poll_misses", 0) + 1
                        if misses >= 12 or pod.now - first_miss >= 90:
                            raise
                        pod._sleep(5)
                        continue
                    if history:
                        if history.get("status", {}).get("status_str") == "error":
                            raise RuntimeError("ComfyUI generation failed; inspect the worker log")
                        for output in history.get("outputs", {}).values():
                            for value in output.values():
                                if not isinstance(value, list):
                                    continue
                                for item in value:
                                    if isinstance(item, dict) and item.get("filename", "").endswith(".mp4"):
                                        job["output"] = item.get("subfolder", "") + "/" + item["filename"]
                                        data = pod.files.get("/workspace/output/" + job["output"])
                                        if not data:
                                            raise RuntimeError("Generated file is missing or empty")
                                        job.update(state="succeeded", finished_at=pod.now, bytes=len(data))
                                        save(job)
                                        return
                        raise RuntimeError("ComfyUI completed without an MP4")
                    save(job)
                    pod._sleep(5)
                raise TimeoutError("Video exceeded the 20-minute job limit")
            except Exception as exc:
                if started or submission_attempted:
                    try:
                        queue = api.engine("/queue")

                        def owned(e):
                            return (len(e) > 3 and e[3].get("client_id") == job["id"]) \
                                or e[1] == job.get("prompt_id")
                        running = queue.get("queue_running", [])
                        pending = [e[1] for e in queue.get("queue_pending", []) if owned(e)]
                        if pending:
                            api.engine("/queue", {"delete": pending})
                        if running and not all(owned(e) for e in running):
                            pod.unsafe = True
                            raise RuntimeError("Unknown backend work requires inspection")
                        if running:
                            api.engine("/interrupt", {})
                        for _ in range(12):
                            if not api.engine("/queue").get("queue_running"):
                                break
                            pod._sleep(5)
                        else:
                            pod.unsafe = True
                    except Exception:
                        pod.unsafe = True
                job.update(state="failed", error=type(exc).__name__ + ": " + str(exc)[:200],
                           finished_at=pod.now)
                save(job)

        api.engine = self._engine
        api.gpu_sample = self._gpu_sample
        api.save = save
        api.make_graph = make_graph
        api.generate = generate
        return api
