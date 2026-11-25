"""Isolated evidence for the adapter's source, cache, fence and socket guards."""

import os
from contextlib import nullcontext
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from haynes_studio.adapters import segmentation as adapter
from haynes_studio.assets import occlusion
from haynes_studio.jsonio import parse_strict
from haynes_studio.library import Content, Library
from haynes_studio.segmentation.inference import Observation, _prompt, observe
from haynes_studio.segmentation.pixels import describe_mask, encode_mask, tight_box
from haynes_studio.segmentation.profile import MASK_FLOOR, PROFILE_ID, SegmentationError, digest
from haynes_studio.store import Blob, blob_locator, canonical_json
from tests.assets.test_candidates import PRODUCTION_ID
from tests.assets.test_occlusion import (
    JSON, PNG, SIZE, Journal, StaleClaim, detector, library_image, run, segmenter,
    world,  # noqa: F401
)
from tests.segmentation.test_backend import pins  # noqa: F401

OTHER_PRODUCTION = "prd_00000000000000000000000002"
BOX = {"kind": "box", "xyxy": [10, 10, 30, 30]}


def artifacts(client, request):
    image = Image.new("RGB", SIZE)
    facts = Observation()
    reason, pixels = observe(image, None, request, detector, segmenter, facts, lambda _: nullcontext())
    if reason is not None:
        return facts.receipt(request, client.profile, "needs_hint", reason), None, None
    mask = encode_mask(pixels)
    descriptor, _ = describe_mask(mask, image.size)
    return facts.receipt(request, client.profile, "ready", mask=descriptor, box=tight_box(pixels)), mask, pixels


def request_for(data, *, hint=BOX, label="menu"):
    width, height = SIZE
    return occlusion.make_request({"sha256": digest(data), "width": width, "height": height},
                                  kind="prop", key="centre", label=label, hint=hint)


@pytest.fixture
def ready(world, monkeypatch):
    store, client, _ = world
    original, data = library_image(store, Image.new("RGB", SIZE), "set")
    journal = Journal()

    with monkeypatch.context() as seed:
        seed.setattr(client, "run_locked", lambda request, *_: artifacts(client, request))
        result = run(world, original, journal, hint=BOX)
    assert result.action == "use_mask"
    return original, data, journal, result


def accessed_unexpectedly(*args, **kwargs):
    pytest.fail("an invalid or fenced operation crossed its boundary")


@pytest.mark.parametrize(("fault", "code"), [
    ("missing-version", "input_unavailable"),
    ("recorded-only", "input_unavailable"),
    ("contentless", "input_unavailable"),
    ("missing-blob", "input_unavailable"),
    ("owner-production", "input_unavailable"),
    ("owner-story", "input_unavailable"),
    ("owner-board", "input_unavailable"),
    ("locator-production", "input_unavailable"),
    ("locator-hash", "input_unavailable"),
    ("locator-media", "input_unavailable"),
    ("target-kind", "invalid_input"),
    ("set-capability", "invalid_input"),
    ("cutout-capability", "invalid_input"),
    ("cutout-kind", "invalid_input"),
    ("advertised-empty", "invalid_input"),
    ("advertised-oversize", "invalid_input"),
])
def test_invalid_source_metadata_stops_before_lookup(world, monkeypatch, fault, code):
    store, _, _ = world
    cutout = fault.startswith("cutout")
    original, _ = library_image(store, Image.new("RGB", SIZE), "prop" if cutout else "set")
    version = original.version
    asset = original.library.asset_of(version.id)
    content = version.content
    options = {}
    if fault == "missing-version":
        options["source_version_id"] = "undefined"
    elif fault == "recorded-only":
        version = replace(version, recorded_without_media=True)
    elif fault == "contentless":
        version = replace(version, content=None)
    elif fault == "missing-blob":
        (Path(store.root) / content.locator).unlink()
    elif fault == "owner-production":
        asset = replace(asset, scope=replace(asset.scope, production_id=OTHER_PRODUCTION))
    elif fault in ("owner-story", "owner-board"):
        asset = replace(asset, scope=replace(asset.scope, **{fault.replace("owner-", "") + "_id": "held"}))
    elif fault == "locator-production":
        version = replace(version, content=replace(content, locator=blob_locator(OTHER_PRODUCTION, content.sha256, PNG)))
    elif fault == "locator-hash":
        version = replace(version, content=replace(content, locator=blob_locator(PRODUCTION_ID, "a" * 64, PNG)))
    elif fault == "locator-media":
        version = replace(version, content=replace(content, locator=blob_locator(PRODUCTION_ID, content.sha256, JSON)))
    elif fault == "target-kind":
        options["kind"] = "face"
    elif fault == "cutout-kind":
        version = replace(version, kind="cast")
    elif fault.endswith("-capability"):
        version = replace(version, capabilities=())
    else:
        length = 0 if fault == "advertised-empty" else occlusion.MAX_SOURCE_BYTES + 1
        version = replace(version, content=replace(content, bytes=length))
    if fault != "missing-blob":
        monkeypatch.setattr(store, "open", accessed_unexpectedly)
    library = Library(assets={asset.id: asset}, versions={version.id: version})
    journal = Journal()
    assert run(world, replace(original, version=version, library=library), journal,
               lookup_ready=accessed_unexpectedly, **options) is None
    assert journal.failures == [code]


@pytest.mark.parametrize("fault", [
    "media-type", "format", "actual-empty", "actual-oversize", "actual-hash", "actual-length",
    "short-side-min", "short-side-max", "long-side-max", "pixels", "animation", "orientation",
    "declared-width", "declared-height", "plate-alpha", "opaque-cutout", "transparent-cutout",
])
def test_source_decoder_rejects_invalid_still(monkeypatch, fault):
    plate = not fault.endswith("cutout")
    alpha = {"plate-alpha": 128, "opaque-cutout": 255, "transparent-cutout": 0}
    image = Image.new("RGBA", SIZE, (90, 100, 110, alpha.get(fault, 255)))
    options = {}
    if fault in ("short-side-min", "short-side-max", "long-side-max"):
        size = {"short-side-min": (64, 31), "short-side-max": (64, 64), "long-side-max": SIZE}[fault]
        image = Image.new("RGB", size)
        if fault == "short-side-max":
            monkeypatch.setattr(occlusion, "MAX_SHORT_SIDE", 63)
        if fault == "long-side-max":
            monkeypatch.setattr(occlusion, "MAX_SIDE", 63)
    elif fault == "pixels":
        monkeypatch.setattr(occlusion, "MAX_PIXELS", SIZE[0] * SIZE[1] - 1)
    elif fault == "animation":
        options.update(save_all=True, append_images=[Image.new("RGBA", SIZE, "blue")])
    elif fault == "orientation":
        exif = Image.Exif()
        exif[274] = 3
        options["exif"] = exif

    with BytesIO() as stream:
        image.save(stream, "PNG", **options)
        data = stream.getvalue()
    if fault == "actual-empty":
        data = b""
    if fault == "actual-oversize":
        monkeypatch.setattr(occlusion, "MAX_SOURCE_BYTES", len(data) - 1)
    media = {"media-type": JSON, "format": "image/jpeg"}.get(fault, PNG)
    content = Content("a" * 64 if fault == "actual-hash" else digest(data),
                      len(data) + (fault == "actual-length"), media, "unused",
                      image.width + (fault == "declared-width"), image.height + (fault == "declared-height"))
    with pytest.raises(SegmentationError, match="^invalid_input$"):
        occlusion.decode_still(content, data, plate=plate)


def test_request_validation_and_text_canonicalization_precede_cache_lookup(world):
    store, _, _ = world
    original, _ = library_image(store, Image.new("RGB", SIZE), "set")
    journal = Journal()
    assert run(world, original, journal, key="Uppercase", lookup_ready=accessed_unexpectedly) is None
    assert journal.failures == ["invalid_input"]

    expected = {"kind": "text", "text": "café"}
    request = request_for(b"still", label="  cafe\u0301 ", hint={"kind": "text", "text": " cafe\u0301 "})
    assert request["hint"] == expected and request["target"]["label"] == "café"


def test_lookup_cannot_relabel_a_byte_identical_source_version(world, ready):
    store, _, _ = world
    version_a, data_a, journal, result = ready
    version_b, data_b = library_image(store, Image.new("RGB", SIZE), "set", key="different-set",
                                      library=version_a.library)
    assert data_a == data_b and version_a.version.id != version_b.version.id
    record = result.completion

    def relabel(key):
        type(key).__init__(key, record.identity.production_id, record.identity.source_version_id,
                           record.identity.request_sha256, record.identity.profile_sha256)
        return record

    assert run(world, version_b, journal, hint=BOX, lookup_ready=relabel) is None
    assert journal.failures == ["invalid_output"]


def forged_blob(blob, **changes):
    # Bypass Blob's constructor to exercise the independent read-back validation.
    record = object.__new__(Blob)
    for field, value in (blob.to_document() | changes).items():
        object.__setattr__(record, field, value)
    return record


@pytest.mark.parametrize("artifact", ["result", "mask"])
@pytest.mark.parametrize("fault", ["locator-media", "locator-hash", "scope", "empty", "oversize"])
def test_readback_refuses_inconsistent_locators_and_lengths(world, ready, monkeypatch, artifact, fault):
    store, _, _ = world
    original, _, journal, result = ready
    record = result.completion
    blob = getattr(record, artifact)
    if fault == "empty":
        wrong = replace(blob, bytes=0)
    elif fault == "oversize":
        limit = occlusion.MAX_REPLY if artifact == "result" else occlusion.MAX_SOURCE_BYTES
        wrong = replace(blob, bytes=limit + 1)
    else:
        different_media = JSON if artifact == "mask" else PNG
        wrong = forged_blob(blob, locator=blob_locator(
            OTHER_PRODUCTION if fault == "scope" else record.identity.scope,
            "a" * 64 if fault == "locator-hash" else blob.sha256,
            different_media if fault == "locator-media" else blob.media_type,
        ))
    open_blob = store.open

    def same_bytes(locator):
        if locator == wrong.locator:
            return open_blob(blob.locator)
        return open_blob(locator)

    if fault in ("empty", "oversize"):
        def check_before_open(locator):
            assert locator != wrong.locator, "descriptor length must be rejected before reading"
            return open_blob(locator)
        monkeypatch.setattr(store, "open", check_before_open)
    else:
        monkeypatch.setattr(store, "open", same_bytes)
    assert run(world, original, journal, hint=BOX,
               lookup_ready=lambda _: replace(record, **{artifact: wrong})) is None
    assert journal.failures == ["invalid_output"]


def republish_receipt(store, record, data):
    return replace(record, result=store.publish(data, scope=record.identity.scope, media_type=JSON))


@pytest.mark.parametrize("fault", ["status", "reason", "missing-mask", "noncanonical", "score", "null-score"])
def test_cached_ready_record_and_receipt_must_agree(world, ready, fault):
    store, _, _ = world
    original, _, journal, result = ready
    record = result.completion
    if fault == "status":
        record = replace(record, status="needs_hint")
    elif fault == "reason":
        record = replace(record, reason="mask_uncertain")
    elif fault == "missing-mask":
        record = replace(record, mask=None)
    elif fault == "noncanonical":
        record = republish_receipt(store, record, result.receipt + b"\n")
    else:
        receipt = parse_strict(result.receipt.decode())
        receipt["scores"]["mask_iou"] = MASK_FLOOR - 0.01 if fault == "score" else None
        record = republish_receipt(store, record, canonical_json(receipt))
    assert run(world, original, journal, hint=BOX, lookup_ready=lambda _: record) is None
    assert journal.failures == ["invalid_output"]


def test_cached_ready_accepts_score_at_profile_floor(world, ready):
    store, _, _ = world
    original, _, journal, result = ready
    receipt = parse_strict(result.receipt.decode())
    receipt["scores"]["mask_iou"] = MASK_FLOOR
    record = republish_receipt(store, result.completion, canonical_json(receipt))
    assert run(world, original, journal, hint=BOX, lookup_ready=lambda _: record).action == "use_mask"


@pytest.mark.parametrize("changed", ["request", "profile"])
def test_cached_expected_digests_are_rechecked(world, ready, monkeypatch, changed):
    store, client, _ = world
    original, _, journal, result = ready
    original_make = occlusion.make_request
    frozen_request = {}

    def capture(*args, **kwargs):
        frozen_request.update(original_make(*args, **kwargs))
        return frozen_request

    def lookup(_):
        if changed == "request":
            frozen_request["target"]["label"] = "updated menu"
        else:
            client.profile = replace(client.profile, revision="a" * 40)
        # All artifacts describe the replacement. Only the held digest still
        # binds the original request/profile, which is outside the lookup.
        receipt, png_data, _ = artifacts(client, frozen_request)
        assert png_data == result.png
        return republish_receipt(store, result.completion, canonical_json(receipt))

    monkeypatch.setattr(occlusion, "make_request", capture)
    assert run(world, original, journal, hint=BOX, lookup_ready=lookup) is None
    assert journal.failures == ["invalid_output"]


@pytest.mark.parametrize("fault", ["outside-alpha", "missed-point"])
def test_mask_support_is_checked_before_publication(world, monkeypatch, fault):
    store, client, _ = world
    if fault == "outside-alpha":
        image = Image.new("RGBA", SIZE)
        image.paste((0, 0, 0, 255), (10, 10, 15, 15))
        original, _ = library_image(store, image, "prop")
        hint = BOX
    else:
        original, _ = library_image(store, Image.new("RGB", SIZE), "set")
        hint = {"kind": "point", "xy": [0, 0]}

    def forged_result(request, *_):
        result, mask, pixels = artifacts(client, {**request, "hint": BOX})
        result["request_sha256"] = digest(canonical_json(request))
        result["provenance"]["parameters"]["sam_hint"] = hint
        # Keep the exact PNG and request binding. Its support is the sole error.
        return result, mask, pixels

    monkeypatch.setattr(client, "run_locked", forged_result)
    monkeypatch.setattr(store, "publish", accessed_unexpectedly)
    journal = Journal()
    assert run(world, original, journal, hint=hint) is None
    assert journal.failures == ["invalid_output"]


@pytest.mark.parametrize("status", ["ready", "needs_hint"])
def test_fresh_receipt_requires_store_readback_before_reporting(world, monkeypatch, status):
    store, client, _ = world
    original, _ = library_image(store, Image.new("RGB", SIZE), "set")
    monkeypatch.setattr(client, "run_locked", lambda request, *_: artifacts(client, request))
    publish = store.publish

    def corrupt(data, **kwargs):
        blob = publish(data, **kwargs)
        if kwargs["media_type"] == JSON:
            path = Path(store.root) / blob.locator
            path.chmod(0o600)
            path.write_bytes(b" " * len(data))
        return blob

    monkeypatch.setattr(store, "publish", corrupt)
    journal = Journal()
    options = {"hint": BOX} if status == "ready" else {"label": "no match"}
    assert run(world, original, journal, **options) is None
    assert journal.failures == ["invalid_output"]
    assert not journal.diagnostics and not journal.completions


def test_publication_must_return_requested_digest_before_writing_receipt(world, monkeypatch):
    store, client, _ = world
    original, _ = library_image(store, Image.new("RGB", SIZE), "set")
    monkeypatch.setattr(client, "run_locked", lambda request, *_: artifacts(client, request))
    created = []

    def wrong_blob(data, *, scope, media_type, expected_sha256):
        created.append(media_type)
        wrong_sha = "a" * 64
        return Blob(wrong_sha, len(data), media_type, blob_locator(scope, wrong_sha, media_type))

    monkeypatch.setattr(store, "publish", wrong_blob)
    journal = Journal()
    assert run(world, original, journal, hint=BOX) is None
    assert created == [PNG]
    assert journal.failures == ["store_failed"]


@pytest.mark.parametrize("where", [
    "before-lookup", "after-cache-readback", "before-mask", "before-receipt",
    "before-ready-commit", "before-failure", "before-diagnostic",
])
def test_fence_guards_each_job_boundary(world, ready, monkeypatch, where):
    store, client, _ = world
    original, _, _, cached = ready
    journal = Journal()
    published = []
    make_request, publish, read_blob = occlusion.make_request, store.publish, occlusion._read_blob

    def construct(*args, **kwargs):
        request = make_request(*args, **kwargs)
        if where == "before-lookup":
            journal.current = False
        return request

    def dispatch(request, *_):
        if where == "before-failure":
            journal.current = False
            raise SegmentationError("inference_failed")
        result = artifacts(client, request)
        if where == "before-mask":
            journal.current = False
        return result

    def write(data, **kwargs):
        published.append(kwargs["media_type"])
        assert journal.current, "publication crossed the claim fence"
        blob = publish(data, **kwargs)
        if where == "before-receipt" and blob.media_type == PNG:
            journal.current = False
        return blob

    def read(store, blob, scope, media, limit):
        data = read_blob(store, blob, scope, media, limit)
        if (where in ("after-cache-readback", "before-ready-commit") and media == PNG
                or where == "before-diagnostic" and media == JSON):
            journal.current = False
        return data

    def lookup(_):
        assert journal.current, "lookup crossed the claim fence"
        return cached.completion if where == "after-cache-readback" else None

    monkeypatch.setattr(occlusion, "make_request", construct)
    monkeypatch.setattr(client, "run_locked", dispatch)
    monkeypatch.setattr(store, "publish", write)
    monkeypatch.setattr(occlusion, "_read_blob", read)
    options = {"label": "no match"} if where == "before-diagnostic" else {"hint": BOX}
    with pytest.raises(StaleClaim):
        run(world, original, journal, lookup_ready=lookup, commit_completion=accessed_unexpectedly,
            record_failure=accessed_unexpectedly, **options)
    assert published == {
        "before-lookup": [], "after-cache-readback": [], "before-mask": [],
        "before-receipt": [PNG], "before-ready-commit": [PNG, JSON],
        "before-failure": [], "before-diagnostic": [JSON],
    }[where]


def test_verified_observation_has_no_writable_instance_storage():
    allocated = object.__new__(occlusion.VerifiedObservation)
    with pytest.raises(AttributeError):
        object.__setattr__(allocated, "_completion", "forged")


def test_readiness_requires_http_200_even_with_exact_body(world, monkeypatch):
    _, client, _ = world
    body = {"profile_id": PROFILE_ID, "profile_sha256": client.profile_sha256, "device": "cpu"}
    monkeypatch.setattr(client, "_call", lambda *_: (201, body))
    monkeypatch.setattr(client, "_attempt", accessed_unexpectedly)
    with pytest.raises(SegmentationError, match="^profile_unavailable$"):
        client.run_locked(request_for(b"still"), b"still", lambda: None)


@pytest.mark.parametrize("fault", [
    "not-an-object", "extra-wrapper-field", "missing-wrapper-field", "non-object-result", "unrecognized-error",
    "wrong-http-status", "wrong-failure-status", "wrong-hash", "oversize", "extra-result-field",
    "unexpected-scratch-mask", "missing-mask", "wrong-mask-box",
])
def test_socket_reply_requires_closed_paired_evidence(world, monkeypatch, tmp_path, fault):
    _, client, _ = world
    request = request_for(b"still")
    mask = None
    status = 200
    if fault == "unexpected-scratch-mask":
        request = request_for(b"still", hint=None, label="no match")
        result, _, _ = artifacts(client, request)
        mask = b"unexpected scratch mask"
    elif fault == "wrong-failure-status":
        result = Observation().receipt(request, client.profile, "failed", "inference_failed")
    else:
        result, mask, _ = artifacts(client, request)

    if fault == "wrong-mask-box":
        result["box_xyxy"][0] += 1
    elif fault == "extra-result-field":
        result["extra"] = 1
    elif fault == "wrong-http-status":
        status = 201

    receipt = canonical_json(result)
    reply = {"result": result, "result_sha256": digest(receipt)}
    if fault == "not-an-object":
        reply = 1
    elif fault == "extra-wrapper-field":
        reply["extra"] = 1
    elif fault == "missing-wrapper-field":
        del reply["result_sha256"]
    elif fault == "non-object-result":
        reply["result"] = [result]
    elif fault == "unrecognized-error":
        reply = {"code": "made_up"}
    elif fault == "wrong-hash":
        reply["result_sha256"] = "a" * 64
    elif fault == "oversize":
        monkeypatch.setattr(adapter, "MAX_REPLY", len(receipt) - 1)

    (tmp_path / "result.json").write_bytes(receipt)
    if mask is not None and fault != "missing-mask":
        (tmp_path / "mask.png").write_bytes(mask)
    fd = os.open(tmp_path, os.O_DIRECTORY | os.O_RDONLY)
    try:
        with pytest.raises(SegmentationError, match="^invalid_output$"):
            client._read_reply(fd, request, status, reply)
    finally:
        os.close(fd)


@pytest.mark.parametrize("fault", [
    "direct-box", "direct-score", "detector-bounds", "detector-float", "missing-operation",
    "direct-grounding", "resize-type", "resize-order", "resize-positive",
    "ready-without-mask", "diagnostic-with-mask",
])
def test_result_verification_checks_operation_geometry(world, fault):
    _, client, _ = world
    grounded = fault in {"detector-bounds", "detector-float", "resize-type", "resize-order", "resize-positive"}
    request = request_for(b"still", hint=None if grounded else BOX)
    result, mask, _ = artifacts(client, request)
    params = result["provenance"]["parameters"]
    if fault == "direct-box":
        result["detector_box_xyxy"] = [2, 2, 30, 30]
    elif fault == "direct-score":
        result["scores"]["detector"] = 0.9
    elif fault in ("detector-bounds", "detector-float"):
        box = [2, 2, SIZE[0] + 1, 30] if fault == "detector-bounds" else [2.0, 2, 30, 30]
        result["detector_box_xyxy"] = box
        params["sam_hint"]["xyxy"] = box
    elif fault == "missing-operation":
        del params["sam_hint"]
    elif fault == "direct-grounding":
        # Failed receipts allow partial execution. Only the direct-hint guard
        # excludes grounding facts here, independent of required fact checks.
        result = Observation(applied={"prompt": _prompt(request)}).receipt(
            request, client.profile, "failed", "inference_failed",
        )
        mask = None
    elif fault in ("resize-type", "resize-order", "resize-positive"):
        params["detector_resize_wh"] = {
            "resize-type": [1.5, 3], "resize-order": [SIZE[0] + 1, 3], "resize-positive": [0, 3],
        }[fault]
    elif fault == "ready-without-mask":
        mask = None
    elif fault == "diagnostic-with-mask":
        request = request_for(b"still", hint=None, label="no match")
        result, _, _ = artifacts(client, request)

    with pytest.raises(SegmentationError, match="^invalid_output$"):
        adapter.verify_result(request, result, mask, client.profile)


@pytest.mark.parametrize("fault", ["envelope", "size"])
def test_request_checks_run_before_staging(world, monkeypatch, fault):
    _, client, _ = world
    request = request_for(b"still")
    if fault == "envelope":
        monkeypatch.setattr(adapter, "uuid4", lambda: SimpleNamespace(hex="not-an-attempt"))
    else:
        monkeypatch.setattr(adapter, "MAX_REQUEST", 1)

    monkeypatch.setattr(Path, "touch", accessed_unexpectedly)
    with pytest.raises(SegmentationError, match="^invalid_input$"):
        client._attempt(request, b"still", lambda: None)
    assert not list(client.scratch.iterdir())


@pytest.mark.parametrize("stop", ["busy", "timeout", "stale-after-busy"])
def test_socket_attempts_bound_busy_waits_and_check_each_claim(world, monkeypatch, stop):
    _, client, _ = world
    events, pauses = [], []
    journal = Journal()

    def get_ready():
        events.append("ready")

    def attempt(*_):
        events.append("request")
        raise SegmentationError("timeout" if stop == "timeout" else "busy")

    def pause(seconds):
        pauses.append(seconds)
        if stop == "stale-after-busy":
            journal.current = False

    monkeypatch.setattr(client, "_ready", get_ready)
    monkeypatch.setattr(client, "_attempt", attempt)
    client.pause = pause
    expected_error = StaleClaim if stop == "stale-after-busy" else SegmentationError
    with pytest.raises(expected_error):
        client.run_locked(request_for(b"still"), b"still", journal.fence)
    waits = {"busy": 13, "timeout": 0, "stale-after-busy": 1}[stop]
    assert pauses == [5] * waits
    assert events == ["ready", "request"] * (14 if stop == "busy" else 1)


def test_dispatch_rechecks_claim_after_staging(world, monkeypatch):
    _, client, _ = world
    journal = Journal()
    create = adapter._create_file

    def stale(fd, name, data):
        create(fd, name, data)
        journal.current = False

    monkeypatch.setattr(adapter, "_create_file", stale)
    monkeypatch.setattr(client, "_call", accessed_unexpectedly)
    with pytest.raises(StaleClaim):
        client._attempt(request_for(b"still"), b"still", journal.fence)
    assert not list(client.scratch.iterdir())


@pytest.mark.parametrize("release", [True, False])
def test_lock_is_nonblocking_and_only_retries_bounded_contention(world, monkeypatch, release):
    _, client, _ = world
    pauses, tries = [], []
    client.pause = pauses.append

    def held(fd, flags):
        assert flags & adapter.LOCK_NB
        tries.append(fd)
        if not release or len(tries) == 1:
            raise BlockingIOError

    monkeypatch.setattr(adapter, "flock", held)
    if release:
        with client.serial(lambda: None):
            assert len(tries) == 2
    else:
        with pytest.raises(SegmentationError, match="^busy$"), client.serial(lambda: None):
            accessed_unexpectedly()
    assert len(tries) == (2 if release else 14)
    assert pauses == [5] * (1 if release else 13)


def test_lock_retry_rechecks_the_claim_after_contention(world, monkeypatch):
    _, client, _ = world
    journal = Journal()
    tries = []

    def held(*_):
        tries.append(True)
        if len(tries) == 1:
            raise BlockingIOError

    def expire(_):
        journal.current = False

    monkeypatch.setattr(adapter, "flock", held)
    client.pause = expire
    with pytest.raises(StaleClaim), client.serial(journal.fence):
        accessed_unexpectedly()
    assert len(tries) == 1


def test_gate_refuses_fifo_with_nonblocking_open(world, monkeypatch):
    _, client, _ = world
    lock = client.scratch / ".studio-segmentation.lock"
    os.mkfifo(lock)
    original_open = os.open
    opens = []

    def tracked_open(path, flags, *args, **kwargs):
        if path == lock:
            opens.append(flags)
            assert flags & os.O_NONBLOCK
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", tracked_open)
    with pytest.raises(SegmentationError, match="^lock_path_invalid$"), client.serial(lambda: None):
        accessed_unexpectedly()
    assert len(opens) == 1


def test_scratch_cleanup_checks_marker_name_age_and_file_type(world, monkeypatch):
    _, client, _ = world
    now = 100 + adapter.SCRATCH_GRACE
    attempts = {
        "old": "a" * 32, "young": "b" * 32, "directory": "c" * 32, "symlink": "d" * 32,
        "wrong-name": "e" * 32 + "-suffix",
    }
    markers = {kind: client.scratch / (".studio-segment-" + token) for kind, token in attempts.items()}
    for kind in ("old", "young", "wrong-name"):
        markers[kind].touch()
        os.utime(markers[kind], (101, 101) if kind == "young" else (100, 100))
    markers["directory"].mkdir()
    os.utime(markers["directory"], (100, 100))
    markers["symlink"].symlink_to(markers["old"])
    os.utime(markers["symlink"], (100, 100), follow_symlinks=False)

    removed = []
    monkeypatch.setattr(adapter, "time", lambda: now)
    monkeypatch.setattr(client, "_remove", lambda *args: removed.append(args))
    client._sweep()
    assert removed == [(attempts["old"], markers["old"])]
