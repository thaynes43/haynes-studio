"""The private input import on the twin of the public records (``tests/importer/twin.py``):
a fake Wan volume on a real folder, the real pinned snippets, the real store, library,
resolver and motion pins. Nothing is sent anywhere."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from dataclasses import replace

import pytest

from haynes_studio.adapters import errors
from haynes_studio.adapters.errors import AdapterError
from haynes_studio.adapters.fakes import FailingRunner, FakeRunner
from haynes_studio.adapters.wan_ledger import MAX_ASSET_BYTES, LedgerReader
from haynes_studio.adapters.wan_volume import MAX_OUTPUT_BYTES, MAX_UPLOAD_BYTES, VolumeReader
from haynes_studio.importer.plan import JOB_OUTPUT, LEDGER_ASSET, LIBRARY, UPLOAD, Item, Plan
from haynes_studio.importer.run import (
    ABSENT,
    HELD,
    MISMATCH,
    NOT_READ,
    STATUSES,
    TO_READ,
    VERIFIED,
    Readers,
    dry_run,
    run_import,
)
from haynes_studio.library.library import Library
from haynes_studio.library.model import locator_for
from haynes_studio.library.resolve import resolve
from haynes_studio.store.base import PRESENT
from haynes_studio.store.local import LocalStore
from tests.importer.twin import twin, twin_volume
from tests.library.fixtures import BY

NOW = "2026-11-13T23:40:00Z"


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        self.t += 0.5
        return self.t


@pytest.fixture
def world(tmp_path):
    t = twin()
    vol = twin_volume(tmp_path / "pod" / "workspace", t)
    (tmp_path / "store").mkdir()
    return t, vol, LocalStore(tmp_path / "store")


def readers(runner):
    return Readers(ledger=LedgerReader(runner), volume=VolumeReader(runner))


def run(t, vol_or_runner, store, *, plan=None, library=None, story=True):
    runner = vol_or_runner if hasattr(vol_or_runner, "run") else FakeRunner(vol_or_runner)
    return run_import(plan or t.plan(), store=store, library=library or t.library,
                      readers=readers(runner), story=t.story if story else None, by=BY,
                      now=lambda: NOW, clock=Clock())


def snapshot(root):
    out = {}
    for folder, dirs, files in os.walk(root):
        for name in sorted(dirs + files):
            path = os.path.join(folder, name)
            st = os.lstat(path)
            out[os.path.relpath(path, root)] = (st.st_ino, st.st_mode, st.st_size, st.st_mtime_ns)
    return out


def only(plan: Plan, *shas: str) -> Plan:
    items = tuple(i for i in plan.items if i.sha256 in shas)
    return replace(plan, items=items, rows=tuple(r for r in plan.rows if r.sha256 in shas))


def row_sha(t, key):
    return next(r.sha256 for r in t.plan().rows if r.key == key)


# The whole import --------------------------------------------------------------------------


def test_every_delivered_hash_is_verified_and_the_story_lacks_only_the_fire_bed(world):
    t, vol, store = world
    result = run(t, vol, store)
    report = result.report
    assert report["stopped"] is None and not result.mismatched
    statuses = Counter((row["role"], row["status"]) for row in report["rows"])
    assert statuses == {
        ("still", VERIFIED): 25, ("set", VERIFIED): 4, ("sfx", VERIFIED): 11,
        ("take", VERIFIED): 38, ("keyframe", VERIFIED): 9, ("doll_loop", VERIFIED): 10,
        ("set_loop", VERIFIED): 1, ("timed_clip", VERIFIED): 11, ("start_image", VERIFIED): 11,
        ("render", VERIFIED): 1,  # set-left-s221: the set's bytes
        ("render", ABSENT): 7, ("bed", ABSENT): 3, ("not_motion", ABSENT): 14}
    # The r4 story resolves against the store's own answers; only the bed is missing.
    lacks = report["lacks"]
    assert [(p["rule"], p["path"]) for p in lacks["story"]] == [
        ("asset.bytes_missing", "/beds/0/asset_version_id")]
    assert lacks["layered_loops"] == []
    assert [v["kind"] for v in lacks["versions_not_held"]] == ["sound"]

    def exists(locator, sha256):
        return store.verify(locator, sha256) == PRESENT
    problems = resolve(t.story, t.library, exists).problems
    assert [p.path for p in problems] == ["/beds/0/asset_version_id"]
    bed = next(r for r in report["rows"] if r["key"] == "r4:bed:sfx/fire-s701.wav")
    assert bed["reason"].startswith("never_delivered") and "D54" in bed["reason"]


def test_each_record_resolves_to_its_existing_version(world):
    t, vol, store = world
    result = run(t, vol, store)
    assert result.library is t.library  # nothing was created
    for item in result.report["hashes"]:
        versions = {v["version_id"] for v in item["versions"]}
        if item["status"] == VERIFIED:
            assert all(v["created"] is False for v in item["versions"])
            assert versions == {v.id for v in t.library.versions.values()
                                if v.content is not None and v.content.sha256 == item["sha256"]}
            for version_id in versions:
                content = t.library.version(version_id).content
                assert content.locator in item["locators"]
                assert store.verify(content.locator, content.sha256) == PRESENT
            for locator in item["locators"]:
                assert store.verify(locator, item["sha256"]) == PRESENT
        else:
            assert versions == set() and item["locators"] == []


def test_each_distinct_hash_is_read_once_and_every_row_is_accounted_for(world):
    t, vol, store = world
    plan = t.plan()
    report = run(t, vol, store).report
    reads = Counter(args[-1] for _, args in vol.runs)
    assert set(reads.values()) == {1} and len(reads) == 68
    assert [row["key"] for row in report["rows"]] == [row.key for row in plan.rows]
    assert {row["status"] for row in report["rows"]} <= set(STATUSES)
    assert all(row["reason"] for row in report["rows"] if row["status"] != VERIFIED)
    totals = report["totals"]
    assert (totals["rows"], totals["hashes"], totals[VERIFIED], totals[ABSENT], totals[MISMATCH]) \
        == (145, 90, 121, 24, 0)
    assert sum(sum(c.values()) for c in totals["by_role"].values()) == 145


def test_the_report_records_where_each_hash_came_from_its_bytes_and_time(world):
    t, vol, store = world
    report = run(t, vol, store).report
    item = next(i for i in report["hashes"] if "r4:still:cutouts/a-proud.png" in i["rows"])
    assert item["read_from"]["kind"] == LEDGER_ASSET and item["attempts"][0]["outcome"] == VERIFIED
    assert item["attempts"][0]["seconds"] == 0.5 and item["bytes_read"] == item["bytes_published"]
    clip = next(i for i in report["hashes"] if i["media_type"] == "video/mp4" and i["status"] == VERIFIED)
    assert clip["read_from"]["kind"] == JOB_OUTPUT
    image = next(i for i in report["hashes"] if any(k.startswith("e0:start_image") for k in i["rows"]))
    assert image["read_from"]["kind"] == UPLOAD
    totals = report["totals"]
    assert totals["bytes_read"] == sum(i["bytes_read"] for i in report["hashes"]) > 0
    assert totals["bytes_published"] == totals["bytes_read"]
    assert (report["started_at"], report["finished_at"]) == (NOW, NOW) and report["elapsed_s"] > 0
    assert report["kind"] == "private-input-import" and report["dry_run"] is False
    json.dumps(report)  # plain JSON


def test_a_second_import_reads_nothing_and_changes_nothing(world, tmp_path):
    t, vol, store = world
    first = run(t, vol, store).report
    before, runs = snapshot(tmp_path / "store"), len(vol.runs)
    second = run(t, vol, store).report
    assert len(vol.runs) == runs  # not one read of the Wan volume
    assert snapshot(tmp_path / "store") == before  # not one write to the store
    assert [(r["key"], r["status"]) for r in second["rows"]] == \
        [(r["key"], r["status"]) for r in first["rows"]]
    assert second["totals"]["bytes_read"] == second["totals"]["bytes_published"] == 0
    held = [i for i in second["hashes"] if i["status"] == VERIFIED]
    assert held and all(i["read_from"] is None and i["attempts"] == [] for i in held)
    assert second["lacks"] == first["lacks"]


def test_a_hash_held_in_one_scope_is_copied_within_the_store_not_read_again(world, tmp_path):
    t, vol, store = world
    plan = t.plan()
    take = next(i for i in plan.items if any(":take:" in k for k in i.rows))
    data = t.data[take.sha256]
    store.publish(data, scope=plan.production_id, media_type=take.media_type)
    two = replace(take, scopes=(LIBRARY, plan.production_id))
    runner = FailingRunner()
    report = run(t, runner, store, plan=replace(plan, items=(two,), rows=tuple(
        r for r in plan.rows if r.sha256 == take.sha256)), story=False).report
    assert runner.calls == []
    item = report["hashes"][0]
    assert item["status"] == VERIFIED and item["read_from"]["kind"] == "store"
    assert store.verify(locator_for(take.sha256, take.media_type, None), take.sha256) == PRESENT


# Every refusal is a named error and no record ---------------------------------------------


def _files(t, vol, item: Item):
    paths = []
    for source in item.sources:
        if source.kind == LEDGER_ASSET:
            paths.append(vol.path(source.path))
        elif source.kind == JOB_OUTPUT:
            paths.append(vol.root / "output" / "video" / f"{source.name}_00001_.mp4")
        else:
            paths.append(vol.root / "input" / "studio-e0" / source.name)
    return paths


def _missing(t, vol, item, path, tmp_path):
    path.unlink()


def _other_bytes(t, vol, item, path, tmp_path):
    os.chmod(path, 0o644)
    path.write_bytes(b"other bytes")


def _oversized(t, vol, item, path, tmp_path):
    if item.sources[0].kind == JOB_OUTPUT:  # its ledger records the size: leave it out
        vol.add_job(item.sources[0].name, None, size=None)
    limit = {LEDGER_ASSET: MAX_ASSET_BYTES, JOB_OUTPUT: MAX_OUTPUT_BYTES, UPLOAD: MAX_UPLOAD_BYTES}
    with open(path, "r+b") as handle:  # sparse
        handle.truncate(limit[item.sources[0].kind] + 1)


def _outside(t, vol, item, path, tmp_path):
    kind = item.sources[0].kind
    if kind == JOB_OUTPUT:
        vol.add_job(item.sources[0].name, None, output="../jobs/elsewhere.mp4", size=None)
    else:  # a ledger asset resolving out of the productions folder
        target = tmp_path / "outside" / path.name
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)


def _link(t, vol, item, path, tmp_path):
    target = path.parent / (".copy-" + path.name)  # a link inside the same folder
    target.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(target)


def _fifo(t, vol, item, path, tmp_path):
    path.unlink()
    os.mkfifo(path)


def _hard_link(t, vol, item, path, tmp_path):
    os.link(path, tmp_path / ("second-name-" + hashlib.sha256(str(path).encode()).hexdigest()[:12]))


CASES = {
    "missing": (_missing, errors.SOURCE_MISSING, ABSENT),
    "other bytes": (_other_bytes, errors.SOURCE_HASH_MISMATCH, MISMATCH),
    "oversized": (_oversized, errors.SOURCE_TOO_LARGE, ABSENT),
    "outside": (_outside, errors.SOURCE_OUTSIDE, ABSENT),
    "link": (_link, errors.SOURCE_LINK, ABSENT),
    "not regular": (_fifo, errors.SOURCE_NOT_REGULAR, ABSENT),
    "hard link": (_hard_link, errors.SOURCE_HARD_LINK, ABSENT),
}
ITEMS = {"still": "r4:still:cutouts/a-proud.png",
         "clip": "e0:clip-records-layers.jsonl:1:layer-a-staring-green",
         "start image": "e0:start_image:a-staring-s301-green.png"}


# An upload's path is built from its hash alone, so it has no recorded path to leave.
COMBINATIONS = [(case, which) for case in sorted(CASES) for which in sorted(ITEMS)
                if (case, which) != ("outside", "start image")]


@pytest.mark.parametrize("case,which", COMBINATIONS)
def test_a_refused_read_is_a_named_error_and_no_record(world, tmp_path, which, case):
    t, vol, store = world
    change, code, status = CASES[case]
    item = t.plan().item(row_sha(t, ITEMS[which]))
    if case == "link" and item.sources[0].kind == LEDGER_ASSET:
        # story 425's fetch snippet resolves the recorded path before its O_NOFOLLOW open,
        # so a link that stays inside the productions folder is followed (and the bytes
        # hash-checked); one that leaves it is refused as outside (case "outside").
        code = errors.SOURCE_OUTSIDE
        change = _outside
    for path in _files(t, vol, item):
        change(t, vol, item, path, tmp_path)
    before = snapshot(tmp_path / "store")
    report = run(t, vol, store, plan=only(t.plan(), item.sha256), story=False).report
    result = report["hashes"][0]
    assert report["stopped"] is None
    assert (result["status"], result["reason"]) == (status, code)
    assert [a["outcome"] for a in result["attempts"]] == [code] * len(item.sources)
    assert result["versions"] == [] and result["locators"] == [] and result["bytes_published"] == 0
    assert snapshot(tmp_path / "store") == before  # no record of any kind
    for scope in item.scopes:
        assert store.verify(locator_for(item.sha256, item.media_type, scope), item.sha256) != PRESENT
    assert {row["status"] for row in report["rows"]} == {status}


def test_the_next_source_is_tried_after_a_refusal_and_reads_stop_at_the_first_good_one(world):
    t, vol, store = world
    item = t.plan().item(row_sha(t, "r4:still:cutouts/a-proud.png"))
    _files(t, vol, item)[0].unlink()  # r1's delivered copy is gone
    report = run(t, vol, store, plan=only(t.plan(), item.sha256), story=False).report
    result = report["hashes"][0]
    assert [a["outcome"] for a in result["attempts"]] == [errors.SOURCE_MISSING, VERIFIED]
    assert result["status"] == VERIFIED and result["read_from"]["ledger_id"] == item.sources[1].name
    assert len(vol.runs) == 2


def test_bytes_the_record_contradicts_are_refused_never_recorded(world, tmp_path):
    t, vol, store = world
    sha = row_sha(t, "r4:still:cutouts/a-proud.png")
    docs = t.library.documents()
    for doc in docs:
        if doc["content"] and doc["content"]["sha256"] == sha:
            doc["content"]["bytes"] += 1  # the record says another size
    library = Library.from_version_documents(docs)
    before = snapshot(tmp_path / "store")
    report = run(t, vol, store, plan=only(t.plan(), sha), library=library, story=False).report
    result = report["hashes"][0]
    assert (result["status"], result["reason"]) == (MISMATCH, "idempotency.mismatch")
    assert result["versions"] == [] and snapshot(tmp_path / "store") == before


@pytest.mark.parametrize("runner,code", [
    (FailingRunner(1, b"Error from server (Forbidden): pods \"wan-video\" is forbidden\n"),
     errors.COMMAND_FAILED),
    (FailingRunner(1, b"PermissionError: [Errno 13] Permission denied\n"), errors.COMMAND_FAILED),
])
def test_a_failure_that_is_not_a_refusal_stops_the_import(world, runner, code):
    t, vol, store = world
    result = run(t, runner, store)
    assert result.stopped["code"] == code and len(runner.calls) == 1  # nothing retried or tried next
    rows = result.report["rows"]
    assert {r["status"] for r in rows} == {ABSENT}
    assert sum(r["reason"].startswith("not_read: the import stopped") for r in rows) > 100
    assert result.report["lacks"] is None


def test_a_timeout_stops_the_import(world):
    t, vol, store = world

    class Slow:
        calls = 0

        def run(self, command):
            Slow.calls += 1
            raise AdapterError(errors.TIMEOUT, command.label, "no answer within 180 s")
    result = run(t, Slow(), store)
    assert result.stopped["code"] == errors.TIMEOUT and Slow.calls == 1


def test_other_bytes_already_at_a_locator_stop_the_import(world, tmp_path):
    t, vol, store = world
    item = t.plan().item(row_sha(t, "r4:still:cutouts/a-proud.png"))
    locator = locator_for(item.sha256, item.media_type, item.scopes[0])
    planted = tmp_path / "store" / locator
    planted.parent.mkdir(parents=True)
    planted.write_bytes(b"not those bytes")
    result = run(t, vol, store, plan=only(t.plan(), item.sha256), story=False)
    assert result.stopped["code"] == "store.hash_mismatch" and vol.runs == []
    assert planted.read_bytes() == b"not those bytes"


# The dry run -----------------------------------------------------------------------------------


def test_the_dry_run_lists_the_plan_and_writes_nothing(world, tmp_path):
    t, vol, store = world
    plan = t.plan()
    before = snapshot(tmp_path)
    report = dry_run(plan, store=store, now=lambda: NOW)
    assert snapshot(tmp_path) == before and vol.runs == []
    assert [r["key"] for r in report["rows"]] == [r.key for r in plan.rows]
    assert Counter(r["would"] for r in report["rows"]) == {TO_READ: 121, NOT_READ: 24}
    assert report["totals"]["reads_at_most"] == sum(len(i.sources) for i in plan.items)
    assert all(h["sources"] for h in report["hashes"] if h["would"] == TO_READ)
    run(t, vol, store)
    after = dry_run(plan, store=store, now=lambda: NOW)
    assert Counter(r["would"] for r in after["rows"]) == {HELD: 121, NOT_READ: 24}
    assert dry_run(plan, store=None, now=lambda: NOW)["rows"] == report["rows"]


def test_the_twin_is_only_hashes_away_from_the_real_records():
    """The twin changes hashes and recorded sizes, nothing else."""
    from tests.importer.twin import public
    p, t = public(), twin()
    assert len(t.library.versions) == len(p.library.versions)
    assert {v.provenance.get("source_key") for v in t.library.versions.values()} == \
        {v.provenance.get("source_key") for v in p.library.versions.values()}
    assert [r["key"] for r in t.recovery_map["rows"]] == [r["key"] for r in p.recovery_map["rows"]]
    for h, s in t.mapping.items():
        assert hashlib.sha256(t.data[s]).hexdigest() == s and h != s
