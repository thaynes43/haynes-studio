"""Create-only atomic publication of one file (contract section 8, steps 1 to 4)."""

from __future__ import annotations

import builtins
import io
import os
import stat

import pytest

from haynes_studio.store import (
    COLLISION,
    HASH_MISMATCH,
    MEDIA_TYPE_UNSUPPORTED,
    MISMATCH,
    MISSING,
    PRESENT,
    LocalStore,
    StageRecord,
    StoreError,
    blob_locator,
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

DATA = b"synthetic still: not media, just bytes " * 1000  # 39 kB, several chunks
OTHER = b"other synthetic bytes"


@pytest.fixture
def root(tmp_path):
    path = tmp_path / "store"
    path.mkdir()
    return path


def test_publish_writes_one_read_only_file_at_its_locator(root):
    calls = FailAt()
    store = LocalStore(root, on_step=calls, chunk_size=4096)
    blob = store.publish(DATA, scope="library", media_type="image/png")
    assert calls.calls == [f"blob:{step}" for step in STEPS]
    assert blob.locator == blob_locator("library", sha(DATA), "image/png")
    assert (blob.sha256, blob.bytes, blob.media_type) == (sha(DATA), len(DATA), "image/png")
    final = root / blob.locator
    assert final.read_bytes() == DATA
    assert stat.S_IMODE(final.stat().st_mode) == 0o444  # proposal: published files are read-only
    assert files(root, ".staging") == []
    assert store.verify(blob.locator, blob.sha256) == PRESENT
    with store.open(blob.locator) as handle:
        assert handle.read() == DATA


def test_sources_bytes_path_and_file_object(root, tmp_path):
    store = LocalStore(root)
    source = tmp_path / "rendered.wav"
    source.write_bytes(DATA)
    from_path = store.publish(source, scope=PRD, media_type="audio/wav")
    from_file = store.publish(io.BytesIO(DATA), scope=PRD, media_type="audio/wav")
    from_bytes = store.publish(bytearray(DATA), scope=PRD, media_type="audio/wav",
                               expected_sha256=sha(DATA))
    assert from_path == from_file == from_bytes
    assert from_path.locator.startswith(f"productions/{PRD}/sha256/")
    assert source.read_bytes() == DATA  # the source is only read


@pytest.mark.parametrize("source", [str("relative/path.wav"), 42, io.StringIO("text")])
def test_bad_sources_and_media_types_are_refused_before_any_write(root, source):
    store = LocalStore(root)
    with pytest.raises(TypeError):
        store.publish(source, scope="library", media_type="audio/wav")
    with pytest.raises(StoreError) as caught:
        store.publish(DATA, scope="library", media_type="image/gif")
    assert caught.value.code == MEDIA_TYPE_UNSUPPORTED
    with pytest.raises(StoreError) as caught:
        store.publish(DATA, scope="prd_nope", media_type="image/png")
    assert caught.value.code == "id.malformed"
    with pytest.raises(FileNotFoundError):
        store.publish(root.parent / "missing.wav", scope="library", media_type="audio/wav")
    assert tree(root) in ({}, {".staging": tree(root).get(".staging")})
    assert files(root, ".staging") == []


def test_same_bytes_again_succeed_without_touching_the_file(root):
    store = LocalStore(root)
    first = store.publish(DATA, scope="library", media_type="image/png")
    before = tree(root)
    again = store.publish(DATA, scope="library", media_type="image/png")
    assert again == first
    assert tree(root)[first.locator] == before[first.locator]  # same inode, mtime, bytes
    assert files(root, ".staging") == []


def test_expected_hash_mismatch_publishes_nothing(root):
    store = LocalStore(root)
    with pytest.raises(StoreError) as caught:
        store.publish(DATA, scope="library", media_type="image/png", expected_sha256=sha(OTHER))
    assert caught.value.code == HASH_MISMATCH
    assert files(root, "library") == []
    assert len(files(root, ".staging")) == 1  # the leftover stays for the doctor (D17)


def test_other_bytes_at_the_path_are_a_collision_and_nothing_is_overwritten(root):
    store = LocalStore(root)
    locator = blob_locator("library", sha(DATA), "image/png")
    plant(root, locator, OTHER)  # damage, or a foreign writer
    before = tree(root)[locator]
    with pytest.raises(StoreError) as caught:
        store.publish(DATA, scope="library", media_type="image/png")
    assert (caught.value.code, caught.value.status, caught.value.locator) == (COLLISION, "failed", locator)
    assert tree(root)[locator] == before
    assert (root / locator).read_bytes() == OTHER
    assert store.verify(locator, sha(DATA)) == MISMATCH


def test_a_symbolic_link_at_the_path_is_a_collision_and_is_not_followed(root, tmp_path):
    store = LocalStore(root)
    outside = tmp_path / "outside.png"
    outside.write_bytes(DATA)
    locator = blob_locator("library", sha(DATA), "image/png")
    (root / locator).parent.mkdir(parents=True)
    (root / locator).symlink_to(outside)
    with pytest.raises(StoreError) as caught:
        store.publish(DATA, scope="library", media_type="image/png")
    assert caught.value.code == COLLISION
    assert (root / locator).is_symlink() and outside.read_bytes() == DATA
    assert store.verify(locator, sha(DATA)) == MISMATCH


@pytest.mark.parametrize("kind", ["directory", "fifo"])
def test_a_directory_or_fifo_at_the_path_is_a_collision(root, kind):
    store = LocalStore(root)
    locator = blob_locator("library", sha(DATA), "image/png")
    (root / locator).parent.mkdir(parents=True)
    if kind == "directory":
        (root / locator).mkdir()
    else:
        os.mkfifo(root / locator)  # opened non-blocking, so this cannot hang
    with pytest.raises(StoreError) as caught:
        store.publish(DATA, scope="library", media_type="image/png")
    assert caught.value.code == COLLISION
    assert store.verify(locator, sha(DATA)) == MISMATCH
    with pytest.raises(StoreError) as caught:
        store.open(locator)
    assert caught.value.code == "store.blob_missing"


def test_a_directory_source_is_refused_before_any_write(root, tmp_path):
    with pytest.raises(IsADirectoryError):
        LocalStore(root).publish(tmp_path, scope="library", media_type="image/png")
    assert files(root, ".staging") == []


@pytest.mark.parametrize("locator", ["../../etc/passwd", "/etc/passwd", "library/../x.png"])
def test_verify_and_open_refuse_a_locator_outside_the_layout(root, locator):
    store = LocalStore(root)
    for call in (lambda: store.verify(locator, sha(DATA)), lambda: store.open(locator)):
        with pytest.raises(StoreError) as caught:
            call()
        assert caught.value.code == "store.locator_invalid"


def test_a_symbolic_link_in_place_of_a_store_folder_is_never_followed(root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    blob = LocalStore(outside).publish(DATA, scope="library", media_type="image/png")
    (root / "library").symlink_to(outside / "library")
    store = LocalStore(root)
    assert store.verify(blob.locator, blob.sha256) == MISMATCH  # not "present"
    with pytest.raises(StoreError) as caught:
        store.open(blob.locator)
    assert caught.value.code == "store.blob_missing"
    with pytest.raises(StoreError) as caught:
        store.publish(DATA, scope="library", media_type="image/png")
    assert caught.value.code == COLLISION


def test_verify_reports_missing_and_open_refuses_a_missing_blob(root):
    store = LocalStore(root)
    locator = blob_locator("library", sha(DATA), "image/png")
    assert store.verify(locator, sha(DATA)) == MISSING
    with pytest.raises(StoreError) as caught:
        store.open(locator)
    assert caught.value.code == "store.blob_missing"


# Failure injection after each step -----------------------------------------------------

# What a crash after each step leaves (fresh store): the final file, and staging files.
AFTER_STEP = {
    "open": (False, 1),  # an empty .part
    "write": (False, 1),  # every byte written, not yet fsynced
    "fsync": (False, 1),
    "check": (False, 1),
    "link": (True, 1),  # final published; the .part is a second link to it
    "unlink": (True, 0),
    "fsync_dir": (True, 0),
}


@pytest.mark.parametrize("step", STEPS)
def test_a_crash_after_each_step_never_leaves_a_partial_final_file(root, step):
    locator = blob_locator("library", sha(DATA), "image/png")
    store = LocalStore(root, on_step=FailAt(step=f"blob:{step}"), chunk_size=4096)
    with pytest.raises(InjectedFault):
        store.publish(DATA, scope="library", media_type="image/png")
    published, leftovers = AFTER_STEP[step]
    assert (root / locator).exists() == published
    if published:
        assert (root / locator).read_bytes() == DATA
    assert len(files(root, ".staging")) == leftovers
    assert_every_blob_is_its_hash(root)
    # A retry with the same bytes converges; the earlier leftover is not tidied.
    assert LocalStore(root).publish(DATA, scope="library", media_type="image/png").locator == locator
    assert (root / locator).read_bytes() == DATA
    assert len(files(root, ".staging")) == leftovers


@pytest.mark.parametrize("step", STEPS)
def test_a_crash_during_a_retry_never_changes_the_published_file(root, step):
    first = LocalStore(root).publish(DATA, scope="library", media_type="image/png")
    before = tree(root)[first.locator]
    with pytest.raises(InjectedFault):
        LocalStore(root, on_step=FailAt(step=f"blob:{step}")).publish(
            DATA, scope="library", media_type="image/png")
    assert tree(root)[first.locator] == before


def test_final_paths_are_only_ever_opened_read_only(root, monkeypatch):
    opened, modes = [], []
    real_open, real_builtin_open = os.open, builtins.open

    def spy(path, flags, *args, dir_fd=None, **kwargs):
        full = os.fspath(path) if dir_fd is None else os.path.join(
            os.readlink(f"/proc/self/fd/{dir_fd}"), os.fspath(path))
        opened.append((full, flags))
        return real_open(path, flags, *args, dir_fd=dir_fd, **kwargs)

    def builtin_spy(file, mode="r", *args, **kwargs):
        modes.append((os.fspath(file) if not isinstance(file, int) else file, mode))
        return real_builtin_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(os, "open", spy)
    monkeypatch.setattr(builtins, "open", builtin_spy)
    store = LocalStore(root)
    blob = store.publish(DATA, scope="library", media_type="image/png")
    store.publish(DATA, scope="library", media_type="image/png")  # EEXIST, re-hash
    plant(root, blob_locator("library", sha(OTHER + b"x"), "image/png"), OTHER)
    with pytest.raises(StoreError):
        store.publish(OTHER + b"x", scope="library", media_type="image/png")  # collision
    store.verify(blob.locator, blob.sha256)
    store.open(blob.locator).close()
    source = root.parent / "source.png"
    source.write_bytes(DATA)
    store.publish(source, scope=PRD, media_type="image/png")  # a path source: builtin open
    writes = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
    written = [path for path, flags in opened if flags & writes]
    assert written and all(os.path.dirname(path) == str(root / ".staging") for path in written)
    assert all(flags & os.O_EXCL for path, flags in opened if flags & writes)
    assert modes and all(mode == "rb" for _file, mode in modes)  # the store's own opens


def test_each_fsync_comes_before_what_depends_on_it(root, monkeypatch):
    """Section 8 order: the staging file is synced before link(); the final folder is
    synced after link(); a blob's folder is synced before a stage record naming it is
    linked, so a durable record never names a blob whose name is not durable."""
    events = []
    real_fsync, real_link = os.fsync, os.link

    def fsync(fd):
        events.append(("fsync", os.readlink(f"/proc/self/fd/{fd}")))
        return real_fsync(fd)

    def link(src, dst, **kwargs):
        events.append(("link", os.fspath(dst)))
        return real_link(src, dst, **kwargs)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "link", link)
    store = LocalStore(root)
    blob = store.publish(DATA, scope=PRD, media_type="image/png")
    store.complete_stage(StageRecord(PRD, RUN, "voice", {"still": blob}))
    staging_sync = next(i for i, (kind, path) in enumerate(events)
                        if kind == "fsync" and path.endswith(".part"))
    blob_link = events.index(("link", str(root / blob.locator)))
    folder_sync = events.index(("fsync", str((root / blob.locator).parent)), blob_link)
    record_link = events.index(("link", str(root / record_path(PRD, RUN, "voice"))))
    assert staging_sync < blob_link < folder_sync < record_link
    record_folder = str((root / record_path(PRD, RUN, "voice")).parent)
    assert ("fsync", record_folder) in events[record_link:]


def test_a_path_source_is_closed_when_staging_fails(root, tmp_path, monkeypatch):
    source = tmp_path / "rendered.png"
    source.write_bytes(DATA)
    plant(root, ".staging", b"a file where the staging folder belongs")
    handles = []
    real_open = builtins.open

    def spy(*args, **kwargs):
        handles.append(real_open(*args, **kwargs))
        return handles[-1]

    monkeypatch.setattr(builtins, "open", spy)
    with pytest.raises(StoreError) as caught:
        LocalStore(root).publish(source, scope="library", media_type="image/png")
    assert caught.value.code == COLLISION
    assert handles and all(handle.closed for handle in handles)
