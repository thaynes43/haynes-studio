"""Segment encoding and the stream-copy splice (story 380), on small synthetic clips."""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from haynes_studio.render.base import SegmentRequest
from haynes_studio.render.encode import EncoderSettings, decode_frames, encode_segment, probe_segment
from haynes_studio.render.errors import CONSERVATION, SPLICE_INCOMPATIBLE, CacheError
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


def test_the_same_frames_encode_to_the_same_bytes():
    assert segment("b", 24) == segment("b", 24) == segment("b", 24)


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
    assert inputs["threads"] == 2 and inputs["threading"] == "sliced" and inputs["bframes"] == 0
    assert inputs["build"].startswith("pyav-")
