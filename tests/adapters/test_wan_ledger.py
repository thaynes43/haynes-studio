"""The legacy ledger reader is read-only by construction and reads through fakes."""

from __future__ import annotations

import ast
import hashlib
import inspect
import json

import pytest

from haynes_studio.adapters import errors, pinned, wan_ledger
from haynes_studio.adapters.errors import AdapterError, RequestInvalid
from haynes_studio.adapters.fakes import FakeRunner, FakeWanLedger, synthetic_wav
from haynes_studio.adapters.runner import Completed
from haynes_studio.adapters.wan_ledger import LedgerReader
from tests.support.policy import REPO_ROOT

TITLE = REPO_ROOT / "titles" / "the-winter-menu"
LEDGERS = [json.loads((TITLE / e / "production.json").read_text())
           for e in ("evidence", "evidence-r2", "evidence-r3", "evidence-r4")]
WRITE_WORDS = ("write", "publish", "put", "post", "delete", "remove", "unlink", "link", "rename",
               "replace", "save", "upload", "create", "mkdir", "touch", "chmod", "copy", "move")
SNIPPETS = ("wan_ledger_read.py", "wan_ledger_list.py", "wan_ledger_fetch.py")
FORBIDDEN_CALLS = {"write_text", "write_bytes", "unlink", "rename", "replace", "mkdir", "rmdir",
                   "link", "symlink_to", "hardlink_to", "touch", "chmod", "remove", "rmtree",
                   "makedirs", "Request", "open", "urlretrieve", "system", "popen", "run"}


def reader(**fake):
    return LedgerReader(FakeRunner(FakeWanLedger(LEDGERS, **fake)))


def test_reader_has_no_write_method():
    public = {name for name, _ in inspect.getmembers(LedgerReader) if not name.startswith("_")}
    assert public == {"get", "get_command", "list", "list_command", "find", "fetch_asset",
                      "fetch_command"}
    for name in public:
        assert not any(word in name for word in WRITE_WORDS), name


@pytest.mark.parametrize("name", SNIPPETS)
def test_ledger_snippets_only_read(name):
    tree = ast.parse(pinned.load(name).text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            called = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            assert called not in FORBIDDEN_CALLS, f"{name}: {ast.unparse(node)}"
            if called == "urlopen":
                assert len(node.args) == 1 and not node.keywords, "urlopen with data would POST"
        if isinstance(node, ast.Attribute) and node.attr == "write":
            assert ast.unparse(node) == "sys.stdout.buffer.write", f"{name}: {ast.unparse(node)}"


def test_the_ported_read_is_a_get_on_the_api():
    text = pinned.load("wan_ledger_read.py").text
    assert "urlopen('http://127.0.0.1:8080/videos/'+sys.argv[1])" in text


def test_get_returns_a_typed_record():
    record = reader().get(LEDGERS[3]["id"])
    assert record.title == "The Winter Menu" and len(record.assets) == len(LEDGERS[3]["assets"])
    first = record.assets[0]
    assert record.asset(first.sha256) == first and record.asset("0" * 64) is None
    with pytest.raises(TypeError):
        record.document["id"] = "x"  # read-only


def test_get_unknown_ledger_is_not_found():
    with pytest.raises(AdapterError) as caught:
        reader().get("f" * 32)
    assert caught.value.code == errors.NOT_FOUND


@pytest.mark.parametrize("ledger_id", ["", "F" * 32, "a" * 31, "../" + "a" * 29, 7])
def test_get_refuses_a_malformed_id_before_running(ledger_id):
    runner = FakeRunner(FakeWanLedger(LEDGERS))
    with pytest.raises(RequestInvalid):
        LedgerReader(runner).get(ledger_id)
    assert runner.calls == []


@pytest.mark.parametrize("change", [
    {"kind": "video"}, {"state": "running"}, {"output": "/etc/passwd.mp4"},
    {"output": "productions/../x.mp4"}, {"sha256": "XYZ"}, {"assets": [{"path": "p"}]},
    {"created_at": "yesterday"},
])
def test_get_refuses_a_ledger_that_fails_the_poc_check(change):
    ledger = {**LEDGERS[0], **change}
    with pytest.raises(AdapterError) as caught:
        LedgerReader(FakeRunner(FakeWanLedger([ledger]))).get(ledger["id"])
    assert caught.value.code == errors.RESPONSE_INVALID
    for value in change.values():
        if isinstance(value, str):
            assert value not in str(caught.value)


def test_get_refuses_an_answer_for_another_ledger():
    class Wrong:
        def run(self, command):
            return Completed(0, json.dumps(LEDGERS[1]).encode())
    with pytest.raises(AdapterError) as caught:
        LedgerReader(Wrong()).get(LEDGERS[0]["id"])
    assert "another ledger" in str(caught.value)


def test_list_and_find():
    listing = reader(unreadable=["0" * 32 + ".json"]).list()
    assert [s.id for s in listing.ledgers] == sorted(ledger["id"] for ledger in LEDGERS)
    assert listing.unreadable == ("0" * 32 + ".json",)
    set_png = "29ab6f47227cee7aa482e83f79cb4aad9949407b4a543f5a33f846119f3c5b58"
    assert {s.id for s in reader().find(set_png)} == {ledger["id"] for ledger in LEDGERS}
    assert [s.id for s in reader().find(LEDGERS[3]["sha256"])] == [LEDGERS[3]["id"]]
    with pytest.raises(RequestInvalid):
        reader().find("abc")


def test_list_refuses_a_malformed_answer():
    class Bad:
        def run(self, command):
            return Completed(0, b'[{"id": "nope"}]')
    with pytest.raises(AdapterError) as caught:
        LedgerReader(Bad()).list()
    assert caught.value.code == errors.RESPONSE_INVALID


def _synthetic_ledger():
    data = synthetic_wav(2400)
    digest = hashlib.sha256(data).hexdigest()
    path = "/workspace/output/productions/synthetic-r1/voices/line-1.wav"
    ledger = {**LEDGERS[0], "id": "a" * 32, "assets": [{"path": path, "bytes": len(data), "sha256": digest}]}
    return ledger, path, data, digest


def test_fetch_asset_returns_hash_checked_bytes():
    ledger, path, data, digest = _synthetic_ledger()
    runner = FakeRunner(FakeWanLedger([ledger], files={path: data}))
    asset = LedgerReader(runner).fetch_asset(ledger["id"], digest, path=path)
    assert (asset.data, asset.sha256, asset.path) == (data, digest, path)
    assert runner.calls[0].argv[-2:] == (ledger["id"], digest)


def test_fetch_asset_refuses_bytes_with_another_hash():
    ledger, path, data, digest = _synthetic_ledger()

    class Liar:
        def run(self, command):
            return Completed(0, data + b"x")
    with pytest.raises(AdapterError) as caught:
        LedgerReader(Liar()).fetch_asset(ledger["id"], digest)
    assert caught.value.code == errors.RESPONSE_INVALID


def test_fetch_asset_reports_a_missing_file():
    ledger, path, data, digest = _synthetic_ledger()
    with pytest.raises(AdapterError) as caught:
        LedgerReader(FakeRunner(FakeWanLedger([ledger]))).fetch_asset(ledger["id"], digest)
    assert caught.value.code == errors.COMMAND_FAILED


def test_fetch_snippet_checks_path_and_hash_in_the_pod():
    text = pinned.load("wan_ledger_fetch.py").text
    for check in ("is_relative_to(base)", "hashlib.sha256(data).hexdigest() != digest",
                  "re.fullmatch('[0-9a-f]{32}', ledger_id)", "st_size > 67108864"):
        assert check in text
    assert wan_ledger.MAX_ASSET_BYTES == 67108864
