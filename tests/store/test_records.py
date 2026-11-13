"""Blobs and stage records: canonical bytes, strict reading, and the ledger."""

from __future__ import annotations

import json

import pytest

from haynes_studio.store import (
    BLOB_MISSING,
    COLLISION,
    LOCATOR_INVALID,
    MAX_OUTPUTS,
    RECORD_INVALID,
    Blob,
    LocalStore,
    StageRecord,
    StoreError,
    canonical_json,
    record_path,
)
from tests.store.helpers import PRD, PRD_OTHER, RUN, plant, sha, tree


def _blob(data: bytes, production: str = PRD, ext: str = "wav") -> Blob:
    h = sha(data)
    return Blob(sha256=h, bytes=len(data), media_type="audio/wav",
                locator=f"productions/{production}/sha256/{h[:2]}/{h}.{ext}")


def test_canonical_json_is_sorted_compact_utf8():
    assert canonical_json({"b": 1, "a": [1.5, "é"]}) == '{"a":[1.5,"é"],"b":1}'.encode()
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})


def test_a_record_encodes_canonically_and_round_trips():
    record = StageRecord(PRD, RUN, "voice", {"take:2": _blob(b"2"), "take:1": _blob(b"1")})
    data = record.encode()
    assert list(json.loads(data)["blobs"]) == ["take:1", "take:2"]
    assert data == canonical_json(json.loads(data))
    assert b"_at" not in data and b"time" not in data  # no wall clock (proposal)
    assert StageRecord.decode(data, source="x") == record


@pytest.mark.parametrize("change", [
    lambda d: d.update(extra=1),
    lambda d: d.update(schema="studio.stage-record/v2"),
    lambda d: d.update(blobs={}),
    lambda d: d.update(stage="../voice"),
    lambda d: d.update(run_id=PRD),
    lambda d: d["blobs"]["take:1"].update(sha256="0" * 64),
    lambda d: d["blobs"]["take:1"].update(bytes=-1),
    lambda d: d["blobs"]["take:1"].update(locator="../../etc/passwd"),
    lambda d: d["blobs"]["take:1"].pop("media_type"),
    lambda d: d["blobs"].update({"bad name": d["blobs"]["take:1"]}),
])
def test_a_malformed_record_is_record_invalid(change):
    document = json.loads(StageRecord(PRD, RUN, "voice", {"take:1": _blob(b"1")}).encode())
    change(document)
    with pytest.raises(StoreError) as caught:
        StageRecord.decode(canonical_json(document), source="r.json")
    assert (caught.value.code, caught.value.locator) == (RECORD_INVALID, "r.json")


def test_non_canonical_or_non_json_bytes_are_record_invalid():
    data = StageRecord(PRD, RUN, "voice", {"take:1": _blob(b"1")}).encode()
    for bad in (json.dumps(json.loads(data), indent=1).encode(), b"\xff", b'{"a":1,"a":2}'):
        with pytest.raises(StoreError) as caught:
            StageRecord.decode(bad, source="r.json")
        assert caught.value.code == RECORD_INVALID


def test_a_record_lists_at_most_max_outputs_blobs():
    StageRecord(PRD, RUN, "voice", {f"t:{i}": _blob(str(i).encode()) for i in range(MAX_OUTPUTS)})
    with pytest.raises(StoreError) as caught:
        StageRecord(PRD, RUN, "voice", {f"t:{i}": _blob(str(i).encode())
                                        for i in range(MAX_OUTPUTS + 1)})
    assert caught.value.code == RECORD_INVALID


def test_a_record_names_only_its_own_productions_blobs():
    with pytest.raises(StoreError) as caught:
        StageRecord(PRD, RUN, "voice", {"take:1": _blob(b"1", PRD_OTHER)})
    assert caught.value.code == LOCATOR_INVALID
    with pytest.raises(StoreError) as caught:
        Blob(sha256=sha(b"1"), bytes=1, media_type="image/png", locator=_blob(b"1").locator)
    assert caught.value.code == LOCATOR_INVALID  # extension and media type disagree


def test_the_ledger_is_create_only(tmp_path):
    store = LocalStore(tmp_path)
    take = store.publish(b"1", scope=PRD, media_type="audio/wav")
    other = store.publish(b"2", scope=PRD, media_type="audio/wav")
    assert store.stage_record(PRD, RUN, "voice") is None
    record = store.complete_stage(StageRecord(PRD, RUN, "voice", {"take:1": take}))
    before = tree(tmp_path)
    assert store.complete_stage(StageRecord(PRD, RUN, "voice", {"take:1": take})) == record
    with pytest.raises(StoreError) as caught:
        store.complete_stage(StageRecord(PRD, RUN, "voice", {"take:1": other}))
    assert (caught.value.code, caught.value.locator) == (COLLISION, record_path(PRD, RUN, "voice"))
    path = record_path(PRD, RUN, "voice")
    assert tree(tmp_path)[path] == before[path]
    assert store.stage_record(PRD, RUN, "voice") == record


def test_the_ledger_refuses_a_record_naming_an_unpublished_blob(tmp_path):
    store = LocalStore(tmp_path)
    with pytest.raises(StoreError) as caught:
        store.complete_stage(StageRecord(PRD, RUN, "voice", {"take:1": _blob(b"never published")}))
    assert caught.value.code == BLOB_MISSING
    assert store.stage_record(PRD, RUN, "voice") is None


def test_a_record_file_for_another_stage_is_refused(tmp_path):
    store = LocalStore(tmp_path)
    take = store.publish(b"1", scope=PRD, media_type="audio/wav")
    plant(tmp_path, record_path(PRD, RUN, "mix"),
          StageRecord(PRD, RUN, "voice", {"take:1": take}).encode())
    with pytest.raises(StoreError) as caught:
        store.stage_record(PRD, RUN, "mix")
    assert caught.value.code == RECORD_INVALID


def test_a_symbolic_link_at_a_record_path_is_not_followed(tmp_path):
    (tmp_path / "store").mkdir()
    store = LocalStore(tmp_path / "store")
    take = store.publish(b"1", scope=PRD, media_type="audio/wav")
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_bytes(StageRecord(PRD, RUN, "voice", {"take:1": take}).encode())
    link = tmp_path / "store" / record_path(PRD, RUN, "voice")
    link.parent.mkdir(parents=True)
    link.symlink_to(elsewhere)
    with pytest.raises(StoreError) as caught:
        store.stage_record(PRD, RUN, "voice")
    assert caught.value.code == RECORD_INVALID
    assert store.doctor().unexpected == (record_path(PRD, RUN, "voice"),)
    with pytest.raises(StoreError) as caught:
        store.complete_stage(StageRecord(PRD, RUN, "voice", {"take:1": take}))
    assert caught.value.code == COLLISION
