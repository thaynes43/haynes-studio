"""``store doctor`` reports and removes nothing (D17); the store code holds no delete,
purge, truncate or rename (contract section 8)."""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from haynes_studio.adapters.wan import FileJournal
from haynes_studio.build.live import journal_path
from haynes_studio.store import Blob, LocalStore, StageRecord, record_path
from haynes_studio.store.layout import ROOT_FILES, WAN_JOURNAL, WAN_JOURNAL_LOCK
from tests.store.helpers import PRD, RUN, FailAt, InjectedFault, plant, tree
from tests.support.policy import REPO_ROOT

SOURCES = [REPO_ROOT / "src/haynes_studio/store", REPO_ROOT / "src/haynes_studio/stages"]


@pytest.fixture
def root(tmp_path):
    path = tmp_path / "store"
    path.mkdir()
    return path


def test_an_empty_store_is_clean(root):
    report = LocalStore(root).doctor()
    assert report.clean and report.blobs == 0 and report.records == 0


def test_doctor_lists_orphans_and_leftovers_and_removes_neither(root):
    store = LocalStore(root)
    kept = store.publish(b"take one", scope=PRD, media_type="audio/wav")
    store.complete_stage(StageRecord(PRD, RUN, "voice", {"take:1": kept}))
    orphan = store.publish(b"a clip no stage completed", scope=PRD, media_type="video/mp4")
    library = store.publish(b"a cast still", scope="library", media_type="image/png")
    with pytest.raises(InjectedFault):
        LocalStore(root, on_step=FailAt(step="blob:check")).publish(
            b"interrupted", scope=PRD, media_type="audio/wav")
    plant(root, "library/notes.txt", b"not the layout")
    (root / "library/sha256/zz").mkdir()
    (root / "library/sha256/zz/link.png").symlink_to(root / library.locator)
    plant(root, ".probe/probe-file", b"the NFS probe area is not reported")
    before = tree(root)

    report = store.doctor()
    assert report.orphans == tuple(sorted([orphan.locator, library.locator]))
    assert len(report.staging) == 1 and report.staging[0].startswith(".staging/")
    assert report.unexpected == ("library/notes.txt", "library/sha256/zz/link.png")
    assert (report.blobs, report.records, report.broken_records, report.dangling) == (3, 1, (), ())
    assert not report.clean
    assert tree(root) == before  # nothing removed, moved, or touched

    named = store.doctor(referenced=[library.locator])
    assert named.orphans == (orphan.locator,)
    assert set(report.to_document()) == {"blobs", "records", "orphans", "staging", "unexpected",
                                         "broken_records", "dangling", "damaged", "mismatched",
                                         "foreign", "unreadable", "journal"}
    assert (report.damaged, report.mismatched, report.foreign) == ((), (), ())
    assert tree(root) == before


def test_doctor_reports_broken_and_dangling_records(root):
    store = LocalStore(root)
    missing = Blob(sha256="ab" * 32, bytes=3, media_type="audio/wav",
                   locator=f"productions/{PRD}/sha256/ab/{'ab' * 32}.wav")
    dangling = record_path(PRD, RUN, "mix")
    plant(root, dangling, StageRecord(PRD, RUN, "mix", {"mix": missing}).encode())
    broken = record_path(PRD, RUN, "master")
    plant(root, broken, b'{"schema": "studio.stage-record/v1"}')
    before = tree(root)
    report = store.doctor()
    assert report.dangling == ((dangling, missing.locator),)
    assert [path for path, _why in report.broken_records] == [broken]
    assert tree(root) == before


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads files whatever their mode")
def test_doctor_reports_what_it_cannot_read_and_does_not_stop(root):
    store = LocalStore(root)
    take = store.publish(b"take", scope=PRD, media_type="audio/wav")
    store.complete_stage(StageRecord(PRD, RUN, "voice", {"take:1": take}))
    record = root / record_path(PRD, RUN, "voice")
    locked = root / "library" / "locked"
    locked.mkdir(parents=True)
    record.chmod(0o000)
    locked.chmod(0o000)
    try:
        report = store.doctor()
    finally:
        record.chmod(0o444)
        locked.chmod(0o755)
    assert report.unreadable == (("library/locked", "Permission denied"),)
    assert report.broken_records == ((record_path(PRD, RUN, "voice"), "Permission denied"),)
    assert report.orphans == (take.locator,)  # its record could not be read
    assert not report.clean


def test_the_layout_names_the_files_the_wan_client_keeps_at_the_root(root):
    """The store cannot import the build (``build.live`` imports the store), so its layout
    names the two files; they are the build's journal and the client's lock file."""
    journal = FileJournal(journal_path(root))
    assert (journal.path.parent, journal.path.name, journal.lock_path.name) == (
        root, WAN_JOURNAL, WAN_JOURNAL_LOCK)
    assert ROOT_FILES == (WAN_JOURNAL, WAN_JOURNAL_LOCK)


def _used_journal(root: Path) -> FileJournal:
    """A store root with the journal and its lock file as the Wan client leaves them:
    made by the client's own ``FileJournal`` (its ``created`` line), then one more line."""
    journal = FileJournal(journal_path(root))
    journal.hold()
    journal.release()
    with open(journal.path, "ab") as handle:  # the test's own append, as a later job's
        handle.write(b'{"event": "settle"}\n')
    return journal


def test_doctor_reports_the_wan_journal_under_its_own_heading_and_never_touches_it(root):
    store = LocalStore(root)
    kept = store.publish(b"take one", scope=PRD, media_type="audio/wav")
    store.complete_stage(StageRecord(PRD, RUN, "voice", {"take:1": kept}))
    journal = _used_journal(root)
    plant(root, "notes.txt", b"still not the layout")
    before = tree(root)
    report = store.doctor()
    assert report.unexpected == ("notes.txt",)
    sizes = {WAN_JOURNAL: journal.path.stat().st_size, WAN_JOURNAL_LOCK: 0}
    assert report.to_document()["journal"] == [
        {"path": name, "present": True, "kind": "file", "bytes": sizes[name]}
        for name in ROOT_FILES]
    assert tree(root) == before  # both files byte-identical, same inode, mode and mtime

    # The doctor takes no lock: it reports the same while the client holds the journal.
    journal.hold()
    try:
        assert store.doctor() == report
    finally:
        journal.release()
    assert tree(root) == before
    assert store.doctor(referenced=[kept.locator]).unexpected == ("notes.txt",)


def test_doctor_reports_an_absent_journal_and_a_linked_one_as_journal_files(root):
    report = LocalStore(root).doctor()
    assert report.clean
    assert report.to_document()["journal"] == [
        {"path": name, "present": False, "kind": None, "bytes": None} for name in ROOT_FILES]
    elsewhere = root.parent / "journal-elsewhere.jsonl"
    elsewhere.write_bytes(b"{}\n")
    (root / WAN_JOURNAL).symlink_to(elsewhere)
    before = tree(root)
    report = LocalStore(root).doctor()
    assert report.unexpected == () and report.clean
    assert report.to_document()["journal"] == [
        {"path": WAN_JOURNAL, "present": True, "kind": "link", "bytes": None},
        {"path": WAN_JOURNAL_LOCK, "present": False, "kind": None, "bytes": None}]
    assert tree(root) == before and elsewhere.read_bytes() == b"{}\n"


PY_FILES = [path for base in SOURCES for path in sorted(base.glob("*.py"))]
WRITE_FLAGS = {"O_WRONLY", "O_RDWR", "O_CREAT", "O_TRUNC", "O_APPEND"}


def _call_name(node: ast.Call) -> str:
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    owner = func.value.id if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) else ""
    return f"{owner}.{name}" if owner else name


def _calls(path: Path) -> list[tuple[str, str, ast.Call]]:
    """``(dotted name, enclosing function, node)`` for every call in ``path``."""
    found = []

    def visit(node: ast.AST, function: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) else function
            if isinstance(child, ast.Call):
                found.append((_call_name(child), inner, child))
            visit(child, inner)

    visit(ast.parse(path.read_text(encoding="utf-8")), "<module>")
    return found


def _keywords(call: ast.Call) -> dict[str, ast.expr]:
    return {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg}


def test_the_store_code_never_deletes_truncates_renames_or_chmods():
    forbidden = {"unlink", "remove", "removedirs", "rmdir", "rmtree", "rename", "renames",
                 "truncate", "ftruncate", "chmod", "fchmod", "lchmod", "chown", "fchown",
                 "lchown", "os.replace", "shutil.move", "shutil.rmtree", "shutil.copyfile",
                 "flock", "lockf"}  # nor takes a lock (the Wan journal's, story 860)
    hits = [(name, function, path.name, call) for path in PY_FILES
            for name, function, call in _calls(path)
            if name in forbidden or name.rpartition(".")[2] in forbidden - {"os.replace"}]
    # The one unlink section 8 names: step 4, this publication's own staging name, removed
    # relative to the staging folder's descriptor (unlinkat), never by a path string.
    assert [(name, function, file) for name, function, file, _call in hits] == [
        ("os.unlink", "_finish", "local.py")]
    unlink = hits[0][3]
    assert set(_keywords(unlink)) == {"dir_fd"}
    assert isinstance(unlink.args[0], ast.Attribute) and unlink.args[0].attr == "name"


def test_the_store_code_opens_only_its_staging_file_for_writing():
    """A write flag appears only in ``_CREATE``, which has ``O_EXCL | O_NOFOLLOW`` and
    is used once: the staging file's ``os.open`` relative to the staging folder. Every
    other ``os.open`` is the root itself or relative to a folder descriptor, every file
    object is opened ``"rb"``, ``os.write`` is only the staging stream's, the one
    ``os.link`` links ``/proc/self/fd`` into a folder descriptor, and ``mkdir`` is
    relative to a folder descriptor."""
    local = SOURCES[0] / "local.py"
    module = ast.parse(local.read_text(encoding="utf-8"))
    create = next(node for node in module.body if isinstance(node, ast.Assign)
                  and [getattr(t, "id", None) for t in node.targets] == ["_CREATE"])
    inside = {id(node) for node in ast.walk(create)}
    flags = {node.attr for node in ast.walk(create.value) if isinstance(node, ast.Attribute)}
    assert {"O_EXCL", "O_NOFOLLOW", "O_CREAT"} <= flags and not flags & {"O_TRUNC", "O_APPEND"}
    for path in PY_FILES:
        tree = module if path == local else ast.parse(path.read_text(encoding="utf-8"))
        stray = [node.lineno for node in ast.walk(tree)
                 if isinstance(node, ast.Attribute) and node.attr in WRITE_FLAGS
                 and id(node) not in inside]
        assert stray == [], f"{path.name}: a write flag outside _CREATE at lines {stray}"
    uses = [node for node in ast.walk(module) if isinstance(node, ast.Name)
            and node.id == "_CREATE" and isinstance(node.ctx, ast.Load)]
    assert len(uses) == 1
    calls = [(name, function, call) for path in PY_FILES for name, function, call in _calls(path)]
    opens = [(function, call) for name, function, call in calls if name == "os.open"]
    staging = [(function, call) for function, call in opens
               if any(isinstance(arg, ast.Name) and arg.id == "_CREATE" for arg in call.args)]
    assert [function for function, _call in staging] == ["_open_staging"]
    assert "dir_fd" in _keywords(staging[0][1])
    for function, call in opens:
        root = (isinstance(call.args[0], ast.Attribute) and call.args[0].attr == "root")
        assert root or "dir_fd" in _keywords(call), f"{function}: os.open by a path string"
    for name, function, call in calls:
        if name in ("open", "io.open", "os.fdopen"):
            assert isinstance(call.args[1], ast.Constant) and call.args[1].value == "rb", function
    assert {function for name, function, _call in calls if name == "os.write"} == {"_stream"}
    links = [(function, call) for name, function, call in calls if name == "os.link"]
    assert [function for function, _call in links] == ["_link"]
    keywords = _keywords(links[0][1])
    assert set(keywords) == {"dst_dir_fd", "follow_symlinks"}
    assert isinstance(keywords["follow_symlinks"], ast.Constant) and keywords["follow_symlinks"].value is True
    source = links[0][1].args[0]
    link_function = next(node for node in ast.walk(module)
                         if isinstance(node, ast.FunctionDef) and node.name == "_link")
    assigned = [node.value for node in ast.walk(link_function) if isinstance(node, ast.Assign)
                and [getattr(t, "id", None) for t in node.targets] == [getattr(source, "id", "")]]
    assert len(assigned) == 1 and _call_name(assigned[0]) == "_proc_path"  # the inode, not a name
    assert all("dir_fd" in _keywords(call) for name, _f, call in calls if name == "os.mkdir")
    assert '_PROC_FD = "/proc/self/fd"' in local.read_text(encoding="utf-8")
