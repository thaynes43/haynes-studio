"""Sound checks as data (story 841): pass on a fixture, fail on a deliberately hot one.

Each check is a pure function of its key's inputs: the artifact's bytes and the
thresholds (which carry the story's targets). The verdicts below come from decoded
samples and the R128 meter, with the stated tolerances.
"""

from __future__ import annotations

import numpy as np
import pytest

from haynes_studio.cache.keys import check_result_key
from haynes_studio.mix import mix, mux
from haynes_studio.mix import checks as sc
from haynes_studio.mix.audio import write_wav24
from tests.mix.fixtures import Blobs, key, noise, tone, track
from tests.mix.test_master import picture

FRAMES = 60


def fixture_mix():
    blobs = Blobs()
    data = track([tone(2000 * 24, 24_000, 440, 0.3)], [200], 2200)
    k = key(tracks=[{"track": blobs.add(data), "start_frame": 0, "spans": [[200, 2200]]}],
            frames=FRAMES)
    return k, mix(k.document, blobs.read).wav


def hot_wav() -> bytes:
    """Full-scale noise with clipped samples: far too loud, peaks over 0 dBTP."""
    hot = np.stack([noise(FRAMES * 2000, 0.9, 5), noise(FRAMES * 2000, 0.9, 6)], 1)
    return write_wav24(np.clip(hot, -1.0, 1.0))


def results(k, artifact: str, data: bytes, on: str) -> dict[str, dict]:
    measured = sc.measure_mix(data) if on == "mix" else sc.measure_master(data)
    out = {}
    for check in sc.CHECKS:
        if check.startswith(on + "."):
            out[check] = sc.evaluate(check, sc.check_key(check, artifact, k.document), measured)
    return out


def test_the_checks_pass_on_the_fixture_mix_and_master():
    k, wav = fixture_mix()
    master = mux(picture(FRAMES), wav).data
    found = {**results(k, "a" * 64, wav, "mix"), **results(k, "b" * 64, master, "master")}
    assert sorted(found) == sorted(sc.CHECKS)
    assert all(r["passed"] for r in found.values()), found
    assert found["mix.length"]["measured"] == {"samples": 120_000, "rate": 48_000, "channels": 2,
                                               "bits": 24}
    assert found["mix.loudness"]["measured"]["integrated_lufs"] == pytest.approx(-20, abs=0.5)
    assert found["master.loudness"]["measured"]["integrated_lufs"] == pytest.approx(-20, abs=0.5)
    assert found["master.true_peak"]["measured"]["true_peak_dbtp"] <= -2.5
    assert found["mix.clipping"]["measured"] == {"clipped_samples": 0}


def test_the_checks_fail_on_a_deliberately_hot_mix_and_master():
    k, _ = fixture_mix()
    wav = hot_wav()
    master = mux(picture(FRAMES), wav).data
    found = {**results(k, "a" * 64, wav, "mix"), **results(k, "b" * 64, master, "master")}
    failed = sorted(name for name, r in found.items() if not r["passed"])
    assert failed == ["master.clipping", "master.loudness", "master.true_peak", "mix.clipping",
                      "mix.loudness", "mix.true_peak"]
    assert found["mix.length"]["passed"]  # the right length, just hot
    assert found["mix.loudness"]["measured"]["integrated_lufs"] > -10
    assert found["mix.true_peak"]["measured"]["true_peak_dbtp"] > 0


def test_a_mix_of_the_wrong_length_fails_its_length_check():
    k, _ = fixture_mix()
    short = write_wav24(np.zeros((FRAMES * 2000 - 48, 2), np.float32))
    found = results(k, "a" * 64, short, "mix")
    assert not found["mix.length"]["passed"]
    assert found["mix.length"]["measured"]["samples"] == FRAMES * 2000 - 48


def test_the_check_key_carries_the_targets_and_the_films_length():
    k, _ = fixture_mix()
    loud = sc.check_key("mix.loudness", "a" * 64, k.document)
    assert dict(loud.document["thresholds"]) == {"target_lufs": -20, "tolerance_lu": 1.5}
    assert loud == check_result_key(artifact="a" * 64, check="mix.loudness",
                                    version=sc.version(), thresholds={"target_lufs": -20,
                                                                      "tolerance_lu": 1.5})
    peak = sc.check_key("master.true_peak", "a" * 64, k.document)
    assert dict(peak.document["thresholds"]) == {"max_dbtp": -2.5}  # legacy validate at -3.5
    other = key(tracks=list(k.document["voice_tracks"]), frames=FRAMES, lufs=-16)
    assert sc.check_key("mix.loudness", "a" * 64, other.document) != loud
    length = sc.check_key("mix.length", "a" * 64, key(frames=FRAMES + 1).document)
    assert length.document["thresholds"]["samples"] == (FRAMES + 1) * 2000
