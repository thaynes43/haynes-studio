"""Another writer inside the store root: the sequences the adversarial review of PR 46
reproduced (findings 1 to 6; finding 7 is in ``tests/stages/test_preflight.py``).

Each is replayed through the store's step hook where the window is inside the store,
or by a swap made just before the system call otherwise. Every test checks what is on
disk afterwards: no final path holds bytes the store published under a wrong name, no
symbolic link stands at a final path, nothing outside the root is written or removed,
and the planted outside file is untouched. Linux only, like the store."""

from __future__ import annotations

import contextlib
import errno
import os
import stat
from pathlib import Path

import pytest

from haynes_studio.stages import StageOutput, commit_stage, completed_stage
from haynes_studio.store import (
    BLOB_MISSING,
    COLLISION,
    HASH_MISMATCH,
    MISMATCH,
    PRESENT,
    Blob,
    LocalStore,
    StageRecord,
    StagingLeftoverWarning,
    StoreError,
    blob_locator,
    record_path,
)
from haynes_studio.store import local
from tests.store.helpers import (
    PRD,
    RUN,
    FailAt,
    InjectedFault,
    assert_every_blob_is_its_hash,
    files,
    plant,
    sha,
    tree,
)

GOOD = b"clip-good-bytes"
BAD = b"clip-BAD!-bytes"  # the same length
SECRET = b"secret-media: a file outside the store"
DATA = b"0123456789"


@pytest.fixture
def root(tmp_path):
    path = tmp_path / "store"
    path.mkdir()
    return path


@pytest.fixture
def outside(tmp_path):
    """A folder outside the root, holding a file another writer would like to reach."""
    path = tmp_path / "outside"
    path.mkdir()
    (path / "secret-media").write_bytes(SECRET)
    return path


class At:
    """``on_step`` that runs ``action`` once, after the step named ``step``."""

    def __init__(self, step: str, action):
        self.step, self.action, self.done = step, action, False

    def __call__(self, name: str) -> None:
        if name == self.step and not self.done:
            self.done = True
            self.action()


def only_entry(folder: Path) -> Path:
    entries = list(folder.iterdir())
    assert len(entries) == 1, entries
    return entries[0]


def good_locator(scope: str = "library") -> str:
    return blob_locator(scope, sha(GOOD), "video/mp4")


# Finding 1: the hash check and link() must be the same inode ----------------------------


def test_f1_other_bytes_swapped_in_after_the_check_are_never_published(root, outside):
    """Review 1A: on ``blob:check``, unlink the ``.part`` and write other bytes of the
    same length under its name."""
    before = tree(outside)

    def swap():
        part = only_entry(root / ".staging")
        os.unlink(part)
        part.write_bytes(BAD)

    store = LocalStore(root, on_step=At("blob:check", swap))
    with pytest.raises(StoreError) as caught:
        commit_stage(store, production_id=PRD, run_id=RUN, stage="segment",
                     outputs={"clip": StageOutput(GOOD, "video/mp4", sha(GOOD))})
    assert caught.value.code == COLLISION  # the checked inode lost its only name
    locator = good_locator(PRD)
    assert not os.path.lexists(root / locator)
    assert completed_stage(LocalStore(root), production_id=PRD, run_id=RUN, stage="segment") is None
    assert only_entry(root / ".staging").read_bytes() == BAD  # left for the doctor
    assert tree(outside) == before
    blob = LocalStore(root).publish(GOOD, scope=PRD, media_type="video/mp4")  # not poisoned
    assert (blob.locator, (root / locator).read_bytes()) == (locator, GOOD)
    assert_every_blob_is_its_hash(root)


def test_f1_a_link_swapped_in_after_the_check_is_never_published(root, outside):
    """Review 1B: on ``blob:check``, replace the ``.part`` with a symbolic link to a
    file outside the root."""
    before = tree(outside)

    def swap():
        part = only_entry(root / ".staging")
        os.unlink(part)
        part.symlink_to(outside / "secret-media")

    with pytest.raises(StoreError) as caught:
        LocalStore(root, on_step=At("blob:check", swap)).publish(
            GOOD, scope="library", media_type="video/mp4")
    assert caught.value.code == COLLISION
    assert not os.path.lexists(root / good_locator())  # no link, no file
    assert tree(outside) == before
    blob = LocalStore(root).publish(GOOD, scope="library", media_type="video/mp4")
    final = root / blob.locator
    assert stat.S_ISREG(final.lstat().st_mode) and final.read_bytes() == GOOD
    assert LocalStore(root).verify(blob.locator, sha(GOOD)) == PRESENT


@pytest.mark.parametrize("restore_mode", [False, True], ids=["left-writable", "mode-restored"])
def test_f1_staging_bytes_rewritten_in_place_after_the_check_are_never_published(root, restore_mode):
    """The same window, the same inode: make the ``.part`` writable, rewrite it, and
    maybe put the mode back. The re-read right before the link sees it."""
    def rewrite():
        part = only_entry(root / ".staging")
        part.chmod(0o644)
        with open(part, "r+b") as handle:
            handle.write(BAD)
        if restore_mode:
            part.chmod(0o444)

    with pytest.raises(StoreError) as caught:
        LocalStore(root, on_step=At("blob:check", rewrite)).publish(
            GOOD, scope="library", media_type="video/mp4")
    assert caught.value.code == (HASH_MISMATCH if restore_mode else COLLISION)
    assert files(root, "library") == []


# Finding 2: the one unlink must remove only the staging inode's own name --------------


def test_f2_a_staging_folder_swapped_for_a_link_before_the_unlink_removes_nothing(root, outside):
    """Review 2: on ``blob:link``, move ``.staging`` aside and put a link to a folder
    holding a file of the same ``.part`` name in its place."""
    seen = {}

    def swap():
        part = only_entry(root / ".staging")
        (root / ".staging").rename(root / ".staging-aside")
        (outside / part.name).write_bytes(b"another writer's file of the same name")
        (root / ".staging").symlink_to(outside, target_is_directory=True)
        seen["outside"] = tree(outside)

    with pytest.warns(StagingLeftoverWarning, match="moved or replaced"):
        blob = LocalStore(root, on_step=At("blob:link", swap)).publish(
            GOOD, scope="library", media_type="video/mp4")
    assert tree(outside) == seen["outside"]  # the same-named file outside is still there
    final = root / blob.locator
    assert stat.S_ISREG(final.lstat().st_mode) and final.read_bytes() == GOOD
    kept = only_entry(root / ".staging-aside")  # the store's own staging name, left in place
    assert kept.stat().st_ino == final.stat().st_ino


def test_f2_a_staging_name_replaced_before_the_unlink_is_left_alone(root):
    def swap():
        part = only_entry(root / ".staging")
        os.unlink(part)
        part.write_bytes(b"another writer's file")

    with pytest.warns(StagingLeftoverWarning, match="no longer names"):
        blob = LocalStore(root, on_step=At("blob:link", swap)).publish(
            GOOD, scope="library", media_type="video/mp4")
    assert only_entry(root / ".staging").read_bytes() == b"another writer's file"
    final = root / blob.locator
    assert final.read_bytes() == GOOD and final.stat().st_nlink == 1


@pytest.mark.parametrize("final", ["linked", "adopted"])
def test_a_staging_file_with_an_extra_name_before_the_unlink_is_left_with_a_warning(root, final):
    """Second review, finding 2: right before the unlink the staging file must have
    exactly its ``.part`` and the final name (only the ``.part`` when the final file
    was adopted). An extra name leaves it in place."""
    if final == "adopted":
        LocalStore(root).publish(GOOD, scope="library", media_type="video/mp4")
    extra = root / "library" / "extra-name"

    def add_name():
        extra.parent.mkdir(exist_ok=True)
        os.link(only_entry(root / ".staging"), extra)

    with pytest.warns(StagingLeftoverWarning, match="names, not"):
        blob = LocalStore(root, on_step=At("blob:link", add_name)).publish(
            GOOD, scope="library", media_type="video/mp4")
    assert (root / blob.locator).read_bytes() == GOOD
    part = only_entry(root / ".staging")
    assert part.stat().st_ino == extra.stat().st_ino  # both names kept


def test_limit_a_folder_move_and_a_name_swap_in_the_last_gap_remove_the_other_file(
        root, outside, monkeypatch):
    """A documented limit: no call removes a name only if it is a given inode. A writer
    that moves the held ``.staging`` out of the root and renames another file onto the
    ``.part`` name between the last check and the unlink loses that file."""
    victim = outside / "victim"
    victim.write_bytes(b"VICTIM-BYTES")
    real_unlink = os.unlink

    def unlink(name, *, dir_fd):
        os.rename(root / ".staging", outside / "moved")
        os.rename(victim, outside / "moved" / name)
        return real_unlink(name, dir_fd=dir_fd)

    monkeypatch.setattr(os, "unlink", unlink)
    blob = LocalStore(root).publish(GOOD, scope="library", media_type="video/mp4")
    monkeypatch.undo()
    assert (root / blob.locator).read_bytes() == GOOD
    assert not victim.exists() and list((outside / "moved").iterdir()) == []


# Finding 3: a folder swapped for a link is never followed on the write path ------------


def test_f3_a_fan_folder_swapped_for_a_link_before_the_link_writes_nothing_outside(
        root, outside, monkeypatch):
    """Review 3A: just before ``link``, move the hash fan folder aside and link its
    name to a folder outside the root."""
    before = tree(outside)
    locator = good_locator()
    fan = (root / locator).parent
    aside = fan.with_name(fan.name + "-aside")
    real_link = os.link

    def link(src, dst, **kwargs):
        fan.rename(aside)
        fan.symlink_to(outside, target_is_directory=True)
        return real_link(src, dst, **kwargs)

    monkeypatch.setattr(os, "link", link)
    with pytest.raises(StoreError) as caught:
        LocalStore(root).publish(GOOD, scope="library", media_type="video/mp4")
    monkeypatch.undo()
    assert (caught.value.code, caught.value.locator) == (COLLISION, locator)
    assert tree(outside) == before
    assert not os.path.lexists(root / locator)  # nothing through the link
    assert LocalStore(root).verify(locator, sha(GOOD)) == MISMATCH  # a link on the way is refused
    # The link landed in the store's own folder, moved aside inside the root; the staging
    # file is kept (nothing further changed after the failed check).
    assert (aside / f"{sha(GOOD)}.mp4").read_bytes() == GOOD
    assert len(files(root, ".staging")) == 1
    assert_every_blob_is_its_hash(root)


def test_f3_a_staging_folder_swapped_for_a_link_before_the_create_writes_nothing_outside(
        root, outside, monkeypatch):
    """Review 3B: just before the ``.part`` is created, move ``.staging`` aside and link
    its name to a folder outside the root."""
    before = tree(outside)
    real_open, swapped = os.open, []

    def spy(path, flags, *args, **kwargs):
        if flags & os.O_CREAT and not swapped:
            swapped.append(path)
            (root / ".staging").rename(root / ".staging-aside")
            (root / ".staging").symlink_to(outside, target_is_directory=True)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", spy)
    with pytest.warns(StagingLeftoverWarning, match="moved or replaced"):
        blob = LocalStore(root).publish(GOOD, scope="library", media_type="video/mp4")
    monkeypatch.undo()
    assert swapped and tree(outside) == before  # no .part outside the root
    final = root / blob.locator
    assert stat.S_ISREG(final.lstat().st_mode) and final.read_bytes() == GOOD
    assert only_entry(root / ".staging-aside").stat().st_ino == final.stat().st_ino


def test_a_final_name_replaced_right_after_the_link_is_an_error_and_nothing_further_changes(
        root, monkeypatch):
    real_link = os.link

    def link(src, dst, *, dst_dir_fd, follow_symlinks):
        real_link(src, dst, dst_dir_fd=dst_dir_fd, follow_symlinks=follow_symlinks)
        os.unlink(dst, dir_fd=dst_dir_fd)  # another writer replaces the new name at once
        fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444, dir_fd=dst_dir_fd)
        os.write(fd, BAD)
        os.close(fd)

    monkeypatch.setattr(os, "link", link)
    with pytest.raises(StoreError) as caught:
        LocalStore(root).publish(GOOD, scope="library", media_type="video/mp4")
    monkeypatch.undo()
    assert (caught.value.code, caught.value.locator) == (COLLISION, good_locator())
    assert only_entry(root / ".staging").read_bytes() == GOOD  # kept: nothing further changed


def test_without_proc_self_fd_publication_fails_closed(root, tmp_path, monkeypatch):
    monkeypatch.setattr(local, "_PROC_FD", str(tmp_path / "no-proc"))
    with pytest.raises(OSError) as caught:
        LocalStore(root).publish(GOOD, scope="library", media_type="video/mp4")
    assert not isinstance(caught.value, StoreError)
    assert caught.value.errno == errno.ENOTSUP and "nothing was linked" in str(caught.value)
    assert files(root, "library") == [] and len(files(root, ".staging")) == 1


# Finding 4: a completion record needs the recorded digest, not only the size ----------


def test_f4_complete_stage_refuses_a_blob_of_the_right_size_with_other_bytes(root):
    good, bad = b"hello-good", b"hello-BAD!"
    locator = blob_locator(PRD, sha(good), "audio/wav")
    plant(root, locator, bad)
    before = tree(root)
    record = StageRecord(PRD, RUN, "voice", {"take:1": Blob(sha(good), len(good), "audio/wav", locator)})
    with pytest.raises(StoreError) as caught:
        LocalStore(root).complete_stage(record)
    assert (caught.value.code, caught.value.locator) == (HASH_MISMATCH, locator)
    assert tree(root) == before  # no record, no staging file, the planted bytes as they were


def test_f4_a_record_over_other_bytes_is_refused_by_readers_and_reported_by_the_doctor(root):
    good, bad = b"hello-good", b"hello-BAD!"
    locator = blob_locator(PRD, sha(good), "audio/wav")
    plant(root, locator, bad)
    record = StageRecord(PRD, RUN, "voice", {"take:1": Blob(sha(good), len(good), "audio/wav", locator)})
    path = record_path(PRD, RUN, "voice")
    plant(root, path, record.encode())  # written past complete_stage, as a foreign writer would
    store = LocalStore(root)
    before = tree(root)
    with pytest.raises(StoreError) as caught:
        store.stage_record(PRD, RUN, "voice")
    assert (caught.value.code, caught.value.locator) == (HASH_MISMATCH, locator)
    with pytest.raises(StoreError) as caught:
        completed_stage(store, production_id=PRD, run_id=RUN, stage="voice")  # safe by default
    assert caught.value.code == HASH_MISMATCH
    assert store.stage_record(PRD, RUN, "voice", verify=False) == record  # the cheap size check only
    report = store.doctor()
    assert (report.mismatched, report.damaged, report.dangling) == (((path, locator),), (locator,), ())
    assert not report.clean
    assert tree(root) == before


# Finding 5: EEXIST adopts only what this store could have published -------------------


@pytest.mark.parametrize("mode, second_name", [
    (0o644, "outside"),  # the review's case: a writable outside file, hard-linked in
    (0o644, None),  # a writable file planted at the path
    (0o444, "outside"),  # read-only, but another name outside the root can change it
    (0o444, "store"),  # read-only, another name in the store that is not a staging file
], ids=["writable-outside-link", "writable", "read-only-outside-link", "read-only-store-link"])
def test_f5_an_existing_file_this_store_did_not_publish_is_a_collision(
        root, outside, mode, second_name):
    locator = good_locator()
    final = root / locator
    final.parent.mkdir(parents=True)
    if second_name is None:
        final.write_bytes(GOOD)
        final.chmod(mode)
    else:
        other = outside / "right-bytes.mp4" if second_name == "outside" else root / "library" / "copy.mp4"
        other.write_bytes(GOOD)
        other.chmod(mode)
        os.link(other, final)
    before, before_outside = tree(root)[locator], tree(outside)
    with pytest.raises(StoreError) as caught:
        LocalStore(root).publish(GOOD, scope="library", media_type="video/mp4")
    assert (caught.value.code, caught.value.locator) == (COLLISION, locator)
    assert tree(root)[locator] == before  # same inode, mode, mtime and bytes: never chmod-ed
    assert tree(outside) == before_outside
    assert final.stat().st_nlink == (1 if second_name is None else 2)


def test_the_doctor_lists_final_files_a_republish_would_refuse(root, outside):
    """Follow-up review, item 2: a hard link from outside (a backup, a dedupe tool) or
    a write bit makes a re-publish a collision; the doctor names those files. The
    ``.part`` left by a crash after ``link`` is the store's own second name: not listed."""
    store = LocalStore(root)
    linked = store.publish(b"linked from a backup", scope="library", media_type="image/png")
    os.link(root / linked.locator, outside / "backup.png")
    writable = store.publish(b"made writable", scope="library", media_type="image/png")
    (root / writable.locator).chmod(0o644)
    with pytest.raises(InjectedFault):
        LocalStore(root, on_step=FailAt(step="blob:link")).publish(
            b"crashed after link", scope="library", media_type="image/png")
    report = store.doctor()
    assert report.foreign == tuple(sorted([linked.locator, writable.locator]))
    assert len(report.staging) == 1 and not report.clean
    with pytest.raises(StoreError) as caught:
        store.publish(b"linked from a backup", scope="library", media_type="image/png")
    assert caught.value.code == COLLISION


def test_eexist_adopts_a_file_whose_other_name_is_a_publication_between_link_and_unlink(root):
    """Two publications of the same bytes: the second meets the first's file while the
    first's ``.part`` is still its second name. That name is in ``.staging``, so it is
    this store's own publication, not a foreign link (deterministic: the second runs
    inside the first's ``link`` step)."""
    seen = {}

    def second():
        final = root / good_locator()
        seen["names"] = final.stat().st_nlink
        seen["blob"] = LocalStore(root).publish(GOOD, scope="library", media_type="video/mp4")

    first = LocalStore(root, on_step=At("blob:link", second)).publish(
        GOOD, scope="library", media_type="video/mp4")
    assert seen["names"] == 2 and seen["blob"] == first
    final = root / first.locator
    assert final.read_bytes() == GOOD and final.stat().st_nlink == 1
    assert files(root, ".staging") == []


def test_part_names_added_only_for_the_count_do_not_hide_outside_names(root, outside, monkeypatch):
    """Second review, finding 3: a read-only final file of the right bytes with two
    names outside the root. While ``.staging`` is listed, another writer adds two
    ``.part`` links of it, and removes them just before the link count is sampled
    again (so both samples agree). The counted names are checked again afterwards."""
    locator = good_locator()
    final = plant(root, locator, GOOD)
    final.chmod(0o444)
    for name in ("one.mp4", "two.mp4"):
        os.link(final, outside / name)
    (root / ".staging").mkdir()
    temps = [root / ".staging" / "temp-a.part", root / ".staging" / "temp-b.part"]
    real_scandir, real_fstat, listing = os.scandir, os.fstat, []

    def scandir(path=None):
        if isinstance(path, int) and not listing:  # the store lists .staging by descriptor
            for temp in temps:
                os.link(final, temp)
            listing.append(True)
        return real_scandir(path) if path is not None else real_scandir()

    def fstat(fd):
        if listing:  # the next fstat after the listing is the second sample
            for temp in temps:
                temp.unlink()
            listing.clear()
        return real_fstat(fd)

    monkeypatch.setattr(os, "scandir", scandir)
    monkeypatch.setattr(os, "fstat", fstat)
    before, before_outside = tree(root)[locator], tree(outside)
    with pytest.raises(StoreError) as caught:
        LocalStore(root).publish(GOOD, scope="library", media_type="video/mp4")
    monkeypatch.undo()
    assert (caught.value.code, caught.value.locator) == (COLLISION, locator)
    assert tree(root)[locator] == before and tree(outside) == before_outside
    assert final.stat().st_nlink == 3 and final.read_bytes() == GOOD


def test_an_adoption_that_sees_the_other_part_lose_its_name_mid_count_succeeds(root, monkeypatch):
    """The legitimate move: while the second publication counts names, the first
    publication's ``.part`` loses its name (its unlink). The count is taken again."""
    real_scandir, seen = os.scandir, {}

    def second():
        part = only_entry(root / ".staging")  # the first publication's .part

        def scandir(path=None):
            entries = list(real_scandir(path))
            if isinstance(path, int) and part.exists():
                os.unlink(part)  # as the first publication's own step 4 would
            return contextlib.nullcontext(entries)

        monkeypatch.setattr(os, "scandir", scandir)
        try:
            seen["blob"] = LocalStore(root).publish(GOOD, scope="library", media_type="video/mp4")
        finally:
            monkeypatch.setattr(os, "scandir", real_scandir)

    first = LocalStore(root, on_step=At("blob:link", second)).publish(
        GOOD, scope="library", media_type="video/mp4")
    assert seen["blob"] == first
    assert (root / first.locator).read_bytes() == GOOD and files(root, ".staging") == []


def test_eexist_adopts_a_read_only_single_name_file_of_the_same_bytes(root):
    locator = good_locator()
    plant(root, locator, GOOD).chmod(0o444)
    before = tree(root)[locator]
    blob = LocalStore(root).publish(GOOD, scope="library", media_type="video/mp4")
    assert blob.locator == locator and tree(root)[locator] == before
    assert files(root, ".staging") == []


class LinkingSource:
    """A source that, on read number ``link_at``, gives the staging file the final path
    of :data:`DATA` (a hard link, or a rename, as another writer could), then hands over
    the next chunk. Its chunks are ``0123``, ``4567`` and ``89``; a read after that
    fails."""

    def __init__(self, root: Path, link_at: int, how: str = "link"):
        self.root, self.link_at, self.how, self.reads, self.linked = root, link_at, how, 0, False
        self.final = root / blob_locator("library", sha(DATA), "image/png")

    def read(self, _size: int) -> bytes:
        self.reads += 1
        if self.linked:
            raise OSError("the source failed")
        if self.reads == self.link_at:
            self.final.parent.mkdir(parents=True, exist_ok=True)
            part = only_entry(self.root / ".staging")
            os.link(part, self.final) if self.how == "link" else part.rename(self.final)
            self.linked = True
        return {1: b"0123", 2: b"4567", 3: b"89"}.get(self.reads, b"")


def test_f5_a_staging_file_linked_to_the_final_path_before_any_write_gets_no_bytes(root):
    """Review 5B: from the source's first read, hard-link the still-empty ``.part``
    onto the final locator, hand over four bytes, then fail."""
    source = LinkingSource(root, link_at=1)
    with pytest.raises(StoreError) as caught:
        LocalStore(root).publish(source, scope="library", media_type="image/png")
    assert caught.value.code == COLLISION and source.reads == 1  # stopped before writing
    assert source.final.read_bytes() == b""  # the other writer's name shows nothing written
    with pytest.raises(StoreError) as caught:
        LocalStore(root).publish(DATA, scope="library", media_type="image/png")
    assert caught.value.code == COLLISION  # a retry never adopts it
    assert source.final.read_bytes() == b""
    assert LocalStore(root).doctor().damaged == (source.final.relative_to(root).as_posix(),)


@pytest.mark.parametrize("how", ["link", "rename"])
def test_limit_a_name_given_mid_stream_shows_only_the_bytes_written_before_it(root, how):
    """A documented limit: the staging file has a name from step 1 (section 8), so a
    final name given to it after the first write shows what was written so far. The
    store stops at the next write and refuses; the path stays refused for those bytes."""
    source = LinkingSource(root, link_at=2, how=how)
    with pytest.raises(StoreError) as caught:
        LocalStore(root).publish(source, scope="library", media_type="image/png")
    assert caught.value.code == COLLISION and source.reads == 2
    assert source.final.read_bytes() == b"0123"
    assert LocalStore(root).verify(source.final.relative_to(root).as_posix(), sha(DATA)) == MISMATCH


@pytest.mark.parametrize("what", ["blob", "record"])
def test_a_staging_file_renamed_onto_its_final_path_gets_no_bytes(root, what):
    """Follow-up review, item 1: on ``open``, rename the ``.part`` onto the final path
    (a record path is known in advance too). Its one name is no longer the ``.part``,
    so the store writes nothing into it and links nothing."""
    store = LocalStore(root)
    take = store.publish(b"take one", scope=PRD, media_type="audio/wav")
    record = StageRecord(PRD, RUN, "voice", {"take:1": take})
    final = root / (good_locator() if what == "blob" else record_path(PRD, RUN, "voice"))

    def rename():
        final.parent.mkdir(parents=True, exist_ok=True)
        only_entry(root / ".staging").rename(final)

    hooked = LocalStore(root, on_step=At(f"{what}:open", rename))
    with pytest.raises(StoreError) as caught:
        if what == "blob":
            hooked.publish(GOOD, scope="library", media_type="video/mp4")
        else:
            hooked.complete_stage(record)
    assert caught.value.code == COLLISION
    assert final.read_bytes() == b""  # the other writer's name; the store wrote nothing
    if what == "record":  # an empty file at the record path: refused, never trusted
        with pytest.raises(StoreError) as caught:
            store.stage_record(PRD, RUN, "voice")
        assert caught.value.code == "store.record_invalid"


def test_a_staging_file_renamed_after_its_last_write_is_not_linked(root):
    def rename():
        final = root / good_locator()
        final.parent.mkdir(parents=True, exist_ok=True)
        only_entry(root / ".staging").rename(final)

    with pytest.raises(StoreError) as caught:
        LocalStore(root, on_step=At("blob:check", rename)).publish(
            GOOD, scope="library", media_type="video/mp4")
    assert caught.value.code == COLLISION  # the name check before the link


def test_a_staging_file_removed_just_before_the_link_is_a_collision(root, monkeypatch):
    real_link = os.link

    def link(src, dst, **kwargs):
        os.unlink(only_entry(root / ".staging"))  # another writer, inside the last gap
        return real_link(src, dst, **kwargs)

    monkeypatch.setattr(os, "link", link)
    with pytest.raises(StoreError) as caught:
        LocalStore(root).publish(GOOD, scope="library", media_type="video/mp4")
    monkeypatch.undo()
    assert (caught.value.code, caught.value.locator) == (COLLISION, good_locator())
    assert not os.path.lexists(root / good_locator())


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes folders whatever their mode")
def test_a_staging_name_that_cannot_be_removed_is_a_warning_not_an_error(root):
    def lock():
        (root / ".staging").chmod(0o555)

    try:
        with pytest.warns(StagingLeftoverWarning, match="could not be removed"):
            blob = LocalStore(root, on_step=At("blob:link", lock)).publish(
                GOOD, scope="library", media_type="video/mp4")
    finally:
        (root / ".staging").chmod(0o755)
    assert (root / blob.locator).read_bytes() == GOOD
    assert LocalStore(root).verify(blob.locator, sha(GOOD)) == PRESENT
    assert len(files(root, ".staging")) == 1


# Finding 6: a record never names a blob removed or replaced after its check -----------


@pytest.mark.parametrize("change", ["removed", "replaced"])
def test_f6_a_blob_removed_or_replaced_before_the_record_link_leaves_no_record(root, change):
    """Review 6: on ``record:check`` (after the blob checks, before the record's
    link), remove the blob, or put other bytes of the same size in its place."""
    store = LocalStore(root)
    take = store.publish(b"take one", scope=PRD, media_type="audio/wav")
    path = root / take.locator

    def act():
        os.unlink(path)
        if change == "replaced":
            path.write_bytes(b"take two")  # the same size, another inode

    record = StageRecord(PRD, RUN, "voice", {"take:1": take})
    with pytest.raises(StoreError) as caught:
        LocalStore(root, on_step=At("record:check", act)).complete_stage(record)
    code = BLOB_MISSING if change == "removed" else HASH_MISMATCH
    assert (caught.value.code, caught.value.locator) == (code, take.locator)
    assert not os.path.lexists(root / record_path(PRD, RUN, "voice"))
    assert store.stage_record(PRD, RUN, "voice") is None


def reuses_inode_numbers(folder: Path) -> bool:
    """Whether this file system gives a freed inode number to the next file created
    (ext4 does at once; xfs does not)."""
    folder.mkdir()
    probe = folder / "probe"
    probe.write_bytes(b"first")
    number = probe.stat().st_ino
    probe.unlink()
    probe.write_bytes(b"other")
    return probe.stat().st_ino == number


def test_f6_a_blob_replaced_where_inode_numbers_are_reused_leaves_no_record(root, tmp_path):
    """Second review, finding 1: on ext4 a blob unlinked and created again gets the
    freed inode number, so a device-and-inode check against a closed descriptor passes.
    The store holds the hashed blob open, so its number is not free to be reused."""
    if not reuses_inode_numbers(tmp_path / "inode-probe"):
        pytest.skip("tmp_path's file system does not give a freed inode number to the next "
                    "file (xfs); run with --basetemp on ext4 to exercise this")
    store = LocalStore(root)
    take = store.publish(b"take one", scope=PRD, media_type="audio/wav")
    path = root / take.locator

    def replace():
        os.unlink(path)
        path.write_bytes(b"take two")  # the same size; the freed number, were it free

    with pytest.raises(StoreError) as caught:
        LocalStore(root, on_step=At("record:check", replace)).complete_stage(
            StageRecord(PRD, RUN, "voice", {"take:1": take}))
    assert (caught.value.code, caught.value.locator) == (HASH_MISMATCH, take.locator)
    assert not os.path.lexists(root / record_path(PRD, RUN, "voice"))
    assert store.stage_record(PRD, RUN, "voice") is None


def test_f6_a_blob_rewritten_in_place_before_the_record_link_leaves_no_record(root):
    """Second review, finding 6 note: chmod, write other bytes of the same size, chmod
    back. The held file's times move, so it is hashed again before the record's link.
    (Its mtime is set far back first, so the rewrite moves it whatever the clock's
    granularity.)"""
    store = LocalStore(root)
    take = store.publish(b"take one", scope=PRD, media_type="audio/wav")
    path = root / take.locator
    os.utime(path, ns=(0, 0))

    def rewrite():
        path.chmod(0o644)
        with open(path, "r+b") as handle:
            handle.write(b"take two")
        path.chmod(0o444)

    with pytest.raises(StoreError) as caught:
        LocalStore(root, on_step=At("record:check", rewrite)).complete_stage(
            StageRecord(PRD, RUN, "voice", {"take:1": take}))
    assert (caught.value.code, caught.value.locator) == (HASH_MISMATCH, take.locator)
    assert not os.path.lexists(root / record_path(PRD, RUN, "voice"))


def test_a_blob_whose_times_moved_with_the_same_bytes_is_hashed_again_and_recorded(root):
    """A link count that moves (another publication of the same bytes unlinking its
    ``.part``) moves ``st_ctime``; the bytes are hashed again and the record goes in."""
    store = LocalStore(root)
    take = store.publish(b"take one", scope=PRD, media_type="audio/wav")
    path = root / take.locator

    def touch():
        extra = path.with_name("extra-name")
        os.link(path, extra)
        os.unlink(extra)
        os.utime(path, ns=(1, 1))  # makes the move visible whatever the clock's granularity

    record = LocalStore(root, on_step=At("record:check", touch)).complete_stage(
        StageRecord(PRD, RUN, "voice", {"take:1": take}))
    assert store.stage_record(PRD, RUN, "voice") == record


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads files whatever their mode")
def test_an_unreadable_blob_is_blob_missing_for_the_ledger_not_an_os_error(root):
    store = LocalStore(root)
    take = store.publish(b"take one", scope=PRD, media_type="audio/wav")
    record = StageRecord(PRD, RUN, "voice", {"take:1": take})
    (root / take.locator).chmod(0o000)
    try:
        with pytest.raises(StoreError) as caught:
            store.complete_stage(record)
    finally:
        (root / take.locator).chmod(0o444)
    assert (caught.value.code, caught.value.locator) == (BLOB_MISSING, take.locator)
    assert "Permission denied" in caught.value.message
    assert not os.path.lexists(root / record_path(PRD, RUN, "voice"))


def test_f6_readers_refuse_a_record_whose_blob_was_removed_after_the_commit(root):
    store = LocalStore(root)
    take = store.publish(b"take one", scope=PRD, media_type="audio/wav")
    store.complete_stage(StageRecord(PRD, RUN, "voice", {"take:1": take}))
    os.unlink(root / take.locator)  # another writer, after the commit
    for verify in (True, False):
        with pytest.raises(StoreError) as caught:
            store.stage_record(PRD, RUN, "voice", verify=verify)
        assert (caught.value.code, caught.value.locator) == (BLOB_MISSING, take.locator)
    with pytest.raises(StoreError) as caught:
        completed_stage(store, production_id=PRD, run_id=RUN, stage="voice")
    assert caught.value.code == BLOB_MISSING
    assert store.doctor().dangling == ((record_path(PRD, RUN, "voice"), take.locator),)


# Third review: an earlier output replaced while a later one is being looked at ---------


def test_an_output_replaced_while_a_later_one_is_checked_leaves_no_record(root, monkeypatch):
    """Third review, finding 1: two outputs; while the final check looks at the second,
    the first is removed and re-created with other bytes of the same size. The second
    sample of the names sees it, and no record is linked."""
    store = LocalStore(root)
    first = store.publish(b"take one", scope=PRD, media_type="audio/wav")
    second = store.publish(b"bbbbbbbb", scope=PRD, media_type="audio/wav")
    record = StageRecord(PRD, RUN, "voice", {"aaa": first, "zzz": second})
    state = {"armed": False, "done": False}
    lstat = LocalStore._lstat

    def swapping(self, rel, root=None):
        if state["armed"] and not state["done"] and rel == second.locator:
            state["done"] = True  # during the look at "zzz", after "aaa" was accepted
            path = Path(self.root) / first.locator
            os.unlink(path)
            path.write_bytes(b"take two")
        return lstat(self, rel, root)

    monkeypatch.setattr(LocalStore, "_lstat", swapping)

    def arm():
        state["armed"] = True

    with pytest.raises(StoreError) as caught:
        LocalStore(root, on_step=At("record:check", arm)).complete_stage(record)
    assert state["done"]
    assert (caught.value.code, caught.value.locator) == (HASH_MISMATCH, first.locator)
    assert not os.path.lexists(root / record_path(PRD, RUN, "voice"))


class _Liar(dict):
    """A mapping that claims one item whatever it holds."""

    def __len__(self) -> int:
        return 1


def test_the_output_limit_counts_items_not_what_the_mapping_claims(root):
    """Third review, finding 2: a mapping whose ``len`` lies is counted as it is copied,
    in the record and in the commit, before anything is written."""
    from haynes_studio.store import MAX_OUTPUTS

    store = LocalStore(root)
    blob = store.publish(b"take one", scope=PRD, media_type="audio/wav")
    with pytest.raises(StoreError) as caught:
        StageRecord(PRD, RUN, "voice", _Liar({f"take:{i}": blob for i in range(MAX_OUTPUTS + 1)}))
    assert caught.value.code == "store.record_invalid"
    before = tree(root)
    outputs = _Liar({f"take:{i}": StageOutput(b"x", "audio/wav") for i in range(MAX_OUTPUTS + 1)})
    with pytest.raises(StoreError) as caught:
        commit_stage(store, production_id=PRD, run_id=RUN, stage="voice-2", outputs=outputs)
    assert caught.value.code == "store.record_invalid"
    assert tree(root) == before  # the refused commit wrote nothing
