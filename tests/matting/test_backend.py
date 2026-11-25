"""The service, test fixtures and guard conditions without any model weights."""

from __future__ import annotations

import copy
import hashlib
import multiprocessing
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from functools import partial
from io import BytesIO
from pathlib import Path
from time import monotonic

import numpy as np
import pytest
from PIL import Image

from haynes_studio.jsonio import read_json
from haynes_studio.matting.backend import (
    REQUEST_SCHEMA, RESULT_SCHEMA, Engine, _read_file, _write_png, envelope, input_signature,
    verify_result,
)
from haynes_studio.matting.fixtures import GREEN, bust, score_eyes, score_shape, score_size
from haynes_studio.matting.pixels import (
    decode_source, encode_png, linear_srgb, matte_pixels, measure_shape, srgb_bytes,
)
from haynes_studio.matting.profile import (
    BUSY, COMMAND_FAILED, DIM, GRAPH_NAME, NOT_FOUND, PIN_MISMATCH, PROFILE_ID,
    PROVIDER, REQUEST_INVALID, RESPONSE_INVALID, TIMEOUT, MatteError, Profile,
)
from haynes_studio.matting.service import _UnixConnection, listening, local_call
from haynes_studio.matting.smoke import _check_fixtures, _request
from haynes_studio.schemas import validator_for
from haynes_studio.store import canonical_json

GRAPH = b"file pin for a matte source that needs no graph"
PROFILE = Profile("sha256:" + "f" * 64, "1" * 40, len(GRAPH), hashlib.sha256(GRAPH).hexdigest())


def fixed_matte(rgb):
    sample = rgb.getpixel((0, 0))[0]
    if sample == 55:
        raise RuntimeError("fake runtime failure")
    alpha = np.zeros((DIM, DIM), dtype=np.float32)
    alpha[256:768, 128:896] = 1
    if sample == 56:
        alpha[0, 0] = np.nan
    elif sample == 57:
        alpha[:] = 0
    elif sample == 58:
        alpha[:] = 1
    return alpha


def load_fake(graph):
    assert graph == GRAPH
    return fixed_matte


class BlockingMatte:
    def __init__(self, started):
        self.started = started

    def __call__(self, rgb):
        if rgb.getpixel((0, 0))[0] == 77:
            self.started.set()
            # Waiting forever in this child models non-cooperative native inference.
            multiprocessing.get_context("spawn").Event().wait()
        return fixed_matte(rgb)


def load_blocking_matte(graph, *, started):
    assert graph == GRAPH
    return BlockingMatte(started)


def fixture_matte(rgb, *, imperfect):
    if rgb.getpixel((0, 0)) == GREEN:
        fixture = bust(green=True)
    else:
        normal = bust()
        fixture = normal if np.array_equal(rgb, normal.rgb) else bust(smaller=True)
    alpha = fixture.alpha.copy()
    if imperfect:
        if rgb.getpixel((0, 0)) == GREEN:
            alpha[fixture.irises[0] > 0] = 0
        else:
            alpha[110:190, 40:144] = 0
            alpha[fixture.strands > 0] = 0
    pixels = Image.fromarray(alpha.astype(np.float32) / 255)
    return np.array(pixels.resize((DIM, DIM), Image.Resampling.BILINEAR))


def load_fixtures(graph, *, imperfect):
    assert graph == GRAPH
    return partial(fixture_matte, imperfect=imperfect)


@pytest.fixture
def prepared(tmp_path):
    weights = tmp_path / "weights"
    weights.mkdir()
    manifest = PROFILE.manifest()
    digest = hashlib.sha256(manifest).hexdigest()
    (weights / "profile.json").write_bytes(manifest)
    (weights / "profile.sha256").write_text(digest + "\n")
    (weights / GRAPH_NAME).write_bytes(GRAPH)
    return tmp_path, weights, digest


def request_for(root, digest, *, value=33, target=None):
    data = encode_png(np.full((64, 64, 3), value, dtype=np.uint8))
    return _request(root, data, 64, 64, digest, target=target)


def artifacts(root, value):
    directory = root / value["attempt_id"]
    return {name: (directory / (name + ".png")).read_bytes() for name in ("cutout", "mask")}


def code_is(error, code):
    assert error.value.code == code


def test_socket_result_replay_and_attempt_collision(prepared):
    root, weights, digest = prepared
    # UDS paths have a short kernel limit. Synthetic media stay under tmp_path.
    with tempfile.TemporaryDirectory(prefix="matte-sock-") as directory, Engine(
        root, weights, PROFILE, factory=load_fake,
    ) as engine:
        path = Path(directory) / "matte.sock"
        with listening(path, engine):
            assert local_call(path, "GET", "/v1/ready") == (200, {
                "profile_id": PROFILE_ID, "profile_sha256": digest, "provider": PROVIDER,
            })
            value = request_for(root, digest, target=256)
            status, result = local_call(path, "POST", "/v1/matte", value)
            assert status == 200
            assert result["shape"] == {
                "bbox_xyxy": [8, 16, 56, 48], "bbox_height_px": 32, "foreground_area_px": 1536,
                "alpha_threshold": 128, "scale": {"numerator": 256, "denominator": 32},
            }
            assert result["input_signature"] == input_signature(value["request"])
            outputs = artifacts(root, value)
            verify_result(value["request"], result, outputs, PROFILE)
            assert local_call(path, "POST", "/v1/matte", value) == (400, {"code": REQUEST_INVALID})
            replay = request_for(root, digest, target=256)
            assert local_call(path, "POST", "/v1/matte", replay) == (200, result)
            assert artifacts(root, replay) == outputs == artifacts(root, value)


def test_http_refuses_oversized_or_ambiguous_json(prepared):
    root, weights, digest = prepared
    value = request_for(root, digest)
    good = canonical_json(value)
    duplicate = good[:-1] + b',"attempt_id":"' + value["attempt_id"].encode() + b'"}'
    with tempfile.TemporaryDirectory(prefix="matte-sock-") as directory, Engine(
        root, weights, PROFILE, factory=load_fake,
    ) as engine:
        path = Path(directory) / "matte.sock"
        with listening(path, engine):
            for body in (good + b" " * 4096, duplicate):
                connection = _UnixConnection(path, 3)
                try:
                    connection.request("POST", "/v1/matte", body=body, headers={"Content-Type": "application/json"})
                    response = connection.getresponse()
                    assert response.status == 400
                    assert response.read() == canonical_json({"code": REQUEST_INVALID})
                finally:
                    connection.close()
    assert {item.name for item in (root / value["attempt_id"]).iterdir()} == {"input"}


@pytest.mark.parametrize(("value", "code"), [
    (55, COMMAND_FAILED), (56, RESPONSE_INVALID), (57, RESPONSE_INVALID), (58, RESPONSE_INVALID),
])
def test_inference_refusals(prepared, value, code):
    root, weights, digest = prepared
    with Engine(root, weights, PROFILE, factory=load_fake) as engine:
        request = request_for(root, digest, value=value)
        with pytest.raises(MatteError) as error:
            engine.run(request)
        code_is(error, code)
        assert sorted(item.name for item in (root / request["attempt_id"]).iterdir()) == ["input"]


def test_hard_deadline_busy_reap_and_replacement(prepared):
    root, weights, digest = prepared
    started = multiprocessing.get_context("spawn").Event()
    factory = partial(load_blocking_matte, started=started)
    with Engine(root, weights, PROFILE, factory=factory, request_seconds=1.5) as engine:
        original = engine._child.process.pid
        first = request_for(root, digest, value=77)
        second = request_for(root, digest)
        with ThreadPoolExecutor(max_workers=1) as executor:
            begun = monotonic()
            pending = executor.submit(engine.run, first)
            assert started.wait(3)
            with pytest.raises(MatteError) as occupied:
                engine.run(second)
            code_is(occupied, BUSY)
            with pytest.raises(MatteError) as timeout:
                pending.result(timeout=6)
            code_is(timeout, TIMEOUT)
            assert monotonic() - begun <= 3.5
        with pytest.raises(ChildProcessError):
            os.waitpid(original, os.WNOHANG)
        assert list((root / first["attempt_id"]).iterdir()) == [root / first["attempt_id"] / "input"]
        engine._recovery.join(timeout=10)
        assert engine.readiness is not None
        assert engine._child.process.pid != original
        assert engine.run(second)["shape"]["bbox_height_px"] == 32


@pytest.mark.parametrize(("name", "code"), [
    ("profile.sha256", PIN_MISMATCH), ("profile.json", PIN_MISMATCH),
    (GRAPH_NAME, PIN_MISMATCH), ("missing", NOT_FOUND),
])
def test_startup_pins(prepared, name, code):
    root, weights, _ = prepared
    if name == "missing":
        (weights / GRAPH_NAME).unlink()
    else:
        path = weights / name
        # Preserve the byte count so the digest independently proves identity.
        path.write_bytes(path.read_bytes().replace(b"f", b"e", 1) if name != GRAPH_NAME
                         else b"!" + GRAPH[1:])
    with pytest.raises(MatteError) as error:
        Engine(root, weights, PROFILE, factory=load_fake)
    code_is(error, code)


def test_graph_byte_count_does_not_follow_the_digest_alone(prepared):
    root, weights, _ = prepared
    profile = replace(PROFILE, graph_bytes=len(GRAPH) + 1)
    manifest = profile.manifest()
    (weights / "profile.json").write_bytes(manifest)
    (weights / "profile.sha256").write_text(hashlib.sha256(manifest).hexdigest() + "\n")
    with pytest.raises(MatteError) as error:
        Engine(root, weights, profile, factory=load_fake)
    code_is(error, PIN_MISMATCH)


@pytest.mark.parametrize("change", [
    "digest", "bytes", "size", "type", "profile", "profile-id", "symlink", "hardlink", "fifo", "attempt-link",
])
def test_staged_input_refusals(prepared, change):
    root, weights, digest = prepared
    value = request_for(root, digest)
    directory = root / value["attempt_id"]
    source = value["request"]["source"]
    path = directory / "input"
    if change == "digest":
        source["sha256"] = "0" * 64
    elif change == "bytes":
        source["bytes"] += 1
    elif change == "size":
        source["height"] = 65
    elif change == "type":
        source["media_type"] = "image/jpeg"
    elif change == "profile":
        value["request"]["profile_sha256"] = "0" * 64
    elif change == "profile-id":
        value["request"]["profile_id"] = "bria-rmbg-1.4-ort-cpu-v1"
    elif change == "attempt-link":
        directory.rename(root / "outside")
        directory.symlink_to(root / "outside", target_is_directory=True)
    else:
        path.rename(root / "original")
        if change == "symlink":
            path.symlink_to(root / "original")
        elif change == "hardlink":
            path.hardlink_to(root / "original")
        else:
            os.mkfifo(path)
    with Engine(root, weights, PROFILE, factory=load_fake) as engine:
        with pytest.raises(MatteError) as error:
            engine.run(value)
        code_is(error, PIN_MISMATCH if change.startswith("profile") else REQUEST_INVALID)
        assert {item.name for item in directory.iterdir()} == {"input"}


def test_envelope_rejects_path_wrong_id_and_fractional_dimensions(prepared):
    root, _, digest = prepared
    good = request_for(root, digest)
    assert envelope(good) == (good["attempt_id"], good["request"])
    for changed in (
        {**good, "attempt_id": "../" + good["attempt_id"]},
        {**good, "request": {**good["request"], "job_id": good["request"]["source"]["asset_version_id"]}},
        {**good, "request": {**good["request"], "graph_url": "https://example.invalid"}},
        {**good, "request": {**good["request"], "source": {**good["request"]["source"], "width": 64.0}}},
    ):
        with pytest.raises(MatteError) as error:
            envelope(changed)
        code_is(error, REQUEST_INVALID)


@pytest.mark.parametrize("kind", ["jpeg", "png", "rgba", "transparency", "icc", "orientation", "animation", "truncated"])
def test_source_decoding(kind):
    image = Image.new("RGBA" if kind == "rgba" else "RGB", (64, 64))
    options = {}
    if kind == "icc":
        options["icc_profile"] = b"ICC fixture"
    elif kind == "orientation":
        exif = Image.Exif()
        exif[274] = 6
        options["exif"] = exif
    elif kind == "animation":
        options.update(save_all=True, append_images=[Image.new("RGB", (64, 64), "white")])
    elif kind == "transparency":
        options["transparency"] = (0, 0, 0)
    jpeg = kind in ("jpeg", "orientation", "truncated")
    buffer = BytesIO()
    image.save(buffer, "JPEG" if jpeg else "PNG", **options)
    data = buffer.getvalue()
    if kind == "truncated":
        data = data[:-30]
    source = {
        "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
        "media_type": "image/jpeg" if jpeg else "image/png", "width": 64, "height": 64,
    }
    if kind in ("jpeg", "png"):
        assert decode_source(data, source).mode == "RGB"
    else:
        with pytest.raises(MatteError) as error:
            decode_source(data, source)
        code_is(error, REQUEST_INVALID)


def test_alpha_rounding_and_no_chroma():
    image = Image.new("RGB", (DIM, DIM), (36, 180, 60))
    alpha = np.zeros((DIM, DIM), dtype=np.float32)
    alpha[0, :8] = [-5, 0, 0.0019, 0.002, 0.4999, 0.5, 1.1, 12 / 255]
    rgba = matte_pixels(image, alpha, None)
    assert rgba[0, :8, 3].tolist() == [0, 0, 0, 1, 127, 128, 255, 12]
    assert not rgba[0, :3, :3].any()
    assert np.all(rgba[0, 3:8, :3] == GREEN)
    with pytest.raises(MatteError) as error:
        matte_pixels(image, alpha[:10], None)
    code_is(error, RESPONSE_INVALID)


def test_euclidean_chroma_rules():
    alpha = np.zeros((DIM, DIM), dtype=np.float32)
    alpha[30:80, 30:80] = 255
    rgb = np.broadcast_to(np.asarray(GREEN, dtype=np.uint8), (DIM, DIM, 3)).copy()
    # More than four pixels inside belongs to the foreground even if translucent.
    alpha[40, 40] = alpha[30, 40] = alpha[33, 40] = 128
    alpha[100, 100] = 243
    rgb[40, 40] = rgb[30, 40] = rgb[33, 40] = rgb[100, 100] = [55, 140, 55]
    # Closest below-threshold pixel is exactly four pixels away at [33, 40].
    alpha[122, 120] = alpha[122, 121] = alpha[122, 122] = 12
    rgb[122, 121] = np.asarray(GREEN) + [2, 2, 1]  # Euclidean distance 3
    rgb[122, 122] = np.asarray(GREEN) + [2, 2, 2]  # distance sqrt(12)
    alpha[21, 50] = 64  # exactly eight pixels beyond the silhouette boundary
    backing = linear_srgb(np.asarray(GREEN))
    rgb[21, 50] = srgb_bytes((64 / 255) * linear_srgb(np.repeat(128, 3)) + (191 / 255) * backing)
    rgba = matte_pixels(Image.fromarray(rgb), alpha / 255, list(GREEN))
    assert rgba[40, 40].tolist() == [55, 140, 55, 128]
    assert rgba[100, 100].tolist() == [55, 140, 55, 243]
    assert not np.array_equal(rgba[30, 40, :3], rgb[30, 40])
    assert not np.array_equal(rgba[33, 40, :3], rgb[33, 40])
    assert rgba[122, 120].tolist() == rgba[122, 121].tolist() == [0, 0, 0, 0]
    assert rgba[122, 122, 3] == 12
    expected = srgb_bytes((linear_srgb(rgb[122, 122]) - (234 / 255) * backing) / (21 / 255))
    np.testing.assert_array_equal(rgba[122, 122, :3], expected)
    assert rgba[21, 50, 3] == 64
    assert np.max(np.abs(rgba[21, 50, :3].astype(int) - 128)) <= 3


@pytest.mark.parametrize("imperfect", [False, True])
def test_synthetic_smoke_with_fixed_matte(prepared, imperfect, monkeypatch):
    root, weights, digest = prepared
    # The engine stages pixels under tmp_path, while the short socket is separate.
    from haynes_studio.matting import smoke
    with tempfile.TemporaryDirectory(prefix="matte-") as directory, Engine(
        root, weights, PROFILE, factory=partial(load_fixtures, imperfect=imperfect),
    ) as engine:
        path = Path(directory) / "matte.sock"
        monkeypatch.setattr(smoke, "local_call", lambda _, *args: local_call(path, *args))
        report = {"scores": {}, "verdicts": {}, "inferences": {}}
        with listening(path, engine):
            _check_fixtures(root, PROFILE, digest, report)
    assert all(report["verdicts"].values())
    assert len(report["inferences"]) == 4
    metrics = report["scores"]
    assert metrics["green_eyes"]["left_coverage"]["passed"] is not imperfect
    assert metrics["shape_fringe"]["strand_mae"]["passed"] is not imperfect
    if not imperfect:
        assert all(metric["passed"] for group in metrics.values() for metric in group.values())


def test_each_eye_lash_and_scale_score_is_independent():
    green = bust(green=True)
    ideal = np.dstack((green.rgb, green.alpha))
    assert all(item["passed"] for item in score_eyes(green, ideal).values())
    altered = ideal.copy()
    altered[green.irises[1] == 255, 0] += 1
    assert not score_eyes(green, altered)["right_rgb_error"]["passed"]
    for index, side in enumerate(("left", "right")):
        alpha = green.alpha.copy()
        alpha[green.lashes[index] == 255] = 0
        assert not score_shape(green, alpha)["lash_" + side]["passed"]
    truth = measure_shape(green.alpha, None)
    small = bust(smaller=True)
    small_truth = measure_shape(small.alpha, truth["bbox_height_px"])
    assert all(item["passed"] for item in score_size(truth, truth, small_truth, small_truth).values())
    bad_shape = copy.deepcopy(small_truth)
    bad_shape["scale"]["numerator"] += 50
    bad_shape["bbox_xyxy"][0] += 4
    scores = score_size(truth, truth, small_truth, bad_shape)
    assert not scores["small_height_error_px"]["passed"]
    assert not scores["small_bounds_error_px"]["passed"]
    assert not scores["scale_ratio_relative_error"]["passed"]


def test_structural_result_guards(prepared):
    root, weights, digest = prepared
    value = request_for(root, digest)
    with Engine(root, weights, PROFILE, factory=load_fake) as engine:
        result = engine.run(value)
    request = value["request"]
    output = artifacts(root, value)
    verify_result(request, result, output, PROFILE)
    for change in ("profile", "signature", "shape", "artifact", "different_alpha", "wrong_mode",
                   "rgb_at_zero", "trailing_data"):
        altered, files = copy.deepcopy(result), dict(output)
        if change == "profile":
            altered["provenance"]["parameters"]["libraries"]["numpy"] = "0"
        elif change == "signature":
            altered["input_signature"] = "sha256:" + "0" * 64
        elif change == "shape":
            altered["shape"]["bbox_xyxy"][1] += 1
        elif change == "artifact":
            altered["artifacts"]["cutout"]["bytes"] += 1
        elif change == "trailing_data":
            files["cutout"] += b"trailing"
            altered["artifacts"]["cutout"].update(
                bytes=len(files["cutout"]), sha256=hashlib.sha256(files["cutout"]).hexdigest(),
            )
        else:
            name = "mask" if change == "different_alpha" else "cutout"
            pixels = np.array(Image.open(BytesIO(files[name])))
            pixels[0, 0] = 1
            if change == "wrong_mode":
                pixels = pixels[..., :3]
            elif change == "rgb_at_zero":
                pixels[0, 0, 3] = 0
            files[name] = encode_png(pixels)
            altered["artifacts"][name].update(bytes=len(files[name]), sha256=hashlib.sha256(files[name]).hexdigest())
        with pytest.raises(MatteError) as error:
            verify_result(request, altered, files, PROFILE)
        code_is(error, RESPONSE_INVALID)


def test_reference_examples():
    root = Path(__file__).resolve().parents[2] / "docs" / "reference" / "matting-examples"
    request = read_json(root / "request.json").document
    receipt = read_json(root / "result.json").document
    validator_for(REQUEST_SCHEMA).validate(request)
    validator_for(RESULT_SCHEMA).validate(receipt)
    assert receipt["input_signature"] == input_signature(request)


def test_png_write_is_create_only(tmp_path):
    png = tmp_path / "cutout.png"
    png.write_bytes(b"original")
    directory = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(FileExistsError):
            _write_png(directory, png.name, b"replacement")
    finally:
        os.close(directory)
    assert png.read_bytes() == b"original"


def test_staged_input_is_regular_before_reading(tmp_path):
    os.mkfifo(tmp_path / "input")
    directory = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(MatteError) as error:
            _read_file(directory, "input", 100, REQUEST_INVALID)
    finally:
        os.close(directory)
    code_is(error, REQUEST_INVALID)


def test_unmixed_rgb_rounds_to_nearest_byte():
    assert srgb_bytes(linear_srgb(np.asarray([128.75]))).tolist() == [129]
