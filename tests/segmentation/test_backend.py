"""Contract guards under deterministic CPU-only fakes."""

from __future__ import annotations

import multiprocessing
import os
import signal
import subprocess
import sys
import threading
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from functools import partial
from importlib.resources import files
from io import BytesIO
from json import loads
from pathlib import Path
from time import monotonic, sleep
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from haynes_studio.schemas import validator_for
from haynes_studio.segmentation import __main__ as cli
from haynes_studio.segmentation import backend, memory, smoke
from haynes_studio.segmentation.backend import Engine
from haynes_studio.segmentation.fixtures import Fixture, fixtures, visible_fraction
from haynes_studio.segmentation.inference import (
    Candidate, Grounding, Observation, observe, select_boxes, validate_request,
)
from haynes_studio.segmentation.pixels import decode_source, describe_mask, encode_mask, tight_box
from haynes_studio.segmentation.profile import (
    FALLBACK_ID, PROFILE_ID, SERVING_PROFILE_ID, Profile, SegmentationError, digest,
)
from haynes_studio.segmentation.service import _UnixConnection, listening, local_call
from haynes_studio.segmentation.smoke import stage
from haynes_studio.store import canonical_json


class TinyProfile(Profile):
    def model_files(self):
        return tuple({
            "directory": name, "repository": f"synthetic/{name}", "revision": "0" * 40,
            "files": [
                {"name": "model.safetensors", "size_bytes": 4, "sha256": digest(b"fake")},
                {"name": "config.json", "size_bytes": 2, "sha256": digest(b"{}")},
            ],
        } for name in ("dino", "sam"))


@pytest.fixture
def pins(tmp_path):
    profile = TinyProfile("sha256:" + "c" * 64, "d" * 40, "e" * 64, (("synthetic", "1"),))
    path = tmp_path / "weights"
    path.mkdir()
    manifest = profile.manifest()
    (path / "profile.json").write_bytes(manifest)
    (path / "profile.sha256").write_text(digest(manifest) + "\n")
    for model in profile.model_files():
        directory = path / model["directory"]
        directory.mkdir()
        (directory / "model.safetensors").write_bytes(b"fake")
        (directory / "config.json").write_bytes(b"{}")
    return profile, path


def _box(box=(10, 10, 35, 35), score=0.9, phrase="prop"):
    return Candidate(box, score, phrase)


def _synthetic_detector(image, prompt):
    return Grounding([_box()], image.size, image.size)


def _synthetic_segmenter(image, hint):
    logits = np.full((1, image.height, image.width), -1.0, dtype=np.float32)
    logits[:, 10:35, 10:35] = 1.0
    return logits, [0.9]


def _factory(weights, phase, strategy):
    return _synthetic_detector, _synthetic_segmenter


def _stalling_factory(weights, phase, strategy, *, started):
    def segmenter(image, hint):
        if hint["kind"] == "point":
            started.set()
            threading.Event().wait()
        return _synthetic_segmenter(image, hint)
    return _synthetic_detector, segmenter


@pytest.fixture
def example():
    image = Image.new("RGB", (64, 48), (100, 110, 120))
    return Fixture(image, np.zeros((48, 64), dtype=bool), "prop", "orange ball", None)


def _measure(image, request, detector=_synthetic_detector, segmenter=_synthetic_segmenter, alpha=None):
    obs = Observation()
    reason, mask = observe(image, alpha, request, detector, segmenter, obs, lambda _: nullcontext())
    return obs, reason, mask


@pytest.mark.parametrize(("field", "value"), [
    ("source_extra", "outside"), ("hint", {"kind": "box", "xyxy": [0, 0, 5, 5], "path": "x"}),
    ("hint", {"kind": "point", "xy": [64, 47]}),
    ("hint", {"kind": "point", "xy": [1.0, 2]}),
    ("hint", {"kind": "point", "xy": [True, 2]}),
    ("hint", {"kind": "box", "xyxy": [0, 0, 0, 7]}),
    ("hint", {"kind": "box", "xyxy": [0, 0, 65, 7]}),
    ("hint", {"kind": "text", "text": " orange ball"}),
    ("hint", {"kind": "text", "text": "e\u0301"}),
    ("hint", {"kind": "text", "text": "a" * 81}),
    ("hint", {"kind": "text", "text": "x\udcff"}),
    ("width", 64.0), ("width", 31), ("height", 1921), ("both_large", None),
    ("sha256", "f" * 64 + "\n"), ("sha256", "A" * 64),
    ("label", None), ("key", ".hidden"), ("key", "prop\n"),
])
def test_request_guards(example, field, value):
    _, request = example.request("prop")
    if field == "both_large":
        request["input"].update(width=1920, height=1081)
    elif field == "source_extra":
        request["input"]["path"] = value
    else:
        group = ("input" if field in request["input"] else "target" if field in request["target"] else None)
        (request[group] if group else request)[field] = value
    with pytest.raises(SegmentationError, match="invalid_input"):
        validate_request(request)


@pytest.mark.parametrize("mutation", ["animated", "orientation", "type", "digest", "dimensions", "bytes"])
def test_source_guards(example, mutation):
    data, request = example.request("prop")
    facts = request["input"]
    buffer = BytesIO()
    if mutation == "animated":
        example.image.save(buffer, "PNG", save_all=True, append_images=[Image.new("RGB", example.image.size)])
    if mutation == "orientation":
        exif = Image.Exif()
        exif[274] = 6
        example.image.save(buffer, "JPEG", exif=exif)
    if mutation == "type":
        example.image.save(buffer, "BMP")
    if mutation == "bytes":
        buffer.write(data + bytes(8 * 1024**2))
    if buffer.tell():
        data = buffer.getvalue()
        facts["sha256"] = digest(data)
    if mutation == "digest":
        facts["sha256"] = "f" * 64
    if mutation == "dimensions":
        facts["width"] -= 1
    with pytest.raises(SegmentationError, match="invalid_input"):
        decode_source(data, facts)


@pytest.mark.parametrize("format", ["PNG", "JPEG", "WEBP"])
def test_valid_sources(example, format):
    buffer = BytesIO()
    example.image.save(buffer, format)
    data = buffer.getvalue()
    _, request = example.request("prop")
    request["input"]["sha256"] = digest(data)
    image, alpha = decode_source(data, request["input"])
    assert image.mode == "RGB" and image.size == example.image.size and alpha is None


@pytest.mark.parametrize(("candidates", "reason"), [
    ([_box(score=0.349)], "no_match"),
    ([_box(phrase=".")], "no_match"),
    ([_box((64, 5, 85, 30))], "no_match"),
    ([_box(), _box((40, 10, 64, 35), 0.81)], "ambiguous_match"),
    ([_box((0, 5, 15.9, 30))], "too_small"),
])
def test_grounding_uncertainty(example, candidates, reason):
    _, request = example.request("prop")
    obs, outcome, mask = _measure(
        example.image, request, lambda image, _: Grounding(candidates, image.size, (100, 100)),
        lambda *_: pytest.fail("ambiguous grounding must not invoke SAM"),
    )
    assert (outcome, mask, obs.executed) == (reason, None, ["dino"])


def test_grounding_compares_against_runner_up(example):
    _, request = example.request("prop")
    candidates = [_box(), _box((40, 10, 64, 35), 0.86), _box((10, 30, 35, 48), 0.55)]
    grounding = Grounding(candidates, example.image.size, example.image.size)
    assert len(select_boxes(grounding)) == 3
    obs, reason, mask = _measure(example.image, request, lambda *_: grounding)
    assert (reason, mask, obs.executed) == ("ambiguous_match", None, ["dino"])


@pytest.mark.parametrize(("runner_up", "reason"), [(0.79, None), (0.81, "ambiguous_match")])
def test_grounding_requires_score_lead(example, runner_up, reason):
    _, request = example.request("prop")
    grounding = Grounding(
        [_box(), _box((40, 10, 64, 35), runner_up)], example.image.size, example.image.size,
    )
    _, outcome, mask = _measure(example.image, request, lambda *_: grounding)
    assert outcome == reason
    if reason is None:
        assert tight_box(mask) == [10, 10, 35, 35]
    else:
        assert mask is None


def test_nms_and_projection(example):
    candidates = [_box((-2, 6.2, 22.2, 23.6)), _box((0, 6, 22, 23), 0.88)]
    grounding = Grounding(candidates, (128, 96), (128, 96))
    assert len(select_boxes(grounding)) == 1
    _, request = example.request("prop")
    obs, reason, _ = _measure(example.image, request, lambda *_: grounding)
    assert reason is None
    assert obs.detector_box == [0, 3, 12, 12]
    assert obs.applied["detector_resize_wh"] == [128, 96]


def test_default_and_override_queries(example):
    _, request = example.request("prop")
    assert _measure(example.image, request)[0].applied["prompt"] == "orange ball."
    request["target"].update(kind="face", label=None)
    assert _measure(example.image, request)[0].applied["prompt"] == "doll face."
    request["target"]["kind"] = "foreground"
    obs, reason, _ = _measure(example.image, request)
    assert (obs.applied["prompt"], reason) == ("table. lectern. chair back.", "foreground_depth_ambiguous")
    request["hint"] = {"kind": "text", "text": "Near Oak Table."}
    assert _measure(example.image, request)[0].applied["prompt"] == "near oak table."


@pytest.mark.parametrize("hint", [{"kind": "point", "xy": [12, 12]}, {"kind": "box", "xyxy": [0, 0, 64, 48]}])
def test_direct_hints_bypass_detector(example, hint):
    _, request = example.request("prop")
    request["hint"] = hint
    obs, reason, mask = _measure(example.image, request, lambda *_: pytest.fail("must bypass detector"))
    assert reason is None and tight_box(mask) == [10, 10, 35, 35]
    assert obs.executed == ["sam"] and obs.detector_box is obs.detector_score is None


@pytest.mark.parametrize("mutation", ["low", "nonfinite_scores", "disagree", "empty", "full", "point", "alpha"])
def test_uncertain_masks(example, mutation):
    _, request = example.request("prop")
    logits, scores = _synthetic_segmenter(example.image, {})
    alpha = None
    if mutation == "disagree":
        scores.append(0.88)
        logits = np.concatenate([logits, np.roll(logits, 25, axis=2)])
    if mutation == "low":
        scores[0] = 0.79
    if mutation == "nonfinite_scores":
        scores[0] = float("nan")
    if mutation == "empty":
        logits[:] = 0
    if mutation == "full":
        logits[:] = 1
    if mutation == "point":
        request["hint"] = {"kind": "point", "xy": [0, 0]}
    if mutation == "alpha":
        alpha = np.zeros(logits.shape[1:], dtype=bool)
    _, reason, mask = _measure(example.image, request, segmenter=lambda *_: (logits, scores), alpha=alpha)
    assert (reason, mask) == ("mask_uncertain", None)


def test_highest_finite_agreeing_mask(example):
    _, request = example.request("prop")
    logits, _ = _synthetic_segmenter(example.image, {})
    _, reason, mask = _measure(example.image, request, segmenter=lambda *_: (
        np.concatenate([-logits, logits, logits]), [float("nan"), 0.80, 0.83],
    ))
    assert reason is None and tight_box(mask) == [10, 10, 35, 35]


def test_rgba_against_gray_and_nonzero_alpha(example):
    source = Image.new("RGBA", example.image.size)
    source.putpixel((11, 15), (250, 250, 250, 1))
    fixture = replace(example, image=source)
    data, request = fixture.request("prop")
    image, alpha = decode_source(data, request["input"])
    assert image.getpixel((0, 0)) == (128, 128, 128)
    assert alpha.sum() == 1
    _, reason, mask = _measure(image, request, alpha=alpha)
    assert reason is None and tight_box(mask) == [11, 15, 12, 16]


def test_competing_masks_agree_on_nontransparent_pixels(example):
    _, request = example.request("prop")
    best, _ = _synthetic_segmenter(example.image, {})
    alpha = best[0] > 0
    other = best.copy()
    other[:, :10, :] = 1.0
    _, reason, mask = _measure(
        example.image, request, segmenter=lambda *_: (np.concatenate([best, other]), [0.90, 0.88]), alpha=alpha,
    )
    assert reason is None and np.array_equal(mask, alpha)


@pytest.mark.parametrize("mutation", ["width", "logit", "score_count"])
def test_invalid_segmenter_output(example, mutation):
    _, request = example.request("prop")
    logits, scores = _synthetic_segmenter(example.image, {})
    if mutation == "width":
        logits = logits[..., :-1]
    if mutation == "logit":
        logits[0, 0, 0] = float("nan")
    if mutation == "score_count":
        scores.append(0.9)
    with pytest.raises(SegmentationError, match="invalid_output"):
        _measure(example.image, request, segmenter=lambda *_: (logits, scores))


@pytest.mark.parametrize("mutation", ["size", "binary", "metadata"])
def test_mask_png_guards(example, mutation):
    logits, _ = _synthetic_segmenter(example.image, {})
    mask = logits[0] > 0
    if mutation == "size":
        # The incorrectly sized file has a perfectly valid digest of its own.
        png = encode_mask(mask[:, :-1])
        assert len(digest(png)) == 64
    else:
        from PIL.PngImagePlugin import PngInfo

        pixels = mask.astype(np.uint8) * 255
        metadata = PngInfo()
        if mutation == "metadata":
            metadata.add_text("source", "fixture")
        else:
            pixels[0, 0] = 128
        buffer = BytesIO()
        Image.fromarray(pixels).save(buffer, "PNG", pnginfo=metadata)
        png = buffer.getvalue()
    with pytest.raises(SegmentationError, match="invalid_output"):
        describe_mask(png, example.image.size)


def test_full_size_truth_fixtures():
    suite = fixtures()
    masks = {}
    for name in ("foreground", "visible_face", "hidden_prop", "point"):
        fixture = suite[name]
        data, request = fixture.request(name)
        image, alpha = decode_source(data, request["input"])
        obs, reason, mask = _measure(image, request, segmenter=lambda *_: (
            np.where(fixture.truth, 1, -1)[None, ...].astype(np.float32), [0.98],
        ), alpha=alpha)
        assert obs.executed == ["sam"] and reason is None and np.array_equal(mask, fixture.truth)
        masks[name] = mask
    assert masks["foreground"].sum() == 1020934
    assert masks["visible_face"].sum() == masks["hidden_prop"].sum() == 15373
    assert visible_fraction(masks["visible_face"], masks["foreground"]) == 1
    # The same fully occluded marker can represent a hidden cast slot.
    hidden_face = replace(suite["hidden_prop"], kind="face", label=None)
    data, hidden_request = hidden_face.request("hidden_face")
    validate_request(hidden_request)
    image, alpha = decode_source(data, hidden_request["input"])
    _, reason, mask = _measure(image, hidden_request, segmenter=lambda *_: (
        np.where(hidden_face.truth, 1, -1)[None, ...].astype(np.float32), [0.98],
    ), alpha=alpha)
    assert reason is None and np.array_equal(mask, hidden_face.truth)
    assert visible_fraction(mask, masks["foreground"]) == 0


@pytest.mark.parametrize("mutation", ["manifest", "pin", "dino", "sam", "config", "extra", "symlink"])
def test_weight_profile_guards(pins, mutation):
    profile, weights = pins
    if mutation == "manifest":
        (weights / "profile.json").write_bytes(replace(profile, revision="a" * 40).manifest())
    elif mutation == "pin":
        (weights / "profile.sha256").write_text("a" * 64 + "\n")
    elif mutation in ("dino", "sam"):
        (weights / mutation / "model.safetensors").write_bytes(b"else")
    elif mutation == "config":
        (weights / "dino/config.json").write_bytes(b"[]")
    elif mutation == "extra":
        (weights / "sam/other.safetensors").touch()
    else:
        path = weights / "sam/config.json"
        path.unlink()
        path.symlink_to("../dino/config.json")
    with pytest.raises(SegmentationError, match="profile_unavailable"):
        profile.verify(weights)


def test_socket_create_only(tmp_path, pins, example):
    profile, weights = pins
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    socket_path = scratch / "s"
    data, request = example.request("prop")
    payload = stage(scratch, data, request)
    with Engine(scratch, weights, profile, factory=_factory) as engine, listening(socket_path, engine):
        assert socket_path.stat().st_mode & 0o777 == 0o660
        assert local_call(socket_path, "GET", "/v1/ready") == (200, {
            "profile_id": PROFILE_ID, "profile_sha256": digest(profile.manifest()), "device": "cpu",
        })
        assert loads(profile.manifest())["profile"] == SERVING_PROFILE_ID
        status, reply = local_call(socket_path, "POST", "/v1/segment", payload)
        assert status == 200 and reply["result"]["status"] == "ready"
        directory = scratch / payload["attempt_id"]
        receipt = (directory / "result.json").read_bytes()
        png = (directory / "mask.png").read_bytes()
        assert receipt == canonical_json(reply["result"])
        assert digest(receipt) == reply["result_sha256"]
        assert digest(png) == reply["result"]["mask"]["sha256"]
        assert reply["result"]["box_xyxy"] == [10, 10, 35, 35]
        assert local_call(socket_path, "POST", "/v1/segment", payload)[0] == 400
        assert (directory / "result.json").read_bytes() == receipt
        assert (directory / "mask.png").read_bytes() == png
        fresh = stage(scratch, data, request)
        assert local_call(socket_path, "POST", "/v1/segment", fresh) == (200, reply)
        connection = _UnixConnection(socket_path, 3)
        try:
            connection.request("POST", "/v1/segment", body=b" " * 5000,
                               headers={"Content-Type": "application/json"})
            assert connection.getresponse().status == 400
        finally:
            connection.close()
    assert not socket_path.exists()


@pytest.mark.parametrize("mutation", [None, "hash", "selector", "extra_key"])
def test_ready_command_checks_exact_model_selector_and_manifest(pins, monkeypatch, mutation):
    profile, _ = pins
    reply = {"profile_id": PROFILE_ID, "profile_sha256": digest(profile.manifest()), "device": "cpu"}
    if mutation == "hash":
        reply["profile_sha256"] = "f" * 64
    elif mutation == "selector":
        reply["profile_id"] = SERVING_PROFILE_ID
    elif mutation == "extra_key":
        reply["serving_profile_id"] = SERVING_PROFILE_ID
    monkeypatch.setattr(Profile, "installed", lambda: profile)
    monkeypatch.setattr("haynes_studio.segmentation.service.local_call", lambda *_, **__: (200, reply))
    monkeypatch.setattr(sys, "argv", ["studio-segmentation", "ready"])
    assert cli.main() == int(mutation is not None)


@pytest.mark.parametrize("mutation", ["symlink", "hardlink", "fifo", "missing", "fallback", "digest"])
def test_artifact_refusals(tmp_path, pins, example, mutation):
    profile, weights = pins
    data, request = example.request("prop")
    payload = stage(tmp_path, data, request)
    directory = tmp_path / payload["attempt_id"]
    source = directory / "input"
    if mutation in ("symlink", "hardlink", "fifo", "missing"):
        source.unlink()
    if mutation in ("symlink", "hardlink"):
        external = tmp_path / "outside"
        external.write_bytes(data)
        if mutation == "symlink":
            source.symlink_to(external)
        else:
            os.link(external, source)
    if mutation == "fifo":
        os.mkfifo(source)
    if mutation == "fallback":
        request["profile"] = FALLBACK_ID
    if mutation == "digest":
        request["input"]["sha256"] = "f" * 64
    with Engine(tmp_path, weights, profile, factory=_factory) as engine:
        result = engine.run(payload)
    assert result["status"] == "failed" and result["box_xyxy"] is result["mask"] is None
    expected = {"fallback": "profile_unavailable", "missing": "input_unavailable"}
    assert result["reason"] == expected.get(mutation, "invalid_input")
    assert not (directory / "mask.png").exists()
    if mutation != "missing":
        assert (directory / "result.json").read_bytes() == canonical_json(result)


def test_busy_timeout_reap(tmp_path, pins, example):
    profile, weights = pins
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    started = multiprocessing.get_context("spawn").Event()
    data, request = example.request("prop")
    stalled = stage(scratch, data, {**request, "hint": {"kind": "point", "xy": [12, 12]}})
    socket_path = scratch / "s"
    replies = []
    factory = partial(_stalling_factory, started=started)
    with Engine(scratch, weights, profile, factory=factory, request_seconds=2) as engine:
        original_pid = engine._child.process.pid
        with listening(socket_path, engine):
            def first_call():
                replies.append(local_call(socket_path, "POST", "/v1/segment", stalled, timeout=5))

            thread = threading.Thread(target=first_call)
            thread.start()
            try:
                assert started.wait(1)
                good = stage(scratch, data, request)
                assert local_call(socket_path, "POST", "/v1/segment", good) == (409, {"code": "busy"})
            finally:
                thread.join()
            [(status, reply)] = replies
            assert status == 504 and reply["result"]["reason"] == "timeout"
            with pytest.raises(ProcessLookupError):
                os.kill(original_pid, 0)
            engine._recovery.join(timeout=5)
            assert engine.readiness and engine._child.process.pid != original_pid
            assert local_call(socket_path, "POST", "/v1/segment", good)[0] == 200



def _terminating_factory(weights, phase, strategy, *, timeout):
    def segmenter(image, hint):
        os.kill(os.getppid(), signal.SIGTERM)
        if timeout:
            threading.Event().wait()
        return _synthetic_segmenter(image, hint)
    return _synthetic_detector, segmenter


def _serve_offline():
    scratch, weights, outcome = sys.argv[1:]
    cli.SCRATCH, cli.WEIGHTS = Path(scratch), Path(weights)
    Profile.installed = lambda: TinyProfile("sha256:" + "c" * 64, "d" * 40, "e" * 64, (("synthetic", "1"),))
    factory = partial(_terminating_factory, timeout=outcome == "timeout")
    backend.Engine = partial(Engine, factory=factory, request_seconds=2)
    cli._serve()


@pytest.mark.parametrize("outcome", ["complete", "timeout"])
def test_sigterm_drains_request_then_refuses_connections(tmp_path, pins, example, outcome):
    _, weights = pins
    socket_path = tmp_path / "segment.sock"
    data, request = example.request("prop")
    payload = stage(tmp_path, data, request)
    with subprocess.Popen(
        [sys.executable, "-c", "from tests.segmentation.test_backend import _serve_offline; _serve_offline()",
         str(tmp_path), str(weights), outcome],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    ) as process:
        try:
            deadline = monotonic() + 10
            while not socket_path.is_socket() and process.poll() is None and monotonic() < deadline:
                sleep(0.025)
            status, reply = local_call(socket_path, "POST", "/v1/segment", payload, timeout=5)
            output, _ = process.communicate(timeout=5)
            assert process.returncode == 0, output
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
    directory = tmp_path / payload["attempt_id"]
    receipt = reply["result"]
    assert canonical_json(receipt) == (directory / "result.json").read_bytes()
    assert reply["result_sha256"] == digest(canonical_json(receipt))
    if outcome == "timeout":
        assert (status, receipt["status"], receipt["reason"], receipt["mask"]) == (504, "failed", "timeout", None)
        assert not (directory / "mask.png").exists()
    else:
        assert status == 200 and receipt["status"] == "ready"
        assert digest((directory / "mask.png").read_bytes()) == receipt["mask"]["sha256"]
    with pytest.raises((ConnectionRefusedError, FileNotFoundError)):
        local_call(socket_path, "GET", "/v1/ready")


def test_slow_receipt_never_returns_ready(tmp_path, pins, example, monkeypatch):
    profile, weights = pins
    data, request = example.request("prop")
    payload = stage(tmp_path, data, request)
    with Engine(tmp_path, weights, profile, factory=_factory) as engine:
        create_file = backend._create_file
        monotonic = backend.monotonic
        delay = 0

        def slow_commit(directory, name, data):
            nonlocal delay
            create_file(directory, name, data)
            delay = 61

        monkeypatch.setattr(backend, "_create_file", slow_commit)
        monkeypatch.setattr(backend, "monotonic", lambda: monotonic() + delay)
        receipt = engine.run(payload)
        assert (receipt["status"], receipt["reason"], receipt["mask"]) == ("failed", "timeout", None)
        staged = (tmp_path / payload["attempt_id"] / "result.json").read_bytes()
        assert digest(staged) != digest(canonical_json(receipt))


def test_smoke_stops_after_unexpected_visibility(tmp_path, pins, monkeypatch):
    profile, weights = pins
    observed = []

    def failed_visibility(scratch, weights, profile, strategy, inputs, report, *, repeat):
        observed.append(strategy)
        report["cases"] = {"foreground": {"status": "ready"}}
        report["verdicts"] = {"visibility": False}
        return {"foreground": (b"result", b"mask")}

    monkeypatch.setattr(Profile, "installed", lambda: profile)
    monkeypatch.setattr(smoke, "fixtures", lambda: {"foreground": object()})
    monkeypatch.setattr(smoke, "_smoke_run", failed_visibility)
    report = smoke.smoke(tmp_path, weights, ("mmap", "buffered"))
    assert observed == ["mmap"] and not report["passed"]


@pytest.fixture
def smoke_workload(pins, monkeypatch):
    profile, weights = pins

    def run(scratch, weights, profile, strategy, inputs, report, *, repeat):
        suffixes = ("", "_repeat", "_third") if repeat else ("",)
        report["cases"] = {f"foreground{suffix}": {"status": "ready"} for suffix in suffixes}
        report["verdicts"] = {"visibility": True}
        return {"foreground": (b"result", b"mask")}

    monkeypatch.setattr(Profile, "installed", lambda: profile)
    monkeypatch.setattr(smoke, "fixtures", lambda: {"foreground": object()})
    monkeypatch.setattr(smoke, "_smoke_run", run)
    monkeypatch.setattr(smoke.os, "geteuid", lambda: 10001)
    monkeypatch.setattr(smoke.os, "getegid", lambda: 10001)
    monkeypatch.setattr(smoke.os, "statvfs", lambda _: SimpleNamespace(f_flag=os.ST_RDONLY))
    monkeypatch.setattr(smoke, "cgroup_bytes", {"max": 16 * 1024**3, "peak": 8 * 1024**3}.get)
    return weights


def test_smoke_fails_when_buffered_output_changes_one_byte(tmp_path, smoke_workload, monkeypatch):
    run = smoke._smoke_run

    def changed_bytes(scratch, weights, profile, strategy, inputs, report, *, repeat):
        results = run(scratch, weights, profile, strategy, inputs, report, repeat=repeat)
        if strategy == "buffered":
            results["foreground"] = (b"result", b"masK")
        return results

    assert smoke.smoke(tmp_path, smoke_workload, ("mmap", "buffered"))["passed"]
    monkeypatch.setattr(smoke, "_smoke_run", changed_bytes)
    report = smoke.smoke(tmp_path, smoke_workload, ("mmap", "buffered"))
    assert report["verdicts"] == {
        "workload": True, "byte_parity": False, "cgroup_allowance": True,
        "all_strategies": True, "fixtures": True,
    }
    assert not report["passed"]


def test_smoke_rejects_writable_weights(tmp_path, smoke_workload, monkeypatch):
    monkeypatch.setattr(
        smoke.os, "statvfs", lambda path: SimpleNamespace(f_flag=0 if path == smoke_workload else os.ST_RDONLY),
    )
    report = smoke.smoke(tmp_path, smoke_workload, ("mmap", "buffered"))
    assert report["verdicts"]["workload"] is False
    assert not report["passed"]


@pytest.mark.parametrize(("strategies", "limit_gib", "passed"), [
    (("mmap", "buffered"), 15, False),
    (("mmap", "buffered"), 20, True),
    (("buffered",), 16, True),
    (("mmap",), 5, False),
    ((), 5, True),
    ((), 6, False),
])
def test_smoke_memory_allowance(tmp_path, smoke_workload, monkeypatch, strategies, limit_gib, passed):
    limit = limit_gib * 1024**3
    monkeypatch.setattr(smoke, "cgroup_bytes", {"max": limit, "peak": 4 * 1024**3}.get)
    report = smoke.smoke(tmp_path, smoke_workload, strategies)
    assert report["cgroup_limit_bytes"] == limit
    assert report["verdicts"]["cgroup_allowance"] is passed and report["passed"] is passed


def _saved_smoke_memory(run):
    fixture = Path(__file__).with_name("fixtures") / f"smoke-{run}-memory.json"
    return loads(fixture.read_text(encoding="utf-8"))


def test_serving_memory_stability_passes_run_04_that_failed_point_comparison():
    memory = _saved_smoke_memory("04")
    requests = memory["requests"]
    end = memory["passes"]["cgroup_resident_bytes"]
    passes = smoke._pass_memory(requests, 6, end)
    assert passes["max_resident_rss_bytes"] == [1678929920, 1679060992, 1686446080]
    assert passes["max_cgroup_resident_bytes"] == [1795072000, 1795846144, 1803661312]
    assert passes["cgroup_resident_bytes"] == [1795325952, 1795813376, 1774198784]
    assert smoke._memory_stable(passes)

    # Apply the former verdict to the same judged requests and phases.
    tolerance = 64 * 1024**2
    old_stable = end[2] <= end[1] + tolerance and all(
        first.keys() == second.keys() and all(
            second[phase][key] <= first[phase][key] + tolerance
            for phase in first for key in ("resident_rss_bytes", "cgroup_resident_bytes")
        )
        for first, second in zip(requests[6:12], requests[12:18], strict=True)
    )
    assert not old_stable


def test_serving_memory_stability_refuses_run_03_with_only_two_passes():
    memory = _saved_smoke_memory("03")
    requests = memory["requests"]
    end = memory["passes"]["cgroup_resident_bytes"]
    assert len(requests) == 12 and len(end) == 2
    assert not smoke._memory_stable(smoke._pass_memory(requests, 6, end))
    # Add a warm-up without changing either observed pass. The growth is within tolerance.
    assert smoke._memory_stable(smoke._pass_memory(requests[:6] + requests, 6, end[:1] + end))


@pytest.mark.parametrize("field", ["max_resident_rss_bytes", "max_cgroup_resident_bytes", "cgroup_resident_bytes"])
def test_serving_memory_stability_refuses_growth_above_tolerance(field):
    baseline = 1024**3
    passes = {
        "max_resident_rss_bytes": [baseline] * 3,
        "max_cgroup_resident_bytes": [baseline] * 3,
        "cgroup_resident_bytes": [baseline] * 3,
    }
    passes[field][2] += 64 * 1024**2
    assert smoke._memory_stable(passes)
    passes[field][2] += 1
    assert not smoke._memory_stable(passes)


@pytest.mark.parametrize("samples", [(512, 800, 800, 800, 800, 800), (800, 800, 800, 710, 710, 800)])
def test_serving_memory_stability_accepts_warmup_and_bidirectional_request_noise(samples):
    mib = 1024**2
    requests = [
        {"sam": {"resident_rss_bytes": value * mib, "cgroup_resident_bytes": (value + 32) * mib}}
        for value in samples
    ]
    passes = smoke._pass_memory(requests, 2, [832 * mib] * 3)
    assert smoke._memory_stable(passes)


class SmokeProfile(TinyProfile):
    def verify(self, root):
        memory.cgroup_bytes = lambda _: 512 * 1024**2
        return super().verify(root)


def _smoke_mask(image):
    red, green, _ = np.moveaxis(np.asarray(image, dtype=np.int16), -1, 0)
    return (red > green) | (green > red + 16)


def _smoke_factory(weights, phase, strategy, *, grow):
    # Keep a tracked resource alive until the worker exits, as a library can.
    semaphore = multiprocessing.get_context("spawn").Semaphore()
    for name in ("runtime_import", "load_dino", "load_sam"):
        with phase(name):
            pass

    mib = 1024**2
    resident = 512 * mib
    detector_used = False
    masks = 0

    class ModelPhases(memory.Phases):
        @contextmanager
        def __call__(self, name):
            with super().__call__(name):
                yield
            self.samples[name]["resident_rss_bytes"] = resident
            self.samples[name]["cgroup_resident_bytes"] = resident + 32 * mib

    backend.Phases = ModelPhases

    def detect(image, prompt):
        nonlocal detector_used, resident
        if not detector_used:
            resident += 192 * mib
            detector_used = True
        with semaphore:
            box = tight_box(_smoke_mask(image))
        candidates = [_box(box, phrase="orange ball")] if box else []
        return Grounding(candidates, image.size, image.size)

    def segment(image, hint):
        nonlocal masks, resident
        masks += 1
        if masks == 1:
            resident += 96 * mib
        if grow and masks == 11:  # Five SAM calls per pass, starting the third pass.
            resident += 65 * mib
        return np.where(_smoke_mask(image)[None, :, :], 1, -1).astype(np.float32), [0.9]

    return detect, segment


def _run_offline_smoke():
    scratch, weights, scenario, *args = sys.argv[1:]
    cli.SCRATCH, cli.WEIGHTS = Path(scratch), Path(weights)
    profile = SmokeProfile("sha256:" + "c" * 64, "d" * 40, "e" * 64, (("synthetic", "1"),))
    Profile.installed = staticmethod(lambda: profile)
    smoke.Engine = partial(Engine, factory=partial(_smoke_factory, grow=scenario == "growth"))
    smoke.os.geteuid = smoke.os.getegid = lambda: 10001
    smoke.os.statvfs = lambda _: SimpleNamespace(f_flag=os.ST_RDONLY)
    smoke.cgroup_bytes = {"max": (16 if args else 5) * 1024**3, "peak": 1024**3, "current": 832 * 1024**2}.get
    if scenario == "deadline":
        smoke.SERVING_RUN_SECONDS = 10
    sys.argv = ["studio-segmentation", "smoke", *args]
    return cli.main()


@pytest.mark.skipif(sys.platform != "linux", reason="Smoke memory phases use Linux /proc")
@pytest.mark.parametrize(("scenario", "args", "exit_code"), [
    ("warmup", (), 0),
    ("growth", (), 1),
    ("deadline", (), 1),
    ("measurement", ("--compare-load-strategy", "buffered"), 0),
])
def test_smoke_report_is_last(tmp_path, pins, scenario, args, exit_code):
    profile, weights = pins
    completed = subprocess.run(
        [sys.executable, "-c", "from tests.segmentation.test_backend import _run_offline_smoke; "
         "raise SystemExit(_run_offline_smoke())", str(tmp_path), str(weights), scenario, *args],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30,
    )
    assert completed.returncode == exit_code, completed.stdout
    last_line = completed.stdout.splitlines()[-1]
    assert last_line.startswith("{"), completed.stdout
    report = loads(last_line)
    assert report["passed"] is (exit_code == 0) and report["profile_id"] == SERVING_PROFILE_ID
    assert report["profile_sha256"] == digest(profile.manifest())
    assert loads(profile.manifest())["parameters"]["weight_load"] == "mmap"
    if args:
        assert report["mode"] == "measurement" and report["verdicts"]["byte_parity"]
        assert [run["weight_load"] for run in report["runs"]] == ["mmap", "buffered"]
    else:
        assert report["mode"] == "serving" and report["cgroup_limit_bytes"] == 5 * 1024**3
        run, = report["runs"]
        assert run["weight_load"] == "mmap" and run["cold_load_ms"] > 0
        expected = {"profile_id": PROFILE_ID, "profile_sha256": digest(profile.manifest()), "device": "cpu"}
        assert run["readiness"] == {"initial": expected, "after": expected}
        if scenario == "deadline":
            assert run["verdicts"]["time_budget"] is False
            assert not run["cases"]
            return
        assert run["verdicts"]["phase_memory"] and run["verdicts"]["create_only_replay"]
        assert {name for name, passed in run["verdicts"].items() if not passed} == (
            {"memory_stable"} if scenario == "growth" else set()
        )
        assert run["memory"]["passes"] == {
            "tolerance_bytes": 64 * 1024**2, "compared_passes": [2, 3],
            "max_resident_rss_bytes": [800 * 1024**2, 800 * 1024**2,
                                       (865 if scenario == "growth" else 800) * 1024**2],
            "max_cgroup_resident_bytes": [832 * 1024**2, 832 * 1024**2,
                                          (897 if scenario == "growth" else 832) * 1024**2],
            "cgroup_resident_bytes": [832 * 1024**2] * 3,
        }
        requests = run["memory"]["requests"]
        assert len(requests) == 18
        assert set(run["cases"]) == {f"{name}{suffix}" for name in fixtures() for suffix in ("", "_repeat", "_third")}
        assert [requests[index]["sam"]["resident_rss_bytes"] // 1024**2 for index in (0, 4, 6, 12)] == [
            608, 800, 800, 865 if scenario == "growth" else 800,
        ]


def test_reference_examples():
    examples = files("haynes_studio.schemas")
    request = loads(examples.joinpath("studio.segmentation-request.v1.example.json").read_text(encoding="utf-8"))
    result = loads(examples.joinpath("studio.segmentation-result.v1.example.json").read_text(encoding="utf-8"))
    validator_for("studio.segmentation-request.v1.schema.json").validate(request)
    validator_for("studio.segmentation-result.v1.schema.json").validate(result)
    validate_request(request)
    assert result["request_sha256"] == digest(canonical_json(request))
    assert result["input"] == request["input"] and result["target"] == request["target"]
    assert result["provenance"]["profile"]["id"] == request["profile"]
