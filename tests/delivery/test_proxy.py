"""The phone proxy's size rule (P-10), measured: the 60 s fixture (the one long encode
contract section 14 allows story 381) delivers to an H.264 720x1280 proxy under
25 000 000 bytes with the expected frames and duration, and the encoder's bit-rate cap
keeps a hard-to-compress picture inside the bound that makes 60 s fit."""

from __future__ import annotations

from datetime import UTC, datetime

import av
import pytest

from haynes_studio.delivery import deliver, inspect, proxy_byte_limit
from haynes_studio.delivery.media import (
    PROXY_AUDIO_BITRATE,
    PROXY_VIDEO_BUFSIZE,
    PROXY_VIDEO_MAXRATE,
    make_proxy,
)
from haynes_studio.store import LocalStore
from tests.delivery.media import write_master
from tests.store.helpers import PRD, RUN, sha

MINUTE = 1440  # frames in 60 s at 24 fps


def byte_bound(frames: int) -> int:
    """The most bytes the proxy encoder can write for ``frames`` frames: video at most
    (maxrate x seconds + bufsize) / 8 under x264's VBV, audio at its bit rate with 10 %
    for the AAC encoder's rate control, and 1 % plus 64 KiB for the MP4 boxes."""
    seconds = frames / 24
    video = (PROXY_VIDEO_MAXRATE * seconds + PROXY_VIDEO_BUFSIZE) / 8
    audio = PROXY_AUDIO_BITRATE * seconds / 8 * 1.1
    return int((video + audio) * 1.01 + 65_536)


def test_the_cap_makes_a_60_s_proxy_fit_under_25_mb():
    assert byte_bound(MINUTE) < proxy_byte_limit(MINUTE) == 25_000_000
    for frames in (1, 24, 1087, 2880, 14_400):  # longer deliveries keep the margin
        assert byte_bound(frames) < proxy_byte_limit(frames)


def test_a_hard_picture_stays_inside_the_cap(tmp_path):
    """4 s of 4x4 noise, which x264 cannot compress: without the cap its proxy would be
    tens of MB; with it the bytes stay inside the bound for 4 s."""
    frames = 96
    master = write_master(tmp_path / "noise.mp4", frames=frames, noise=True)
    proxy = tmp_path / "proxy.mp4"
    make_proxy(master, proxy, width=720, height=1280, frames=frames)
    size = proxy.stat().st_size
    assert size <= byte_bound(frames), size
    # The cap, not the picture, set the size: the stream ran close to the maximum rate.
    assert size * 8 > PROXY_VIDEO_MAXRATE * frames / 24 * 0.8, size
    assert inspect(proxy, width=720, height=1280, expected_frames=frames).ok


@pytest.fixture(scope="module")
def minute(tmp_path_factory):
    """The 60 s, 1080x1920 synthetic master, delivered once."""
    folder = tmp_path_factory.mktemp("minute")
    master = write_master(folder / "final.mp4", frames=MINUTE, long=True)
    root = folder / "store"
    root.mkdir()
    delivery = deliver(master, store=LocalStore(root), production_id=PRD, run_id=RUN,
                       expected_frames=MINUTE, now=datetime(2026, 11, 13, tzinfo=UTC))
    return master, root, delivery


def test_the_60_s_fixture_delivers_a_proxy_under_25_mb(minute, record_property):
    master, root, delivery = minute
    proxy = root / delivery.proxy.locator
    size = proxy.stat().st_size
    for name, value in [("master_sha256", delivery.master.sha256),
                        ("master_bytes", delivery.master.bytes),
                        ("proxy_sha256", delivery.proxy.sha256), ("proxy_bytes", size)]:
        record_property(name, value)
    assert sha(master.read_bytes()) == delivery.master.sha256
    assert size == delivery.proxy.bytes < 25_000_000
    assert delivery.verification.proxy_under_bytes == 25_000_000
    assert delivery.master.frames == delivery.proxy.frames == MINUTE
    report = inspect(proxy, width=720, height=1280, expected_frames=MINUTE, max_bytes=25_000_000)
    assert report.ok, report.problems
    assert (report.video_codec, report.audio_codec, report.frames) == ("h264", "aac", MINUTE)
    assert report.audio_samples == MINUTE * 2000  # exactly 60 s of audio
    with av.open(str(proxy)) as container:
        video = container.streams.video[0]
        assert video.duration * video.time_base == 60  # exactly 60 s of picture
        assert video.codec_context.profile == "High"
    with open(proxy, "rb") as handle:  # +faststart: the index comes before the media
        head = handle.read(64 * 1024)
    assert 0 <= head.find(b"moov") < head.find(b"mdat") or b"mdat" not in head
