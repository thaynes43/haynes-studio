"""The transcript check of a master (VOICE-8; story 406), behind an interface.

A :class:`Transcriber` turns a 16 kHz mono 16-bit WAV into text: the Whisper client of
story 425 live (:class:`WhisperTranscriber`), a fake in tests. The check is the PoC's
(``poc/edit.py transcript``): the master's audio at 16 kHz mono, the recognizer's words
against the script's words in film order, each heard word replaced by the story's
word-level tolerance (``checks.asr_tolerances``) before comparing, so a tolerance
cannot hide a different mismatch.

The result is a cached check result (section 4: artifact hash, check, version,
thresholds; the plan adds the story's tolerances and the script's hash). A second
build of an unchanged master asks the recognizer nothing. A failing transcript is a
result (``passed: false``), never an exception; the build decides.
"""

from __future__ import annotations

import io
import json
import re
import wave
from collections.abc import Mapping
from typing import Any, Protocol

import av
import numpy as np

from haynes_studio.cache.artifacts import ArtifactCache
from haynes_studio.cache.errors import ENTRY_INVALID, CacheError
from haynes_studio.cache.keys import CHECK_RESULT, CacheKey, make_key
from haynes_studio.canonical.model import Story
from haynes_studio.jsonio import thaw
from haynes_studio.store import HASH_MISMATCH, StoreError, blob_locator, canonical_json

CHECK = "master.transcript"
VERSION = "1"  # proposal: the comparison of poc/edit.py transcript, word-level tolerances
SCHEMA = "studio.check-result/v1"  # story 841's proposal
RATE = 16_000
JSON, MP4 = "application/json", "video/mp4"


class Transcriber(Protocol):
    """What a recognizer offers: the text it heard in a WAV."""

    name: str

    def transcribe(self, wav: bytes) -> str: ...


class WhisperTranscriber:
    """Story 425's Whisper client as a :class:`Transcriber` (live: its real runner,
    passed in at the command line only)."""

    name = "whisper (ai/deploy/whisper, Wyoming ASR)"

    def __init__(self, client: Any):
        self.client = client

    def transcribe(self, wav: bytes) -> str:
        from haynes_studio.adapters.whisper import TranscriptRequest
        return self.client.transcribe(TranscriptRequest(wav)).text


def check_spec() -> dict[str, Any]:
    """The toolchain's ``checks`` entry for this check (the plan keys it)."""
    return {"on": "master", "version": VERSION, "thresholds": {}, "transcript": True}


def script_lines(story: Story) -> list[list[str]]:
    """The script as the plan hashes it: ``[speaker, text]`` in film order."""
    return [[line.speaker, line.text] for board in story.ordered_boards() for line in board.lines]


def words(text: str) -> list[str]:
    """``poc/edit.py``'s ``norm``: lower case, letters, digits and spaces, split."""
    return re.sub("[^a-z0-9 ]", " ", text.lower()).split()


def compare(heard: str, expected: str, tolerances: Mapping[str, str] | None) -> dict[str, Any]:
    """The PoC's comparison: exact, else with each heard word's tolerance applied."""
    tolerated = {k.lower(): v.lower().split() for k, v in (tolerances or {}).items()}
    got = [w for word in words(heard) for w in tolerated.get(word, [word])]
    exact = words(heard) == words(expected)
    with_tolerances = got == words(expected)
    used = sorted({word for word in words(heard) if word in tolerated}) if with_tolerances else []
    return {"exact_match": exact, "match_with_tolerances": with_tolerances,
            "tolerances_used": [] if exact else used}


def dialogue_wav(master: bytes) -> bytes:
    """The master's audio as a 16 kHz mono 16-bit WAV (``ffmpeg -ar 16000 -ac 1`` in
    the PoC), for the recognizer."""
    chunks = []
    with av.open(io.BytesIO(master), "r") as container:
        stream = container.streams.audio[0]
        stream.codec_context.thread_count = 1
        resampler = av.AudioResampler(format="s16", layout="mono", rate=RATE)
        for frame in container.decode(stream):
            for part in resampler.resample(frame):
                chunks.append(part.to_ndarray().reshape(-1))
        for part in resampler.resample(None):
            chunks.append(part.to_ndarray().reshape(-1))
    samples = np.concatenate(chunks) if chunks else np.zeros(0, np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(samples.astype("<i2").tobytes())
    return buffer.getvalue()


class TranscriptChecks:
    """The ``master.transcript`` check results through ``cache`` (a plan content
    source for ``check_result`` keys of this check). With no ``transcriber`` (the
    offline phase) it answers cached results only: a miss is ``build.offline_missing``
    naming the check and its master, and the recognizer, a service, is never asked."""

    def __init__(self, cache: ArtifactCache, transcriber: Transcriber | None, story: Story):
        self.cache = cache
        self.transcriber = transcriber
        self.story = story
        self.made: list[str] = []

    def handles(self, key: CacheKey) -> bool:
        return key.kind == CHECK_RESULT and key.document.get("check") == CHECK

    def __call__(self, key: CacheKey) -> str:
        found = self.cache.lookup(key, JSON)
        if found is not None:
            return found.sha256
        if self.transcriber is None:
            from haynes_studio.build.errors import OFFLINE_MISSING, BuildError
            raise BuildError(OFFLINE_MISSING, f"the transcript check {key.value} of master "
                             f"{key.document['artifact'][:12]}... is not in the cache; the offline "
                             "phase calls no service: run `studio build --phase service` (which "
                             "checks a cached master) or a full build", stage=CHECK_RESULT)
        return self.cache.commit(key, self._make(key), JSON).sha256

    def result(self, sha256: str) -> dict[str, Any]:
        """A check result document by its hash, re-hashed."""
        return json.loads(self._read(sha256, JSON))

    def _read(self, sha256: str, media_type: str) -> bytes:
        import hashlib
        locator = blob_locator(self.cache.production_id, sha256, media_type)
        with self.cache.store.open(locator) as handle:
            data = handle.read()
        if hashlib.sha256(data).hexdigest() != sha256:
            raise StoreError(HASH_MISMATCH, "not the bytes the key names", locator=locator)
        return data

    def _make(self, key: CacheKey) -> bytes:
        document = thaw(key.document)
        thresholds = dict(document["thresholds"])
        script = script_lines(self.story)
        if make_key("script", {"lines": script}).hex != thresholds.get("script_sha256"):
            raise CacheError(ENTRY_INVALID, "the check key names another script than the story's",
                             where=key.value)
        tolerances = thresholds.get("asr_tolerances")
        assert self.transcriber is not None
        heard = self.transcriber.transcribe(dialogue_wav(self._read(document["artifact"], MP4)))
        if not isinstance(heard, str):
            raise CacheError(ENTRY_INVALID, "the recognizer returned no text", where=key.value)
        expected = " ".join(text for _, text in script)
        verdict = compare(heard, expected, tolerances)
        passed = verdict["exact_match"] or verdict["match_with_tolerances"]
        result = "pass" if verdict["exact_match"] else ("pass_with_tolerances" if passed else "fail")
        self.made.append(key.value)
        return canonical_json({
            "schema": SCHEMA, "check": CHECK, "version": document["version"],
            "artifact": document["artifact"], "thresholds": thresholds,
            "measured": {"heard": heard, "expected": expected, "recognizer": self.transcriber.name,
                         **verdict},
            "result": result, "passed": passed})


__all__ = ["CHECK", "Transcriber", "TranscriptChecks", "VERSION", "WhisperTranscriber",
           "check_spec", "compare", "dialogue_wav", "script_lines", "words"]
