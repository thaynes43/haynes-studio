"""Run the Studio claim adapter against the pinned service with synthetic inference."""

import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from fcntl import LOCK_EX, flock
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
from haynes_studio.adapters.matting import MattingClient, MattingUnavailable
from haynes_studio.assets.matte import run_matte_job
from haynes_studio.layered.matte_size import SHAPE_INVALID, MatteSize
from haynes_studio.canonical.model import to_document
from haynes_studio.errors import ContractError
from haynes_studio.formats.recipe import recipe_hash, validate_recipe
from haynes_studio.layered import compose
from haynes_studio.layered.errors import CLIP_INVALID, LAYOUT_INVALID, LayeredError
from haynes_studio.layered.photo import _place_still
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


@pytest.mark.parametrize("present_with_wrong_bytes", [False, True])
def test_recorded_matte_repairs_missing_blobs_and_refuses_corruption(world, monkeypatch, present_with_wrong_bytes):
    store, weights, client, _ = world
    original = source(store, np.full((256, 256, 3), 33, dtype=np.uint8))
    requests = []
    dispatch = client.run

    def record_dispatch(request, *args, **kwargs):
        requests.append(request["job_id"])
        return dispatch(request, *args, **kwargs)

    monkeypatch.setattr(client, "run", record_dispatch)
    with Engine(client.scratch, weights, PROFILE, factory=load_fake) as engine:
        with listening(client.socket, engine):
            result, failures = run(world, original)
            assert not failures
            outputs = (to_document(result.version.content), params(result)["mask"], params(result)["receipt_blob"])
            paths = [Path(store.root) / output["locator"] for output in outputs]
            original_bytes = [path.read_bytes() for path in paths]
            if present_with_wrong_bytes:
                paths[0].unlink()
                paths[1].unlink()
                paths[1].write_bytes(b"present, but corrupted")
                paths[1].chmod(0o444)
            else:
                for path in paths:
                    path.unlink()
            replay, failures = run(world, original, library=result.library, job_id=OTHER_JOB)
    if present_with_wrong_bytes:
        assert replay is None
        assert [issue["code"] for issue in failures] == ["store.hash_mismatch"]
        assert requests == [JOB_ID]
        assert not paths[0].exists()
        assert paths[1].read_bytes() == b"present, but corrupted"
    else:
        assert not failures
        assert requests == [JOB_ID, JOB_ID]
        assert not replay.created and replay.version is result.version
        assert [path.read_bytes() for path in paths] == original_bytes


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
    mocked_call = client._call
    requests = []

    def record_call(method, route, *args, **kwargs):
        if method == "POST":
            requests.append(route)
        return mocked_call(method, route, *args, **kwargs)

    client._call = record_call
    with Engine(client.scratch, weights, PROFILE, factory=partial(load_blocking_matte, started=started),
                request_seconds=1) as engine:
        with listening(client.socket, engine):
            assert_failed(world, original, "adapter.timeout")
    assert started.is_set()
    assert requests == ["/v1/matte"]
    assert list(client.scratch.iterdir()) == []


def test_client_timeout_waits_for_late_writes_before_cleaning(world, monkeypatch):
    store, weights, client, _ = world
    original = source(store, np.full((160, 160, 3), 77, dtype=np.uint8))
    context = multiprocessing.get_context("spawn")
    entered, resume = context.Event(), context.Event()
    completed = Event()
    client.timeout = 1
    factory = partial(load_waiting_matte, entered=entered, resume=resume)
    with Engine(client.scratch, weights, PROFILE, factory=factory) as engine:
        run_backend = engine.run

        def signal_result(payload):
            result = run_backend(payload)
            completed.set()
            return result

        def wait_for_quiescence(seconds):
            assert seconds == matting.POST_QUIESCENCE_SECONDS
            assert entered.is_set()
            # The ready endpoint is already green while this request owns the files.
            client.ready()
            (attempt,) = [path for path in client.scratch.iterdir() if path.is_dir()]
            assert (attempt / "input").is_file()
            resume.set()
            assert completed.wait(5)
            assert (attempt / "cutout.png").is_file()
            assert (attempt / "mask.png").is_file()

        client.pause = wait_for_quiescence
        monkeypatch.setattr(engine, "run", signal_result)
        with listening(client.socket, engine):
            assert_failed(world, original, "adapter.timeout")
    assert list(client.scratch.iterdir()) == []


def test_socket_open_timeout_needs_no_quiescence_wait(world, monkeypatch):
    store, weights, client, _ = world
    original = source(store, np.full((256, 256, 3), 33, dtype=np.uint8))
    send = client._call

    def timeout_on_connect(method, *args, **kwargs):
        if method == "POST":
            raise MattingUnavailable("adapter.timeout", "matting", "The socket could not be opened")
        return send(method, *args, **kwargs)

    monkeypatch.setattr(client, "_call", timeout_on_connect)
    monkeypatch.setattr(client, "_ready_after_timeout",
                        lambda **_: pytest.fail("An unopened socket cannot leave active work"))
    with Engine(client.scratch, weights, PROFILE, factory=load_fake) as engine, listening(client.socket, engine):
        with pytest.raises(MattingUnavailable):
            run(world, original, before_dispatch=lambda: None)
    assert list(client.scratch.iterdir()) == []


def test_a_stray_marker_name_in_the_scratch_does_not_stop_matting(world, tmp_path):
    """The scratch is shared with the service. A symlink or a directory that merely has
    a marker's name is not this adapter's: it is left alone and the job still runs."""
    store, weights, client, _ = world
    original = source(store, np.full((256, 256, 3), 33, dtype=np.uint8))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.write_bytes(b"not a marker")
    link = client.scratch / f".studio-matting-{'d' * 32}"
    link.symlink_to(elsewhere)
    directory = client.scratch / f".studio-matting-{'e' * 32}"
    directory.mkdir()
    with Engine(client.scratch, weights, PROFILE, factory=load_fake) as engine:
        with listening(client.socket, engine):
            result, failures = run(world, original)
    assert not failures and result is not None
    assert link.is_symlink() and elsewhere.read_bytes() == b"not a marker"
    assert directory.is_dir()


def test_next_dispatch_sweeps_older_adapter_attempts_only(world, monkeypatch):
    store, weights, client, _ = world
    original = source(store, np.full((256, 256, 3), 33, dtype=np.uint8))
    attempt_id = "a" * 32
    marker = client.scratch / f".studio-matting-{attempt_id}"
    marker.touch()
    os.utime(marker, (1, 1))
    abandoned = client.scratch / attempt_id
    abandoned.mkdir()
    (abandoned / "cutout.png").touch()
    unrelated = client.scratch / ("b" * 32)
    unrelated.mkdir()
    active = client.scratch / ("c" * 32)
    active.mkdir()
    active_marker = client.scratch / f".studio-matting-{active.name}"
    real_call = client._call

    def check_sweep(method, *args, **kwargs):
        if method == "POST":
            assert unrelated.is_dir()
            assert active.is_dir()
            assert not abandoned.exists() and not marker.exists()
        return real_call(method, *args, **kwargs)

    monkeypatch.setattr(client, "_call", check_sweep)
    with Engine(client.scratch, weights, PROFILE, factory=load_fake) as engine:
        with listening(client.socket, engine), active_marker.open("xb") as owner:
            flock(owner, LOCK_EX)
            os.utime(owner.fileno(), (1, 1))
            result, failures = run(world, original)
    assert not failures and result.created
    assert set(client.scratch.iterdir()) == {unrelated, active, active_marker}


def test_busy_retry_budget_ends_without_publication(world, monkeypatch):
    store, _, client, _ = world
    original = source(store, np.full((160, 160, 3), 33, dtype=np.uint8))
    waits = []
    client.pause = waits.append
    monkeypatch.setattr(client, "ready", lambda **kwargs: None)
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
    with pytest.raises(ContractError, match="matting.slot_mismatch"):
        plan_photo(replace(story, format_version_id="fmv_00000000000000000000000002"), board, promoted.library)
    with pytest.raises(ContractError, match="matting.slot_mismatch"):
        plan_photo(story, replace(board, cast=(replace(board.cast[0], slot="b"),)), promoted.library)
    short = replace(story, layouts={"trial": {"height": 81, "x": 0.5, "bottom": TARGET - 1}})
    with pytest.raises(ContractError, match="matting.target_exceeds_frame"):
        plan_photo(short, board, promoted.library)
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


@pytest.mark.parametrize("at_right", [False, True])
def test_layered_placement_checks_the_full_sprite_including_its_fractional_fringe(at_right):
    alpha = np.zeros((160, 160), dtype=np.uint8)
    alpha[20:140, 35:125] = 255
    alpha[65, 5:35] = alpha[65, 125:155] = 64
    rgba = np.zeros((160, 160, 4), dtype=np.uint8)
    rgba[..., 3] = alpha
    cutout = Image.fromarray(rgba)
    frame_width = 360
    # The silhouette alone fits within the horizontal margin by one pixel.
    center = 45 - compose.PAD + 1
    if at_right:
        center = frame_width - center
    slot = compose.Slot(height=120, bottom=500, x=center / frame_width, crop=None)
    measured = measure_shape(alpha, 120)
    compose.place((90, 120), slot, frame_width, "a")
    with pytest.raises(LayeredError) as refused:
        _place_still(cutout, slot, "a", frame_width, 1080, {"target_height_px": 120, "shape": measured})
    assert refused.value.code == LAYOUT_INVALID


@pytest.mark.parametrize(("box", "target"), [
    ((20, 20, 80, 100), 321),
    ((100, 20, 160, 100), 100),
    ((20, 80, 80, 160), 100),
])
def test_matte_size_refuses_excess_upscale_and_trailing_edges(box, target):
    with pytest.raises(matting.AdapterError) as refused:
        MatteSize.measured({"bbox_xyxy": box, "foreground_area_px": 4800}, (160, 160), target)
    assert refused.value.code == SHAPE_INVALID


@pytest.mark.parametrize(("case", "code", "message"), [
    ("changed_measurement", CLIP_INVALID, "differs from its pinned measurement"),
    ("crop", LAYOUT_INVALID, "cannot use a layout crop"),
    ("too_tall", "matting.target_exceeds_frame", "target height 1200 px exceeds frame height 1080 px"),
    ("above_slot", "matting.target_exceeds_frame", "does not fit above its bottom line at 500 px"),
])
def test_layered_placement_refuses_incompatible_matte(case, code, message):
    alpha = np.zeros((400, 200), dtype=np.uint8)
    alpha[20:380, 50:150] = 255
    rgba = np.zeros((400, 200, 4), dtype=np.uint8)
    rgba[..., 3] = alpha
    cutout = Image.fromarray(rgba)
    target = {"too_tall": 1200, "above_slot": 800}.get(case, 360)
    measured = measure_shape(alpha, target)
    if case == "changed_measurement":
        measured["foreground_area_px"] -= 1
    crop = (0, 0, 200, 400) if case == "crop" else None
    # "above_slot": the target fits the frame but not the 500 px above the slot's line.
    slot = compose.Slot(height=360, bottom=500 if case == "above_slot" else 1080, x=0.5, crop=crop)
    with pytest.raises(LayeredError, match=message) as refused:
        _place_still(cutout, slot, "a", 1920, 1080, {"target_height_px": target, "shape": measured})
    assert refused.value.code == code
