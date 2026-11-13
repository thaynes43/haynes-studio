"""The fakes are deterministic and their synthetic media is small and well formed."""

from __future__ import annotations

import io
import wave

import pytest

from haynes_studio.adapters.comfyui import ImageClient, TextToImage
from haynes_studio.adapters.fakes import (
    FakeComfyUI,
    FakeKokoro,
    FakeRunner,
    snippet_of,
    synthetic_png,
    synthetic_wav,
)
from haynes_studio.adapters.kokoro import KokoroClient, SpeechRequest


def test_synthetic_wav_is_deterministic_pcm():
    data = synthetic_wav(4800, seed=3)
    assert data == synthetic_wav(4800, seed=3) != synthetic_wav(4800, seed=4)
    with wave.open(io.BytesIO(data)) as reader:
        assert (reader.getnchannels(), reader.getsampwidth(), reader.getframerate(),
                reader.getnframes()) == (1, 2, 24000, 4800)
    with pytest.raises(ValueError):
        synthetic_wav(24000 * 11)


def test_synthetic_png_is_deterministic_and_small():
    assert synthetic_png(seed=1) == synthetic_png(seed=1) != synthetic_png(seed=2)
    assert synthetic_png().startswith(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(ValueError):
        synthetic_png(1080, 1920)


def test_same_request_same_bytes():
    def once():
        return KokoroClient(FakeRunner(FakeKokoro())).synthesize(SpeechRequest("af_bella", "Nay!"))
    assert once().sha256 == once().sha256

    def image():
        request = TextToImage(job="j", name="n", prompt="p", seed=5)
        return ImageClient(FakeRunner(FakeComfyUI())).render(request)
    first, second = image(), image()
    assert (first.sha256, first.prompt_id) == (second.sha256, second.prompt_id)


def test_snippet_of_names_the_pinned_snippet():
    command = KokoroClient(FakeRunner()).command(SpeechRequest("af_bella", "Nay!"))
    assert snippet_of(command) == ("kokoro_tts.py", ())
