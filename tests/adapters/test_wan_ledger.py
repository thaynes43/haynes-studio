"""The legacy ledger reader is read-only by construction and reads through fakes."""

from __future__ import annotations

import ast
import hashlib
import inspect
import io
import json
import os
import pathlib
import re
import sys

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
# Every call the three ledger snippets make, by full name, and the read-only methods
# they call on values (a path's resolve, a dict's get). A snippet may also call a
# function it defines itself.
ALLOWED_CALLS = {"print", "sorted", "isinstance", "len", "SystemExit", "ValueError", "bytearray",
                 "json.loads", "json.dumps", "pathlib.Path", "re.fullmatch", "hashlib.sha256",
                 "sys.stdout.buffer.write", "urllib.request.urlopen", "out.append",
                 "os.open", "os.fstat", "os.read", "os.close", "stat.S_ISREG"}
ALLOWED_METHODS = {"glob", "get", "resolve", "is_relative_to", "hexdigest", "decode", "read",
                   "urlopen"}
# os.open may only take these flags, and must take the first two.
OPEN_FLAGS = {"os.O_RDONLY", "os.O_NOFOLLOW", "os.O_NONBLOCK"}


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
    """An allowlist: every call in the three snippets is one of these. A new call (a
    process, a copy, a POST, a write) fails here until someone reviews it."""
    tree = ast.parse(pinned.load(name).text)
    own = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            called = ast.unparse(node.func)
            base = called.rsplit(".", 1)[-1]
            assert called in ALLOWED_CALLS | own or (base in ALLOWED_METHODS and "." in called), \
                f"{name}: {ast.unparse(node)}"
            if base == "urlopen":
                assert len(node.args) == 1 and not node.keywords, "urlopen with data would POST"
            if called == "os.open":
                assert len(node.args) == 2 and not node.keywords, ast.unparse(node)
                flags = set(re.findall(r"os\.O_\w+", ast.unparse(node.args[1])))
                assert {"os.O_RDONLY", "os.O_NOFOLLOW"} <= flags <= OPEN_FLAGS, ast.unparse(node)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = {a.name for a in node.names} | {getattr(node, "module", None) or ""}
            assert names <= {"hashlib", "json", "os", "pathlib", "re", "stat", "sys",
                             "urllib.request", ""}, name


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


def _asset(path):
    return {"path": path, "bytes": 1, "sha256": "a" * 64}


@pytest.mark.parametrize("change", [
    {"kind": "video"}, {"state": "running"}, {"output": "/etc/passwd.mp4"},
    {"output": "productions/../x.mp4"}, {"sha256": "XYZ"}, {"assets": [{"path": "p"}]},
    {"created_at": "yesterday"},
    # Finding 5: asset paths that fetch_asset's rule would refuse.
    {"assets": [_asset("/etc/passwd")]},
    {"assets": [_asset("voices/line-1.wav")]},
    {"assets": [_asset("/workspace/output/productions/../../jobs/x.json")]},
    {"assets": [_asset("/workspace/output/productions/job/../../secret.wav")]},
    {"assets": [_asset("/workspace/output/productionsX/job/a.wav")]},
    {"assets": [_asset("/workspace/output/productions/")]},
])
def test_get_refuses_a_ledger_that_fails_the_poc_check(change):
    ledger = {**LEDGERS[0], **change}
    with pytest.raises(AdapterError) as caught:
        LedgerReader(FakeRunner(FakeWanLedger([ledger]))).get(ledger["id"])
    assert caught.value.code == errors.RESPONSE_INVALID
    for value in change.values():
        if isinstance(value, str):
            assert value not in str(caught.value)
        if isinstance(value, list) and value and "bytes" in value[0]:
            assert "ledger asset 0 path is not under" in str(caught.value)
            if value[0]["path"] != wan_ledger.ASSET_ROOT:
                assert value[0]["path"] not in str(caught.value)


def test_every_recorded_ledger_asset_path_passes_the_fetch_rule():
    for ledger in LEDGERS:
        assert len(wan_ledger.record_from_document(ledger).assets) == len(ledger["assets"])
        assert all(a["path"].startswith(wan_ledger.ASSET_ROOT) for a in ledger["assets"])


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


def test_list_reports_a_malformed_entry_and_keeps_the_rest():
    good = {"id": "b" * 32, "asset_sha256": []}
    entries = [{"id": "nope"}, {"id": "c" * 32, "asset_sha256": ["XYZ"]}, good, 7]

    class Odd:
        def run(self, command):
            return Completed(0, json.dumps(entries).encode())
    listing = LedgerReader(Odd()).list()
    assert [s.id for s in listing.ledgers] == ["b" * 32]
    assert listing.unreadable == ("entry 0", "c" * 32 + ".json", "entry 3")

    class NotAList:
        def run(self, command):
            return Completed(0, b'{"id": "x"}')
    with pytest.raises(AdapterError) as caught:
        LedgerReader(NotAList()).list()
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
                  "re.fullmatch('[0-9a-f]{32}', ledger_id)", "LIMIT = 67108864",
                  "st.st_size > LIMIT", "st.st_nlink != 1", "stat.S_ISREG(st.st_mode)",
                  "ledger.resolve().is_relative_to(jobs)"):
        assert check in text
    assert wan_ledger.MAX_ASSET_BYTES == 67108864


# The two new snippets, run here against a temporary tree ------------------------------
#
# Each run executes the pinned text in this process with its two /workspace roots
# rewritten to folders under tmp_path, so it opens nothing else, and with sys.argv and
# sys.stdout replaced for the run. Nothing is sent anywhere.

class _Stdout:
    def __init__(self):
        self.buffer = io.BytesIO()
        self.text = io.StringIO()

    def write(self, text):
        return self.text.write(text)

    def flush(self):
        pass


def _run_snippet(monkeypatch, root, name, *args):
    """``(stdout bytes, stdout text, refusal)``: refusal is None when the snippet ran to
    the end, else its SystemExit message or the exception it raised."""
    text = pinned.load(name).text
    for folder in ("/workspace/jobs", "/workspace/output/productions"):
        quoted = repr(folder)
        assert text.count(quoted) <= 1
        text = text.replace(quoted, repr(str(root / folder.lstrip("/"))))
    assert "'/workspace" not in text
    out = _Stdout()
    monkeypatch.setattr(sys, "argv", ["-c", *args])
    monkeypatch.setattr(sys, "stdout", out)
    refusal = None
    try:
        exec(compile(text, name, "exec"), {"__name__": "__main__"})
    except SystemExit as stop:
        refusal = str(stop.code)
    except Exception as error:  # in the pod: a traceback and exit status 1
        refusal = type(error).__name__
    return out.buffer.getvalue(), out.text.getvalue(), refusal


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "pod"
    for folder in ("workspace/jobs", "workspace/output/productions/synthetic-r1", "outside"):
        (root / folder).mkdir(parents=True)
    return root


def _write_ledger(root, ledger, folder="workspace/jobs"):
    path = root / folder / (ledger["id"] + ".json")
    path.write_text(json.dumps(ledger))
    return path


def _asset_ledger(root, data=b"line one", ledger_id="a" * 32):
    asset = root / "workspace/output/productions/synthetic-r1/line-1.wav"
    asset.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    ledger = {**LEDGERS[0], "id": ledger_id,
              "assets": [{"path": str(asset), "bytes": len(data), "sha256": digest}]}
    _write_ledger(root, ledger)
    return asset, digest


def test_list_snippet_answers_like_the_fake_for_the_recorded_ledgers(monkeypatch, tree):
    for ledger in LEDGERS:
        _write_ledger(tree, ledger)
    _, printed, refusal = _run_snippet(monkeypatch, tree, "wan_ledger_list.py")
    assert refusal is None
    fake = FakeWanLedger(LEDGERS).answer("wan_ledger_list.py", None, ())
    assert json.loads(printed) == json.loads(fake.stdout)


def test_list_snippet_skips_a_ledger_that_is_a_symlink_or_not_a_file(monkeypatch, tree):
    """Finding 4: a ledger symlinked out of /workspace/jobs, one symlinked inside it, and
    a folder named like a ledger are each listed as unreadable, by file name only."""
    good = {**LEDGERS[0], "id": "a" * 32}
    _write_ledger(tree, good)
    outside = _write_ledger(tree, {**LEDGERS[1], "id": "b" * 32, "title": "Outside Title"},
                            folder="outside")
    jobs = tree / "workspace/jobs"
    (jobs / ("b" * 32 + ".json")).symlink_to(outside)
    (jobs / ("c" * 32 + ".json")).symlink_to(jobs / ("a" * 32 + ".json"))
    (jobs / ("d" * 32 + ".json")).mkdir()
    _, printed, refusal = _run_snippet(monkeypatch, tree, "wan_ledger_list.py")
    assert refusal is None and "Outside Title" not in printed
    answer = json.loads(printed)
    assert [entry.get("id") for entry in answer if "id" in entry] == ["a" * 32]
    assert [entry for entry in answer if "file" in entry] == [
        {"file": c * 32 + ".json", "error": "unreadable"} for c in "bcd"]


def test_fetch_snippet_prints_a_checked_asset(monkeypatch, tree):
    asset, digest = _asset_ledger(tree)
    data, _, refusal = _run_snippet(monkeypatch, tree, "wan_ledger_fetch.py", "a" * 32, digest)
    assert (refusal, data) == (None, asset.read_bytes())


def test_fetch_snippet_refuses_an_asset_swapped_for_a_symlink_after_the_checks(monkeypatch, tree):
    """Finding 3: the asset passes the path checks, then becomes a symlink to a file
    outside the productions folder with the same bytes; nothing is printed."""
    asset, digest = _asset_ledger(tree)
    secret = tree / "outside" / "same-bytes.wav"
    secret.write_bytes(asset.read_bytes())
    resolved = asset.resolve()
    check = pathlib.PurePath.is_relative_to

    def swap_after_check(self, *other):
        answer = check(self, *other)
        if self == resolved:
            asset.unlink()
            asset.symlink_to(secret)
        return answer
    monkeypatch.setattr(pathlib.PurePath, "is_relative_to", swap_after_check)
    data, _, refusal = _run_snippet(monkeypatch, tree, "wan_ledger_fetch.py", "a" * 32, digest)
    assert asset.is_symlink() and data == b""
    assert refusal == "OSError"  # ELOOP from O_NOFOLLOW


def test_fetch_snippet_refuses_a_hard_linked_asset(monkeypatch, tree):
    """Finding 3: an asset with a second hard link (here, outside the productions folder)
    is refused; so is one that is not a regular file."""
    asset, digest = _asset_ledger(tree)
    os.link(asset, tree / "outside" / "second-name.wav")
    data, _, refusal = _run_snippet(monkeypatch, tree, "wan_ledger_fetch.py", "a" * 32, digest)
    assert (data, refusal) == (b"", "asset has more than one hard link")


def test_fetch_snippet_refuses_an_asset_that_is_not_a_regular_file(monkeypatch, tree):
    asset, digest = _asset_ledger(tree)
    asset.unlink()
    asset.mkdir()
    data, _, refusal = _run_snippet(monkeypatch, tree, "wan_ledger_fetch.py", "a" * 32, digest)
    assert (data, refusal) == (b"", "asset is not a regular file")


@pytest.mark.parametrize("target,refused", [
    ("outside", "ledger path is outside /workspace/jobs"),
    ("inside", "OSError"),  # resolves under /workspace/jobs, but O_NOFOLLOW refuses the link
])
def test_fetch_snippet_refuses_a_symlinked_ledger(monkeypatch, tree, target, refused):
    """Finding 4: the ledger itself is a symlink."""
    asset, digest = _asset_ledger(tree, ledger_id="e" * 32)
    jobs = tree / "workspace/jobs"
    real = jobs / ("e" * 32 + ".json")
    if target == "outside":
        real = real.rename(tree / "outside" / real.name)
    (jobs / ("a" * 32 + ".json")).symlink_to(real)
    data, _, refusal = _run_snippet(monkeypatch, tree, "wan_ledger_fetch.py", "a" * 32, digest)
    assert (data, refusal) == (b"", refused)
