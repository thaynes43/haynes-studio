"""Exercise profile, artifact and worker behavior without model weights or OpenCV contrib."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from functools import partial
from hashlib import sha1, sha256
from io import BytesIO
import json
import os
from threading import Event
from time import monotonic, sleep

import pytest
from PIL import Image, ImageDraw, PngImagePlugin

from haynes_studio.render.delivery_profile import fit_set_plate, resolve_delivery_upscaler
from haynes_studio.store import canonical_json
from haynes_studio.upscaling import comparison, observe
from haynes_studio.upscaling import profile as profile_module
from haynes_studio.upscaling import smoke as measuring
from haynes_studio.upscaling.backend import PLATE_COMPARISON_SCHEMA, Engine, envelope, verify_result
from haynes_studio.upscaling.comparison import _decode, _publish, _source, compare
from haynes_studio.upscaling.fixtures import Motion, baseline_meets_former_caps, portrait, scores, verdicts
from haynes_studio.upscaling.pixels import crop_plate, decode_png, encode_png
from haynes_studio.upscaling.profile import (
    BUSY, GRAPH_NAME, MAX_INPUT, PIN_MISMATCH, REQUEST_INVALID, RESPONSE_INVALID, TIMEOUT, Profile, UpscaleError,
)
from haynes_studio.upscaling.service import _UnixConnection, listening, local_call
from haynes_studio.upscaling.trial import frame, stage

TARGET = (1080, 1920)
SOURCE = (540, 960)


class FakeFsrcnn:
    def __init__(self, graph):
        assert graph == b"toy-graph"

    def __call__(self, rgb):
        return rgb.resize((rgb.width * 2, rgb.height * 2), Image.Resampling.NEAREST)


class StallOnce(FakeFsrcnn):
    def __init__(self, graph, marker):
        super().__init__(graph)
        self.marker = marker

    def __call__(self, rgb):
        try:
            with self.marker.open("xb"):
                pass
        except FileExistsError:
            return super().__call__(rgb)
        Event().wait(30)
        return super().__call__(rgb)


@pytest.fixture
def pins(tmp_path):
    graph = b"toy-graph"
    blob = sha1(b"blob " + str(len(graph)).encode() + b"\0" + graph, usedforsecurity=False).hexdigest()
    profile = Profile("sha256:" + "a" * 64, "1" * 40, b'{"cpu":{"model":"fake"},"native_sha256":{}}',
                      len(graph), sha256(graph).hexdigest(), blob)
    weights = tmp_path / "weights"
    weights.mkdir()
    manifest = profile.manifest()
    digest = sha256(manifest).hexdigest()
    (weights / GRAPH_NAME).write_bytes(graph)
    (weights / "profile.json").write_bytes(manifest)
    (weights / "profile.sha256").write_text(digest + "\n")
    return weights, profile, digest


@pytest.fixture
def rgb():
    return Image.new("RGB", SOURCE, (20, 70, 180))


def test_transport(tmp_path, pins, rgb):
    weights, profile, digest = pins
    socket = tmp_path / "s"
    receipts = []
    for _ in range(2):
        with Engine(tmp_path, weights, profile, factory=FakeFsrcnn) as engine, listening(socket, engine):
            assert local_call(socket, "GET", "/v1/ready") == (200, engine.readiness)
            png, receipt, _ = frame(tmp_path, socket, rgb, TARGET, profile, digest)
            assert receipt["output"]["width"] == TARGET[0]
            assert decode_png(png, TARGET, RESPONSE_INVALID).getpixel((10, 10)) == rgb.getpixel((0, 0))
            receipts.append(canonical_json(receipt))
    assert receipts[0] == receipts[1]


def test_refusals(tmp_path, pins, rgb):
    weights, profile, digest = pins
    socket = tmp_path / "s"
    with Engine(tmp_path, weights, profile, factory=FakeFsrcnn) as engine, listening(socket, engine):
        good = stage(tmp_path, encode_png(rgb), rgb.size, TARGET, digest)
        for override, code, expected in (
            ({"profile_sha256": "0" * 64}, PIN_MISMATCH, 409),
            ({"profile_id": "unknown"}, PIN_MISMATCH, 409),
            ({"source": {**good["request"]["source"], "sha256": "0" * 64}}, PIN_MISMATCH, 409),
            ({"source": {**good["request"]["source"], "bytes": MAX_INPUT + 1}}, REQUEST_INVALID, 400),
            ({"target": {"width": 1080.0, "height": 1920}}, REQUEST_INVALID, 400),
            ({"source": {**good["request"]["source"], "width": 539}}, REQUEST_INVALID, 400),
            ({"unexpected": 1}, REQUEST_INVALID, 400),
        ):
            value = {**good, "request": {**good["request"], **override}}
            assert local_call(socket, "POST", "/v1/upscale-frame", value) == (expected, {"code": code})
        for body in (b'{"attempt_id": 1, "attempt_id": 2}', b"X" * 6000):
            connection = _UnixConnection(socket, 5)
            try:
                connection.request("POST", "/v1/upscale-frame", body=body,
                                   headers={"Content-Type": "application/json"})
                response = connection.getresponse()
                assert response.status == 400 and json.loads(response.read()) == {"code": REQUEST_INVALID}
            finally:
                connection.close()
        assert not (tmp_path / good["attempt_id"] / "result").exists()
        assert local_call(socket, "POST", "/v1/upscale-frame", good)[0] == 200
        output = tmp_path / good["attempt_id"] / "result/output.png"
        assert output.parent.parent.stat().st_mode & 0o7777 == 0o2770
        assert output.parent.stat().st_mode & 0o7777 == 0o2770
        assert output.stat().st_mode & 0o777 == 0o640
        saved = output.read_bytes()
        assert local_call(socket, "POST", "/v1/upscale-frame", good)[0] == 400
        assert output.read_bytes() == saved


def test_symlinks(tmp_path, pins, rgb):
    weights, profile, digest = pins
    value = stage(tmp_path, encode_png(rgb), rgb.size, TARGET, digest)
    attempt = tmp_path / value["attempt_id"]
    external = tmp_path / "external"
    (attempt / "input.png").rename(external)
    (attempt / "input.png").symlink_to(external)
    with Engine(tmp_path, weights, profile, factory=FakeFsrcnn) as engine:
        with pytest.raises(UpscaleError, match=REQUEST_INVALID):
            engine.run(value)
    assert not (attempt / "result").exists()


def test_manifest_pins(tmp_path, pins):
    weights, profile, _ = pins
    (weights / GRAPH_NAME).write_bytes(b"toy-grapH")
    with pytest.raises(UpscaleError, match=PIN_MISMATCH):
        Engine(tmp_path, weights, profile, factory=FakeFsrcnn)


def test_git_blob_pin(pins):
    weights, profile, _ = pins
    graph = (weights / GRAPH_NAME).read_bytes()
    assert profile.verify(weights)[1] == graph
    profile = replace(profile, graph_blob="0" * 40)
    manifest = profile.manifest()
    (weights / "profile.json").write_bytes(manifest)
    (weights / "profile.sha256").write_text(sha256(manifest).hexdigest() + "\n")
    with pytest.raises(UpscaleError, match=PIN_MISMATCH):
        profile.verify(weights)


def test_installed_refuses_glibc_tunables(monkeypatch):
    monkeypatch.setenv("STUDIO_UPSCALING_IMAGE", profile_module.IMAGE_REPOSITORY + "@sha256:" + "a" * 64)
    monkeypatch.setenv("STUDIO_UPSCALING_REVISION", "1" * 40)
    monkeypatch.setattr(profile_module, "runtime_identity", lambda: b"{}")
    monkeypatch.delenv("GLIBC_TUNABLES", raising=False)
    assert Profile.installed().settings == "default"
    monkeypatch.setenv("GLIBC_TUNABLES", "glibc.malloc.arena_max=1")
    with pytest.raises(UpscaleError, match=PIN_MISMATCH):
        Profile.installed()


def test_timeout(tmp_path, pins, rgb):
    weights, profile, digest = pins
    socket = tmp_path / "s"
    marker = tmp_path / "inflight"
    factory = partial(StallOnce, marker=marker)
    with Engine(tmp_path, weights, profile, factory=factory, request_seconds=1) as engine, listening(socket, engine):
        first = stage(tmp_path, encode_png(rgb), rgb.size, TARGET, digest)
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(local_call, socket, "POST", "/v1/upscale-frame", first)
            stop = monotonic() + 0.8
            while not marker.exists() and monotonic() < stop:
                sleep(0.01)
            assert marker.exists()
            assert local_call(socket, "POST", "/v1/upscale-frame", first) == (409, {"code": BUSY})
            assert pending.result(2) == (504, {"code": TIMEOUT})
        partial_run = tmp_path / first["attempt_id"]
        assert not (partial_run / "result").exists()
        stop = monotonic() + 3
        while engine.readiness is None and monotonic() < stop:
            sleep(0.01)
        assert engine.readiness["profile_sha256"] == digest
        _, receipt, _ = frame(tmp_path, socket, rgb, TARGET, profile, digest)
        assert receipt["source"] == first["request"]["source"]
        assert (partial_run / "input.png").read_bytes() == encode_png(rgb)


def test_png(rgb, tmp_path):
    assert decode_png(encode_png(rgb), SOURCE, REQUEST_INVALID).size == SOURCE
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("not_normalized", "proof")
    file = tmp_path / "metadata.png"
    rgb.save(file, pnginfo=metadata)
    for invalid in (file.read_bytes(), encode_png(rgb.convert("RGBA")), encode_png(rgb) + b"tail"):
        with pytest.raises(UpscaleError, match=REQUEST_INVALID):
            decode_png(invalid, SOURCE, REQUEST_INVALID)


def test_result(tmp_path, pins, rgb):
    weights, profile, digest = pins
    value = stage(tmp_path, encode_png(rgb), rgb.size, TARGET, digest)
    _, request = envelope(value)
    with Engine(tmp_path, weights, profile, factory=FakeFsrcnn) as engine:
        receipt = engine.run(value)
    data = (tmp_path / value["attempt_id"] / "result/output.png").read_bytes()
    modified = deepcopy(receipt)
    modified["provenance"]["manifest"]["png"]["compress_level"] = 4
    with pytest.raises(UpscaleError, match=RESPONSE_INVALID):
        verify_result(request, modified, data, profile)
    with pytest.raises(UpscaleError, match=RESPONSE_INVALID):
        verify_result(request, receipt, data[:-1], profile)


@pytest.fixture
def compare_still(tmp_path, pins, monkeypatch):
    weights, profile, _ = pins
    source, output = tmp_path / "source", tmp_path / "output"
    source.mkdir()
    output.mkdir()
    monkeypatch.setattr(comparison, "RESERVE", 0)
    monkeypatch.setattr(comparison, "BUDGET", 0)

    def run(image, **overrides):
        png = encode_png(image)
        (source / "private.png").write_bytes(png)
        config = {"relative": "private.png", "source_sha256": sha256(png).hexdigest(), "target": TARGET,
                  "rois": {"lettering": (0, 0, 15, 15)}, "factory": FakeFsrcnn, **overrides}
        return compare(tmp_path, weights, source, output, profile, **config)

    return run, source, output


@pytest.mark.parametrize("plate", [False, True], ids=["frame", "fractional-cover-plate"])
def test_comparison_uses_delivery_bytes(compare_still, plate):
    run, source, output = compare_still
    # A 900x999 plate has a 561.9375-pixel-wide center crop. Give the crop
    # boundaries asymmetric detail so a whole-pixel crop cannot match it.
    size = (900, 999) if plate else (576, 1024)
    image = Image.new("RGB", size, (20, 70, 180))
    draw = ImageDraw.Draw(image)
    for x in range(145, 186, 3):
        draw.line((x, 0, x, size[1] - 1), fill=(250, 192, 24))
    draw.rectangle((48, 80, size[0] - 65, 130), outline=(30, 220, 0), width=3)
    summary = run(image, plate=plate)
    report = json.loads((output / "report.json").read_bytes())
    assert "private.png" not in json.dumps(summary) + json.dumps(report)
    assert len(list(output.iterdir())) == 3
    assert report["review"] == "comparison pending"
    assert report["plate"] == plate
    assert report["source"]["sha256"] == summary["source"]["sha256"] == sha256(
        (source / "private.png").read_bytes(),
    ).hexdigest()
    expected = fit_set_plate if plate else resolve_delivery_upscaler(None).scale
    assert (output / "lanczos.png").read_bytes() == encode_png(expected(image, TARGET))
    doubled = FakeFsrcnn(b"toy-graph")(image)
    assert (output / "fsrcnn.png").read_bytes() == encode_png(expected(doubled, TARGET))
    for label, artifact in summary["outputs"].items():
        data = (output / f"{label}.png").read_bytes()
        assert artifact["sha256"] == sha256(data).hexdigest()


def test_plate_comparison_request_is_refused_by_service(tmp_path, pins):
    weights, profile, digest = pins
    socket = tmp_path / "s"
    rgb = Image.new("RGB", (900, 999))
    value = stage(tmp_path, encode_png(rgb), rgb.size, TARGET, digest, schema=PLATE_COMPARISON_SCHEMA)
    with Engine(tmp_path, weights, profile, factory=FakeFsrcnn) as engine, listening(socket, engine):
        assert local_call(socket, "POST", "/v1/upscale-frame", value) == (400, {"code": REQUEST_INVALID})


def test_comparison_source_hash(compare_still, rgb, monkeypatch):
    run, _, output = compare_still

    def reject_unverified_decode(_data):
        pytest.fail("unverified source reached the decoder")

    monkeypatch.setattr(comparison, "_decode", reject_unverified_decode)
    with pytest.raises(UpscaleError, match=PIN_MISMATCH):
        run(rgb, source_sha256="0" * 64)
    assert not list(output.iterdir())


@pytest.mark.parametrize("mode", ["RGBA", "I;16", "P"])
def test_comparison_refuses_source_mode(mode):
    buffer = BytesIO()
    Image.new(mode, SOURCE).save(buffer, format="PNG")
    with pytest.raises(UpscaleError, match=REQUEST_INVALID):
        _decode(buffer.getvalue())


@pytest.mark.parametrize("roi", [(-1, 0, 15, 15), (0, 0, 1081, 15), (0, 0, 15, 1921), (0, 0, 1, 15)])
def test_comparison_roi_bounds(compare_still, rgb, roi, monkeypatch):
    run, _, output = compare_still

    def reject_read_with_invalid_roi(*_args):
        pytest.fail("out-of-bounds ROI reached the source read")

    monkeypatch.setattr(comparison, "_source", reject_read_with_invalid_roi)
    with pytest.raises(UpscaleError, match=REQUEST_INVALID):
        run(rgb, rois={"lettering": roi})
    assert not list(output.iterdir())


def test_comparison_refuses_nonempty_output(compare_still):
    _, _, output = compare_still
    existing = output / "unrelated"
    existing.write_bytes(b"retain")
    with pytest.raises(UpscaleError, match=REQUEST_INVALID):
        _publish(output, {"lanczos": b"new"}, {"memory_by_phase": {}})
    assert list(output.iterdir()) == [existing]
    assert existing.read_bytes() == b"retain"


def test_comparison_source_path(tmp_path):
    (tmp_path / "private.png").write_bytes(b"source")
    (tmp_path / "link").symlink_to(tmp_path / "private.png")
    with pytest.raises(OSError):
        _source(tmp_path, "link")
    with pytest.raises(UpscaleError, match=REQUEST_INVALID):
        _source(tmp_path, "../private.png")


def test_source_refuses_hard_links(tmp_path):
    path = tmp_path / "private.png"
    path.write_bytes(b"source")
    assert _source(tmp_path, path.name) == b"source"
    os.link(path, tmp_path / "other-name.png")
    with pytest.raises(UpscaleError, match=REQUEST_INVALID):
        _source(tmp_path, path.name)


def test_fixture_geometry():
    reference = portrait()
    result = scores(reference, reference)
    assert [band["correct"] for band in result["text"]] == [4, 4, 4]
    assert all(distance == 0 for distance in result["face_displacement_px"].values())
    assert result["edge"]["median_spread_px"] == pytest.approx(0.8)
    assert result["flat"]["std"] == pytest.approx(0)
    motion = Motion()
    for index in (0, 1):
        shifted = portrait(index)
        motion.add(shifted, shifted, index)
    assert motion.report() == {"worst_mean": 0.0, "worst_p95": 0.0, "identical_background": True}
    cropped, box = crop_plate(Image.new("RGB", (626, 1024)), TARGET)
    assert cropped.size == (576, 1024) and box == (25, 0, 601, 1024)


@pytest.fixture
def measured_quality():
    def quality(overshoot, undershoot, spread, worst_mean, worst_p95, text_errors):
        return {
            "edge": {"overshoot": overshoot, "dark_undershoot": undershoot, "median_spread_px": spread},
            "motion": {"worst_mean": worst_mean, "worst_p95": worst_p95, "identical_background": True},
            "text": [
                {"cap_height_px": height, "correct": 4, "luma_mae": error}
                for height, error in zip((14, 21, 28), text_errors, strict=True)
            ],
            # OP461 reported these companion verdicts passing without numeric scores.
            "face_displacement_px": {"left_highlight": 0, "right_highlight": 0, "left_lash": 0, "right_lash": 0},
            "flat": {"std": 0, "mean_shift": 0, "max_channel_span": 0},
        }

    lanczos = quality(0.121569, 0.117647, 2.1173, 0.011209, 0.080104, (0.0554, 0.0686, 0.0618))
    fsrcnn = quality(0.070588, 0.066667, 1.6216, 0.011776, 0.076465, (0.0482, 0.0568, 0.0469))
    return lanczos, fsrcnn


def test_measured_quality_passes_relative_rules_but_failed_former_caps(measured_quality):
    lanczos, fsrcnn = measured_quality
    assert all(verdicts(lanczos, fsrcnn).values())
    for result in (lanczos, fsrcnn):
        assert result["edge"]["overshoot"] > 12 / 255
        assert result["motion"]["worst_mean"] > 2 / 255
    assert baseline_meets_former_caps(lanczos) == {"edge_overshoot": False, "motion_residual": False}
    lanczos["edge"]["overshoot"] = 12 / 255
    lanczos["motion"]["worst_mean"] = 2 / 255
    assert baseline_meets_former_caps(lanczos) == {"edge_overshoot": True, "motion_residual": True}


@pytest.mark.parametrize(("group", "metric", "margin", "verdict"), [
    ("edge", "overshoot", 2 / 255, "edge_overshoot"),
    ("motion", "worst_mean", 0.5 / 255, "motion_residual"),
    ("motion", "worst_p95", 2 / 255, "motion_residual"),
])
def test_quality_fails_just_over_each_relative_margin(measured_quality, group, metric, margin, verdict):
    lanczos, fsrcnn = measured_quality
    fsrcnn[group][metric] = lanczos[group][metric] + margin
    assert verdicts(lanczos, fsrcnn)[verdict]
    fsrcnn[group][metric] += 0.000001
    assert not verdicts(lanczos, fsrcnn)[verdict]


def test_quality_passes_a_tie_on_overshoot_and_motion(measured_quality):
    lanczos, fsrcnn = measured_quality
    fsrcnn["edge"]["overshoot"] = lanczos["edge"]["overshoot"]
    fsrcnn["motion"] = lanczos["motion"]
    assert all(verdicts(lanczos, fsrcnn).values())


def test_measuring_smoke(tmp_path, pins, monkeypatch):
    weights, profile, _ = pins
    # The hosted runner need not expose its job's cgroup at the mount root.
    # Supply cgroup readings while preserving the real worker's /proc samples.
    monkeypatch.setattr(observe, "_read", lambda name: 7 * 1024**3 if name == "memory.max" else 1)
    # The separate timeout test drives a real stall and a replacement child.
    monkeypatch.setattr(measuring, "_deadline", lambda *_: True)
    report = measuring.smoke(tmp_path, weights, profile, factory=FakeFsrcnn)
    assert report["measuring_limit_bytes"] == 7 * 1024**3
    assert report["verdicts"]["allocator_measured"] and report["verdicts"]["allocator_byte_match"]
    assert report["verdicts"]["fresh_worker_repeat"] and report["verdicts"]["plate_crop"]
    for item in report["settings"].values():
        assert item["frame_count"] == 19 and all(item["refusals"].values())
        assert item["baseline_meets_former_caps"] == {"edge_overshoot": False, "motion_residual": False}
        phases = item["memory_by_phase"]
        assert phases["startup"]["worker"]["peak_rss_bytes"] > 0
        assert phases["replay_startup"]["worker"]["peak_rss_bytes"] > 0
        assert phases["replayed_frame"]["worker"]["rss_after_bytes"] > 0
        assert all(phases[f"{name}_fsrcnn"]["worker"]["rss_after_bytes"] > 0 for name in item["frames"])

    # Reuse the measured default data to isolate the CLI's default-only
    # verdict from the fake graph's intentional differences from Lanczos.
    default = report["settings"]["default"]
    default["quality_verdicts"] = {}
    default["timing"] = {"warm_mean_seconds": 0.1, "warm_p95_seconds": 0.2, "max_seconds": 0.3}
    monkeypatch.setattr(measuring, "_exercise", lambda *_args, **_kwargs: default)
    single = measuring.smoke(tmp_path, weights, profile, try_compact=False)
    assert single["passed"]
    assert "allocator_measured" not in single["verdicts"]
    assert list(single["settings"]) == ["default"]


def test_cgroup_memory_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(observe, "CGROUP", tmp_path)
    assert observe.cgroup_limit() is None
    limit = tmp_path / "memory.max"
    limit.write_text("max\n")
    assert observe.cgroup_limit() is None
    limit.write_text("1073741824\n")
    assert observe.cgroup_limit() == 1073741824
