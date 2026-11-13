"""The media checks on their own (``haynes_studio.delivery.media.inspect``): what they
measure, and that a master made the PoC's way passes them."""

from __future__ import annotations

import subprocess
import wave

import imageio_ffmpeg
import numpy as np
import pytest

from haynes_studio.delivery import inspect
from tests.delivery.media import write_master

FRAMES = 239  # 9.958 s: a length that does not fall on a whole AAC frame


def test_a_good_master_reports_what_it_measured(tmp_path):
    master = write_master(tmp_path / "final.mp4", frames=24)
    report = inspect(master, width=1080, height=1920, expected_frames=24, threads=1)
    assert report.ok and report.problems == ()
    assert (report.brand, report.video_codec, report.audio_codec) == ("isom", "h264", "aac")
    assert (report.width, report.height, report.pixel_format) == (1080, 1920, "yuv420p")
    assert (report.frames, report.audio_rate, report.audio_samples) == (24, 48_000, 48_000)


def test_a_byte_limit_is_strict(tmp_path):
    master = write_master(tmp_path / "final.mp4", frames=24)
    size = master.stat().st_size
    assert inspect(master, width=1080, height=1920, expected_frames=24, max_bytes=size + 1).ok
    report = inspect(master, width=1080, height=1920, expected_frames=24, max_bytes=size)
    assert [p.check for p in report.problems] == ["bytes"]


@pytest.mark.parametrize("expected", [0, -1, 24.0, True])
def test_the_expected_count_is_a_positive_integer(tmp_path, expected):
    with pytest.raises(ValueError):
        inspect(tmp_path / "missing.mp4", width=1080, height=1920, expected_frames=expected)


def test_a_master_made_the_poc_way_passes(tmp_path):
    """``poc/edit.py``: picture with libx264, soundtrack WAV muxed as AAC 192k with
    ``-t`` at 4 decimals and ``+faststart``. Its AAC stream is a few samples off
    ``frames x 2000``, inside the one-AAC-frame tolerance."""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    picture, sound, final = tmp_path / "picture.mp4", tmp_path / "soundtrack.wav", tmp_path / "final.mp4"
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
                    "-threads", "2", "-f", "lavfi", "-i", "color=c=gray:s=1080x1920:r=24",
                    "-frames:v", str(FRAMES), "-c:v", "libx264", "-threads", "2",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(picture)], check=True)
    tone = (0.1 * np.sin(2 * np.pi * 440 * np.arange(FRAMES * 2000) / 48_000) * 32767)
    with wave.open(str(sound), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(48_000)
        out.writeframes(np.repeat(tone.astype("<i2"), 2).tobytes())
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
                    "-threads", "2", "-i", str(picture), "-i", str(sound), "-map", "0:v:0",
                    "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-t", f"{FRAMES / 24:.4f}", "-movflags", "+faststart", str(final)],
                   check=True)
    report = inspect(final, width=1080, height=1920, expected_frames=FRAMES)
    assert report.ok, report.problems
    assert abs(report.audio_samples - FRAMES * 2000) <= 1024
