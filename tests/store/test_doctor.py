"""``store doctor`` reports and removes nothing (D17); the store code holds no delete,
purge, truncate or rename (contract section 8)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from haynes_studio.store import Blob, LocalStore, StageRecord, record_path
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
                                         "broken_records", "dangling"}
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


def _calls(path: Path) -> list[tuple[str, int, str]]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            owner = func.value.id if isinstance(func, ast.Attribute) and isinstance(
                func.value, ast.Name) else ""
            found.append((f"{owner}.{name}" if owner else name, node.lineno, path.name))
    return found


def test_the_store_code_never_deletes_truncates_or_renames():
    forbidden = {"unlink", "remove", "removedirs", "rmdir", "rmtree", "rename", "renames",
                 "truncate", "ftruncate", "os.replace", "shutil.move", "shutil.rmtree"}
    calls = [call for base in SOURCES for path in sorted(base.glob("*.py")) for call in _calls(path)]
    hits = [(name, line, file) for name, line, file in calls
            if name in forbidden or name.rpartition(".")[2] in forbidden - {"os.replace"}]
    # The one unlink section 8 names: step 4, the store's own staging file.
    assert [(name, file) for name, _line, file in hits] == [("os.unlink", "local.py")]
    source = (SOURCES[0] / "local.py").read_text(encoding="utf-8")
    finish = source[source.index("def _finish"):source.index("# Helpers")]
    assert "os.unlink(staged.path)" in finish
