"""The assembled track: takes at their TIME-2 offsets, whole-sample silence, the takes'
own rate (no resampling), and refusals for takes it cannot join without converting."""

from __future__ import annotations

import io
import struct
import wave

import pytest

from haynes_studio.adapters.fakes import synthetic_wav
from haynes_studio.errors import ContractError
from haynes_studio.timebase import line_spans, take_duration_ms
from haynes_studio.voice.track import assemble, read_wav


def pcm_of(data: bytes) -> tuple[int, bytes]:
    with wave.open(io.BytesIO(data), "rb") as reader:
        return reader.getframerate(), reader.readframes(reader.getnframes())


@pytest.mark.parametrize("rate", [24000, 22050, 44100])
def test_takes_sit_at_their_offsets_with_whole_sample_silence(rate):
    takes = [read_wav(synthetic_wav(frames, rate=rate, seed=seed))
             for seed, frames in enumerate([rate // 3 + 7, rate // 5 + 1, rate // 4 - 3])]
    durations = [take_duration_ms(take.frames, rate) for take in takes]
    spans = line_spans(250, durations, [None, 300, 0])  # a zero gap still never overlaps
    track = assemble(takes, [s.start_ms for s in spans], spans[-1].end_ms)
    got_rate, pcm = pcm_of(track)
    assert got_rate == rate
    assert len(pcm) == (spans[-1].end_ms * rate // 1000) * 2
    cursor = 0
    for take, span in zip(takes, spans):
        start = span.start_ms * rate // 1000
        assert start >= cursor
        assert pcm[cursor * 2:start * 2] == bytes((start - cursor) * 2)
        assert pcm[start * 2:(start + take.frames) * 2] == take.data
        cursor = start + take.frames
    assert set(pcm[cursor * 2:]) <= {0}


def test_assembly_is_deterministic():
    takes = [read_wav(synthetic_wav(4800, seed=1))]
    assert assemble(takes, [500], 700) == assemble(takes, [500], 700)


def test_takes_of_different_formats_are_refused():
    a = read_wav(synthetic_wav(2400, rate=24000))
    b = read_wav(synthetic_wav(2205, rate=22050))
    with pytest.raises(ContractError) as caught:
        assemble([a, b], [0, 200], 400)
    assert {v.rule for v in caught.value.violations} == {"voice.format_mismatch"}
    stereo = read_wav(synthetic_wav(2400, channels=2))
    with pytest.raises(ContractError):
        assemble([a, stereo], [0, 200], 400)


def test_only_16_bit_pcm_with_audio_is_a_take():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(1)
        writer.setframerate(24000)
        writer.writeframes(b"\x80" * 240)
    for data in (buffer.getvalue(), b"RIFF0000WAVE", b""):
        with pytest.raises(ContractError) as caught:
            read_wav(data, "/voice/lines/0")
        assert {(v.rule, v.path) for v in caught.value.violations} == {
            ("voice.format_mismatch", "/voice/lines/0")}


def test_a_take_longer_than_its_slot_is_refused():
    take = read_wav(synthetic_wav(2400))  # 100 ms
    with pytest.raises(ContractError):
        assemble([take, take], [0, 50], 300)  # the second starts inside the first
    with pytest.raises(ContractError):
        assemble([take], [0], 99)  # the track ends before the take


def test_a_truncated_wav_is_refused():
    data = bytearray(synthetic_wav(2400))
    struct.pack_into("<I", data, 40, 4800 * 2)  # the data chunk claims more frames
    with pytest.raises(ContractError):
        read_wav(bytes(data))
