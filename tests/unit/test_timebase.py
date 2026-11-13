"""Integer time helpers: contract section 3, rules TIME-1 to TIME-4 and TIME-7."""

from __future__ import annotations

import subprocess
import sys
from decimal import Decimal

import pytest

from haynes_studio import timebase as tb


def test_units_are_the_contract_units():
    assert (tb.DELIVERY_FPS, tb.MIX_RATE) == (24, 48_000)
    assert (tb.SAMPLES_PER_FRAME, tb.SAMPLES_PER_MS) == (2000, 48)
    assert (tb.DEFAULT_LEAD_MS, tb.DEFAULT_GAP_MS, tb.DEFAULT_TAIL_MS) == (500, 300, 700)
    assert (tb.HOLD_MIN_MS, tb.HOLD_MAX_MS, tb.TAIL_MIN_MS) == (100, 120_000, 250)


@pytest.mark.parametrize(("samples", "rate", "ms"), [
    (0, 24_000, 0),
    (24_000, 24_000, 1000),
    (24_001, 24_000, 1001),  # TIME-1 rounds up: never shorter than the audio
    (23_999, 24_000, 1000),
    (1, 48_000, 1),
])
def test_take_duration_rounds_up(samples, rate, ms):
    assert tb.take_duration_ms(samples, rate) == ms


@pytest.mark.parametrize(("ms", "frames"), [
    (0, 0), (1, 1), (1000, 24), (1001, 25), (6363, 153), (3888, 94), (1900, 46),
    (10427, 251), (4481, 108),
])
def test_frames_for_ms_rounds_up(ms, frames):
    assert tb.frames_for_ms(ms) == frames


def test_frames_for_ms_is_the_contract_formula():
    # TIME-3 states it in integers as (content_ms * 24 + 999) div 1000.
    assert all(tb.frames_for_ms(ms) == (ms * 24 + 999) // 1000 for ms in range(0, 3001))


@pytest.mark.parametrize("bad", [1.5, True, "3", None])
def test_helpers_refuse_non_integers(bad):
    with pytest.raises(TypeError):
        tb.frames_for_ms(bad)
    with pytest.raises(TypeError):
        tb.take_duration_ms(bad, 24_000)


def test_helpers_refuse_negative_durations():
    with pytest.raises(ValueError):
        tb.frames_for_ms(-1)
    with pytest.raises(ValueError):
        tb.take_duration_ms(10, 0)


def test_line_spans_follow_time_2():
    # The Winter Menu r4 board 8 (contract section 3, worked example).
    spans = tb.line_spans(1900, [1003, 811, 875, 512, 1024, 1152], [None, 300, 200, 250, 700, 900])
    assert [(s.start_ms, s.end_ms) for s in spans] == [
        (1900, 2903), (3203, 4014), (4214, 5089), (5339, 5851), (6551, 7575), (8475, 9627)]
    assert tb.spoken_content_ms(1900, [1003, 811, 875, 512, 1024, 1152],
                                [None, 300, 200, 250, 700, 900], 800) == 10427


def test_line_spans_refuse_a_first_gap_and_bad_lengths():
    with pytest.raises(ValueError, match="first_line_gap"):
        tb.line_spans(500, [1000], [300])
    with pytest.raises(ValueError):
        tb.line_spans(500, [1000, 1000], [None])
    with pytest.raises(TypeError):
        tb.line_spans(500, [1000, 1000], [None, None])
    with pytest.raises(ValueError):
        tb.spoken_content_ms(500, [], [], 700)


def test_film_placement_follows_time_7():
    frames = [153, 94, 146, 84, 83, 122, 46, 251, 108]
    assert tb.film_start_frames(frames) == (0, 153, 247, 393, 477, 560, 682, 728, 979)
    # The gavel: 50 ms after "Motion carried." ends on board 8 (film frame 728).
    assert tb.mix_sample(728, 7625) == 1_822_000
    assert tb.frames_to_samples(1087) == 2_174_000
    assert tb.ms_to_samples(1000) == 48_000


@pytest.mark.parametrize(("frames", "text"), [
    (0, "0.000"), (1, "0.042"), (24, "1.000"), (1087, "45.292"), (662, "27.583"),
])
def test_display_seconds(frames, text):
    assert tb.display_seconds(frames) == text


@pytest.mark.parametrize(("value", "ms"), [
    (0, 0), (3, 3000), (0.35, 350), (1.9, 1900), (5.163, 5163), (0.3, 300), (0.05, 50),
    ("0.25", 250), (Decimal("2.475"), 2475), (-0.5, -500),
])
def test_ms_from_seconds_is_exact(value, ms):
    assert tb.ms_from_seconds(value) == ms


@pytest.mark.parametrize("value", [0.0005, 1.0001, "0.3333", float("nan"), float("inf"), "x"])
def test_ms_from_seconds_refuses_what_is_not_a_whole_ms(value):
    with pytest.raises(ValueError):
        tb.ms_from_seconds(value)


@pytest.mark.parametrize("value", [True, None, [1]])
def test_ms_from_seconds_refuses_non_numbers(value):
    with pytest.raises(TypeError):
        tb.ms_from_seconds(value)


def test_time_helpers_import_no_media_or_schema_library():
    code = ("import sys, haynes_studio.timebase; "
            "print(sorted(m for m in sys.modules if m.split('.')[0] in "
            "{'numpy', 'PIL', 'av', 'cv2', 'imageio_ffmpeg', 'jsonschema'}))")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            check=True)
    assert result.stdout.strip() == "[]"


@pytest.mark.parametrize("value", [10**30 + 1, "1e999999", 1e308, -(10**15)])
def test_ms_from_seconds_refuses_out_of_range_values(value):
    with pytest.raises(ValueError, match="out of range"):
        tb.ms_from_seconds(value)


def test_ms_from_seconds_is_exact_beyond_the_decimal_context():
    # 28 significant digits is Decimal's default precision; the result must not round.
    with pytest.raises(ValueError, match="whole number"):
        tb.ms_from_seconds("0.0010000000000000000000000000001")
    assert tb.ms_from_seconds(10**15 - 1) == (10**15 - 1) * 1000
