"""Segment encoding and the stream-copy splice (story 380), on small synthetic clips."""

from __future__ import annotations

import hashlib
import io
import itertools

import av
import numpy as np
import pytest

from haynes_studio.render.base import SegmentRequest
from haynes_studio.render.encode import EncoderSettings, decode_frames, encode_segment, probe_segment
from haynes_studio.render.errors import (
    CONSERVATION, FRAME_COUNT, FRAME_INVALID, SPLICE_INCOMPATIBLE, CacheError,
)
from haynes_studio.render.splice import SpliceInput, splice
from haynes_studio.render.synthetic import SyntheticRenderer, fingerprint, read_code

SETTINGS = EncoderSettings()


def request(key_digit: str, frames: int, width: int = 360, height: int = 640) -> SegmentRequest:
    key = "sha256:" + key_digit * 64
    return SegmentRequest(key=key, inputs={"frames": frames, "width": width, "height": height,
                                           "fps": 24, "layers": [{"phase": 3}],
                                           "procedural_stream": 5})


def segment(key_digit: str, frames: int, width: int = 360, height: int = 640) -> bytes:
    req = request(key_digit, frames, width, height)
    return encode_segment(SyntheticRenderer().render(req), frames_expected=frames, width=width,
                          height=height, fps=24, settings=SETTINGS)


def test_a_segment_holds_its_frames_and_decodes_its_board_clock():
    data = segment("a", 30)
    info = probe_segment(data, fps=24)
    assert info.frames == 30 and (info.width, info.height) == (360, 640) and info.codec == "h264"
    assert [read_code(frame) for frame in decode_frames(data)] == [
        (n, fingerprint("sha256:" + "a" * 64)) for n in range(30)]


class _EncoderWithoutAssembly(EncoderSettings):
    def options(self) -> dict[str, str]:
        options = super().options()
        # The old sliced encoder varied more often with x264's C implementations.
        options["x264-params"] += ":asm=0"
        return options


@pytest.mark.parametrize("fixture", ["bars", "moving-texture"])
def test_the_same_frames_encode_to_the_same_bytes(fixture):
    if fixture == "bars":
        frames = list(SyntheticRenderer().render(request("b", 24)))
        settings = _EncoderWithoutAssembly()
    else:
        # The 360-pixel width exercises a partial block in x264's lookahead.
        rng = np.random.default_rng(955)
        texture = rng.integers(0, 256, (160, 90, 3), dtype=np.uint8)
        texture = texture.repeat(4, axis=0).repeat(4, axis=1)
        frames = [np.roll(texture, shift=(n, 3 * n), axis=(0, 1)) for n in range(48)]
        settings = SETTINGS

    def encode():
        return encode_segment(frames, frames_expected=len(frames), width=360, height=640, fps=24,
                              settings=settings)

    expected = encode()
    for run in range(2, 11):
        actual = encode()
        if actual != expected:
            pytest.fail(f"encode {run} differs from encode 1: "
                        f"{hashlib.sha256(actual).hexdigest()} != "
                        f"{hashlib.sha256(expected).hexdigest()}", pytrace=False)


def test_the_synthetic_renderer_draws_only_from_its_request():
    first = list(SyntheticRenderer().render(request("c", 5)))
    second = list(SyntheticRenderer().render(request("c", 5)))
    other = list(SyntheticRenderer().render(request("d", 5)))
    assert all(np.array_equal(a, b) for a, b in zip(first, second))
    assert not np.array_equal(first[0], other[0])


def test_splice_decodes_to_the_segments_frames_in_order():
    parts = [segment("1", 10), segment("2", 7), segment("3", 13)]
    film = splice([SpliceInput(data, frames) for data, frames in zip(parts, (10, 7, 13))])
    assert probe_segment(film, fps=24).frames == 30
    expected = itertools.chain.from_iterable(decode_frames(part) for part in parts)
    count = 0
    for a, b in itertools.zip_longest(decode_frames(film), expected):
        assert a is not None and b is not None and np.array_equal(a, b)
        count += 1
    assert count == 30


def test_a_segment_that_does_not_hold_its_boards_frames_fails_conservation():
    with pytest.raises(CacheError) as caught:
        splice([SpliceInput(segment("1", 10), 10), SpliceInput(segment("2", 7), 8)])
    assert caught.value.code == CONSERVATION and "segment 1" in str(caught.value)


def test_segments_of_another_size_cannot_be_spliced():
    with pytest.raises(CacheError) as caught:
        splice([SpliceInput(segment("1", 4), 4), SpliceInput(segment("2", 4, 640, 360), 4)])
    assert caught.value.code == SPLICE_INCOMPATIBLE


def test_an_empty_film_is_refused():
    with pytest.raises(CacheError) as caught:
        splice([])
    assert caught.value.code == CONSERVATION


def test_encoder_settings_name_their_build_and_threading():
    inputs = SETTINGS.key_inputs()
    assert inputs["threads"] == 1 and inputs["threading"] == "single" and inputs["bframes"] == 0
    assert inputs["build"].startswith("pyav-")
    assert inputs["asm"] in {"AVX2", "0"}
    assert f"asm={inputs['asm']}" in SETTINGS.options()["x264-params"].split(":")
    assert b"threads=1 lookahead_threads=1 sliced_threads=0 " in segment("b", 1)


def _without_first_packet(data: bytes) -> bytes:
    """The segment's packets from the second on, retimed to start at frame 0: a segment
    that starts mid-GOP."""
    out = io.BytesIO()
    with av.open(io.BytesIO(data)) as source, av.open(out, mode="w", format="mp4") as target:
        stream = source.streams.video[0]
        copy = target.add_stream_from_template(stream)
        copy.time_base = stream.time_base
        packets = [packet for packet in source.demux(stream) if packet.size]
        tick = packets[1].pts - packets[0].pts
        for packet in packets[1:]:
            packet.pts = packet.dts = packet.pts - tick
            packet.stream = copy
            target.mux(packet)
    return out.getvalue()


def test_a_segment_that_does_not_start_on_a_keyframe_is_refused():
    broken = _without_first_packet(segment("e", 6))
    with pytest.raises(CacheError) as caught:
        probe_segment(broken, fps=24)
    assert caught.value.code == SPLICE_INCOMPATIBLE and "keyframe" in str(caught.value)
    with pytest.raises(CacheError) as caught:
        splice([SpliceInput(segment("1", 4), 4), SpliceInput(broken, 5)])
    assert caught.value.code == SPLICE_INCOMPATIBLE


def test_splice_reads_a_lazy_segment_only_when_it_reaches_it():
    calls = []

    def later() -> bytes:
        calls.append("read")
        return segment("2", 3)

    film = splice([SpliceInput(segment("1", 4), 4), SpliceInput(later, 3)])
    assert calls == ["read"] and probe_segment(film, fps=24).frames == 7


@pytest.mark.parametrize(("shape", "expected", "code"), [
    ((4, 4, 3), 1, FRAME_COUNT),
    ((3, 4, 3), 2, FRAME_INVALID),
])
def test_a_rejected_frame_closes_the_render_iterator_before_the_error_returns(shape, expected, code):
    closed = []

    def render():
        try:
            yield np.zeros((4, 4, 3), dtype=np.uint8)
            yield np.zeros(shape, dtype=np.uint8)
        finally:
            closed.append(True)

    # Retain both iterator and traceback: resource cleanup must not depend on GC.
    frames = render()
    try:
        with pytest.raises(CacheError) as error:
            encode_segment(frames, frames_expected=expected, width=4, height=4, fps=24,
                           settings=SETTINGS)
        assert error.value.code == code
        assert closed == [True]
    finally:
        frames.close()


def test_an_encode_failure_closes_its_live_input_decoder():
    frames = decode_frames(segment("1", 2, width=4, height=4))
    try:
        with pytest.raises(CacheError) as error:
            encode_segment(frames, frames_expected=2, width=8, height=4, fps=24,
                           settings=SETTINGS)
        assert error.value.code == FRAME_INVALID
        assert frames.gi_frame is None  # decode_frames has exited its av.open context
    finally:
        frames.close()
