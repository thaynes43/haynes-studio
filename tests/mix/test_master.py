"""The master (story 841): the film picture and the mix muxed, frames conserved.

The picture is a few seconds of drawn frames encoded as story 380 encodes segments;
the master must decode to exactly those frames (stream copy), carry exactly
``frames x 2000`` samples of AAC as recorded, decode within one AAC frame, and pass
story 381's checks. Decoded frames and samples are compared, never encoded bytes
across builds.
"""

from __future__ import annotations

import io

import av
import numpy as np
import pytest

from haynes_studio.delivery.media import inspect
from haynes_studio.mix import MUX, MixError, mix, mux
from haynes_studio.mix.audio import decode_audio, write_wav24
from haynes_studio.render.encode import EncoderSettings, decode_frames, encode_segment
from tests.mix.fixtures import Blobs, key, tone, track

FRAMES = 60


def picture(frames: int = FRAMES, width: int = 64, height: int = 112) -> bytes:
    drawn = (np.full((height, width, 3), (7 * n) % 256, np.uint8) for n in range(frames))
    return encode_segment(drawn, frames_expected=frames, width=width, height=height, fps=24,
                          settings=EncoderSettings())


def mixed(frames: int = FRAMES) -> bytes:
    blobs = Blobs()
    data = track([tone(1500 * 24, 24_000, 440, 0.3)], [200], 1700)
    k = key(tracks=[{"track": blobs.add(data), "start_frame": 0, "spans": [[200, 1700]]}],
            frames=frames)
    return mix(k.document, blobs.read).wav


def test_the_master_holds_exactly_the_films_frames_and_samples(tmp_path):
    pic, wav = picture(), mixed()
    master = mux(pic, wav, workdir=tmp_path)
    assert (master.frames, master.width, master.height) == (FRAMES, 64, 112)
    assert master.audio_samples == FRAMES * 2000  # recorded exactly
    assert FRAMES * 2000 <= master.decoded_audio_samples < FRAMES * 2000 + 1024  # AAC padding
    # Stream copy: the master's picture decodes to the film picture's frames.
    ours = list(decode_frames(master.data))
    theirs = list(decode_frames(pic))
    assert len(ours) == len(theirs) == FRAMES
    assert all(np.array_equal(a, b) for a, b in zip(ours, theirs))
    with av.open(io.BytesIO(master.data)) as container:
        assert [s.type for s in container.streams] == ["video", "audio"]
        audio = container.streams.audio[0].codec_context
        assert (audio.name, audio.sample_rate, audio.channels) == ("aac", 48_000, 2)
    path = tmp_path / "master.mp4"
    path.write_bytes(master.data)
    assert inspect(path, width=64, height=112, expected_frames=FRAMES).ok
    assert list(tmp_path.iterdir()) == [path]  # the scratch folder is gone


def test_the_masters_sound_is_the_mix():
    wav = mixed()
    master = mux(picture(), wav)
    ours = decode_audio(master.data, where="master")
    theirs = decode_audio(wav, where="mix")
    # AAC is lossy and delayed by its priming (trimmed by the MP4 edit list): compare
    # the envelope where the tone plays, 0.3 s to 1.6 s.
    lo, hi = 14_400, 76_800
    rms = lambda a: float(np.sqrt(np.mean(a[lo:hi].astype(np.float64) ** 2)))
    assert rms(ours) == pytest.approx(rms(theirs), rel=0.05)
    assert float(np.max(np.abs(ours[:9000]))) < 1e-3  # silence before the line


def test_a_mix_of_the_wrong_length_fails_conservation():
    wav = write_wav24(np.zeros((FRAMES * 2000 - 1, 2), np.float32))
    with pytest.raises(MixError) as error:
        mux(picture(), wav)
    assert error.value.code == "time.conservation"


def test_a_mix_that_is_not_48khz_stereo_fails():
    wav = write_wav24(np.zeros((FRAMES * 1000, 2), np.float32), rate=24_000)
    with pytest.raises(MixError) as error:
        mux(picture(), wav)
    assert error.value.code == "mix.master_invalid"


def test_the_mux_settings_are_a_key_input_with_the_build():
    inputs = MUX.key_inputs()
    assert inputs["audio"] == "aac" and inputs["audio_bitrate"] == 192_000
    assert inputs["video"] == "copy" and inputs["faststart"] is True
    assert inputs["build"].startswith("pyav-")
