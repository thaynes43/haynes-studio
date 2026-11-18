"""Literal remote programs against a temp volume; no cluster or network calls."""
from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from haynes_studio.adapters.runner import WAN_API, Completed
from haynes_studio.build.validate import validate_run
from haynes_studio.cli import Clients, main
from haynes_studio.private_view import CODE, PrivateViewError, put_private_view
from haynes_studio.stages import StageOutput, commit_stage
from haynes_studio.store import LocalStore, StageRecord, canonical_json
from tests.store.helpers import PRD, RUN

EXAMPLES = Path(__file__).parents[2] / "docs/contracts/examples/valid"
JOB = "test-private-view"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def snapshot(root):
    return {str(p.relative_to(root)): ("link", os.readlink(p)) if p.is_symlink()
            else p.read_bytes() for p in root.rglob("*") if p.is_symlink() or p.is_file()}


class LocalRoute:
    def __init__(self, root):
        self.root = root
        self.calls = []
        self.hook = lambda action, request: None
        self.after = lambda action, request: None
        self.bad = None

    def run(self, command):
        self.calls.append(command)
        if command.label.startswith("private_view."):
            # No shell: the exact source at argv[11], separately encoded parameters.
            action, _root, raw = command.argv[-3:]
            assert command.argv[:11] == WAN_API.argv("")[:11]
            assert command.argv[11] == CODE
            request = json.loads(raw)
            self.hook(action, request)
            if action == self.bad:
                return Completed(1, stderr=b"injected route failure")
            result = subprocess.run(
                [sys.executable, str(Path(__file__).with_name("remote_harness.py")),
                 CODE, action, str(self.root), raw], input=command.stdin,
                capture_output=True, timeout=10, check=False)
            if result.returncode == 0:
                self.after(action, request)
            return Completed(result.returncode, result.stdout, result.stderr)
        self.hook(command.label, {})
        if command.label == self.bad:
            return Completed(1, stderr=b"injected read-back failure")
        jobs = self.root / "jobs"
        if command.label == "wan_ledger.get":
            ledger_id = command.argv[-1]
            answer = json.loads((jobs / (ledger_id + ".json")).read_bytes())
        elif command.label == "wan_ledger.list":
            answer = []
            for path in jobs.glob("*.json"):
                try:
                    doc = json.loads(path.read_bytes())
                    answer.append({**{k: doc[k] for k in
                                      ("id", "title", "state", "output", "bytes", "sha256", "created_at")},
                                   "asset_sha256": [a["sha256"] for a in doc["assets"]]})
                except (ValueError, KeyError):
                    answer.append({"file": path.name, "error": "unreadable"})
        else:
            raise AssertionError(command.label)
        return Completed(0, canonical_json(answer))


@pytest.fixture
def setup(tmp_path):
    (tmp_path / "store").mkdir()
    store = LocalStore(tmp_path / "store")
    delivery = json.loads((EXAMPLES / "delivery.json").read_text())
    blobs = {}
    for name in ("master", "proxy"):
        content = (name + " synthetic test bytes").encode()
        blob = store.publish(content, scope=PRD, media_type="video/mp4")
        blobs[name] = blob
        delivery[name].update(blob.to_document())
    delivery["store"] = {"adapter": "local", "writable": True}
    blobs["delivery"] = store.publish(canonical_json(delivery), scope=PRD,
                                      media_type="application/json")
    # commit_stage also works through the real create-only store and verifies hashes.
    store.complete_stage(StageRecord(
        production_id=PRD, run_id=RUN, stage="delivery", blobs=blobs))
    run = json.loads((EXAMPLES / "run-succeeded.json").read_text())
    run["delivery_id"] = delivery["id"]
    run["outputs"].update(master_sha256=delivery["master"]["sha256"],
                          proxy_sha256=delivery["proxy"]["sha256"])
    assert validate_run(run) == []
    record_run(store, run, extra=True)
    remote = tmp_path / "volume"
    (remote / "output/productions").mkdir(parents=True)
    (remote / "jobs").mkdir()
    route = LocalRoute(remote)
    return dict(store=store, production_id=PRD, run_id=RUN, job=JOB,
                out=tmp_path / "result", runner=route, title="Synthetic private viewing")


def record_run(store, run, *, extra=False, stage="run-0001"):
    outputs = {"run": StageOutput(canonical_json(run), "application/json")}
    if extra:
        outputs["aaa"] = StageOutput(b'{"not":"the run"}', "application/json")
    commit_stage(store, production_id=PRD, run_id=RUN, stage=stage, outputs=outputs)


def folder(args):
    return args["runner"].root / "output/productions" / JOB


def no_served(args):
    assert list((args["runner"].root / "jobs").glob("*.json")) == []


@pytest.mark.parametrize("master", [False, True])
def test_delivery_and_named_run_verified_then_selected_file_plays(setup, master):
    args = setup
    result = put_private_view(**args, master=master)
    played = "final.mp4" if master else "proxy.mp4"
    assert result["plays"] == ("master" if master else "proxy")
    assert result["ledger"]["output"].endswith("/" + played)
    assert result["served_file"]["sha256"] == sha((folder(args) / played).read_bytes())
    assert json.loads((args["out"] / "production.json").read_bytes()) == result
    assert json.loads((folder(args) / "run.json").read_bytes())["id"] == RUN
    assert {a["path"].rsplit("/", 1)[1] for a in result["files"]} == {
        "final.mp4", "proxy.mp4", "run.json", "delivery.json"}
    assert [c.label for c in args["runner"].calls] == [
        "private_view.preflight", "private_view.reserve", *["private_view.copy"] * 4,
        "private_view.verify", "private_view.prepare", "private_view.link", "wan_ledger.get",
        "private_view.fetch", "wan_ledger.list", "private_view.verify"]


def test_check_only_writes_nothing_and_prints_plan(setup):
    args = setup
    before = snapshot(args["out"].parent)
    result = put_private_view(**args, check_only=True)
    assert result["status"] == "check-only" and result["plays"] == "proxy"
    assert len(result["plan"]) == 6
    assert snapshot(args["out"].parent) == before
    assert not args["out"].exists()
    assert [c.label for c in args["runner"].calls] == ["private_view.preflight"]


@pytest.mark.parametrize("when", ["preflight", "reserve"])
def test_existing_folder_is_refused_unchanged(setup, when):
    args = setup
    def plant(action, request):
        if action == when:
            folder(args).mkdir()
            (folder(args) / "kept").write_bytes(b"existing production")
    args["runner"].hook = plant
    with pytest.raises(PrivateViewError):
        put_private_view(**args)
    assert snapshot(folder(args)) == {"kept": b"existing production"}
    no_served(args)


@pytest.mark.parametrize("same_bytes", [False, True])
def test_existing_final_file_is_refused_even_if_identical(setup, same_bytes):
    args = setup
    planted = []
    def plant(action, request):
        if action == "copy" and not planted:
            content = b"master synthetic test bytes" if same_bytes else b"other bytes"
            (folder(args) / request["name"]).write_bytes(content)
            planted.append(content)
    args["runner"].hook = plant
    with pytest.raises(PrivateViewError):
        put_private_view(**args)
    assert (folder(args) / "final.mp4").read_bytes() == planted[0]
    no_served(args)


def test_existing_ledger_is_refused_unchanged(setup):
    args = setup
    winner = []
    def plant(action, request):
        if action == "link":
            path = args["runner"].root / "jobs" / (request["id"] + ".json")
            path.write_bytes(b"another attempt's ledger")
            winner.append(path)
    args["runner"].hook = plant
    with pytest.raises(PrivateViewError):
        put_private_view(**args)
    assert winner[0].read_bytes() == b"another attempt's ledger"
    assert list((args["runner"].root / "jobs").glob("*.json")) == winner


@pytest.mark.parametrize("attack", ["replace-before-link", "move-after-copy", "symlink-after-reserve"])
def test_review_folder_substitutions_are_refused_before_link(setup, attack):
    args = setup
    target = args["out"].parent / "other-production"
    target.mkdir()
    (target / "final.mp4").write_bytes(b"another film")
    initial = snapshot(target)
    done = []
    def swap(action, request):
        when = {"replace-before-link": "link", "move-after-copy": "copy",
                "symlink-after-reserve": "copy"}[attack]
        if action != when or done:
            return
        if attack == "move-after-copy" and request["name"] == "final.mp4":
            return  # move on the second copy, after the master has been written
        folder(args).rename(folder(args).with_name("moved"))
        if attack != "move-after-copy":
            folder(args).symlink_to(target, target_is_directory=True)
        done.append(True)
    args["runner"].hook = swap
    with pytest.raises(PrivateViewError):
        put_private_view(**args)
    assert done and snapshot(target) == initial
    no_served(args)


@pytest.mark.parametrize("bad", ["wan_ledger.get", "fetch", "wan_ledger.list"])
def test_readback_failure_renames_only_own_ledger(setup, bad):
    args = setup
    jobs = args["runner"].root / "jobs"
    neighbor = jobs / "other-file"
    neighbor.write_bytes(b"leave this alone")
    args["runner"].bad = bad
    before_failure = []
    def at_readback(action, request):
        if action == "wan_ledger.get":
            before_failure.append(snapshot(args["runner"].root))
    args["runner"].hook = at_readback
    with pytest.raises(PrivateViewError) as caught:
        put_private_view(**args)
    result = caught.value.record
    assert result["withdrawal"]["withdrawn"] is True
    no_served(args)
    assert neighbor.read_bytes() == b"leave this alone"
    before = before_failure[0]
    served = "jobs/" + result["ledger"]["id"] + ".json"
    renamed = "jobs/.private-view-" + result["ledger"]["id"] + "/withdrawn"
    before[renamed] = before.pop(served)
    assert snapshot(args["runner"].root) == before
    assert json.loads((args["out"] / "production.json").read_bytes())["status"] == "failed"


@pytest.mark.parametrize("change", ["id", "delivery_id", "status", "schema", "master_sha256"])
def test_wrong_run_delivery_or_nonfinal_state_is_refused_before_remote_calls(setup, change):
    args = setup
    # Read the actual first named run output from the store, then add the next stage.
    from haynes_studio.build.run import RunRecords
    run = RunRecords(args["store"], PRD).latest(RUN)
    if change == "status":
        run[change] = "running"
    elif change == "schema":
        run[change] = "wrong/v1"
    elif change == "master_sha256":
        run["outputs"][change] = "0" * 64
    else:
        run[change] = run[change][:-1] + "9"
    record_run(args["store"], run, stage="run-0002")
    with pytest.raises(PrivateViewError, match="private_view.invalid"):
        put_private_view(**args)
    assert args["runner"].calls == [] and not args["out"].exists()


@pytest.mark.parametrize("job", ["../film", "ab", "Film", "a" * 65, "abc/def", "abc\n", "$(id)", "x';raise Exception();#"])
def test_bad_job_names_never_reach_a_runner(setup, job):
    with pytest.raises(PrivateViewError, match="JOB"):
        put_private_view(**{**setup, "job": job})
    assert setup["runner"].calls == []


def test_untrusted_title_stays_json_data_not_shell_or_python_code(setup):
    args = {**setup, "title": "';__import__('os').system('false');# $(touch pwned)\n"}
    result = put_private_view(**args)
    assert result["ledger"]["title"] == args["title"]
    assert not (args["out"].parent / "pwned").exists()
    for command in args["runner"].calls:
        if command.label.startswith("private_view."):
            assert command.argv[11] == CODE and args["title"] not in CODE


def test_cli_check_only_uses_injected_route_and_prints_selected_file(setup):
    args = setup
    out, err = io.StringIO(), io.StringIO()
    status = main(["private-view", RUN, "--store", str(args["store"].root),
                   "--production", PRD, "--job", JOB, "--out", str(args["out"]),
                   "--title", args["title"], "--master", "--check-only"], stdout=out, stderr=err,
                  clients=Clients(lambda: None, lambda: None, lambda: args["runner"]))
    assert status == 0 and err.getvalue() == ""
    assert json.loads(out.getvalue())["plays"] == "master"
    assert not args["out"].exists()


@pytest.mark.parametrize("parent", ["output", "productions", "jobs"])
def test_symlink_parent_is_refused_without_touching_its_target(setup, parent):
    args = setup
    root = args["runner"].root
    path = root / ("output/productions" if parent == "productions" else parent)
    target = path.with_name(path.name + "-moved")
    path.rename(target)
    path.symlink_to(target, target_is_directory=True)
    before = snapshot(root)
    with pytest.raises(PrivateViewError):
        put_private_view(**args)
    assert snapshot(root) == before
    assert not args["out"].exists()


@pytest.mark.parametrize("parent", ["output", "productions", "jobs"])
def test_replaced_parent_after_reservation_is_refused(setup, parent):
    args = setup
    root = args["runner"].root
    path = root / ("output/productions" if parent == "productions" else parent)
    done = []
    def swap(action, request):
        if action == "copy" and not done:
            path.rename(path.with_name(path.name + "-original"))
            path.mkdir()
            if parent == "output":
                (path / "productions" / JOB).mkdir(parents=True)
            elif parent == "productions":
                (path / JOB).mkdir()
            done.append(snapshot(path))
    args["runner"].hook = swap
    with pytest.raises(PrivateViewError):
        put_private_view(**args)
    assert done and snapshot(path) == done[0]
    no_served(args)


@pytest.mark.parametrize("attack", ["symlink", "changed-bytes", "fifo"])
def test_final_file_is_reopened_and_checked_before_link(setup, attack):
    args = setup
    other = args["out"].parent / "other"
    other.write_bytes(b"unchanged by the publisher")
    def plant(action, request):
        if action == "link":
            path = folder(args) / "final.mp4"
            if attack == "changed-bytes":
                path.write_bytes(b"wrong movie")
            else:
                path.rename(folder(args) / "original-master")
                if attack == "symlink":
                    path.symlink_to(other)
                else:
                    os.mkfifo(path)
    args["runner"].hook = plant
    with pytest.raises(PrivateViewError):
        put_private_view(**args)
    no_served(args)
    assert other.read_bytes() == b"unchanged by the publisher"


def test_folder_recreated_after_first_copy_is_not_adopted(setup):
    args = setup
    done = []
    def swap(action, request):
        if action == "copy" and request["name"] == "proxy.mp4":
            folder(args).rename(folder(args).with_name("first-copy-moved"))
            folder(args).mkdir()
            (folder(args) / "other").write_bytes(b"owned by somebody else")
            done.append(True)
    args["runner"].hook = swap
    with pytest.raises(PrivateViewError):
        put_private_view(**args)
    assert done and snapshot(folder(args)) == {"other": b"owned by somebody else"}
    no_served(args)


def test_lost_link_reply_withdraws_using_prepared_identity(setup):
    args = setup
    original = args["runner"].run
    def lost_reply(command):
        result = original(command)
        if command.label == "private_view.link" and result.returncode == 0:
            return Completed(1, stderr=b"lost reply after link")
        return result
    args["runner"].run = lost_reply
    with pytest.raises(PrivateViewError) as caught:
        put_private_view(**args)
    assert caught.value.record["withdrawal"]["withdrawn"] is True
    no_served(args)


def test_substitution_during_readback_withdraws_even_if_folder_moved(setup):
    args = setup
    def swap(action, request):
        if action == "wan_ledger.list":
            folder(args).rename(folder(args).with_name("moved-during-readback"))
    args["runner"].hook = swap
    with pytest.raises(PrivateViewError) as caught:
        put_private_view(**args)
    assert caught.value.record["withdrawal"]["withdrawn"] is True
    no_served(args)


def test_unreadable_listing_is_a_failed_readback_and_withdraws(setup):
    args = setup
    def plant(action, request):
        if action == "wan_ledger.list":
            (args["runner"].root / "jobs" / ("f" * 32 + ".json")).write_bytes(b"not json")
    args["runner"].hook = plant
    with pytest.raises(PrivateViewError) as caught:
        put_private_view(**args)
    assert caught.value.code == "private_view.readback_failed"
    assert caught.value.record["withdrawal"]["withdrawn"] is True
    assert (args["runner"].root / "jobs" / ("f" * 32 + ".json")).read_bytes() == b"not json"


def test_failed_readback_cannot_withdraw_replacement_ledger(setup):
    args = setup
    args["runner"].bad = "fetch"
    replacement = []
    def swap(action, request):
        if action == "withdraw":
            path = args["runner"].root / "jobs" / (request["id"] + ".json")
            path.rename(path.with_suffix(".original"))
            path.write_bytes(b"another writer's replacement")
            replacement.append(path)
    args["runner"].hook = swap
    with pytest.raises(PrivateViewError) as caught:
        put_private_view(**args)
    assert caught.value.code == "private_view.withdraw_failed"
    assert caught.value.record["withdrawal"]["served_name_may_remain"] is True
    assert replacement[0].read_bytes() == b"another writer's replacement"


def test_failed_readback_cannot_overwrite_existing_quarantine_target(setup):
    args = setup
    args["runner"].bad = "fetch"
    target = []
    def plant(action, request):
        if action == "withdraw":
            path = args["runner"].root / "jobs" / (".private-view-" + request["id"]) / "withdrawn"
            path.write_bytes(b"do not replace")
            target.append(path)
    args["runner"].hook = plant
    with pytest.raises(PrivateViewError) as caught:
        put_private_view(**args)
    assert caught.value.code == "private_view.withdraw_failed"
    assert target[0].read_bytes() == b"do not replace"


def test_a_lexically_later_noncontiguous_stage_is_not_the_latest_run(setup):
    args = setup
    commit_stage(args["store"], production_id=PRD, run_id=RUN, stage="run-9999",
                 outputs={"run": StageOutput(b'{"not":"a run"}', "application/json")})
    assert put_private_view(**args)["status"] == "verified"


def test_missing_named_run_output_is_refused_before_remote_calls(setup):
    args = setup
    commit_stage(args["store"], production_id=PRD, run_id=RUN, stage="run-0002",
                 outputs={"other": StageOutput(b'{}', "application/json")})
    with pytest.raises(PrivateViewError, match="invalid"):
        put_private_view(**args)
    assert args["runner"].calls == []


def test_changed_store_media_is_refused_before_remote_calls(setup):
    from haynes_studio.store import StoreError
    args = setup
    paths = list(Path(args["store"].root).rglob("*.mp4"))
    paths[0].chmod(0o600)
    paths[0].write_bytes(b"tampered local media")
    with pytest.raises(StoreError):
        put_private_view(**args)
    assert args["runner"].calls == []


def test_existing_local_output_and_out_inside_store_are_refused(setup):
    args = setup
    args["out"].mkdir()
    existing = args["out"] / "production.json"
    existing.write_bytes(b"existing local record")
    before = snapshot(args["out"])
    with pytest.raises(PrivateViewError):
        put_private_view(**args)
    assert snapshot(args["out"]) == before
    with pytest.raises(PrivateViewError, match="outside"):
        put_private_view(**{**args, "out": Path(args["store"].root) / "new"})
    assert args["runner"].calls == []


def test_low_free_space_stops_readonly_preflight(setup):
    from haynes_studio.adapters.errors import AdapterError
    from haynes_studio.private_view import Route
    args = setup
    before = snapshot(args["runner"].root)
    with pytest.raises(AdapterError):
        Route(args["runner"]).call("preflight", {"job": JOB, "id": "0" * 32, "need": 1 << 70})
    assert snapshot(args["runner"].root) == before
    assert not folder(args).exists()


@pytest.mark.parametrize("when", ["preflight", "reserve"])
def test_existing_ledger_name_in_preflight_is_unchanged(setup, when):
    args = setup
    winner = []
    def plant(action, request):
        if action == when:
            path = args["runner"].root / "jobs" / (request["id"] + ".json")
            path.write_bytes(b"preexisting ledger bytes")
            winner.append(path)
    args["runner"].hook = plant
    with pytest.raises(PrivateViewError):
        put_private_view(**args)
    assert winner[0].read_bytes() == b"preexisting ledger bytes"
    assert not folder(args).exists()


@pytest.mark.parametrize("what", ["ledger", "file"])
def test_wrong_readback_content_is_withdrawn(setup, what):
    args = setup
    original = args["runner"].run
    def wrong_answer(command):
        result = original(command)
        if command.label == ("wan_ledger.get" if what == "ledger" else "private_view.fetch"):
            value = json.loads(result.stdout)
            if what == "ledger":
                value["title"] = "different ledger"
            else:
                value["sha256"] = "0" * 64
            return Completed(0, canonical_json(value))
        return result
    args["runner"].run = wrong_answer
    with pytest.raises(PrivateViewError) as caught:
        put_private_view(**args)
    assert caught.value.code == "private_view.readback_failed"
    assert caught.value.record["withdrawal"]["withdrawn"] is True
    no_served(args)


def test_withdraw_requires_inode_even_when_replacement_bytes_are_identical(setup):
    args = setup
    args["runner"].bad = "fetch"
    replacement = []
    def swap(action, request):
        if action == "withdraw":
            path = args["runner"].root / "jobs" / (request["id"] + ".json")
            content = path.read_bytes()
            path.rename(path.with_suffix(".original"))
            path.write_bytes(content)
            replacement.append(path)
    args["runner"].hook = swap
    with pytest.raises(PrivateViewError) as caught:
        put_private_view(**args)
    assert caught.value.code == "private_view.withdraw_failed"
    assert replacement[0].exists()
    assert "withdrawn" not in snapshot(replacement[0].parent / (".private-view-" + replacement[0].stem))


def test_final_assets_have_one_link_and_failed_copy_has_no_final_name(setup):
    result = put_private_view(**setup)
    assert result["status"] == "verified"
    for name in ("final.mp4", "proxy.mp4", "run.json", "delivery.json"):
        assert (folder(setup) / name).stat().st_nlink == 1
    assert {p.name for p in folder(setup).iterdir()} == {"final.mp4", "proxy.mp4", "run.json", "delivery.json"}


def test_copy_hash_mismatch_has_no_final_name(setup):
    args = setup
    original = args["runner"].run
    def truncated(command):
        if command.label == "private_view.copy":
            from dataclasses import replace
            command = replace(command, stdin=command.stdin[:-1])
        return original(command)
    args["runner"].run = truncated
    with pytest.raises(PrivateViewError):
        put_private_view(**args)
    assert list(folder(args).iterdir()) == []
    no_served(args)


def test_both_local_ledger_validators_run_before_any_write_and_again_before_link(setup, monkeypatch):
    import haynes_studio.private_view as view
    args = setup
    called = []
    route_check, parser_check = view.remote.check_ledger, view.record_from_document
    def route(document):
        called.append("route")
        return route_check(document)
    def parser(document):
        called.append("parser")
        return parser_check(document)
    monkeypatch.setattr(view.remote, "check_ledger", route)
    monkeypatch.setattr(view, "record_from_document", parser)
    def check(action, request):
        if action in ("preflight", "reserve"):
            assert called == ["route", "parser"]
        if action == "link":
            assert called == ["route", "parser", "route", "parser"]
    args["runner"].hook = check
    assert put_private_view(**args)["status"] == "verified"


def test_invalid_cli_job_prints_a_failure_without_route_call(setup):
    args = setup
    out, err = io.StringIO(), io.StringIO()
    result = main(["private-view", RUN, "--store", str(args["store"].root), "--production", PRD,
                   "--job", "../bad", "--out", str(args["out"]), "--title", "Test"],
                  stdout=out, stderr=err,
                  clients=Clients(lambda: None, lambda: None, lambda: args["runner"]))
    assert result == 1 and "private_view.invalid" in err.getvalue()
    assert out.getvalue() == "" and args["runner"].calls == []


def test_corrupted_own_ledger_is_withdrawn_by_identity(setup):
    args = setup
    own_inode = []
    def corrupt(action, request):
        if action == "wan_ledger.get":
            path = next((args["runner"].root / "jobs").glob("*.json"))
            own_inode.append(path.stat().st_ino)
            path.write_bytes(b"corrupted own ledger")
    args["runner"].hook = corrupt
    with pytest.raises(PrivateViewError) as caught:
        put_private_view(**args)
    record = caught.value.record
    assert record["withdrawal"]["withdrawn"] is True
    withdrawn = args["runner"].root / "jobs" / (".private-view-" + record["ledger"]["id"]) / "withdrawn"
    assert withdrawn.stat().st_ino == own_inode[0]
    assert withdrawn.read_bytes() == b"corrupted own ledger"
    no_served(args)
