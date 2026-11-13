"""Stage commit (contract section 8): all blobs, then one create-only completion
record; readers trust only completed stages."""

from __future__ import annotations

import threading

import pytest

from haynes_studio.stages import StageOutput, commit_stage, completed_stage
from haynes_studio.store import (
    COLLISION,
    HASH_MISMATCH,
    MEDIA_TYPE_UNSUPPORTED,
    RECORD_INVALID,
    LocalStore,
    StoreError,
    record_path,
)
from tests.store.helpers import (
    PRD,
    RUN,
    STEPS,
    FailAt,
    InjectedFault,
    assert_every_blob_is_its_hash,
    files,
    plant,
    sha,
    tree,
)

OUTPUTS = {  # three synthetic outputs of one stage, committed in name order
    "s2v_clip:a": (b"synthetic clip a " * 300, "video/mp4"),
    "s2v_clip:b": (b"synthetic clip b " * 200, "video/mp4"),
    "drive:a": (b"synthetic drive track a " * 100, "audio/wav"),
}
SEQUENCE = [f"{what}:{step}" for what in ["blob"] * len(OUTPUTS) + ["record"] for step in STEPS]
RECORD = record_path(PRD, RUN, "segment")


def outputs(changed: str | None = None) -> dict[str, StageOutput]:
    out = {name: StageOutput(data, media) for name, (data, media) in OUTPUTS.items()}
    if changed is not None:
        out[changed] = StageOutput(OUTPUTS[changed][0] + b" (a different render)", OUTPUTS[changed][1])
    return out


def commit(store, changed: str | None = None):
    return commit_stage(store, production_id=PRD, run_id=RUN, stage="segment",
                        outputs=outputs(changed))


def read(store, verify=True):
    return completed_stage(store, production_id=PRD, run_id=RUN, stage="segment",
                           store=store if verify else None)


def assert_no_incomplete_set(root, store) -> None:
    """Either no record, or a record whose every blob is present with its hash."""
    assert_every_blob_is_its_hash(root)
    record = read(store)  # re-hashes every blob it lists, raising if one is not right
    assert record is None or set(record.blobs) == set(OUTPUTS)


@pytest.fixture
def root(tmp_path):
    path = tmp_path / "store"
    path.mkdir()
    return path


def test_a_stage_commits_its_blobs_then_its_record(root):
    calls = FailAt()
    store = LocalStore(root, on_step=calls)
    assert read(store) is None
    record = commit(store)
    assert calls.calls == SEQUENCE
    assert sorted(record.blobs) == sorted(OUTPUTS)
    for name, (data, media) in OUTPUTS.items():
        blob = record.blobs[name]
        assert (blob.sha256, blob.bytes, blob.media_type) == (sha(data), len(data), media)
        assert blob.locator.startswith(f"productions/{PRD}/sha256/")
    assert read(store) == record
    assert (root / RECORD).read_bytes() == record.encode()
    assert files(root, ".staging") == []


def test_a_commit_is_checked_before_anything_is_written(root):
    store = LocalStore(root)
    bad = [
        ({"production_id": "prd_x"}, "id.malformed"),
        ({"run_id": PRD}, "id.type_mismatch"),
        ({"stage": "../segment"}, RECORD_INVALID),
        ({"outputs": {}}, RECORD_INVALID),
        ({"outputs": {"a/b": StageOutput(b"x", "video/mp4")}}, RECORD_INVALID),
        ({"outputs": {"clip": StageOutput(b"x", "video/quicktime")}}, MEDIA_TYPE_UNSUPPORTED),
        # a later output's bad hash is refused before an earlier output is published
        ({"outputs": {**outputs(), "z": StageOutput(b"x", "video/mp4", "BAD")}}, "store.locator_invalid"),
    ]
    for change, code in bad:
        arguments = {"production_id": PRD, "run_id": RUN, "stage": "segment",
                     "outputs": outputs(), **change}
        with pytest.raises(StoreError) as caught:
            commit_stage(store, **arguments)
        assert caught.value.code == code
    with pytest.raises(TypeError):
        commit_stage(store, production_id=PRD, run_id=RUN, stage="segment",
                     outputs={**outputs(), "z": StageOutput("a/str/path.mp4", "video/mp4")})
    assert tree(root) == {}


@pytest.mark.parametrize("index", range(len(SEQUENCE)), ids=lambda i: f"{i:02d}-{SEQUENCE[i]}")
def test_a_crash_after_any_step_leaves_no_incomplete_set(root, index):
    store = LocalStore(root, on_step=FailAt(index=index))
    with pytest.raises(InjectedFault):
        commit(store)
    reader = LocalStore(root)
    record = read(reader)
    # The record exists only once its own link() ran, and then it is complete.
    assert (record is not None) == (index >= SEQUENCE.index("record:link"))
    assert_no_incomplete_set(root, reader)
    # A retry of the same outputs converges on the same record.
    assert commit(reader) == commit(LocalStore(root)) == read(reader)
    assert_no_incomplete_set(root, reader)


@pytest.mark.parametrize("index", range(len(SEQUENCE)), ids=lambda i: f"{i:02d}-{SEQUENCE[i]}")
def test_a_crash_while_recommitting_never_changes_a_finished_stage(root, index):
    finished = commit(LocalStore(root))
    before = tree(root)[RECORD]
    with pytest.raises((InjectedFault, StoreError)) as caught:
        commit(LocalStore(root, on_step=FailAt(index=index)), changed="s2v_clip:b")
    if isinstance(caught.value, StoreError):  # reached the record's link: other bytes
        assert caught.value.code == COLLISION and index > SEQUENCE.index("record:check")
    assert tree(root)[RECORD] == before
    assert read(LocalStore(root)) == finished
    assert_no_incomplete_set(root, LocalStore(root))


def test_a_retried_commit_of_a_finished_stage_cannot_overwrite_it(root):
    store = LocalStore(root)
    finished = commit(store)
    before = tree(root)
    assert commit(store) == finished  # same outputs: idempotent
    published = {path: entry for path, entry in tree(root).items() if path != ".staging"}
    assert published == {path: entry for path, entry in before.items() if path != ".staging"}
    with pytest.raises(StoreError) as caught:
        commit(store, changed="drive:a")
    assert (caught.value.code, caught.value.locator) == (COLLISION, RECORD)
    assert tree(root)[RECORD] == before[RECORD]
    assert read(store) == finished
    assert store.doctor().orphans  # the new render's blob is an orphan, harmless


def test_expected_hashes_are_checked_before_the_record(root):
    store = LocalStore(root)
    wrong = {**outputs(), "drive:a": StageOutput(OUTPUTS["drive:a"][0], "audio/wav",
                                                 expected_sha256=sha(b"something else"))}
    with pytest.raises(StoreError) as caught:
        commit_stage(store, production_id=PRD, run_id=RUN, stage="segment", outputs=wrong)
    assert caught.value.code == HASH_MISMATCH
    assert read(store) is None


def test_a_reader_detects_a_damaged_blob_of_a_completed_stage(root):
    store = LocalStore(root)
    record = commit(store)
    blob = record.blobs["drive:a"]
    path = root / blob.locator
    path.chmod(0o644)
    plant(root, blob.locator, b"damaged")
    assert read(store, verify=False) == record
    with pytest.raises(StoreError) as caught:
        read(store)
    assert (caught.value.code, caught.value.locator) == (HASH_MISMATCH, blob.locator)


def _race(root, changed_second: str | None):
    """Two commits of one stage on two threads, in lockstep at every ``check`` step,
    so each blob link and the record link race (no sleeps)."""
    barrier = threading.Barrier(2, timeout=30)

    def lockstep(step: str) -> None:
        if step.endswith(":check"):
            barrier.wait()

    results: list = [None, None]

    def run(slot: int, changed: str | None) -> None:
        try:
            results[slot] = commit(LocalStore(root, on_step=lockstep), changed=changed)
        except StoreError as error:
            results[slot] = error

    threads = [threading.Thread(target=run, args=(0, None)),
               threading.Thread(target=run, args=(1, changed_second))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not any(thread.is_alive() for thread in threads)
    return results


def test_two_parallel_commits_of_the_same_outputs_both_succeed_with_one_record(root):
    first, second = _race(root, None)
    assert first == second == read(LocalStore(root))
    assert files(root, f"productions/{PRD}/records") == [RECORD]
    assert (root / RECORD).read_bytes() == first.encode()
    assert files(root, ".staging") == []


def test_two_parallel_commits_of_different_outputs_end_with_exactly_one_record(root):
    results = _race(root, "s2v_clip:a")
    errors = [r for r in results if isinstance(r, StoreError)]
    records = [r for r in results if not isinstance(r, StoreError)]
    assert len(errors) == 1 and len(records) == 1
    assert errors[0].code == COLLISION
    assert files(root, f"productions/{PRD}/records") == [RECORD]
    assert read(LocalStore(root)) == records[0]
    assert (root / RECORD).read_bytes() == records[0].encode()
    assert_no_incomplete_set(root, LocalStore(root))
