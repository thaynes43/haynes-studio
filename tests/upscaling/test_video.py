"""Comparison delivery frames use generated media and the bundled decoder."""

from hashlib import sha256
import json
from math import log10
import os
from pathlib import Path
import sys

import av
import cv2
import numpy as np
import pytest
from PIL import Image

from haynes_studio.delivery.media import make_proxy
from haynes_studio.store import blob_locator
from haynes_studio.timebase import DELIVERY_FPS
from haynes_studio.upscaling import __main__, comparison, video
from haynes_studio.upscaling.profile import (
    DELIVERY_ID_REQUIRED, FRAME_OUT_OF_RANGE, NONZERO_START_TIMESTAMP, PIN_MISMATCH, REQUEST_INVALID, UpscaleError,
)
from tests.delivery.media import write_master

from .test_backend import FakeFsrcnn, TARGET, pins  # noqa: F401 (pytest fixture)

PROXY_SIZE = (540, 960)
FRAMES = (32, 128, 224)
DELIVERY_ID = "dlv_" + "0" * 26


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


@pytest.fixture(scope="module")
def h264_proxy(tmp_path_factory):
    root = tmp_path_factory.mktemp("h264-proxy")
    frame_count = 2 * DELIVERY_FPS + 6
    master = write_master(
        root / "master.mp4", frames=frame_count, width=540, height=960, threads=1,
        video_options={"preset": "veryfast", "g": "48", "x264-params": "bframes=3:b-adapt=0:scenecut=0"},
    )
    proxy = root / "proxy.mp4"
    make_proxy(master, proxy, width=540, height=960, frames=frame_count, threads=1)
    relative = _store(root, proxy)
    with av.open(str(root / relative)) as movie:
        assert movie.streams.video[0].codec_context.name == "h264"
        movie.streams.video[0].codec_context.thread_count = 1
        facts = [(frame.pts * frame.time_base, frame.key_frame, frame.pict_type,
                  memoryview(frame.planes[0])[0]) for frame in movie.decode(video=0)]
    assert len(facts) == frame_count
    return root, relative, facts


def test_delivery_h264_frames_in_presentation_order(h264_proxy):
    root, relative, facts = h264_proxy
    after_b = next(index + 1 for index, frame in enumerate(facts) if frame[2] == av.video.frame.PictureType.B)
    gop_boundary = next(index for index, frame in enumerate(facts) if index and frame[1])
    assert gop_boundary == 2 * DELIVERY_FPS
    selections = [(str(index), None, index) for index in (0, after_b, gop_boundary, len(facts) - 1)]
    selections.append((None, "0.0625", 1))  # halfway between frames 1 and 2
    for index, timestamp, expected in selections:
        selected = video.frame_selector(index, timestamp)
        assert selected == expected
        image, report = video.read_frame(root, relative, selected, TARGET)
        pts, _, _, luma = facts[expected]
        assert pts * DELIVERY_FPS == expected
        assert report["frame_index"] == expected and report["frame_count"] == len(facts)
        assert report["first_timestamp_seconds"] == 0
        assert all(abs(channel - (luma - 16) * 255 / 219) <= 3 for channel in image.getpixel((0, 0)))
    with pytest.raises(UpscaleError) as error:
        video.read_frame(root, relative, len(facts), TARGET)
    assert error.value.code == FRAME_OUT_OF_RANGE


@pytest.fixture
def h264_without_edits(tmp_path, h264_proxy):
    root, relative, _ = h264_proxy
    path = tmp_path / "without-edit-list.mp4"
    with av.open(str(root / relative)) as source, av.open(str(path), "w", options={"use_editlist": "0"}) as out:
        stream = out.add_stream_from_template(source.streams.video[0])
        for packet in source.demux(video=0):
            if packet.dts is not None:
                packet.stream = stream
                out.mux(packet)
    return path


def test_h264_clock_without_edit_list_is_refused(tmp_path, h264_without_edits):
    offset = _store(tmp_path, h264_without_edits)
    with pytest.raises(UpscaleError) as error:
        video.read_frame(tmp_path, offset, 2, TARGET)
    assert error.value.code == NONZERO_START_TIMESTAMP
    report = video.probe_frames(tmp_path, offset, 2, TARGET)
    assert report["passed"] is False and report["code"] == NONZERO_START_TIMESTAMP
    assert report["source"]["first_timestamp_seconds"] > 0
    assert report["source"]["resolved"] is False


@pytest.mark.parametrize("offset", [-123, 123])
def test_h264_clock_refuses_a_subframe_origin(tmp_path, h264_without_edits, offset):
    # Modify the first composition offset in the generated, unedited MP4.
    # With one positive or negative sub-frame shift, OpenCV can expose PTS 0.
    with av.open(str(h264_without_edits)) as movie:
        time_base = movie.streams.video[0].time_base
    data = bytearray(h264_without_edits.read_bytes())
    ctts = data.index(b"ctts\0\0\0\0")
    data[ctts + 4] = 1  # version 1 permits signed composition offsets
    data[ctts + 16:ctts + 20] = offset.to_bytes(4, "big", signed=True)
    h264_without_edits.write_bytes(data)
    relative = _store(tmp_path, h264_without_edits)
    with pytest.raises(UpscaleError) as error:
        video.read_frame(tmp_path, relative, 0, TARGET)
    assert error.value.code == NONZERO_START_TIMESTAMP
    report = video.probe_frames(tmp_path, relative, 0, TARGET)
    assert report["code"] == NONZERO_START_TIMESTAMP
    assert report["source"]["first_timestamp_seconds"] == float(offset * time_base)
    assert report["source"]["resolved"] is False


def test_h264_seek_must_land_on_the_requested_timestamp(h264_proxy, monkeypatch):
    root, relative, _ = h264_proxy
    capture_type = cv2.VideoCapture

    class WrongSeekTimestamp:
        def __init__(self):
            self.capture = capture_type()

        def __getattr__(self, name):
            return getattr(self.capture, name)

        def get(self, prop):
            value = self.capture.get(prop)
            if prop == cv2.CAP_PROP_PTS and self.capture.get(cv2.CAP_PROP_POS_FRAMES) > 1:
                return value + 1
            return value

    monkeypatch.setattr(cv2, "VideoCapture", WrongSeekTimestamp)
    with pytest.raises(UpscaleError) as error:
        video.read_frame(root, relative, 2, TARGET)
    assert error.value.code == REQUEST_INVALID


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


@pytest.mark.parametrize("probe", [False, True])
@pytest.mark.parametrize(("arguments", "code"), [
    (["--master", "private-master"], DELIVERY_ID_REQUIRED),
    (["--master", "private-master", "--delivery-id", "invalid"], REQUEST_INVALID),
    (["--delivery-id", DELIVERY_ID], REQUEST_INVALID),
])
def test_cli_delivery_pair_refusals(monkeypatch, capsys, arguments, code, probe):
    def unexpected_profile():
        pytest.fail("argument refusals should precede profile setup")

    monkeypatch.setattr(__main__.Profile, "installed", unexpected_profile)
    command = ["studio-upscaling", "compare", "--proxy", "private-proxy", "--frame-index", "0", *arguments]
    if probe:
        command.append("--probe")
    monkeypatch.setattr(sys, "argv", command)
    assert __main__.main() == 1
    report = json.loads(capsys.readouterr().out)
    assert report["code"] == code and "private-" not in json.dumps(report)


def test_comparison_refuses_unlabelled_master_before_reading():
    with pytest.raises(UpscaleError) as error:
        comparison.compare(None, None, None, None, None, target=TARGET, proxy="proxy", frame_index=0, master="master")
    assert error.value.code == DELIVERY_ID_REQUIRED


@pytest.mark.parametrize("frame_index", [1, len(FRAMES)])
def test_cli_probe_reads_both_descriptors_without_loading_a_profile(tmp_path, stored_proxy, monkeypatch, capsys, frame_index):
    master = _video(tmp_path, TARGET)

    def unexpected_call(*args, **kwargs):
        pytest.fail("probe should only hash and decode the selected frames")

    monkeypatch.setattr(__main__.Profile, "installed", unexpected_call)
    monkeypatch.setattr(comparison, "compare", unexpected_call)
    monkeypatch.setattr(__main__, "Path", lambda path: tmp_path if path == "/store" else Path(path))
    monkeypatch.setattr(sys, "argv", [
        "studio-upscaling", "compare", "--probe", "--proxy", stored_proxy, "--master", master,
        "--delivery-id", DELIVERY_ID, "--frame-index", str(frame_index),
    ])
    resolves = frame_index < len(FRAMES)
    assert __main__.main() == int(not resolves)
    streams = capsys.readouterr()
    assert not streams.err and len(streams.out.splitlines()) == 1
    report = json.loads(streams.out)
    assert report["passed"] is resolves
    assert report["source"] == {
        "bytes": (tmp_path / stored_proxy).stat().st_size, "sha256": Path(stored_proxy).stem,
        "size": list(PROXY_SIZE), "fps": DELIVERY_FPS, "frame_count": len(FRAMES),
        "frame_index": frame_index, "first_timestamp_seconds": 0, "resolved": resolves,
    }
    if resolves:
        assert report["delivery_id"] == DELIVERY_ID
        assert report["reference"]["sha256"] == Path(master).stem
        assert report["reference"]["size"] == list(TARGET)
        assert report["reference"]["frame_count"] == len(FRAMES)
        assert report["reference"]["first_timestamp_seconds"] == 0 and report["reference"]["resolved"] is True
    else:
        assert report["code"] == FRAME_OUT_OF_RANGE
    assert str(tmp_path) not in streams.out and stored_proxy not in streams.out and master not in streams.out


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
    args = {"proxy": stored_proxy, "frame_index": 1, "master": master, "target": TARGET, "factory": FakeFsrcnn,
            "delivery_id": DELIVERY_ID if with_master else None}
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
        assert report["delivery_id"] == summary["delivery_id"] == DELIVERY_ID
        assert report["pairing_verification"] == summary["pairing_verification"] == comparison.PAIRING_VERIFICATION
        assert "encoded downscale of the master" in report["ground_truth_scope"]
        assert "real low-resolution sources" in report["ground_truth_scope"]
        assert summary["ground_truth_scope"] == report["ground_truth_scope"]
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
