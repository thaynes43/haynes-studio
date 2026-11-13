"""Delivering a master through the store (contract section 8, story 381): checked
before anything is written, one completed stage, idempotent, safe to interrupt or
race. Masters are synthetic, 0.5 to 1 s at delivery size, made under ``tmp_path``."""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

import haynes_studio.delivery.publish as deliver_module
from haynes_studio.canonical.model import to_document
from haynes_studio.delivery import (
    MASTER_CHANGED,
    MASTER_INVALID,
    RECORD_INVALID,
    STAGE,
    DeliveryError,
    deliver,
    inspect,
    read_delivery,
    validate_delivery,
)
from haynes_studio.stages import StageOutput, commit_stage
from haynes_studio.store import COLLISION, LocalStore, StoreError, record_path
from tests.delivery.media import write_master
from tests.store.helpers import (
    PRD,
    RUN,
    STEPS,
    FailAt,
    InjectedFault,
    assert_every_blob_is_its_hash,
    files,
    sha,
    tree,
)

FRAMES = 12  # 0.5 s
NOW = datetime(2026, 11, 13, 12, 0, 0, tzinfo=UTC)
DLV = "dlv_01M79V9FC00000000000000009"
RECORD = record_path(PRD, RUN, STAGE)
# A delivery publishes the master, the proxy and its document, then the record.
SEQUENCE = [f"{what}:{step}" for what in ["blob"] * 3 + ["record"] for step in STEPS]


@pytest.fixture
def root(tmp_path):
    path = tmp_path / "store"
    path.mkdir()
    return path


@pytest.fixture(scope="module")
def master(tmp_path_factory):
    return write_master(tmp_path_factory.mktemp("master") / "final.mp4", frames=FRAMES)


@pytest.fixture(scope="module")
def other_master(tmp_path_factory):
    return write_master(tmp_path_factory.mktemp("other") / "final.mp4", frames=FRAMES, seed=1,
                        audio_samples=FRAMES * 2000 - 500)


def run(store, master, **change):
    arguments = {"store": store, "production_id": PRD, "run_id": RUN,
                 "expected_frames": FRAMES, "delivery_id": DLV, "now": NOW, **change}
    return deliver(master, **arguments)


def test_a_master_delivers_to_a_verified_master_and_proxy(root, master, tmp_path):
    calls = FailAt()
    store = LocalStore(root, on_step=calls)
    delivery = run(store, master, workdir=tmp_path)
    assert calls.calls == SEQUENCE
    document = to_document(delivery)
    assert validate_delivery(document, context="read") == []
    assert (delivery.id, delivery.run_id, delivery.created_at) == (DLV, RUN, "2026-11-13T12:00:00Z")
    assert (delivery.store.adapter, delivery.store.writable, delivery.legacy) == ("local", True, None)
    data = master.read_bytes()
    assert (delivery.master.sha256, delivery.master.bytes) == (sha(data), len(data))
    assert (delivery.master.width, delivery.master.height, delivery.master.frames) == (1080, 1920, FRAMES)
    assert (delivery.proxy.width, delivery.proxy.height, delivery.proxy.frames) == (720, 1280, FRAMES)
    for media in (delivery.master, delivery.proxy):
        assert (media.fps, media.video_codec, media.audio_codec) == (24, "h264", "aac")
        assert media.locator == f"productions/{PRD}/sha256/{media.sha256[:2]}/{media.sha256}.mp4"
        assert sha((root / media.locator).read_bytes()) == media.sha256
        assert (root / media.locator).stat().st_size == media.bytes
    assert delivery.verification.decoded_frames == delivery.verification.expected_frames == FRAMES
    assert delivery.verification.sha256_verified is True
    assert delivery.verification.proxy_under_bytes == 25_000_000
    proxy = inspect(root / delivery.proxy.locator, width=720, height=1280, expected_frames=FRAMES,
                    max_bytes=25_000_000)
    assert proxy.ok and proxy.audio_samples == FRAMES * 2000
    # One record lists the master, the proxy and the delivery document.
    record = json.loads((root / RECORD).read_bytes())
    assert sorted(record["blobs"]) == ["delivery", "master", "proxy"]
    stored = json.loads((root / record["blobs"]["delivery"]["locator"]).read_bytes())
    assert stored == document
    assert read_delivery(LocalStore(root), production_id=PRD, run_id=RUN) == delivery
    assert len(files(root, f"productions/{PRD}/sha256")) == 3
    assert files(root, ".staging") == []
    assert list(tmp_path.glob("studio-delivery-*")) == []  # the scratch folder is gone
    assert_every_blob_is_its_hash(root)


def test_a_video_master_gets_a_landscape_proxy(root, tmp_path):
    master = write_master(tmp_path / "video.mp4", frames=FRAMES, width=1920, height=1080)
    delivery = run(LocalStore(root), master, media_kind="video")
    assert (delivery.master.width, delivery.master.height) == (1920, 1080)
    assert (delivery.proxy.width, delivery.proxy.height) == (1280, 720)


def test_delivering_the_same_master_again_returns_it_and_writes_nothing(root, master):
    first = run(LocalStore(root), master)
    before = tree(root)
    calls = FailAt()
    again = run(LocalStore(root, on_step=calls), master, delivery_id=None, now=None)
    assert again == first
    assert calls.calls == []  # no store step at all
    assert tree(root) == before


@pytest.mark.parametrize("change", [{"expected_frames": FRAMES + 1}, {"media_kind": "video"}])
def test_the_same_master_for_another_frame_count_or_kind_is_a_collision(root, master, change):
    run(LocalStore(root), master)
    before = tree(root)
    with pytest.raises(DeliveryError) as caught:
        run(LocalStore(root), master, **change)
    assert caught.value.code == COLLISION
    assert tree(root) == before


def test_another_master_for_a_delivered_run_is_a_collision(root, master, other_master):
    first = run(LocalStore(root), master)
    before = tree(root)
    with pytest.raises(DeliveryError) as caught:
        run(LocalStore(root), other_master)
    assert caught.value.code == COLLISION
    assert tree(root) == before
    assert read_delivery(LocalStore(root), production_id=PRD, run_id=RUN) == first


# A master with the wrong frame count, size, rate, codec, container or audio is refused
# with a problem naming what was wrong, before anything is written.
BAD_MASTERS = {
    "frame_count": ({"frames": FRAMES - 1}, "frame_count"),
    "frame_size": ({"frames": FRAMES, "width": 1080, "height": 1080}, "frame_size"),
    "frame_size_video": ({"frames": FRAMES, "width": 1920, "height": 1080}, "frame_size"),
    "frame_rate": ({"frames": FRAMES, "fps": 25}, "frame_rate"),
    "video_codec": ({"frames": FRAMES, "video_codec": "mpeg4"}, "video_codec"),
    "audio_codec": ({"frames": FRAMES, "audio_codec": "ac3"}, "audio_codec"),
    "audio_rate": ({"frames": FRAMES, "audio_rate": 44_100}, "audio_rate"),
    "audio_short": ({"frames": FRAMES, "audio_samples": FRAMES * 2000 - 2500}, "audio_duration"),
    "no_audio": ({"frames": FRAMES, "audio_codec": None}, "streams"),
    "quicktime": ({"frames": FRAMES, "container": "mov"}, "container"),
    "matroska": ({"frames": FRAMES, "container": "mkv"}, "container"),
}


@pytest.mark.parametrize("case", sorted(BAD_MASTERS))
def test_a_bad_master_is_refused_before_anything_is_published(root, tmp_path, case):
    arguments, check = BAD_MASTERS[case]
    master = write_master(tmp_path / f"{case}.mp4", **arguments)
    with pytest.raises(DeliveryError) as caught:
        run(LocalStore(root), master)
    assert caught.value.code == MASTER_INVALID
    assert check in {problem.check for problem in caught.value.problems}
    assert check in str(caught.value)
    assert tree(root) == {}


@pytest.mark.parametrize("content", [b"", b"not a video at all", None])
def test_a_file_that_is_no_video_is_refused(root, tmp_path, master, content):
    path = tmp_path / "broken.mp4"
    # None: the first half of a real master, cut off in the middle
    data = master.read_bytes()
    path.write_bytes(data[: len(data) // 2] if content is None else content)
    with pytest.raises(DeliveryError) as caught:
        run(LocalStore(root), path)
    assert caught.value.code == MASTER_INVALID and caught.value.problems
    assert tree(root) == {}


def test_a_master_that_is_not_a_regular_file_is_refused(root, tmp_path):
    with pytest.raises(DeliveryError) as caught:
        run(LocalStore(root), tmp_path)
    assert caught.value.code == MASTER_INVALID
    assert tree(root) == {}


def test_a_master_changed_while_it_is_checked_is_refused(root, tmp_path, master, monkeypatch):
    copy = tmp_path / "final.mp4"
    copy.write_bytes(master.read_bytes())
    real = deliver_module.make_proxy

    def make_proxy_then_change_the_master(*args, **kwargs):
        real(*args, **kwargs)
        with open(copy, "ab") as handle:
            handle.write(b"\0")

    monkeypatch.setattr(deliver_module, "make_proxy", make_proxy_then_change_the_master)
    with pytest.raises(DeliveryError) as caught:
        run(LocalStore(root), copy)
    assert caught.value.code == MASTER_CHANGED
    assert tree(root) == {}


@pytest.mark.parametrize("change, error", [
    ({"production_id": "prd_x"}, StoreError),
    ({"run_id": PRD}, StoreError),
    ({"media_kind": "square"}, ValueError),
    ({"expected_frames": 0}, ValueError),
    ({"expected_frames": 12.0}, ValueError),
    ({"delivery_id": "run_01M79V9FC00000000000000001"}, ValueError),
    ({"threads": 0}, ValueError),
    ({"now": datetime(2026, 11, 13)}, ValueError),
])
def test_arguments_are_checked_before_anything_is_written(root, master, change, error):
    with pytest.raises(error):
        run(LocalStore(root), master, **change)
    assert tree(root) == {}


def test_a_string_path_is_refused(root, master):
    with pytest.raises(TypeError):
        run(LocalStore(root), str(master))
    assert tree(root) == {}


@pytest.mark.parametrize("index", range(len(SEQUENCE)), ids=lambda i: f"{i:02d}-{SEQUENCE[i]}")
def test_an_interrupted_delivery_leaves_one_complete_delivery_or_none(root, master, index):
    with pytest.raises(InjectedFault):
        run(LocalStore(root, on_step=FailAt(index=index)), master)
    reader = LocalStore(root)
    found = read_delivery(reader, production_id=PRD, run_id=RUN)  # re-hashes every blob
    # The delivery exists only once its record's link() ran, and then it is complete.
    assert (found is not None) == (index >= SEQUENCE.index("record:link"))
    assert_every_blob_is_its_hash(root)
    assert files(root, f"productions/{PRD}/records") == ([RECORD] if found else [])
    # Delivering again converges on one complete delivery.
    again = run(reader, master)
    assert again == read_delivery(reader, production_id=PRD, run_id=RUN)
    assert found is None or again == found
    assert_every_blob_is_its_hash(root)


def _race(root, first, second):
    """Two deliveries of one run in lockstep at every store check (a barrier, no
    sleeps), one encoder thread each so the pair stays within 2 threads."""
    barrier = threading.Barrier(2, timeout=60)

    def lockstep(step: str) -> None:
        if step.endswith(":check"):
            barrier.wait()

    results: list = [None, None]

    def go(slot: int, master: Path) -> None:
        try:
            results[slot] = run(LocalStore(root, on_step=lockstep), master, threads=1,
                                delivery_id=None)
        except (DeliveryError, StoreError) as error:
            results[slot] = error

    threads = [threading.Thread(target=go, args=(0, first)),
               threading.Thread(target=go, args=(1, second))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert not any(thread.is_alive() for thread in threads)
    return results


def test_two_parallel_deliveries_of_one_master_end_with_one_delivery(root, master):
    first, second = _race(root, master, master)
    assert first == second == read_delivery(LocalStore(root), production_id=PRD, run_id=RUN)
    assert files(root, f"productions/{PRD}/records") == [RECORD]
    assert_every_blob_is_its_hash(root)


def test_two_parallel_deliveries_of_different_masters_end_with_exactly_one(root, master,
                                                                           other_master):
    results = _race(root, master, other_master)
    errors = [r for r in results if isinstance(r, Exception)]
    deliveries = [r for r in results if not isinstance(r, Exception)]
    assert len(errors) == len(deliveries) == 1
    assert errors[0].code == COLLISION
    assert read_delivery(LocalStore(root), production_id=PRD, run_id=RUN) == deliveries[0]
    assert files(root, f"productions/{PRD}/records") == [RECORD]
    assert_every_blob_is_its_hash(root)


def test_a_delivery_stage_that_is_not_a_delivery_is_refused(root):
    commit_stage(LocalStore(root), production_id=PRD, run_id=RUN, stage=STAGE,
                 outputs={"master": StageOutput(b"not a delivery", "video/mp4")})
    with pytest.raises(DeliveryError) as caught:
        read_delivery(LocalStore(root), production_id=PRD, run_id=RUN)
    assert caught.value.code == RECORD_INVALID


def test_a_delivery_document_that_names_other_files_is_refused(root, master, tmp_path):
    delivery = run(LocalStore(root), master)
    document = to_document(delivery)
    document["proxy"] = {**document["master"], "width": 720, "height": 1280}
    other_run = "run_01M79V9FC00000000000000002"
    store = LocalStore(root)
    blobs = {name: store.publish(root / getattr(delivery, name).locator, scope=PRD,
                                 media_type="video/mp4") for name in ("master", "proxy")}
    from haynes_studio.store import StageRecord, canonical_json
    blobs["delivery"] = store.publish(canonical_json({**document, "run_id": other_run}),
                                      scope=PRD, media_type="application/json")
    store.complete_stage(StageRecord(production_id=PRD, run_id=other_run, stage=STAGE,
                                     blobs=blobs))
    with pytest.raises(DeliveryError) as caught:
        read_delivery(store, production_id=PRD, run_id=other_run)
    assert caught.value.code == RECORD_INVALID


def test_no_run_has_a_delivery_until_one_completes(root):
    assert read_delivery(LocalStore(root), production_id=PRD, run_id=RUN) is None
    assert os.listdir(root) == []
