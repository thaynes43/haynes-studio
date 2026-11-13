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
from haynes_studio.voice import track
from haynes_studio.voice.track import TRACK_MAX_BYTES, Pcm, assemble, read_wav


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
    stereo = Pcm(channels=2, sample_width=2, rate=24000, frames=2400, data=bytes(9600))
    with pytest.raises(ContractError) as caught:
        assemble([a, stereo], [0, 200], 400)
    assert {v.rule for v in caught.value.violations} == {"voice.format_mismatch"}


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


# Review finding 2: nothing is sized from a header or a time before it is bounded -----------


def reviewer_wav_a() -> bytes:
    """Input A: a 46-byte 16-bit mono WAV of one frame whose sample-rate field is
    4294967295."""
    data = bytearray(synthetic_wav(1))
    assert len(data) == 46
    struct.pack_into("<I", data, 24, 0xFFFFFFFF)
    return bytes(data)


def wav_claiming(frames: int, rate: int) -> bytes:
    """A 16-bit mono WAV of one frame whose data chunk claims ``frames`` frames."""
    data = bytearray(synthetic_wav(1, rate=rate))
    struct.pack_into("<I", data, 40, frames * 2)
    return bytes(data)


@pytest.fixture
def no_buffer(monkeypatch):
    """Fails the test if the track buffer (``bytearray`` in the track module) or a take's
    frames (``wave.Wave_read.readframes``) are sized. Returns what was asked for."""
    asked = []

    def refuse(*args):
        asked.append(args)
        raise AssertionError("a buffer was sized before the refusal")

    monkeypatch.setattr(track, "bytearray", refuse, raising=False)
    monkeypatch.setattr(wave.Wave_read, "readframes", refuse)
    return asked


def test_the_buffer_spies_see_a_normal_take_and_track(monkeypatch):
    """The control for ``no_buffer``: the two places it watches are where a take's
    frames and the track's buffer are sized."""
    asked = []
    readframes = wave.Wave_read.readframes
    monkeypatch.setattr(track, "bytearray", lambda n: asked.append(("track", n)) or bytearray(n),
                        raising=False)
    monkeypatch.setattr(wave.Wave_read, "readframes",
                        lambda self, n: asked.append(("frames", n)) or readframes(self, n))
    take = read_wav(synthetic_wav(2400))
    assemble([take], [500], 600)
    assert asked == [("frames", 2400), ("track", 600 * 24 * 2)]


def test_input_a_is_refused_from_its_header(no_buffer):
    with pytest.raises(ContractError) as caught:
        read_wav(reviewer_wav_a(), "/voice/lines/0")
    assert {(v.rule, v.path) for v in caught.value.violations} == {
        ("voice.format_mismatch", "/voice/lines/0")}
    with pytest.raises(ContractError) as caught:  # the same take built by hand
        assemble([Pcm(channels=1, sample_width=2, rate=0xFFFFFFFF, frames=1, data=b"\0\0")],
                 [500], 501)
    assert {v.rule for v in caught.value.violations} == {"voice.format_mismatch"}
    assert no_buffer == []


@pytest.mark.parametrize("channels, rate", [(2, 24000), (1, 7999), (1, 48001)])
def test_a_take_is_mono_at_8_to_48_khz(no_buffer, channels, rate):
    with pytest.raises(ContractError) as caught:
        read_wav(synthetic_wav(1, rate=rate, channels=channels))
    assert {v.rule for v in caught.value.violations} == {"voice.format_mismatch"}
    assert no_buffer == []


@pytest.mark.parametrize("rate", [8000, 48000])
def test_the_rate_bounds_are_takes(rate):
    take = read_wav(synthetic_wav(rate // 10, rate=rate))
    assert (take.shape, take.frames) == ((1, 2, rate), rate // 10)


def test_a_take_over_120000_ms_is_refused_from_its_header(no_buffer):
    with pytest.raises(ContractError) as caught:
        read_wav(wav_claiming(960_001, 8000), "/voice/lines/0")  # 120000.125 ms
    assert {(v.rule, v.path) for v in caught.value.violations} == {
        ("schema.invalid", "/voice/lines/0")}
    long = Pcm(channels=1, sample_width=2, rate=8000, frames=960_001, data=b"")
    with pytest.raises(ContractError) as caught:
        assemble([long], [0], 120_001)
    assert {(v.rule, v.path) for v in caught.value.violations} == {("schema.invalid", "/takes/0")}
    assert no_buffer == []


def test_a_take_of_exactly_120000_ms_passes_the_bound():
    """The bound is inclusive: this header passes it, and the take is then refused only
    because its data holds one frame, not 960000."""
    with pytest.raises(ContractError) as caught:
        read_wav(wav_claiming(960_000, 8000))
    assert [v.message for v in caught.value.violations] == [
        "the WAV holds fewer frames than its header says"]


ONE_MS = Pcm(channels=1, sample_width=2, rate=24000, frames=24, data=bytes(48))


@pytest.mark.parametrize("offsets, end, path", [
    ([1_000_000_000], 1_000_000_001, "/takes/0"),  # input B: the lead of r4 board 1
    ([120_001], 120_002, "/takes/0"),
    ([0, 1 + 120_001], 120_003, "/takes/1"),  # a gap
    ([120_000, 240_001, 360_002, 480_003, 600_004], 600_005, "/speech_end_ms"),  # the track
], ids=["input-b-lead", "lead", "gap", "track"])
def test_times_over_their_bounds_are_refused_before_the_buffer(no_buffer, offsets, end, path):
    with pytest.raises(ContractError) as caught:
        assemble([ONE_MS] * len(offsets), offsets, end)
    assert {(v.rule, v.path) for v in caught.value.violations} == {("schema.invalid", path)}
    assert no_buffer == []


def test_the_track_buffer_bound_follows_from_the_time_and_format_bounds():
    assert TRACK_MAX_BYTES == 600_000 * 48 * 2 == 57_600_000


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
