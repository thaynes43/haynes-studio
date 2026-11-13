"""Transcript check: the Whisper service's Wyoming ASR inside ``ai/deploy/whisper``
(configured model ``nemo-parakeet-tdt-0.6b-v2``).

Ported from ``poc/studio.py`` ``transcribe``: the same ``kubectl exec`` vector, a WAV
on stdin, the same 55 s timeout and the pinned snippet ``whisper_asr.py`` (45 s
overall, 30 s per event). The answer is one JSON line, ``{"transcript": "..."}``.

A matching transcript shows the words are intelligible; it says nothing about voice
quality or comic timing (docs/reference/services.md).

    client = WhisperClient(runner)
    heard = client.transcribe(TranscriptRequest(wav=data)).text
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from haynes_studio.adapters import pinned
from haynes_studio.adapters.errors import RESPONSE_INVALID, AdapterError, RequestInvalid
from haynes_studio.adapters.kokoro import parse_wav
from haynes_studio.adapters.runner import WHISPER, Command, ExecTarget, Runner, run_checked
from haynes_studio.jsonio import parse_strict

LABEL = "whisper.transcribe"
SNIPPET = "whisper_asr.py"
TIMEOUT_S = 55  # poc/studio.py transcribe; the snippet's own limit is 45 s
MAX_WAV_BYTES = 64 * 1024 * 1024  # proposal: a 60 s 48 kHz stereo master is about 11 MB
MAX_ANSWER_BYTES = 1024 * 1024


@dataclass(frozen=True)
class TranscriptRequest:
    wav: bytes = field(repr=False)

    def __post_init__(self):
        if not isinstance(self.wav, bytes) or not self.wav:
            raise RequestInvalid(LABEL, "wav must be non-empty bytes")
        if len(self.wav) > MAX_WAV_BYTES:
            raise RequestInvalid(LABEL, f"wav is over {MAX_WAV_BYTES} bytes")
        try:
            parse_wav(self.wav, LABEL)
        except AdapterError:
            raise RequestInvalid(LABEL, "wav is not a PCM WAV with audio") from None


@dataclass(frozen=True)
class Transcript:
    text: str


def normalized(text: str) -> str:
    """The comparison ``poc/speech.py`` uses (``norm``): lower case, letters and digits only."""
    return re.sub('[^a-z0-9]', '', text.lower())


def heard_matches(heard: str, text: str) -> bool:
    """``heard_matches`` as ``poc/speech.py`` records it."""
    return normalized(heard) == normalized(text)


class WhisperClient:
    def __init__(self, runner: Runner, *, snippet: pinned.PinnedInput | None = None,
                 target: ExecTarget = WHISPER):
        self.runner = runner
        self.snippet = pinned.check(snippet, SNIPPET) if snippet else pinned.load(SNIPPET)
        self.target = target

    def command(self, request: TranscriptRequest) -> Command:
        pinned.check(self.snippet, SNIPPET)
        return Command(LABEL, self.target.argv(self.snippet.text), request.wav, TIMEOUT_S,
                       self.target.describe())

    def transcribe(self, request: TranscriptRequest) -> Transcript:
        result = run_checked(self.runner, self.command(request))
        if len(result.stdout) > MAX_ANSWER_BYTES:
            raise AdapterError(RESPONSE_INVALID, LABEL, "answer is too long")
        try:
            answer = parse_strict(result.stdout.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise AdapterError(RESPONSE_INVALID, LABEL, "answer is not one JSON object") from None
        if not isinstance(answer, dict) or set(answer) != {"transcript"} \
                or not isinstance(answer["transcript"], str):
            raise AdapterError(RESPONSE_INVALID, LABEL, 'answer is not {"transcript": <text>}')
        return Transcript(answer["transcript"])
