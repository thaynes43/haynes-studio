"""Run the Studio claim adapter against the pinned service with synthetic inference."""

import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from functools import partial
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event

import numpy as np
import pytest
from PIL import Image

from haynes_studio.adapters import matting
from haynes_studio.adapters.matting import MattingClient
from haynes_studio.assets.matte import run_matte_job
from haynes_studio.layered.matte_size import SHAPE_INVALID, MatteSize
from haynes_studio.canonical.model import to_document
from haynes_studio.errors import ContractError
from haynes_studio.formats.recipe import recipe_hash, validate_recipe
from haynes_studio.library import EMPTY, Content, Library, Scope, VersionRequest, import_version, promote
from haynes_studio.library.model import CANDIDATE, Licence
from haynes_studio.matting.backend import Engine
from haynes_studio.matting.fixtures import GREEN, bust, score_eyes, score_shape, score_size
from haynes_studio.matting.pixels import encode_png, measure_shape
from haynes_studio.matting.profile import DIM
from haynes_studio.matting.service import listening
from haynes_studio.photo import compose_layered_photo, plan_photo
from haynes_studio.store import LocalStore, StoreError
from tests.assets.test_candidates import BY, JOB_ID, NOW, PRODUCTION_ID
from tests.formats.fixtures import doll_short
from tests.matting.test_backend import (
    GRAPH, PROFILE, fixed_matte, load_blocking_matte, load_fake, load_fixtures, prepared,  # noqa: F401
)
from tests.photo.conftest import base_story

PNG = "image/png"
TARGET = measure_shape(bust().alpha, None)["bbox_height_px"]
OTHER_JOB = "job_00000000000000000000000002"


def shape_matte(image):
    alpha = np.zeros((DIM, DIM), dtype=np.float32)
    mode = image.getpixel((0, 0))[0]
    if mode == 61:
        alpha[:800, 310:714] = 1
    elif mode == 62:
        alpha[410:614, 310:714] = 1
    elif mode == 63:
        alpha[100:900, 495:529] = 1
    else:
        alpha[120:900, 310:325] = 1
        alpha[120:900, 705:720] = 1
    return alpha


def load_shapes(graph):
    assert graph == GRAPH
    return shape_matte


@pytest.fixture
def world(prepared):
    tmp, weights, profile_digest = prepared
    root = tmp / "store"
    root.mkdir()
    store = LocalStore(root)
    scratch = tmp / "scratch"
    scratch.mkdir()
    recipe = doll_short()["recipe"]
    recipe["cast"]["matte_slots"] = {"a": {"target_height_px": TARGET}}
    assert not validate_recipe(recipe)
    format_version = {"id": "fmv_00000000000000000000000001", "recipe": recipe,
                      "sha256": recipe_hash(recipe)}
    with TemporaryDirectory(prefix="matte-sock-") as folder:
        socket = Path(folder) / "matte.sock"
        client = MattingClient(PROFILE, profile_digest, scratch=scratch, socket=socket)
        yield store, weights, client, format_version


def source(store, rgb, *, version_number=1, legacy=False, kind="cast"):
    png = encode_png(rgb)
    blob = store.publish(png, scope=PRODUCTION_ID, media_type=PNG)
    height, width = rgb.shape[:2]
    content = Content(blob.sha256, None if legacy else blob.bytes, PNG, blob.locator,
                      None if legacy else width, None if legacy else height)
    return import_version(EMPTY, VersionRequest(
        kind=kind, name="A doll", scope=Scope(PRODUCTION_ID), capabilities=("opaque_photo",),
        content=content, provenance={"origin": "derived" if kind == "photo" else "imported",
                                     "source_key": "import:cast",
                                     "generator": {"role": "image"}, "external": None},
        licence=Licence.unknown("Synthetic fixture"),
        version_id=f"asv_{version_number:026}",
    ), by=BY, now=NOW)


def run(world, original, *, library=None, **changes):
    store, _, client, fmt = world
    failures = []
    arguments = dict(source_version_id=original.version.id, job_id=JOB_ID, production_id=PRODUCTION_ID,
                     format_version=fmt, slot="a", by=BY, now=NOW, store=store, client=client,
                     check_fence=lambda: None, record_failure=lambda **issue: failures.append(issue))
    result = run_matte_job(original.library if library is None else library, **(arguments | changes))
    return result, failures


def params(outcome):
    return to_document(outcome.version.provenance["generator"]["params"])


def image(store, descriptor):
    with store.open(descriptor["locator"]) as data, Image.open(data) as art:
        return art.copy()


def test_verified_edges_green_eyes_and_size_match_with_deterministic_candidates(world):
    store, weights, client, _ = world
    fixtures = [bust(), bust(green=True), bust(smaller=True)]
    results = []
    with Engine(client.scratch, weights, PROFILE, factory=partial(load_fixtures, imperfect=False)) as engine:
        with listening(client.socket, engine):
            for number, fixture in enumerate(fixtures, 1):
                original = source(store, fixture.rgb, version_number=number, legacy=number == 1)
                result, failures = run(world, original, chroma_rgb=GREEN if number == 2 else None)
                assert not failures and result.created
                assert result.version.state == CANDIDATE
                assert result.version.capabilities == ("rgba_cutout", "mask")
                assert result.library.version(original.version.id) is original.version
                assert result.library.latest(result.version.asset_id) is None
                normalized = params(result)
                receipt = normalized["receipt"]
                assert normalized["profile_sha256"] == client.profile_sha256
                assert normalized["image_digest"] == PROFILE.image_digest
                assert normalized["input_signature"] == receipt["input_signature"]
                assert normalized["normalization"]["target_height_px"] == TARGET
                assert Library.from_version_documents(result.library.documents()).version(
                    result.version.id) == result.version
                outputs = result.version.content, normalized["mask"], normalized["receipt_blob"]
                for artifact in (to_document(outputs[0]), *outputs[1:]):
                    with store.open(artifact["locator"]) as handle:
                        assert sha256(handle.read()).hexdigest() == artifact["sha256"]
                cutout = image(store, to_document(outputs[0]))
                alpha = np.asarray(image(store, outputs[1]))
                assert cutout.size == (fixture.rgb.shape[1], fixture.rgb.shape[0])
                assert np.array_equal(np.asarray(cutout)[..., 3], alpha)
                if number == 2:
                    assert all(metric["passed"] for metric in score_eyes(fixture, np.asarray(cutout)).values())
                else:
                    assert all(metric["passed"] for metric in score_shape(fixture, alpha).values())
                size = MatteSize.measured(receipt["shape"], cutout.size, TARGET)
                resized, silhouette, _ = size.sprite(cutout)
                assert silhouette[1] == TARGET
                measured = measure_shape(np.asarray(resized)[..., 3], None)
                assert abs(measured["bbox_height_px"] - TARGET) <= 1
                replay, failures = run(world, original, job_id=OTHER_JOB,
                                       chroma_rgb=GREEN if number == 2 else None)
                assert not failures and replay.version.id == result.version.id
                assert replay.version.content == result.version.content
                assert params(replay)["mask"] == outputs[1]
                cached, failures = run(world, original, library=result.library, job_id=OTHER_JOB,
                                       chroma_rgb=GREEN if number == 2 else None)
                assert not failures and not cached.created and cached.version is result.version
                results.append(receipt["shape"])
    base, _, small = results
    assert all(metric["passed"] for metric in score_size(
        measure_shape(fixtures[0].alpha, TARGET), base,
        measure_shape(fixtures[2].alpha, TARGET), small,
    ).values())
    assert list(client.scratch.iterdir()) == []


@pytest.mark.parametrize(("value", "factory", "code"), [
    (55, load_fake, "adapter.command_failed"),
    (56, load_fake, "adapter.response_invalid"),
    (61, load_shapes, SHAPE_INVALID),
    (62, load_shapes, SHAPE_INVALID),
    (63, load_shapes, SHAPE_INVALID),
    (64, load_shapes, SHAPE_INVALID),
])
def test_refused_matte_only_records_failure(world, value, factory, code):
    store, weights, client, _ = world
    original = source(store, np.full((160, 160, 3), value, dtype=np.uint8))
    with Engine(client.scratch, weights, PROFILE, factory=factory) as engine:
        with listening(client.socket, engine):
            assert_failed(world, original, code)


def assert_failed(world, original, code, **changes):
    store, _, client, _ = world
    root = client.scratch.parent / "store"
    before = set(root.rglob("*.png")) | set(root.rglob("*.json"))
    result, failures = run(world, original, **changes)
    assert result is None
    assert [issue["code"] for issue in failures] == [code]
    assert len(original.library.versions) == 1
    assert set(root.rglob("*.png")) | set(root.rglob("*.json")) == before


def test_unavailable_pin_mismatch_bad_reply_and_bad_source(world, monkeypatch):
    store, weights, client, _ = world
    original = source(store, np.full((160, 160, 3), 33, dtype=np.uint8))
    assert_failed(world, original, "adapter.not_found")
    profile = replace(PROFILE, image_digest="sha256:" + "e" * 64)
    other = MattingClient(profile, sha256(profile.manifest()).hexdigest(),
                          scratch=client.scratch, socket=client.socket)
    with Engine(client.scratch, weights, PROFILE, factory=load_fake) as engine:
        with listening(client.socket, engine):
            assert_failed(world, original, "adapter.pin_mismatch", client=other)
            real_call = matting.local_call

            def corrupt(*args, **kwargs):
                status, reply = real_call(*args, **kwargs)
                if args[1] == "POST":
                    reply["artifacts"]["mask"]["sha256"] = "0" * 64
                return status, reply

            monkeypatch.setattr(matting, "local_call", corrupt)
            assert_failed(world, original, "adapter.response_invalid")
            monkeypatch.setattr(store, "open", lambda _: BytesIO(b"replacement"))
            assert_failed(world, original, "adapter.request_invalid")


def waiting_matte(image, *, entered, resume):
    if image.getpixel((0, 0))[0] == 77:
        entered.set()
        if not resume.wait(8):
            raise RuntimeError("The waiting test matte did not receive a resume signal")
    return fixed_matte(image)


def load_waiting_matte(graph, *, entered, resume):
    assert graph == GRAPH
    return partial(waiting_matte, entered=entered, resume=resume)


def test_concurrent_busy_wait_then_succeeds(world):
    store, weights, client, _ = world
    first = source(store, np.full((256, 256, 3), 77, dtype=np.uint8))
    second = source(store, np.full((256, 256, 3), 33, dtype=np.uint8))
    context = multiprocessing.get_context("spawn")
    entered, resume = context.Event(), context.Event()
    complete = Event()
    waits = []

    def pause(seconds):
        waits.append(seconds)
        assert entered.is_set()
        resume.set()
        assert complete.wait(5)

    client.pause = pause
    factory = partial(load_waiting_matte, entered=entered, resume=resume)
    with Engine(client.scratch, weights, PROFILE, factory=factory) as engine:
        with listening(client.socket, engine), ThreadPoolExecutor(max_workers=1) as pool:
            def first_request():
                outcome = run(world, first)
                complete.set()
                return outcome

            pending = pool.submit(first_request)
            assert entered.wait(5)
            outcome, errors = run(world, second, job_id=OTHER_JOB)
            result, errors_first = pending.result(timeout=5)
    assert waits == [matting.BUSY_INTERVAL]
    assert not errors_first and result.version.state == CANDIDATE
    assert not errors and outcome.version.state == CANDIDATE


def test_hard_timeout_is_recorded_without_replaying(world):
    store, weights, client, _ = world
    original = source(store, np.full((256, 256, 3), 77, dtype=np.uint8))
    started = multiprocessing.get_context("spawn").Event()
    client.pause = lambda _: pytest.fail("Timeout must not dispatch a retry")
    with Engine(client.scratch, weights, PROFILE, factory=partial(load_blocking_matte, started=started),
                request_seconds=1) as engine:
        with listening(client.socket, engine):
            assert_failed(world, original, "adapter.timeout")
    assert started.is_set()


def test_busy_retry_budget_ends_without_publication(world, monkeypatch):
    store, _, client, _ = world
    original = source(store, np.full((160, 160, 3), 33, dtype=np.uint8))
    waits = []
    client.pause = waits.append
    monkeypatch.setattr(client, "ready", lambda: None)
    monkeypatch.setattr(matting, "local_call", lambda *a, **kw: (409, {"code": "adapter.busy"}))
    assert_failed(world, original, "adapter.busy")
    assert waits == [matting.BUSY_INTERVAL] * matting.BUSY_RETRIES


def test_failed_mask_write_never_commits_candidate(world, monkeypatch):
    store, weights, client, _ = world
    original = source(store, np.full((256, 256, 3), 33, dtype=np.uint8))
    publish = store.publish
    calls = []

    def fail_mask(data, **kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            raise StoreError("store.collision", "Synthetic publication failure")
        return publish(data, **kwargs)

    monkeypatch.setattr(store, "publish", fail_mask)
    with Engine(client.scratch, weights, PROFILE, factory=load_fake) as engine:
        with listening(client.socket, engine):
            outcome, failures = run(world, original)
    assert outcome is None and len(original.library.versions) == 1
    assert [failure["code"] for failure in failures] == ["store.collision"]
    assert len(calls) == 2


def test_recipe_target_is_required_in_the_authorized_scope(world):
    store, _, _, fmt = world
    original = source(store, np.full((256, 256, 3), 33, dtype=np.uint8))
    assert_failed(world, original, "adapter.request_invalid", production_id=None)
    assert_failed(world, original, "adapter.request_invalid", slot="absent")
    assert_failed(world, original, "adapter.request_invalid", format_version=fmt | {"sha256": "0" * 64})


def test_layered_photo_places_only_a_manually_promoted_matte_at_the_recipe_height(world):
    store, weights, client, fmt = world
    original = source(store, np.full((256, 256, 3), (230, 20, 20), dtype=np.uint8), kind="photo")
    with Engine(client.scratch, weights, PROFILE, factory=load_fake) as engine:
        with listening(client.socket, engine):
            result, failures = run(world, original)
    assert not failures
    assert result.version.kind == "cast"
    assert result.library.version(original.version.id) == original.version

    background = np.full((64, 64, 3), 255, dtype=np.uint8)
    blob = store.publish(encode_png(background), scope=PRODUCTION_ID, media_type=PNG)
    plate = import_version(result.library, VersionRequest(
        kind="set", name="White plate", scope=Scope(PRODUCTION_ID), capabilities=("opaque_plate",),
        content=Content(blob.sha256, blob.bytes, PNG, blob.locator, 64, 64),
        provenance={"origin": "imported", "source_key": "import:set", "external": None,
                    "generator": {"role": "image"}},
        licence=Licence.unknown("Synthetic fixture"),
    ), by=BY, now=NOW)
    story = base_story()
    board = story.ordered_boards()[0]
    board = replace(board, cast=(replace(board.cast[0], slot="a", asset_version_id=result.version.id),),
                    layout=replace(board.layout, preset="trial", foreground=False), cues=())
    story = replace(story, set=replace(story.set, asset_version_id=plate.version.id),
                    production_id=PRODUCTION_ID, format_version_id=fmt["id"],
                    layouts={"trial": {"height": 81, "x": 0.5, "bottom": 800}})

    with pytest.raises(ContractError, match="ref.unpromoted"):
        plan_photo(story, board, plate.library)
    promoted = promote(plate.library, result.version.id, by=BY, now=NOW)
    plan = plan_photo(story, board, promoted.library)
    assert plan.layers.document()["matte_sizes"]["a"]["target_height_px"] == TARGET

    def fetch(locator, _digest):
        with store.open(locator) as stream:
            return stream.read()

    prepared_photo = compose_layered_photo(plan, fetch=fetch)
    with Image.open(BytesIO(prepared_photo.image.png)) as photo:
        column = np.asarray(photo)[:, photo.width // 2]
    # Over the neutral plate, red minus green reaches 105 at half coverage.
    visible = np.flatnonzero(column[:, 0].astype(int) - column[:, 1] >= 105)
    assert abs(len(visible) - TARGET) <= 1
    assert abs(visible[-1] + 1 - 800) <= 1
