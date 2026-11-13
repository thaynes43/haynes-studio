"""The media checks on their own (``haynes_studio.delivery.media.inspect``): what they
measure, and that a master made the PoC's way passes them."""

from __future__ import annotations

import subprocess
import wave

import av
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


@pytest.mark.parametrize("gap, check", [((8192, 16384), "audio_continuity"),
                                        ((0, 4096), "audio_continuity")],
                         ids=["hole", "late-start"])
def test_audio_with_a_hole_or_a_late_start_is_refused(tmp_path, gap, check):
    """The header can claim a full-length track while frames are missing: the decoded
    audio must run on from 0, with no hole."""
    master = write_master(tmp_path / "final.mp4", frames=12, audio_gap=gap)
    report = inspect(master, width=1080, height=1920, expected_frames=12)
    assert check in {p.check for p in report.problems}
    assert report.decoded_audio_samples < 12 * 2000


def test_a_damaged_frame_is_refused(tmp_path):
    master = write_master(tmp_path / "final.mp4", frames=12)
    with av.open(str(master)) as container:
        first = next(p for p in container.demux(video=0) if p.size)
        position, size = first.pos, first.size
    data = bytearray(master.read_bytes())
    middle = position + size // 2
    data[middle:middle + 16] = bytes(b ^ 0xFF for b in data[middle:middle + 16])
    damaged = tmp_path / "damaged.mp4"
    damaged.write_bytes(bytes(data))
    report = inspect(damaged, width=1080, height=1920, expected_frames=12)
    assert "decode" in {p.check for p in report.problems}


def test_a_stream_with_no_decoder_is_reported_not_raised(tmp_path):
    data = write_master(tmp_path / "final.mp4", frames=12).read_bytes()
    entry = data.find(b"avc1", data.find(b"stsd"))
    unknown = tmp_path / "unknown.mp4"
    unknown.write_bytes(data[:entry] + b"zzzz" + data[entry + 4:])
    report = inspect(unknown, width=1080, height=1920, expected_frames=12)
    assert [p.check for p in report.problems] == ["video_codec"]


def test_an_unreadable_path_is_reported_not_raised(tmp_path):
    report = inspect(tmp_path / "missing.mp4", width=1080, height=1920, expected_frames=12)
    assert [p.check for p in report.problems] == ["container"]
    assert report.frames == 0


def test_the_proxy_audio_is_checked_exactly(tmp_path):
    """A master may be one AAC frame off; the proxy, whose audio the encoder places
    exactly, may not (``audio_tolerance=0``)."""
    master = write_master(tmp_path / "final.mp4", frames=24, audio_samples=24 * 2000 - 512)
    assert inspect(master, width=1080, height=1920, expected_frames=24).ok
    report = inspect(master, width=1080, height=1920, expected_frames=24, audio_tolerance=0)
    assert "audio_duration" in {p.check for p in report.problems}
