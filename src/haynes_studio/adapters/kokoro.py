"""Text to speech: Kokoro-82M v1.0 over Wyoming, inside ``ai/deploy/kokoro``.

Ported from ``poc/studio.py`` ``synthesize``: the same ``kubectl exec`` vector, the same
JSON on stdin (``{"voice", "text"}``), the same 55 s timeout and the pinned snippet
``kokoro_tts.py``. The snippet gives up after 45 s overall, 30 s per event, or 2 000 000
bytes of audio. The answer is one WAV on stdout.

    client = KokoroClient(runner)
    take = client.synthesize(SpeechRequest(voice="bf_emma", text="Aye."))
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import wave
from dataclasses import dataclass, field

from haynes_studio.adapters import pinned
from haynes_studio.adapters.errors import RESPONSE_INVALID, AdapterError, RequestInvalid
from haynes_studio.adapters.runner import KOKORO, Command, ExecTarget, Runner, run_checked

LABEL = "kokoro.synthesize"
SNIPPET = "kokoro_tts.py"
TIMEOUT_S = 55  # poc/studio.py synthesize; the snippet's own limit is 45 s
MAX_TEXT = 1000  # proposal: one board line is far shorter
MAX_WAV_BYTES = 4 * 1024 * 1024  # the snippet stops at 2 000 000 bytes of audio
VOICE = re.compile(r"[a-z]{2}_[a-z0-9]+")  # Kokoro stock voice names: af_heart, bf_emma


@dataclass(frozen=True)
class SpeechRequest:
    voice: str
    text: str

    def __post_init__(self):
        if not isinstance(self.voice, str) or not VOICE.fullmatch(self.voice):
            raise RequestInvalid(LABEL, "voice must be a Kokoro stock voice name such as af_heart")
        if not isinstance(self.text, str) or not self.text.strip():
            raise RequestInvalid(LABEL, "text must be non-empty")
        if len(self.text) > MAX_TEXT:
            raise RequestInvalid(LABEL, f"text is over {MAX_TEXT} characters")

    def payload(self) -> bytes:
        """The stdin bytes, exactly as ``poc/studio.py`` writes them."""
        return json.dumps({'voice': self.voice, 'text': self.text}).encode()


@dataclass(frozen=True)
class SpeechTake:
    """One synthesized WAV and what its header says."""

    wav: bytes = field(repr=False)
    sha256: str
    channels: int
    sample_width: int
    rate: int
    frames: int

    @property
    def bytes(self) -> int:
        return len(self.wav)

    @property
    def legacy_duration_s(self) -> float:
        """``duration_s`` as ``poc/speech.py`` recorded it (seconds, 3 decimals)."""
        return round(self.frames / self.rate, 3)


def parse_wav(data: bytes, label: str) -> tuple[int, int, int, int]:
    """``(channels, sample_width, rate, frames)`` of a PCM WAV, or ``adapter.response_invalid``."""
    try:
        with wave.open(io.BytesIO(data), "rb") as reader:
            shape = (reader.getnchannels(), reader.getsampwidth(), reader.getframerate(),
                     reader.getnframes())
    except (wave.Error, EOFError, ValueError) as error:
        raise AdapterError(RESPONSE_INVALID, label, f"not a PCM WAV: {type(error).__name__}") from None
    if shape[2] <= 0 or shape[3] <= 0:
        raise AdapterError(RESPONSE_INVALID, label, "the WAV has no audio")
    return shape


class KokoroClient:
    def __init__(self, runner: Runner, *, snippet: pinned.PinnedInput | None = None,
                 target: ExecTarget = KOKORO):
        self.runner = runner
        self.snippet = pinned.check(snippet, SNIPPET) if snippet else pinned.load(SNIPPET)
        self.target = target

    def command(self, request: SpeechRequest) -> Command:
        """The command :meth:`synthesize` runs, built without running anything."""
        pinned.check(self.snippet, SNIPPET)
        return Command(LABEL, self.target.argv(self.snippet.text), request.payload(), TIMEOUT_S,
                       self.target.describe())

    def synthesize(self, request: SpeechRequest) -> SpeechTake:
        result = run_checked(self.runner, self.command(request))
        if len(result.stdout) > MAX_WAV_BYTES:
            raise AdapterError(RESPONSE_INVALID, LABEL, f"answer is over {MAX_WAV_BYTES} bytes")
        channels, width, rate, frames = parse_wav(result.stdout, LABEL)
        return SpeechTake(result.stdout, hashlib.sha256(result.stdout).hexdigest(), channels, width,
                          rate, frames)
