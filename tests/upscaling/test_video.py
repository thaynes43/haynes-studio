"""Comparison delivery frames use generated media and the bundled decoder."""

from hashlib import sha256
import json
from math import log10
import os
from pathlib import Path
import sys

import cv2
import numpy as np
import pytest
from PIL import Image

from haynes_studio.store import blob_locator
from haynes_studio.timebase import DELIVERY_FPS
from haynes_studio.upscaling import __main__, comparison, video
from haynes_studio.upscaling.profile import FRAME_OUT_OF_RANGE, PIN_MISMATCH, REQUEST_INVALID, UpscaleError

from .test_backend import FakeFsrcnn, TARGET, pins  # noqa: F401 (pytest fixture)

PROXY_SIZE = (540, 960)
FRAMES = (32, 128, 224)


def _store(root, path, *, digest=None):
    relative = blob_locator("library", digest or sha256(path.read_bytes()).hexdigest(), "video/mp4")
    (root / relative).parent.mkdir(parents=True, exist_ok=True)
    path.rename(root / relative)
    return relative


def _video(root, size, *, shades=FRAMES, fps=DELIVERY_FPS):
    path = root / "generated.mp4"
    writer = cv2.VideoWriter(str(path), cv2.CAP_FFMPEG, cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    try:
        assert writer.isOpened()
        for shade in shades:
            writer.write(np.full((size[1], size[0], 3), shade, dtype=np.uint8))
    finally:
        writer.release()
    return _store(root, path)


@pytest.fixture
def stored_proxy(tmp_path):
    return _video(tmp_path, PROXY_SIZE)


@pytest.mark.parametrize(("index", "timestamp", "expected"), [("1", None, 1), (None, "0.091", 2), (None, "0", 0)])
def test_select_frame(tmp_path, stored_proxy, index, timestamp, expected):
    image, facts = video.read_frame(tmp_path, stored_proxy, video.frame_selector(index, timestamp), TARGET)
    assert facts["frame_index"] == expected
    assert facts["frame_count"] == len(FRAMES)
    # MP4 encoding changes the exact levels. Each frame still has its own shade.
    assert all(abs(channel - FRAMES[expected]) <= 5 for channel in image.getpixel((0, 0)))


@pytest.mark.parametrize(("index", "timestamp"), [("3", None), (None, "0.125"), (None, "9999999999")])
def test_frame_bound(tmp_path, stored_proxy, index, timestamp):
    with pytest.raises(UpscaleError) as error:
        video.read_frame(tmp_path, stored_proxy, video.frame_selector(index, timestamp), TARGET)
    assert error.value.code == FRAME_OUT_OF_RANGE


def test_blob_hash_checked_before_decode(tmp_path, stored_proxy):
    wrong = _store(tmp_path, tmp_path / stored_proxy, digest="a" * 64)
    with pytest.raises(UpscaleError) as error:
        video.read_frame(tmp_path, wrong, 0, TARGET)
    assert error.value.code == PIN_MISMATCH


def test_master_must_be_target_size(tmp_path, stored_proxy):
    with pytest.raises(UpscaleError) as error:
        video.read_frame(tmp_path, stored_proxy, 1, TARGET, master_frames=len(FRAMES))
    assert error.value.code == REQUEST_INVALID


@pytest.mark.parametrize("kind", ["symlink", "shard-symlink", "hard-link", "fifo", "missing", "byte-bound", "empty"])
def test_unsafe_video_blob(tmp_path, stored_proxy, monkeypatch, kind):
    blob = tmp_path / stored_proxy
    if kind == "shard-symlink":
        shard = blob.parent
        actual = shard.rename(tmp_path / "actual_shard")
        shard.symlink_to(actual, target_is_directory=True)
    elif kind == "byte-bound":
        monkeypatch.setattr(video, "MAX_VIDEO_BYTES", blob.stat().st_size - 1)
    else:
        actual = blob.rename(tmp_path / "outside")
        if kind == "symlink":
            blob.symlink_to(actual)
        elif kind == "hard-link":
            blob.hardlink_to(actual)
        elif kind == "fifo":
            os.mkfifo(blob)
        elif kind == "empty":
            blob.touch()
    with pytest.raises(UpscaleError) as error:
        video.read_frame(tmp_path, stored_proxy, 0, TARGET)
    assert error.value.code == REQUEST_INVALID


@pytest.mark.parametrize("relative", ["../outside.mp4", "/library/sha256/ab/private.mp4", "library/private.mp4"])
def test_invalid_locator(tmp_path, relative):
    with pytest.raises(UpscaleError) as error:
        video.read_frame(tmp_path, relative, 0, TARGET)
    assert error.value.code == REQUEST_INVALID


def test_video_decode_and_geometry_refusals(tmp_path):
    wrong_fps = _video(tmp_path, PROXY_SIZE, fps=25)
    wrong_aspect = _video(tmp_path, (540, 800))
    target_size = _video(tmp_path, TARGET)
    bad_container = tmp_path / "fake.mp4"
    bad_container.write_bytes(b"a hash-verified file that does not decode")
    bad_container = _store(tmp_path, bad_container)
    for relative, master_frames in ((wrong_fps, None), (wrong_aspect, None), (target_size, None),
                                    (bad_container, None), (target_size, 4)):
        with pytest.raises(UpscaleError) as error:
            video.read_frame(tmp_path, relative, 0, TARGET, master_frames=master_frames)
        assert error.value.code == REQUEST_INVALID


@pytest.mark.parametrize("arguments", [
    [], ["--frame-index", "-1"], ["--timestamp", "nan"], ["--timestamp", "1e1"],
    ["--frame-index", "0", "--timestamp", "0"], ["--frame-index", "0", "--plate"],
    ["--frame-index", "0", "--input-sha256", "a" * 64],
])
def test_cli_selector_refusals(monkeypatch, capsys, arguments):
    monkeypatch.setattr(sys, "argv", ["studio-upscaling", "compare", "--proxy", "private-locator", *arguments])
    try:
        assert __main__.main() == 1
    except SystemExit as error:
        assert error.code == 2
    streams = capsys.readouterr()
    assert json.loads(streams.out or streams.err) == {"code": REQUEST_INVALID}


def test_known_fidelity():
    truth = Image.new("RGB", (48, 64), (0, 0, 0))
    truth.paste((255, 255, 255), (25, 0, 48, 64))
    proxy = truth.resize((24, 32), Image.Resampling.BOX)
    restored = proxy.resize(truth.size, Image.Resampling.NEAREST)
    values = comparison._measure(proxy, truth, restored, {"lettering": (24, 0, 26, 64)}, truth)
    exact = values["lanczos"]["ground_truth"]
    assert exact == {"luma_mae": 0.0, "luma_psnr_db": None, "luma_ssim": 1.0,
                     "roi_luma_mae": {"lettering": 0.0}}
    lossy = values["fsrcnn"]["ground_truth"]
    assert lossy["luma_mae"] == pytest.approx(0.5 / 24)
    mse = (128**2 + 127**2) / (48 * 255**2)
    assert lossy["luma_psnr_db"] == pytest.approx(-10 * log10(mse))
    assert 0 < lossy["luma_ssim"] < 1
    assert lossy["roi_luma_mae"]["lettering"] == pytest.approx(0.5)


@pytest.mark.parametrize("with_master", [False, True])
def test_comparison_publishes_private_frames(tmp_path, stored_proxy, pins, monkeypatch, with_master):
    weights, profile, _ = pins
    master = _video(tmp_path, TARGET) if with_master else None
    output = tmp_path / "private-output"
    output.mkdir()
    monkeypatch.setattr(comparison, "RESERVE", 0)
    monkeypatch.setattr(comparison, "BUDGET", 0)
    args = {"proxy": stored_proxy, "frame_index": 1, "master": master, "target": TARGET, "factory": FakeFsrcnn}
    before = {p: p.read_bytes() for p in tmp_path.rglob("*.mp4")}
    summary = comparison.compare(tmp_path, weights, tmp_path, output, profile, **args)
    text = (output / "report.json").read_text()
    assert str(tmp_path) not in text and stored_proxy not in text and "private-output" not in text
    report = json.loads(text)
    assert report["review"] == "comparison pending"
    assert report["source"]["sha256"] == Path(stored_proxy).stem and report["source"]["frame_index"] == 1
    saved = {"proxy.png", "lanczos.png", "fsrcnn.png", "report.json"}
    if with_master:
        saved.add("master.png")
        assert master not in text
        assert report["reference"]["sha256"] == Path(master).stem and report["reference"]["frame_index"] == 1
        assert "encoded downscale of the master" in report["ground_truth_scope"]
        assert "real low-resolution sources" in report["ground_truth_scope"]
        assert all("ground_truth" in report["objective_measures"][arm] for arm in ("lanczos", "fsrcnn"))
        assert summary["normalized_reference"]["sha256"] == sha256((output / "master.png").read_bytes()).hexdigest()
    else:
        assert "reference" not in summary and "ground_truth" not in report["objective_measures"]["lanczos"]
    assert {p.name for p in output.iterdir()} == saved
    assert sha256((output / "proxy.png").read_bytes()).hexdigest() == summary["normalized_source"]["sha256"]
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*.mp4")}
    with pytest.raises(UpscaleError) as error:
        comparison._publish(output, {}, report)
    assert error.value.code == REQUEST_INVALID
    assert (output / "report.json").read_text() == text
