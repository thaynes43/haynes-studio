"""The mixer as a pure function of the mix key (story 841), on synthetic audio.

Placement, levels and fades are read from the mix itself, sample by sample: lines and
sounds made of constant (DC) signals at 48 kHz pass the resampler unchanged, so every
fade is visible as a ratio to the steady value, and a 1 kHz tone line elsewhere sets
the programme's loudness (K-weighting removes DC). Nothing compares encoded bytes
across builds; the same inputs give the same bytes within one build.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from haynes_studio.mix import MIXER, MixError, mix, planned_starts
from haynes_studio.mix.audio import measure, read_pcm
from haynes_studio.mix.mixer import _loop
from haynes_studio.store import BLOB_MISSING, HASH_MISMATCH, StoreError
from tests.mix.fixtures import Blobs, key, noise, tone, track, wav16

RATE = 48_000
LEVEL = 10 ** (-22 / 20)  # the line RMS, -22 dBFS


def samples_of(result) -> np.ndarray:
    pcm = read_pcm(result.wav, where="test")
    assert (pcm.rate, pcm.channels, pcm.width) == (RATE, 2, 3)
    return pcm.samples


def dc(n: int, value: float) -> np.ndarray:
    return np.full(n, value, np.float32)


def loud_line(blobs: Blobs, *, frame: int, start_ms: int = 100, ms: int = 1000) -> dict:
    """A 1 kHz tone line at 24 kHz: it sets the programme loudness."""
    data = track([tone(ms * 24, 24_000, 1000, 0.3)], [start_ms], start_ms + ms)
    return {"track": blobs.add(data), "start_frame": frame, "spans": [[start_ms, start_ms + ms]]}


def test_every_line_starts_at_its_time7_sample_and_stays_inside_its_span():
    blobs = Blobs()
    # Board at film frame 40: two DC lines in a 48 kHz track (no resampling).
    data = track([dc(48_000, 0.4), dc(24_000, 0.05)], [500, 1800], 2300, rate=RATE)
    lines = {"track": blobs.add(data), "start_frame": 40, "spans": [[500, 1500], [1800, 2300]]}
    k = key(tracks=[loud_line(blobs, frame=0), lines], frames=96)
    result = mix(k.document, blobs.read)
    out = samples_of(result)
    starts = [40 * 2000 + 500 * 48, 40 * 2000 + 1800 * 48]  # TIME-7: F[k]*2000 + start*48
    ends = [40 * 2000 + 1500 * 48, 40 * 2000 + 2300 * 48]
    assert starts == [104_000, 166_400] and ends == [152_000, 190_400]
    placed = [(p["start_sample"], p["end_sample"]) for p in result.placement["lines"][1:]]
    assert placed == list(zip(starts, ends))
    assert planned_starts(k.document)["lines"][1:] == [
        {"track": 1, "line": i, "start_sample": s, "end_sample": e}
        for i, (s, e) in enumerate(zip(starts, ends))]
    loud_end = 100 * 48 + 1000 * 48  # the tone line, board at frame 0
    nonzero = np.flatnonzero(out[loud_end:, 0]) + loud_end
    # The first and last sample of each line are the fades' zeros.
    for start, end in zip(starts, ends):
        inside = nonzero[(nonzero >= start - 1000) & (nonzero < end + 1000)]
        assert (inside.min(), inside.max()) == (start + 1, end - 2)
    assert not out[ends[1]:].any()


def test_a_24khz_line_is_resampled_to_exactly_its_span():
    blobs = Blobs()
    data = track([tone(1003 * 24, 24_000, 300, 0.3)], [1900], 2903)
    k = key(tracks=[{"track": blobs.add(data), "start_frame": 728, "spans": [[1900, 2903]]}],
            frames=979 - 0)
    result = mix(k.document, blobs.read)
    line = result.placement["lines"][0]
    assert (line["start_sample"], line["end_sample"]) == (728 * 2000 + 1900 * 48,
                                                          728 * 2000 + 2903 * 48)
    out = samples_of(result)
    assert not out[:line["start_sample"]].any() and not out[line["end_sample"]:].any()
    assert out[line["start_sample"]:line["end_sample"]].any()


def test_lines_are_levelled_to_the_line_rms_and_faded_5_ms():
    blobs = Blobs()
    data = track([dc(48_000, 0.4), dc(24_000, 0.05)], [500, 1800], 2300, rate=RATE)
    lines = {"track": blobs.add(data), "start_frame": 0, "spans": [[500, 1500], [1800, 2300]]}
    k = key(tracks=[lines, loud_line(blobs, frame=60)], frames=96)
    result = mix(k.document, blobs.read)
    out = samples_of(result)[:, 0].astype(np.float64)
    master = 10 ** (result.placement["master_gain_db"] / 20)
    for start, end in ((24_000, 72_000), (86_400, 110_400)):
        steady = out[start + 2000]
        # Every line at the same RMS (a DC line's RMS is its value), then the master gain.
        assert steady == pytest.approx(LEVEL * master, rel=1e-4)
        assert np.allclose(out[start:start + 240] / steady, np.linspace(0, 1, 240), atol=1e-4)
        assert np.allclose(out[end - 240:end] / steady, np.linspace(1, 0, 240), atol=1e-4)
        assert np.allclose(out[start + 240:end - 240], steady, rtol=1e-4)
    gains = [line["gain_db"] for line in result.placement["lines"][:2]]
    # 0.4 and 0.05 DC, upmixed to stereo at -3 dB, each brought to -22 dBFS RMS.
    assert gains[0] == pytest.approx(-22 - 20 * math.log10(0.4 / math.sqrt(2)), abs=0.01)
    assert gains[1] == pytest.approx(-22 - 20 * math.log10(0.05 / math.sqrt(2)), abs=0.01)


def test_a_sound_cue_is_trimmed_levelled_faded_and_placed_at_its_sample():
    blobs = Blobs()
    ramp = (np.arange(48_000, dtype=np.float32) + 1) / 48_000 * 0.5  # source sample i is (i+1)/N
    sound = blobs.add(wav16(np.stack([ramp, ramp], 1), RATE))
    flat = blobs.add(wav16(np.stack([dc(48_000, 0.3)] * 2, 1), RATE))
    sounds = [{"sound": sound, "start_sample": 30_000, "trim_ms": [100, 300],
               "level_rms_dbfs": -24},
              {"sound": flat, "start_sample": 80_000, "trim_ms": None, "level_rms_dbfs": -20}]
    k = key(tracks=[loud_line(blobs, frame=72)], sounds=sounds, frames=120)
    result = mix(k.document, blobs.read)
    out = samples_of(result)[:, 0].astype(np.float64)
    first, second = result.placement["sounds"]
    assert (first["start_sample"], first["end_sample"], first["samples"]) == (30_000, 39_600, 9600)
    assert (second["start_sample"], second["end_sample"]) == (80_000, 128_000)
    assert not first["cut_at_film_end"] and first["trim_ms"] == [100, 300]
    # Trim: the placed samples are source samples 4800..14399, in proportion.
    j = np.arange(600, 7000)
    expected = (4800 + j + 1) / (4800 + 3000 + 1)
    assert np.allclose(out[30_000 + j] / out[30_000 + 3000], expected, rtol=1e-3)
    # Fades: 10 ms in (480 samples), 50 ms out (2400 samples), on the flat sound.
    steady = out[80_000 + 10_000]
    assert np.allclose(out[80_000:80_480] / steady, np.linspace(0, 1, 480), atol=1e-4)
    assert np.allclose(out[128_000 - 2400:128_000] / steady, np.linspace(1, 0, 2400), atol=1e-4)
    master = 10 ** (result.placement["master_gain_db"] / 20)
    assert steady == pytest.approx(10 ** (-20 / 20) * master, rel=1e-4)


def test_a_sound_past_the_cut_is_cut_at_film_end_and_recorded():
    blobs = Blobs()
    flat = blobs.add(wav16(np.stack([dc(48_000, 0.3)] * 2, 1), RATE))
    k = key(tracks=[loud_line(blobs, frame=0)], frames=60,
            sounds=[{"sound": flat, "start_sample": 120_000 - 14_400, "trim_ms": None,
                     "level_rms_dbfs": -20}])
    result = mix(k.document, blobs.read)
    sound = result.placement["sounds"][0]
    assert sound["cut_at_film_end"] is True
    placed = (sound["end_sample"], sound["samples"], sound["cut_samples"])
    assert placed == (120_000, 48_000, 33_600)
    out = samples_of(result)
    assert out.shape == (120_000, 2)  # TIME-11: frames x 2000, the sound no further
    assert out[-1, 0] != 0  # cut, not faded: the fade-out was past the film's end


def test_a_bed_loops_with_1s_crossfades_and_fades_in_over_half_a_second():
    blobs = Blobs()
    bed = blobs.add(wav16(np.stack([dc(120_000, 0.2)] * 2, 1), RATE))  # 2.5 s
    k = key(tracks=[loud_line(blobs, frame=60)], frames=96,
            beds=[{"sound": bed, "level_rms_dbfs": -40, "clock": "film"}])
    result = mix(k.document, blobs.read)
    out = samples_of(result)[:, 0].astype(np.float64)
    placed = result.placement["beds"][0]
    assert (placed["start_sample"], placed["end_sample"], placed["loops"]) == (0, 192_000, 2)
    steady = out[60_000]
    master = 10 ** (result.placement["master_gain_db"] / 20)
    assert steady == pytest.approx(10 ** (-40 / 20) * master, rel=1e-3)
    assert np.allclose(out[:24_000] / steady, np.linspace(0, 1, 24_000), atol=2e-3)
    # A constant bed crossfades into itself seamlessly: constant up to the tone line.
    assert np.allclose(out[24_000:119_000], steady, rtol=2e-3)


def _legacy_loop(b: np.ndarray, fade: int, total: int) -> np.ndarray:
    """``poc/edit.py``'s bed loop, verbatim but for the buffer length."""
    loop = b.copy()
    while len(loop) < total:
        ramp = np.linspace(0, 1, fade)[:, None]
        loop = np.concatenate([loop[:-fade], loop[-fade:] * (1 - ramp) + b[:fade] * ramp, b[fade:]])
    return loop[:total]


@pytest.mark.parametrize("length,total", [(2_401, 9_000), (5_000, 4_000), (3_000, 30_011),
                                          (10_000, 10_000)])
def test_the_bed_loop_is_the_legacy_loop(length, total):
    bed = np.stack([noise(length, 0.2, 7), noise(length, 0.2, 8)], 1)
    ours, _ = _loop(bed, 1_200, total)
    assert ours.shape == (total, 2)
    assert np.allclose(ours, _legacy_loop(bed, 1_200, total), atol=1e-6)


def test_headroom_then_loudness_target_then_the_limiter():
    blobs = Blobs()
    hot = blobs.add(wav16(np.stack([noise(48_000, 0.6, 3)] * 2, 1).clip(-1, 1), RATE))
    k = key(tracks=[loud_line(blobs, frame=0, ms=3000)], frames=96,
            sounds=[{"sound": hot, "start_sample": 20_000, "trim_ms": None, "level_rms_dbfs": -6}])
    result = mix(k.document, blobs.read)
    p = result.placement
    assert p["premaster_peak"] > 0.5
    assert p["headroom_db"] == pytest.approx(20 * math.log10(0.5 / p["premaster_peak"]), abs=1e-5)
    measured = measure(samples_of(result), where="test")
    assert measured.integrated_lufs == pytest.approx(-20, abs=1.0)
    assert measured.true_peak_dbtp <= -3.5 + 0.5
    assert p["limiter"] == {"limit": 0.5957, "attack_ms": 2, "release_ms": 60, "latency": True}


def test_the_same_inputs_give_the_same_bytes():
    blobs = Blobs()
    bed = blobs.add(wav16(np.stack([noise(3 * 44_100, 0.05, 2)] * 2, 1), 44_100))
    k = key(tracks=[loud_line(blobs, frame=0)], frames=48,
            beds=[{"sound": bed, "level_rms_dbfs": -40, "clock": "film"}])
    assert mix(k.document, blobs.read) == mix(k.document, blobs.read)


@pytest.mark.parametrize("change,code", [
    ({"start_sample": 96_000}, "cue.out_of_range"),  # the film's first sample past its end
    ({"trim_ms": [0, 1001]}, "mix.input_invalid"),  # past the sound's end
    ({"trim_ms": [0, 49]}, "mix.input_invalid"),  # shorter than its 50 ms fade out
])
def test_a_sound_the_mixer_cannot_place_fails(change, code):
    blobs = Blobs()
    flat = blobs.add(wav16(np.stack([dc(48_000, 0.3)] * 2, 1), RATE))
    cue = {"sound": flat, "start_sample": 1000, "trim_ms": None, "level_rms_dbfs": -20, **change}
    with pytest.raises(MixError) as error:
        mix(key(sounds=[cue], frames=48).document, blobs.read)
    assert error.value.code == code


def test_inputs_the_mixer_refuses():
    blobs = Blobs()
    short_bed = blobs.add(wav16(np.stack([dc(96_000, 0.1)] * 2, 1), RATE))  # 2 s: no loop
    stereo = blobs.add(wav16(np.stack([dc(48_000, 0.1)] * 2, 1), RATE))
    line = loud_line(blobs, frame=0)
    cases = [
        (key(frames=48, beds=[{"sound": short_bed, "level_rms_dbfs": -40, "clock": "film"}]),
         "mix.input_invalid"),
        (key(frames=48, tracks=[{"track": stereo, "start_frame": 0, "spans": [[0, 500]]}]),
         "mix.input_invalid"),  # a board voice track is mono (VOICE-2)
        (key(frames=48, mixer="studio.mixer/0"), "mix.input_invalid"),
        # A line running into the next board (which starts at frame 20) fails TIME-11.
        (key(frames=48, tracks=[line, {**line, "start_frame": 20}]), "time.conservation"),
    ]
    for k, code in cases:
        with pytest.raises(MixError) as error:
            mix(k.document, blobs.read)
        assert error.value.code == code, k.document


def test_a_missing_or_wrong_input_fails_with_the_stores_code():
    blobs = Blobs()
    line = loud_line(blobs, frame=0)
    k = key(tracks=[line], frames=48)

    def missing(sha256, where):
        raise StoreError(BLOB_MISSING, f"{where}: absent")

    with pytest.raises(StoreError) as error:
        mix(k.document, missing)
    assert error.value.code == BLOB_MISSING
    with pytest.raises(StoreError) as error:
        mix(k.document, lambda sha256, where: b"other bytes")
    assert error.value.code == HASH_MISMATCH


def test_a_true_peak_target_the_limiter_cannot_take_fails_before_any_filter_error():
    blobs = Blobs()
    k = key(tracks=[loud_line(blobs, frame=0)], frames=48, true_peak=-30)
    with pytest.raises(MixError) as error:
        mix(k.document, blobs.read)
    assert (error.value.code, error.value.where) == ("mix.input_invalid", "true_peak_dbtp")


def test_a_truncated_wav_is_an_input_error():
    data = wav16(dc(1000, 0.1), 24_000)
    for cut in (1, 3):
        with pytest.raises(MixError) as error:
            read_pcm(data[:-cut], where="track")
        assert error.value.code == "mix.input_invalid"


def test_fades_are_at_least_one_ms():
    import dataclasses
    for name in ("line_fade_ms", "sound_fade_out_ms", "bed_crossfade_ms"):
        with pytest.raises(ValueError):
            dataclasses.replace(MIXER, **{name: 0})


def test_the_mixer_version_names_every_setting():
    assert MIXER.version().startswith("studio.mixer/1:")
    import dataclasses
    for name in ("line_fade_ms", "sound_fade_in_ms", "sound_fade_out_ms", "bed_crossfade_ms",
                 "bed_fade_in_ms", "headroom_peak", "limiter_margin_db", "limiter_latency"):
        value = getattr(MIXER, name)
        changed = (not value) if isinstance(value, bool) else value + 1
        other = dataclasses.replace(MIXER, **{name: changed})
        assert other.version() != MIXER.version(), name
