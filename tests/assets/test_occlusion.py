"""The worker contract against the real Unix socket and a synthetic CPU graph.

The fake proves request binding, artifact checks and publication. It says
nothing about detector quality on a miniature set.
"""

from __future__ import annotations

import multiprocessing
import os
import socket
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from functools import partial
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event

import numpy as np
import pytest
from PIL import Image

from haynes_studio.adapters import segmentation as adapter
from haynes_studio.adapters.segmentation import SegmentationClient
from haynes_studio.assets.occlusion import SegmentationOutcome, VerifiedObservation, run_segmentation_job
from haynes_studio.errors import ContractError
from haynes_studio.library import EMPTY, Content, Library, Scope, VersionRequest, import_version, validate_asset_version
from haynes_studio.library.model import Licence
from haynes_studio.segmentation.backend import Engine
from haynes_studio.segmentation.inference import Candidate, Grounding
from haynes_studio.segmentation.pixels import encode_mask
from haynes_studio.segmentation.profile import SegmentationError, digest
from haynes_studio.segmentation.service import listening
from haynes_studio.store import LocalStore, StoreError, blob_locator, canonical_json
from tests.assets.test_candidates import BY, NOW, PRODUCTION_ID
from tests.canonical.fixtures import example
from tests.segmentation.test_backend import pins  # noqa: F401

SIZE = (64, 48)
PNG = "image/png"
JSON = "application/json"


def png(image):
    with BytesIO() as buffer:
        image.save(buffer, "PNG")
        return buffer.getvalue()


def library_image(store, image, kind, *, library=EMPTY, key=None, config=None,
                  production_id=PRODUCTION_ID, **overrides):
    data = png(image)
    blob = store.publish(data, scope=production_id or "library", media_type=PNG)
    content = Content(blob.sha256, blob.bytes, PNG, blob.locator, *image.size)
    request = VersionRequest(
        kind=kind, name=key or kind, scope=Scope(production_id),
        capabilities=("opaque_plate" if kind == "set" else "rgba_cutout",), content=content,
        provenance={"origin": "imported", "source_key": f"synthetic:{key or kind}",
                    "generator": {"role": "image"}, "external": None},
        licence=Licence.unknown("Synthetic fixture"), occlusion=config,
    )
    recorded = import_version(library, replace(request, **overrides), by=BY, now=NOW)
    return recorded, data


def detector(image, prompt):
    usual = Candidate((10, 10, 30, 30), 0.9, prompt)
    if "no match" in prompt:
        boxes = []
    elif "ambiguous" in prompt:
        boxes = [usual, Candidate((40, 10, 62, 30), 0.87, prompt)]
    elif "tiny" in prompt:
        boxes = [Candidate((10, 10, 15, 15), 0.9, prompt)]
    else:
        boxes = [usual]
    return Grounding(boxes, image.size, image.size)


def segmenter(image, hint):
    logits = np.full((1, image.height, image.width), -1.0, dtype=np.float32)
    x0, y0, x1, y1 = hint.get("xyxy", (10, 10, 30, 30))
    logits[:, y0:y1, x0:x1] = 1
    return logits, [0.2 if image.getpixel((0, 0))[0] == 81 else 0.9]


def factory(weights, phase, strategy):
    return detector, segmenter


def matching_factory(weights, phase, strategy):
    return lambda image, prompt: detector(image, "synthetic match"), segmenter


def blocking_factory(weights, phase, strategy, *, started, release):
    def blocking(image, hint):
        started.set()
        release.wait()
        return segmenter(image, hint)
    return detector, blocking


class StaleClaim(Exception):
    pass


class Journal:
    """Exercise the writer's atomic contract with a fresh in-memory claim."""

    def __init__(self):
        self.current = True
        self.completions = []
        self.diagnostics = []
        self.failures = []

    def fence(self):
        if not self.current:
            raise StaleClaim

    def commit(self, completion):
        self.fence()
        assert not any(item.identity == completion.identity for item in self.completions)
        self.completions.append(completion)

    def lookup(self, key):
        self.fence()
        return next((r for r in self.completions if r.identity == key and r.status == "ready"), None)

    def diagnose(self, *, code, diagnostic=None):
        self.fence()
        if diagnostic is None:
            self.failures.append(code)
        else:
            assert code == diagnostic.reason
            self.diagnostics.append(diagnostic)


@pytest.fixture
def world(tmp_path, pins):
    profile, weights = pins
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    store_root = tmp_path / "store"
    store_root.mkdir()
    store = LocalStore(store_root)
    with TemporaryDirectory(prefix="op452-") as directory:
        client = SegmentationClient(profile, digest(profile.manifest()), scratch=scratch,
                                    socket=Path(directory) / "segment.sock")
        yield store, client, weights


def run(world, original, journal, **options):
    store, client, _ = world
    default = dict(source_version_id=original.version.id, production_id=PRODUCTION_ID,
                   kind="prop", key="centre", label="menu", store=store, client=client,
                   check_fence=journal.fence, lookup_ready=journal.lookup, commit_completion=journal.commit,
                   record_failure=journal.diagnose)
    return run_segmentation_job(original.library, **(default | options))


def test_create_only_order_receipt_and_reuse_same_request(world, monkeypatch):
    store, client, weights = world
    source, original = library_image(store, Image.new("RGB", SIZE, (30, 50, 70)), "set")
    journal = Journal()
    methods, events = [], []
    call, publish = adapter.local_call, store.publish

    def counted(path, method, route, payload, **kwargs):
        methods.append((method, payload))
        return call(path, method, route, payload, **kwargs)

    def publish_then_record(data, **args):
        blob = publish(data, **args)
        events.append(blob.media_type)
        return blob

    def commit(completion):
        events.append("completion")
        assert store.verify(completion.mask.locator, completion.mask.sha256) == "present"
        assert store.verify(completion.result.locator, completion.result.sha256) == "present"
        journal.commit(completion)

    monkeypatch.setattr(adapter, "local_call", counted)
    monkeypatch.setattr(store, "publish", publish_then_record)
    with Engine(client.scratch, weights, client.profile, factory=factory) as engine, listening(client.socket, engine):
        a = run(world, source, journal, label=" Cafe\u0301 ", commit_completion=commit)
        b = run(world, source, journal, label="Café", commit_completion=commit)
        hint = {"kind": "point", "xy": [15, 15]}
        c = run(world, source, journal, label="Café", hint=hint, commit_completion=commit)
        d = run(world, source, journal, label="Café", hint=hint, commit_completion=commit)

    for fresh, cached in ((a, b), (c, d)):
        assert type(fresh) is type(cached) is VerifiedObservation
        assert (fresh.completion, fresh.png, fresh.receipt) == (cached.completion, cached.png, cached.receipt)
    assert a.action == c.action == "use_mask" and a.png == c.png
    assert a.completion.identity.request_sha256 != c.completion.identity.request_sha256
    assert a.completion.result.sha256 != c.completion.result.sha256
    posts = [payload for method, payload in methods if method == "POST"]
    assert len(posts) == 2
    assert posts[0]["request"]["target"]["label"] == "Café"
    assert posts[1]["request"]["hint"] == hint
    for payload, outcome in zip(posts, [a, c]):
        assert digest(canonical_json(payload["request"])) == outcome.completion.identity.request_sha256
    assert events == [PNG, JSON, "completion"] * 2
    assert not journal.failures
    assert source.library.get(source.version.id) == source.version
    with store.open(source.version.content.locator) as stored:
        assert stored.read() == original


@pytest.mark.parametrize(("kind", "label", "red", "reason"), [
    ("prop", "no match", 30, "no_match"),
    ("prop", "ambiguous", 30, "ambiguous_match"),
    ("prop", "tiny", 30, "too_small"),
    ("foreground", None, 30, "foreground_depth_ambiguous"),
    ("prop", "menu", 81, "mask_uncertain"),
])
def test_uncertainty_is_recorded_for_a_person(world, kind, label, red, reason):
    store, client, weights = world
    source, _ = library_image(store, Image.new("RGB", SIZE, (red, 50, 70)), "set")
    journal = Journal()
    with Engine(client.scratch, weights, client.profile, factory=factory) as engine, listening(client.socket, engine):
        result = run(world, source, journal, kind=kind, label=label)
    assert result.action == "review"
    assert result.completion.reason == reason and result.completion.status == "needs_hint"
    assert result.png is None and result.completion.mask is None
    assert journal.diagnostics == [result.completion]
    assert not journal.completions
    assert journal.lookup(result.completion.identity) is None
    assert not journal.failures


def test_needs_hint_does_not_reserve_a_later_ready_completion(world):
    store, client, weights = world
    source, _ = library_image(store, Image.new("RGB", SIZE, (30, 50, 70)), "set")
    journal = Journal()
    hint = {"kind": "point", "xy": [15, 15]}
    with Engine(client.scratch, weights, client.profile, factory=factory) as engine, listening(client.socket, engine):
        review = run(world, source, journal, label="no match")
        hinted = run(world, source, journal, label="no match", hint=hint)
    assert review.action == "review" and hinted.action == "use_mask"
    assert review.completion.identity != hinted.completion.identity

    # A new inference attempt can also resolve the same request and profile.
    with Engine(client.scratch, weights, client.profile, factory=matching_factory) as engine, \
            listening(client.socket, engine):
        repeated = run(world, source, journal, label="no match")
    assert repeated.action == "use_mask" and repeated.completion.identity == review.completion.identity
    assert journal.diagnostics == [review.completion]
    assert journal.completions == [hinted.completion, repeated.completion]


def test_symlink_at_scratch_lock_is_reported_without_following_it(world):
    store, client, _ = world
    source, _ = library_image(store, Image.new("RGB", SIZE), "set")
    lock = client.scratch / ".studio-segmentation.lock"
    target = client.scratch / "untouched"
    lock.symlink_to(target)
    journal = Journal()

    assert run(world, source, journal) is None
    assert journal.failures == ["lock_path_invalid"]
    assert lock.is_symlink() and not target.exists()
    assert not journal.completions


def test_socket_at_scratch_lock_is_reported_as_invalid(world):
    store, client, weights = world
    source, _ = library_image(store, Image.new("RGB", SIZE), "set")
    journal = Journal()
    with TemporaryDirectory(prefix="s452-") as directory:
        scratch = Path(directory)
        lock = scratch / ".studio-segmentation.lock"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.bind(str(lock))
        client = SegmentationClient(client.profile, client.profile_sha256, scratch=scratch)

        assert run((store, client, weights), source, journal) is None
        assert lock.is_socket()
    assert journal.failures == ["lock_path_invalid"]
    assert not journal.completions


def test_fifo_at_scratch_lock_is_reported_as_invalid(world):
    store, client, _ = world
    source, _ = library_image(store, Image.new("RGB", SIZE), "set")
    lock = client.scratch / ".studio-segmentation.lock"
    os.mkfifo(lock)
    journal = Journal()

    assert run(world, source, journal) is None
    assert journal.failures == ["lock_path_invalid"]
    assert lock.is_fifo()
    assert not journal.completions


def test_directory_at_scratch_lock_is_reported_as_invalid(world):
    store, client, _ = world
    source, _ = library_image(store, Image.new("RGB", SIZE), "set")
    lock = client.scratch / ".studio-segmentation.lock"
    lock.mkdir()
    journal = Journal()

    assert run(world, source, journal) is None
    assert journal.failures == ["lock_path_invalid"]
    assert lock.is_dir() and not journal.completions


@pytest.mark.parametrize("mutation", [
    "width", "height", "non_binary", "digest", "missing", "result", "pin", "prompt", "sam_hint",
    "input", "target", "request_sha256",
])
def test_tampered_artifacts_never_complete(world, monkeypatch, mutation):
    store, client, weights = world
    source, _ = library_image(store, Image.new("RGB", SIZE), "set")
    journal = Journal()
    dispatch = Engine.run

    def tamper(engine, payload):
        result = dispatch(engine, payload)
        folder = client.scratch / payload["attempt_id"]
        mask_file, result_file = folder / "mask.png", folder / "result.json"
        if mutation == "missing":
            mask_file.unlink()
        elif mutation == "result":
            result_file.write_bytes(b"{}")
        elif mutation == "pin":
            result["provenance"]["profile"]["sha256"] = "9" * 64
            result_file.write_bytes(canonical_json(result))
        elif mutation == "digest":
            result["mask"]["sha256"] = "9" * 64
            result_file.write_bytes(canonical_json(result))
        elif mutation in {"input", "target", "request_sha256"}:
            if mutation == "input":
                result["input"]["sha256"] = "9" * 64
            elif mutation == "target":
                result["target"]["key"] = "another"
            else:
                result["request_sha256"] = "9" * 64
            result_file.write_bytes(canonical_json(result))
        elif mutation in {"prompt", "sam_hint"}:
            result["provenance"]["parameters"][mutation] = (
                "another prop." if mutation == "prompt" else {"kind": "box", "xyxy": [12, 12, 39, 39]})
            result_file.write_bytes(canonical_json(result))
        else:
            width, height = SIZE
            width -= mutation == "width"
            height -= mutation == "height"
            pixels = np.zeros((height, width), dtype=bool)
            pixels[10:30, 10:30] = True
            bad = encode_mask(pixels)
            if mutation == "non_binary":
                raw = Image.fromarray(pixels.astype(np.uint8) * 255)
                raw.putpixel((10, 10), 128)
                bad = png(raw)
            result["mask"].update(sha256=digest(bad), bytes=len(bad), width=width, height=height)
            mask_file.write_bytes(bad)
            result_file.write_bytes(canonical_json(result))
        return result

    monkeypatch.setattr(Engine, "run", tamper)
    with Engine(client.scratch, weights, client.profile, factory=factory) as engine, listening(client.socket, engine):
        assert run(world, source, journal) is None
    assert journal.failures == ["profile_unavailable" if mutation == "pin" else "invalid_output"]
    assert not journal.completions


def test_missing_service_wrong_readiness_and_refused_version(world):
    store, client, weights = world
    source, _ = library_image(store, Image.new("RGB", SIZE), "set")
    journal = Journal()
    assert run(world, source, journal) is None
    assert journal.failures == ["profile_unavailable"]
    with Engine(client.scratch, weights, client.profile, factory=factory) as engine, listening(client.socket, engine):
        assert run(world, source, journal, production_id="prd_00000000000000000000000002") is None
        other = replace(client.profile, revision="a" * 40)
        bad = SegmentationClient(other, digest(other.manifest()), scratch=client.scratch, socket=client.socket)
        assert run(world, source, journal, client=bad) is None
    with pytest.raises(SegmentationError, match="profile_unavailable"):
        SegmentationClient(client.profile, "9" * 64)
    assert journal.failures == ["profile_unavailable", "input_unavailable", "profile_unavailable"]
    assert not journal.completions


@pytest.mark.parametrize(("field", "value"), [
    ("profile_id", "other"), ("profile_sha256", "9" * 64), ("device", "cuda"), ("extra", True),
])
def test_readiness_requires_the_exact_frozen_response(world, monkeypatch, field, value):
    store, client, weights = world
    source, _ = library_image(store, Image.new("RGB", SIZE), "set")
    journal = Journal()
    original = adapter.local_call

    def altered(socket, method, route, payload, **kwargs):
        status, body = original(socket, method, route, payload, **kwargs)
        return (status, {**body, field: value}) if route == "/v1/ready" else (status, body)

    monkeypatch.setattr(adapter, "local_call", altered)
    with Engine(client.scratch, weights, client.profile, factory=factory) as engine, listening(client.socket, engine):
        assert run(world, source, journal) is None
    assert journal.failures == ["profile_unavailable"] and not journal.completions


@pytest.mark.parametrize("stage", [PNG, JSON, "completion", "stale"])
def test_storage_failure_and_stale_commit_cannot_complete(world, monkeypatch, stage):
    store, client, weights = world
    source, original = library_image(store, Image.new("RGB", SIZE), "set")
    journal = Journal()
    publish = store.publish

    def fault(data, **args):
        if args["media_type"] == stage:
            raise StoreError("store.write_failed", "synthetic write failure")
        return publish(data, **args)

    def commit(record):
        if stage == "stale":
            journal.current = False  # lost after the adapter's check, at the atomic commit
        if stage == "completion":
            raise StoreError("store.write_failed", "synthetic write failure")
        journal.commit(record)

    monkeypatch.setattr(store, "publish", fault)
    with Engine(client.scratch, weights, client.profile, factory=factory) as engine, listening(client.socket, engine):
        if stage == "stale":
            with pytest.raises(StaleClaim):
                run(world, source, journal, commit_completion=commit)
            assert not journal.failures
        else:
            assert run(world, source, journal, commit_completion=commit) is None
            assert journal.failures == ["store_failed"]
    assert not journal.completions
    with store.open(source.version.content.locator) as stream:
        assert stream.read() == original


def test_cache_readback_refuses_missing_or_corrupt_blob_without_a_second_call(world):
    store, client, weights = world
    source, _ = library_image(store, Image.new("RGB", SIZE), "set")
    journal = Journal()
    with Engine(client.scratch, weights, client.profile, factory=factory) as engine, listening(client.socket, engine):
        outcome = run(world, source, journal)
    mask_path = Path(store.root) / outcome.completion.mask.locator
    mask_path.chmod(0o600)
    mask_path.write_bytes(b"corrupt")
    assert run(world, source, journal) is None
    assert journal.failures == ["invalid_output"]
    assert journal.completions == [outcome.completion]
    mask_path.unlink()
    assert run(world, source, journal) is None
    assert journal.failures == ["invalid_output", "store_failed"]


def test_cached_completion_with_wrong_identity_is_never_exposed(world):
    store, client, weights = world
    source, _ = library_image(store, Image.new("RGB", SIZE), "set")
    journal = Journal()
    with Engine(client.scratch, weights, client.profile, factory=factory) as engine, listening(client.socket, engine):
        outcome = run(world, source, journal)
    completion = outcome.completion
    wrong = replace(completion, identity=replace(completion.identity, source_version_id="other version"))
    assert run(world, source, journal, lookup_ready=lambda _: wrong) is None
    assert journal.failures == ["invalid_output"]


@pytest.mark.parametrize(("artifact", "fault"), [
    ("result", "length"), ("result", "hash"), ("result", "media_type"),
    ("mask", "length"), ("mask", "media_type"),
])
def test_cached_observation_must_match_the_readback_descriptor(world, monkeypatch, artifact, fault):
    store, client, weights = world
    source, _ = library_image(store, Image.new("RGB", SIZE), "set")
    journal = Journal()
    with Engine(client.scratch, weights, client.profile, factory=factory) as engine, listening(client.socket, engine):
        outcome = run(world, source, journal)
    completion = outcome.completion
    blob = getattr(completion, artifact)
    sha = "9" * 64 if fault == "hash" else blob.sha256
    media_type = (PNG if artifact == "result" else JSON) if fault == "media_type" else blob.media_type
    wrong = replace(blob, bytes=blob.bytes + (fault == "length"), sha256=sha, media_type=media_type,
                    locator=blob_locator(completion.identity.scope, sha, media_type))
    # Keep the stored bytes, scope, canonical request, identity and other blob
    # fixed even if the changed descriptor needs another valid locator.
    open_blob = store.open
    monkeypatch.setattr(store, "open", lambda ref: open_blob(blob.locator if ref == wrong.locator else ref))
    cached = replace(completion, **{artifact: wrong})
    assert run(world, source, journal, lookup_ready=lambda _: cached) is None
    assert journal.failures == ["invalid_output"]


def test_cached_receipt_for_another_target_cannot_verify_with_the_same_mask(world):
    store, client, weights = world
    source, _ = library_image(store, Image.new("RGB", SIZE), "set")
    journal = Journal()
    with Engine(client.scratch, weights, client.profile, factory=factory) as engine, listening(client.socket, engine):
        first = run(world, source, journal, key="first")
        second = run(world, source, journal, key="second")
    assert first.completion.mask == second.completion.mask
    graft = replace(first.completion, result=second.completion.result)
    assert run(world, source, journal, key="first", lookup_ready=lambda _: graft) is None
    assert journal.failures == ["invalid_output"]


def test_ready_observations_cannot_be_built_by_hand(world):
    store, client, weights = world
    source, _ = library_image(store, Image.new("RGB", SIZE), "set")
    with Engine(client.scratch, weights, client.profile, factory=factory) as engine, listening(client.socket, engine):
        ready = run(world, source, Journal())
    fields = (ready.completion, ready.png, ready.receipt)
    with pytest.raises(TypeError):
        VerifiedObservation(*fields)
    with pytest.raises(TypeError, match="Only the segmentation adapter"):
        VerifiedObservation()
    with pytest.raises(TypeError, match="cannot be subclassed"):
        type("ForgedObservation", (VerifiedObservation,), {})

    allocated = object.__new__(VerifiedObservation)
    with pytest.raises(AttributeError):
        SegmentationOutcome.__init__(allocated, *fields)
    for name, value in zip(("completion", "png", "receipt"), fields, strict=True):
        with pytest.raises(AttributeError):
            object.__setattr__(allocated, name, value)
        with pytest.raises(TypeError, match="Only the segmentation adapter"):
            getattr(allocated, name)


def test_dataclass_initializers_cannot_rewrite_verified_completion(world):
    store, client, weights = world
    source, _ = library_image(store, Image.new("RGB", SIZE), "set")
    journal = Journal()
    with Engine(client.scratch, weights, client.profile, factory=factory) as engine, listening(client.socket, engine):
        ready = run(world, source, journal)

    exposed = ready.completion
    persisted, = journal.completions
    expected_id = exposed.identity.source_version_id
    expected_mask_length = exposed.mask.bytes
    for record in (exposed, persisted):
        identity = record.identity
        type(identity).__init__(identity, identity.production_id, "other source", "9" * 64, identity.profile_sha256)
        mask = record.mask
        type(mask).__init__(mask, mask.sha256, mask.bytes + 1, mask.media_type, mask.locator)
        type(record).__init__(record, identity, record.result, "failed", "invalid_output", mask)

    assert ready.completion.status == "ready" and ready.completion.reason is None
    assert ready.completion.identity.source_version_id == expected_id
    assert ready.completion.mask.bytes == expected_mask_length == len(ready.png)


def test_verified_observation_rejects_mask_and_descriptor_from_another_receipt(world):
    store, client, weights = world
    source, _ = library_image(store, Image.new("RGB", SIZE), "set")
    journal = Journal()
    with Engine(client.scratch, weights, client.profile, factory=factory) as engine, listening(client.socket, engine):
        first = run(world, source, journal)
        second = run(world, source, journal, hint={"kind": "box", "xyxy": [31, 10, 51, 30]})

    # Both artifacts match their own stored descriptors. The first receipt does
    # not describe the second mask, so the mixed triple cannot be verified.
    assert first.png != second.png
    graft = replace(first.completion, mask=second.completion.mask)
    assert run(world, source, journal, lookup_ready=lambda _: graft) is None
    assert journal.failures == ["invalid_output"]
    assert journal.completions == [first.completion, second.completion]


def test_second_client_waits_and_reads_completed_result(world, monkeypatch):
    store, first, weights = world
    source, _ = library_image(store, Image.new("RGB", SIZE), "set")
    journal = Journal()
    entered, release = Event(), Event()
    original = adapter.local_call
    posts, waits = [], []

    def held(path, method, route, payload, **kwargs):
        if method == "POST":
            posts.append(payload)
            entered.set()
            assert release.wait(5)
        return original(path, method, route, payload, **kwargs)

    monkeypatch.setattr(adapter, "local_call", held)
    with Engine(first.scratch, weights, first.profile, factory=factory) as engine, listening(first.socket, engine):
        with ThreadPoolExecutor(max_workers=1) as executor:
            in_flight = executor.submit(run, world, source, journal)
            try:
                assert entered.wait(5)

                def wait(delay):
                    waits.append(delay)
                    release.set()
                    assert in_flight.result(timeout=5).action == "use_mask"

                second = SegmentationClient(first.profile, first.profile_sha256, scratch=first.scratch,
                                            socket=first.socket, pause=wait)
                observed = run(world, source, journal, client=second)
                ready = in_flight.result(timeout=5)
                assert type(observed) is type(ready) is VerifiedObservation
                assert (observed.completion, observed.png, observed.receipt) == (
                    ready.completion, ready.png, ready.receipt,
                )
            finally:
                release.set()
    assert len(posts) == len(waits) == len(journal.completions) == 1


@pytest.mark.parametrize("releases", [True, False])
def test_service_busy_waits_then_recovers_or_stops(world, monkeypatch, releases):
    store, client, weights = world
    source, _ = library_image(store, Image.new("RGB", SIZE), "set")
    journal = Journal()
    run_engine = Engine.run
    attempts, pauses = [], []

    def busy(engine, payload):
        attempts.append(payload["attempt_id"])
        if not releases or len(attempts) == 1:
            raise SegmentationError("busy")
        return run_engine(engine, payload)

    monkeypatch.setattr(adapter, "BUSY_WAITS", 2)
    monkeypatch.setattr(Engine, "run", busy)
    client.pause = pauses.append
    with Engine(client.scratch, weights, client.profile, factory=factory) as engine, listening(client.socket, engine):
        result = run(world, source, journal)
    assert len(set(attempts)) == len(pauses) + 1 == (2 if releases else 3)
    if releases:
        assert result.action == "use_mask" and not journal.failures
    else:
        assert result is None and journal.failures == ["busy"] and not journal.completions


def test_backend_timeout_commits_only_diagnostic(world):
    store, client, weights = world
    source, _ = library_image(store, Image.new("RGB", SIZE), "set")
    journal = Journal()
    context = multiprocessing.get_context("spawn")
    started, release = context.Event(), context.Event()
    with Engine(client.scratch, weights, client.profile, request_seconds=0.2,
                factory=partial(blocking_factory, started=started, release=release)) as engine:
        with listening(client.socket, engine):
            result = run(world, source, journal)
    assert started.is_set()
    assert result.action == "stop" and result.completion.reason == "timeout"
    assert result.completion.mask is None and result.png is None
    assert journal.diagnostics == [result.completion] and not journal.completions
    assert journal.lookup(result.completion.identity) is None


def test_transport_timeout_keeps_scratch_quarantined_and_publishes_nothing(world, monkeypatch):
    store, client, weights = world
    source, _ = library_image(store, Image.new("RGB", SIZE), "set")
    journal = Journal()
    original = adapter.local_call

    def confirmed_files_unconfirmed_reply(path, method, route, payload, **kwargs):
        reply = original(path, method, route, payload, **kwargs)
        if method == "POST":
            raise TimeoutError
        return reply

    with Engine(client.scratch, weights, client.profile, factory=factory) as engine, listening(client.socket, engine):
        monkeypatch.setattr(adapter, "local_call", confirmed_files_unconfirmed_reply)
        assert run(world, source, journal) is None
        attempt, = [p for p in client.scratch.iterdir() if p.is_dir()]
        assert (attempt / "mask.png").exists()
        assert not journal.completions and journal.failures == ["timeout"]
        monkeypatch.setattr(adapter, "local_call", original)
        monkeypatch.setattr(adapter, "SCRATCH_GRACE", 0)
        assert run(world, source, journal).action == "use_mask"
    assert not attempt.exists()


def test_set_version_round_trips_and_layout_metadata_is_immutable(world):
    store, _, _ = world
    image = Image.new("RGB", SIZE)
    declarations = {"foreground": [{"key": "shelf", "label": "shelf", "layer_order": 50}],
                    "focal_props": [{"key": "menu", "label": "menu", "depth": "foreground",
                                     "foreground_role": "shelf", "layer_order": 50}]}
    first, _ = library_image(store, image, "set", config=declarations)
    second_declarations = {**declarations, "foreground": [
        {**declarations["foreground"][0], "hint": {"kind": "point", "xy": [20, 20]}}]}
    second, _ = library_image(store, image, "set", library=first.library, config=second_declarations)
    same, _ = library_image(store, image, "set", library=second.library, config=second_declarations)
    assert second.version.number == 2 and not same.created
    assert first.version.content == second.version.content
    assert second.library.pin(first.version.id) != second.library.pin(second.version.id)
    docs = [second.library.document(item.id) for item in (first.version, second.version)]
    assert Library.from_version_documents(docs).document(first.version.id) == docs[0]


def test_legacy_asset_version_serializes_byte_for_byte():
    document = example("valid/asset-version-cast.json")
    library = Library.from_version_documents([document])
    serialized = canonical_json(library.document(document["id"]))
    assert digest(serialized) == "0bed0e0ba32539363867664eaa51b34706493823e126ba90a8ec12c20d02168d"


def test_set_declarations_validate_kind_keys_and_depth(world):
    store, _, _ = world
    plate, _ = library_image(store, Image.new("RGB", SIZE), "set")
    document = plate.library.document(plate.version.id)
    role = {"key": "shelf", "label": "shelf", "layer_order": 30}
    prop = {"key": "menu", "label": "menu", "depth": "foreground", "foreground_role": "shelf", "layer_order": 30}
    valid = {"foreground": [role], "focal_props": [prop]}
    assert not validate_asset_version({**document, "occlusion": valid})

    cases = [
        ({"foreground": [], "focal_props": []}, "schema.invalid", "/occlusion"),
        ({**valid, "focal_props": [{**prop, "key": "shelf"}]}, "ref.duplicate", "/occlusion/focal_props/0/key"),
        ({**valid, "focal_props": [{**prop, "layer_order": 31}]}, "schema.invalid", "/occlusion/focal_props/0"),
        ({**valid, "focal_props": [{**prop, "foreground_role": "missing"}]},
         "schema.invalid", "/occlusion/focal_props/0"),
    ]
    for block, code, path in cases:
        assert [(v.rule, v.path) for v in validate_asset_version({**document, "occlusion": block})] == [(code, path)]

    cast, _ = library_image(store, Image.new("RGBA", SIZE), "cast")
    assert [(v.rule, v.path) for v in validate_asset_version({**cast.library.document(cast.version.id), "occlusion": valid})] == [
        ("asset.capability_mismatch", "/occlusion"),
    ]


@pytest.mark.parametrize(("group", "fields", "path"), [
    ("foreground", {"key": "shelf\n"}, "/key"),
    ("foreground", {"label": "\ud800"}, "/label"),
    ("foreground", {"label": "cafe\u0301"}, "/label"),
    ("foreground", {"hint": {"kind": "text", "text": "warm\tlight"}}, "/hint/text"),
    ("foreground", {"hint": {"kind": "box", "xyxy": [30, 10, 10, 20]}}, "/hint/xyxy"),
    ("foreground", {"hint": {"kind": "box", "xyxy": [10, 30, 20, 10]}}, "/hint/xyxy"),
    ("foreground", {"hint": {"kind": "box", "xyxy": [30, 10, 30, 20]}}, "/hint/xyxy"),
    ("foreground", {"hint": {"kind": "box", "xyxy": [10, 30, 20, 30]}}, "/hint/xyxy"),
    ("foreground", {"hint": {"kind": "box", "xyxy": [0, 0, 65, 48]}}, "/hint/xyxy"),
    ("foreground", {"hint": {"kind": "box", "xyxy": [0, 0, 64, 49]}}, "/hint/xyxy"),
    ("foreground", {"hint": {"kind": "point", "xy": [64, 10]}}, "/hint/xy"),
    ("focal_props", {"hint": {"kind": "point", "xy": [10, 48]}}, "/hint/xy"),
    ("focal_props", {"depth": "background", "layer_order": 1}, ""),
    ("focal_props", {"depth": "separate", "layer_order": 1}, ""),
    ("focal_props", {"depth": "unspecified", "layer_order": 0}, ""),
])
def test_import_validates_declaration_before_hashing(world, monkeypatch, group, fields, path):
    store, _, _ = world
    entry = {"key": "shelf", "label": "shelf", "layer_order": 30}
    if group == "focal_props":
        entry.update(depth="background", layer_order=0)
    block = {"foreground": [], "focal_props": [], group: [{**entry, **fields}]}
    monkeypatch.setattr("haynes_studio.library.library.pin", lambda *_: pytest.fail("hashed invalid declaration"))
    with pytest.raises(ContractError) as caught:
        library_image(store, Image.new("RGB", SIZE), "set", config=block)
    assert [(v.rule, v.path) for v in caught.value.violations] == [("schema.invalid", f"/occlusion/{group}/0{path}")]


def test_set_import_freezes_declarations_and_refuses_replacing_a_version(world):
    store, _, _ = world
    image = Image.new("RGB", SIZE)
    role = {"key": "shelf", "label": "shelf", "layer_order": 10.0,
            "hint": {"kind": "point", "xy": [12.0, 13.0]}}
    prop = {"key": "menu", "label": "menu", "depth": "background", "layer_order": 0}
    block = {"foreground": [role], "focal_props": [prop]}
    first, _ = library_image(store, image, "set", config=block)
    saved = first.library.document(first.version.id)
    first_pin = first.library.pin(first.version.id)
    role["hint"]["xy"][0] = 14
    prop["label"] = "new menu"
    assert first.library.document(first.version.id) == saved
    assert first.library.pin(first.version.id) == first_pin
    assert type(first.version.occlusion["foreground"][0]["layer_order"]) is int
    assert first.version.occlusion["foreground"][0]["hint"]["xy"] == (12, 13)
    with pytest.raises(TypeError):
        first.version.occlusion["foreground"][0]["key"] = "rewritten"

    for revised in (block, {**block, "foreground": []}, {**block, "focal_props": []}, None):
        with pytest.raises(ContractError) as caught:
            library_image(store, image, "set", library=first.library, config=revised,
                          version_id=first.version.id)
        assert [(v.rule, v.path) for v in caught.value.violations] == [("ref.duplicate", "/version_id")]
    second, _ = library_image(store, image, "set", library=first.library)
    assert second.version.id != first.version.id and second.version.number == 2
    assert second.version.occlusion is None
    assert second.library.document(first.version.id) == saved


def test_existing_version_comparison_includes_declaration_even_if_pins_match(world, monkeypatch):
    store, _, _ = world
    image = Image.new("RGB", SIZE)
    role = {"key": "shelf", "label": "shelf", "layer_order": 10}
    config = {"foreground": [role], "focal_props": []}
    first, _ = library_image(store, image, "set", config=config)
    monkeypatch.setattr("haynes_studio.library.library.pin", lambda *_: "matching pin")
    changed = {**config, "foreground": [{**role, "label": "counter"}]}
    with pytest.raises(ContractError) as caught:
        library_image(store, image, "set", library=first.library, config=changed)
    assert caught.value.violations[0].rule == "idempotency.mismatch"


def test_focal_prop_hint_uses_the_separate_still_dimensions(world):
    store, _, _ = world
    cutout, _ = library_image(store, Image.new("RGBA", (32, 32)), "prop")
    prop = {"key": "menu", "label": "menu", "depth": "separate", "layer_order": 10,
            "source_asset_version_id": cutout.version.id, "hint": {"kind": "box", "xyxy": [0, 0, 32, 32]}}
    role = {"key": "shelf", "label": None, "layer_order": 10}
    block = {"foreground": [], "focal_props": [prop]}
    image = Image.new("RGB", SIZE)
    assert library_image(store, image, "set", library=cutout.library, config=block)[0].created
    with pytest.raises(ContractError) as caught:
        library_image(store, image, "set", library=cutout.library, config={**block, "foreground": [role]})
    assert [(v.rule, v.path) for v in caught.value.violations] == [
        ("ref.duplicate", "/occlusion/focal_props/0/layer_order"),
    ]
    prop["hint"]["xyxy"][2] = 33
    with pytest.raises(ContractError) as caught:
        library_image(store, image, "set", library=cutout.library, config=block)
    assert [(v.rule, v.path) for v in caught.value.violations] == [
        ("schema.invalid", "/occlusion/focal_props/0/hint/xyxy"),
    ]
    # Archive imports can refer to a still whose dimensions have not been recorded.
    standalone, _ = library_image(store, image, "set", config=block)
    assert standalone.created
    with pytest.raises(ContractError) as caught:
        Library.from_version_documents([standalone.library.document(standalone.version.id),
                                        cutout.library.document(cutout.version.id)])
    assert [(v.rule, v.path) for v in caught.value.violations] == [
        ("schema.invalid", "/occlusion/focal_props/0/hint/xyxy"),
    ]


def test_stored_hint_defaults_and_explicit_hint_is_a_new_request(world, monkeypatch):
    store, client, weights = world
    stored_hint = {"kind": "box", "xyxy": [0, 35, 64, 48]}
    source, _ = library_image(
        store, Image.new("RGB", SIZE), "set",
        config={"foreground": [{"key": "table", "label": "table", "layer_order": 30, "hint": stored_hint}],
                "focal_props": []},
    )
    journal = Journal()
    sent = []
    original = adapter.local_call

    def record(path, method, route, payload, **kwargs):
        if method == "POST":
            sent.append(payload["request"])
        return original(path, method, route, payload, **kwargs)

    monkeypatch.setattr(adapter, "local_call", record)
    with Engine(client.scratch, weights, client.profile, factory=factory) as engine, listening(client.socket, engine):
        auto = run(world, source, journal, kind="foreground", key="table", label=None)
        manual = run(world, source, journal, kind="foreground", key="table", label=None,
                     hint={"kind": "box", "xyxy": [0, 36, 64, 48]})
    assert auto.action == manual.action == "use_mask"
    assert sent[0]["hint"] == stored_hint and sent[0]["target"]["label"] == "table"
    assert auto.completion.identity.request_sha256 != manual.completion.identity.request_sha256


def test_waits_out_real_busy_inference_on_the_socket(world):
    from haynes_studio.assets.occlusion import make_request
    from haynes_studio.segmentation.smoke import stage

    store, client, weights = world
    source, data = library_image(store, Image.new("RGB", SIZE), "set")
    journal = Journal()
    proc = multiprocessing.get_context("spawn")
    started, release = proc.Event(), proc.Event()
    request = make_request({"sha256": digest(data), "width": SIZE[0], "height": SIZE[1]},
                           kind="prop", key="first", label="menu", hint=None)
    first_attempt = stage(client.scratch, data, request)
    with Engine(client.scratch, weights, client.profile,
                factory=partial(blocking_factory, started=started, release=release)) as engine:
        with listening(client.socket, engine), ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(adapter.local_call, client.socket, "POST", "/v1/segment", first_attempt)
            try:
                assert started.wait(5)
                pauses = []

                def wait(delay):
                    pauses.append(delay)
                    release.set()
                    assert future.result(timeout=5)[0] == 200

                client.pause = wait
                second = run(world, source, journal)
                assert second.action == "use_mask"
                assert pauses == [adapter.BUSY_INTERVAL]
            finally:
                release.set()
