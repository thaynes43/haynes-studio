# Store, stages and the pre-build check

`haynes_studio.store` and `haynes_studio.stages` (story
[379](https://work.haynesnetwork.com/work_packages/379), epic
[372](https://work.haynesnetwork.com/work_packages/372)): the D39 store layout,
create-only atomic publication, stage completion records, a read-only `store doctor`,
and the checks a build runs before its first renderer call. Built against
[contract v1](../contracts/studio-contracts-v1.md) section 8, with sections 4 and 6 for
what the pre-build check reads. Nothing here deletes, purges, truncates or renames
(D17), and there is no command line yet.

Only the `local` adapter (the CLI and tests) is built. The installed store, NFS blobs
with a Postgres ledger and a start-up probe, is story
[434](https://work.haynesnetwork.com/work_packages/434).

The target is Linux (session pods, CI, the render worker): the adapter walks folders
with `openat` and links through `/proc/self/fd`. It needs a file system that keeps
file modes and hard links, with `/proc` mounted.

## Modules

| Module | What |
|---|---|
| `store.layout` | the layout, `parse_locator`, `blob_locator`, `record_path`, media type to extension |
| `store.base` | the `Store` (blobs) and `StageLedger` (completion records) interfaces |
| `store.local` | `LocalStore`: publication, the ledger as files, `doctor()` |
| `store.records` | `Blob`, `StageRecord` and `canonical_json` |
| `store.errors` | `StoreError` and the codes below |
| `stages.commit` | `commit_stage`, `completed_stage` |
| `stages.preflight` | `preflight`, `ensure_buildable`, `ResolvedVersion`, `Problem` |

## Layout and locators

```
<root>/library/sha256/<h[0:2]>/<h>.<ext>
<root>/productions/<production_id>/sha256/<h[0:2]>/<h>.<ext>
<root>/productions/<production_id>/records/<run_id>/<stage>.json   (local adapter only)
<root>/.staging/<random>.part
<root>/.probe/                                                       (NFS adapter, story 434)
```

A locator is a blob's relative path, matched whole: `library` or
`productions/prd_<ULID>`, then `sha256/`, the hash's first two hex digits, the
64-digit lower-case hash and one of `mp4`, `wav`, `png`, `jpg`, `webp`, `json`.
Anything else fails `store.locator_invalid`: an absolute path, `..`, `.`, an empty
component, a backslash, a trailing newline, upper-case hex, a fan folder that is not
`h[0:2]`, another extension, a record path. Nothing is normalized first.

The extension comes from the media type the caller gives (`video/mp4`, `audio/wav`,
`image/png`, `image/jpeg`, `image/webp`, `application/json`); the store does not sniff
bytes. Another media type is `store.media_type_unsupported`.

## Publishing one file

`LocalStore(root).publish(source, scope=..., media_type=..., expected_sha256=None)`
returns a `Blob` (`sha256`, `bytes`, `media_type`, `locator`). `scope` is `"library"`
or a production ID; `source` is bytes, a `pathlib.Path` or a binary file object (a
plain `str` is refused).

Every write works on descriptors, as every read does. A publication opens the root
once and reaches each folder below it one component at a time with
`O_DIRECTORY | O_NOFOLLOW`, making a missing one with `mkdir` relative to its parent's
descriptor and `fsync`ing that parent (also when another writer made the folder, so a
blob's name is durable before a record that names it). A symbolic link or a file where
a folder belongs is `store.collision`; it is never followed. Each step of section 8 is
one method, and `on_step` is called after each one, so a test can inject a failure
there:

| Section 8 step | As implemented | Method | `on_step` |
|---|---|---|---|
| 1. open `.staging/<random>.part` with `O_CREAT \| O_EXCL` | `O_CREAT \| O_EXCL \| O_NOFOLLOW`, relative to the `.staging` descriptor; the file's and the folder's descriptors stay open until the publication ends | `_open_staging` | `open` |
| 1. stream the bytes while hashing | before each write the file's only name must still be its `.part` in the held `.staging` (not linked or renamed elsewhere) and it must have no write bit, else `store.collision` | `_stream` | `write` |
| 2. `fsync` | the staging descriptor | `_sync_and_check` | `fsync` |
| 2. check size and hash, and the expected hash | re-read through the staging descriptor (`pread`), never by name | `_sync_and_check` | `check` |
| 3. `link()` to the final path | the same name and mode check (`store.collision`), re-read the hash (`store.hash_mismatch`), then `link("/proc/self/fd/<fd>", name, dst_dir_fd=<final folder>)`: the checked inode, not a name. Afterwards the final path, walked again from the root, must be a regular file with that device and inode, else `store.collision` naming the final path and nothing further changes | `_link` | `link` |
| 3. on `EEXIST`, re-hash the existing file | held open from here to the end; success only if it is a regular file (not a link) of the staged hash and size, with no write bit, and every other name it has is a `.part` in the store's `.staging`; else `store.collision`. The names are counted by sampling the link count, listing `.staging` for `.part` names of that inode, sampling again, and checking each counted name again; it counts only if nothing moved (up to three tries), and then the link count less one must equal the count. The file is never changed or `chmod`ed | `_adopt` | `link` |
| 4. unlink the staging file | `unlink(name, dir_fd=<.staging>)`, only if the root's `.staging` is still the folder the publication holds, the staging file has exactly two names (its `.part` and the final name; one, the `.part`, when the final file was adopted) and the name still names it; otherwise, or if the unlink fails, the name is left and a `StagingLeftoverWarning` says so (the publication succeeded) | `_finish` | `unlink` |
| 4. `fsync` the directories | the final and staging folders' descriptors | `_finish` | `fsync_dir` |

- Final paths are only ever opened `O_RDONLY | O_NOFOLLOW | O_NONBLOCK`. A link,
  folder, FIFO or socket at a final path is a collision (and `mismatch` to `verify`).
  Published files are mode `0444`; nothing ever `chmod`s, truncates or renames.
- If `/proc/self/fd/<fd>` does not reach the staging descriptor's inode, publication
  fails closed with `OSError` (`ENOTSUP`); it never falls back to linking a name. The
  store relies on `/proc` being the kernel's procfs, where that path is a magic link
  to the open file itself (only a test replaces the constant `_PROC_FD`).
- Wherever the store asks whether a file is still the one it checked, one side is a
  descriptor it has held open since the check. ext4 gives a freed inode number to the
  next file at once, so a device and inode taken from a closed descriptor or an
  earlier `stat` proves nothing.
- `verify` and `open` raise the `OSError` of a blob they cannot read (a mode, a
  folder's mode, a lease); the ledger and the pre-build check turn it into
  `store.blob_missing`.
- The only `unlink` is step 4's, of the publication's own staging name. A refused or
  interrupted publication leaves its `.part` file; nothing tidies it, and the doctor
  reports it. `tests/store/test_doctor.py` checks the source: one `os.unlink`, in
  `_finish`, with `dir_fd`; a write flag only in the staging file's open; one
  `os.link`, of `/proc/self/fd`, into a folder descriptor.
- Cost: each published byte is read three times (hashed while streaming, re-read in
  step 2, re-read before the link), the re-reads from the page cache.

After a crash at each step (tests: `tests/store/test_publish.py`):

| Crash after | Final file | Staging |
|---|---|---|
| `open` | absent | one empty `.part` |
| `write` | absent | one `.part`, not yet synced |
| `fsync`, `check` | absent | one complete `.part` |
| `link` | present, complete | one `.part` (a second link to it) |
| `unlink`, `fsync_dir` | present, complete | none |

A retry of the same bytes then succeeds. A crash during a retry of a published file
changes nothing about that file (same inode, mode, mtime and bytes).

### Another writer inside the root

What another writer does, and what the store then does (tests:
`tests/store/test_hostile.py`; the review of PR 46, findings 1 to 6):

| When | The other writer | Result |
|---|---|---|
| after `check` | replaces the `.part` name with other bytes or a symbolic link | `store.collision` (the checked inode lost its name); nothing published; the swapped-in entry stays in `.staging`; a later publish of the right bytes succeeds |
| after `check` | makes the `.part` writable and rewrites it | `store.collision` (write bit), or `store.hash_mismatch` if it restored the mode (re-read before the link) |
| during the stream | hard-links or renames the `.part` onto the final path (a blob's, or a record's, which is known in advance) | `store.collision` at the store's next check, before its next write: the final name shows only what was written up to then (nothing, if before the first write); a retry is `store.collision`; the doctor lists a blob as `damaged`, readers refuse a record (`store.record_invalid`) |
| after the last write | renames the `.part` onto the final path | `store.collision` at the name check before the link; nothing is linked |
| in the last gap before `link` | removes the `.part` | `store.collision` (`link` finds no file); nothing is linked |
| just before `link` | swaps the final folder for a link out of the root | the link lands in the store's own folder (moved aside); the walk after it fails: `store.collision`, `.part` kept, nothing outside |
| just after `link` | replaces the final name | `store.collision` naming the final path; `.part` kept |
| just before the `.part` is created | swaps `.staging` for a link out of the root | the `.part` is made in the store's own folder (moved aside); its unlink is skipped with a warning; nothing outside |
| after `link` | swaps `.staging` for a link, or replaces the `.part` name | no unlink, a warning; the other file is untouched |
| after `link` | makes `.staging` read-only | the unlink fails: a warning, the publication stands |
| after `link` | gives the staging file another name | no unlink (it has three names, not two), a warning |
| before the publish | leaves a writable file, or one with another name (outside the root, or in the store but not a `.part` in `.staging`), at the final path | `store.collision`; the file is not changed |
| while an existing final file's names are counted | adds `.part` links of it only for the count, and removes them before the second sample | `store.collision` (a counted name is gone at the re-check); the file is not changed |
| after a record's blob checks (`record:check`) | removes a blob | `store.blob_missing`; no record |
| after a record's blob checks (`record:check`) | unlinks a blob and creates other bytes of the same size in its place (on ext4 that new file would get the freed inode number, but the store holds the hashed blob open, so the number is not free) | `store.hash_mismatch`; no record |
| after a record's blob checks (`record:check`) | rewrites a blob in place (`chmod`, write, `chmod` back) | if its size, `st_mtime` or `st_ctime` moved, the store hashes it again: `store.hash_mismatch`, no record. A rewrite that moves none of them (see the limits) is not seen here; readers and the doctor find it by re-hashing |
| any time | plants other bytes of the recorded size at a blob's locator | `complete_stage` and `stage_record`: `store.hash_mismatch`; doctor: `damaged` and `mismatched` |
| any time | makes a blob or its folder unreadable | the pre-build check reports `store.blob_missing` for that locator; the doctor lists it in `unreadable` |

Threat model: another writer with write access to the folders inside the root can
create, remove, rename, link, `chmod` or rewrite any entry there at any moment. It
cannot make the store follow a symbolic link, write or remove an entry outside the
folders the store opened, remove any name but a publication's own staging name (except
in the one gap below), or get a file linked or recorded other than the inode the store
hashed and still holds open; it can still change that inode's bytes in place (`chmod`,
then write) after the store's last read of it, which only a re-hash finds.

Limits that remain:

- Every check is a moment: one system call separates it from the call it guards (the
  name and mode checks and re-read before the link, the blob checks before a record's
  link, the name and link-count checks before the unlink).
- There is no call that removes a name only if it is a given inode. A rename of the
  held folder plus a name swap in that last gap can remove a different file, possibly
  outside the root: a writer that moves `.staging` out of the root and renames another
  file onto the `.part` name between the checks and the unlink loses that file, and no
  warning is given (`test_limit_a_folder_move_and_a_name_swap_in_the_last_gap_remove_the_other_file`).
  The checks narrow the gap to that one call; they cannot close it.
- The `.part` has a name from step 1 (section 8 requires it), so a writer can hard-link
  or rename it onto a final path while the bytes are written. The final name then shows
  what the store wrote up to its next check (at most one chunk after the link); the
  store stops, refuses, and the path stays refused for the real bytes until a person
  removes the file (D17). Only an unnamed staging file (`O_TMPFILE`) would close this,
  and section 8 does not use one.
- A writer that moves a folder the publication holds out of the root (on the same file
  system) moves the link or the `.part` with it. The store notices and fails, or keeps
  the `.part` with a warning, but cannot undo it.
- On `EEXIST`, a read-only regular file of the right bytes with no other name is
  adopted, whoever wrote it; its owner is not checked. No sequence of samples is
  atomic: a writer that times its link and unlink calls around each sample (adding
  `.part` links of the file for the listing, removing them just before the second
  sample and adding them back before the re-check) can still hide outside names, as
  many as it adds `.part` links for. One outside name is enough to change the bytes
  later, if its writer may write the file.
- The same rule refuses honest second names: a hard-link dedupe (`hardlink`, `rdfind`)
  across the store, a hard-link backup of it (`cp -al`, rsnapshot), or a leftover
  `.part` moved out of `.staging`. Publishing those bytes again, or retrying a
  completed stage's commit, is then `store.collision` and leaves a `.part` each time
  (nothing tidies it, D17). Back the store up by copying, not by hard links. The
  doctor lists such files as `foreign`.
- A writer running as the store's user can `chmod` a file and open it for writing at
  any time (a `.part` from its creation on, or a published file) and write through that
  descriptor after the store's last read: the mode and name checks cannot see an open
  descriptor. `verify`, `stage_record` (by default), the pre-build check and the doctor
  find it by re-hashing; only running the store as its own user would prevent it.
- Before a record's link, an in-place rewrite of a blob is seen only through the held
  file's size, `st_mtime` and `st_ctime`. On a kernel without fine-grained file
  timestamps (Linux before 6.13, or a file system without them) the times move in
  clock ticks of a few milliseconds, so a same-size rewrite within the tick of the hash
  can leave all three unchanged and the record goes in; readers and the doctor still
  find it by re-hashing. A move (a link count that changed, say) makes the store hash
  the file again, up to three times, before it gives up with `store.hash_mismatch`.
- The root itself is opened by its path, without `O_NOFOLLOW` (the caller names it and
  may name a link), once per operation: one publication, or one `complete_stage`, which
  holds it across its blob checks and the record. Every folder below it is reached
  with `O_NOFOLLOW`. A writer that can rename or replace the root, from its parent
  folder, is outside this model.
- The store relies on `/proc` being the kernel's procfs. If a normal symbolic link
  stood in place of `/proc/self/fd/<fd>`, a writer able to retarget it between the
  store's check and its `link` could deposit another file at the final path; the call
  then raises `store.collision` and that file stays.
- A stage lists at most `MAX_OUTPUTS` (256) outputs (proposal): `complete_stage` holds
  one descriptor per output until the record is linked. `commit_stage` and
  `StageRecord` refuse more with `store.record_invalid` before anything is written.

### What the store promises, and what it does not

The store is not a security boundary against a process that can write inside its root.
What it guarantees to such a writer's peers is this: a file is never published outside
the root or over another file, and a reader that verifies (the default for
`stage_record`, and what `verify`, the pre-build check and the doctor do) either gets
the bytes the record names or an error. The checks made while publishing are early
detection, not proof. Three gaps are known and stay open:

- **Between the last look at a blob and the record's link.** The final check samples
  every output's name twice in a row, so a blob replaced during the first sample is
  caught by the second. A blob replaced during the second sample is not: with *n*
  outputs that window is up to *n* system calls. The record then names bytes that are
  no longer there; a verifying reader and the doctor report it.
- **The last call of a publication.** A writer that renames the held staging folder
  out of the root and swaps the staging name inside the `unlink` call gets another
  file removed, possibly outside the root. Inside that same call, a hard link made
  from the staging name to a path outside the root survives, so the published file
  keeps an outside name through which it can later be rewritten. There is no
  unlink-by-inode call to close this.
- **Adoption of an existing final file.** A writer that adds and removes staging names
  exactly around both link-count samples can hide outside names of a file the store
  then accepts as its own.

## Stage commit

`commit_stage(store, production_id=, run_id=, stage=, outputs={name: StageOutput(source,
media_type, expected_sha256)})` checks the IDs, the stage name, the output names and
media types before writing anything, publishes every output into the production's
folder in name order, then writes one completion record through the ledger
(`store.complete_stage`). Readers use `completed_stage(ledger, ...)`, which returns
`None` until the record exists.

- `complete_stage` opens every blob the record lists read-only through the descriptor
  walk and re-hashes it: each must be a regular file of its recorded hash and size
  (`store.blob_missing` if absent or unreadable, `store.hash_mismatch` otherwise). It
  keeps each descriptor open until the record's `link` has returned, which pins the
  inode: its number cannot be given to a file created in its place. Immediately before
  that `link`, each locator must still name the held inode (walked again, no link
  followed), and the held file's size, `st_mtime_ns` and `st_ctime_ns` must be as they
  were when it was hashed; if they moved, it is hashed again through the held
  descriptor (up to three times). Otherwise the store links no record. The checks and
  the record's publication share one root descriptor. A stage lists at most
  `MAX_OUTPUTS` (256) outputs, so at most that many descriptors are held.
- `LocalStore.stage_record(..., verify=True)` refuses a record whose blob is absent
  (`store.blob_missing`) or not a regular file of the recorded size
  (`store.hash_mismatch`). With `verify` (the default) it also re-hashes every blob,
  which reads all of the stage's outputs on every call: about the cost of reading the
  files once. `verify=False` costs one `fstat` per blob and does not prove the bytes;
  use it only to list.
- `completed_stage(..., store=)` re-hashes every blob again through the store, for a
  ledger that cannot see the blobs (the product's Postgres ledger, story 434). With
  the local ledger it is already done by default.

The record (`studio.stage-record/v1`, a local-adapter file) is canonical JSON of
`production_id`, `run_id`, `stage` and `blobs` (`name` to `sha256`, `bytes`,
`media_type`, `locator`). It holds no time or writer, so the same outputs always
give the same bytes. Sources and expected hashes are checked for every output before
the first is published:

- Any crash before the record's `link()` leaves no record: only orphan blobs and
  staging leftovers, which no reader trusts. From the record's `link()` on, the record
  exists and every blob it names is already published with its recorded hash.
- A retried or concurrent commit of the same outputs succeeds and returns the same
  record. One with other outputs fails `store.collision` and the finished record is
  unchanged; its new blobs stay as orphans.

Tests: `tests/stages/test_commit.py` injects a failure after each of the 28 steps of
a three-output commit, with and without a finished stage already there, and races two
threads in lockstep at every `check` step (a barrier, no sleeps).

## Store doctor

`LocalStore.doctor(referenced=())` reads the tree and returns a `DoctorReport`:
`orphans` (blobs no completed record lists and the caller did not name in
`referenced`, such as library assets from story 382), `staging` (every file under
`.staging/`, including one being written right now: check its age before removing
it), `unexpected` (files and links not in the layout; empty folders are not listed),
`broken_records` (unreadable or malformed records), `dangling` (a record naming a
missing blob; publication order makes this impossible), `damaged` (a blob whose bytes
do not hash to its name), `mismatched` (a record naming a blob that is there but not
its recorded hash and size), `foreign` (a blob or record file with a write bit, or a
name outside `.staging`: publishing it again is `store.collision`) and `unreadable`
(folders it could not list, blobs it could not read). It walks the tree through descriptors without following a link, and
reads every blob in full. It removes, moves and repairs nothing; removing a leftover
is a user action (D17).

## Pre-build check

`preflight(story, facts=, resolved=, store=)` takes story 404's `Story` model with its
boards embedded, its `Facts`, and the asset versions the library resolved
(`{asset_version_id: ResolvedVersion}`; `ResolvedVersion.of(sha256, locator)` for one
blob, `DEFINITION_ONLY` for a stock voice). It reports every problem: story-level
ones first, then by the board's place in `board_order`, then field:

1. the story's `queue_run` validation (`validate_story(..., context="queue_run",
   facts=...)`): voices, photos, methods, cue anchors and ranges, and every write rule;
2. every referenced asset version is resolved (`asset.unresolved`), and each blob a
   build reads is at a valid locator in the library or the story's own production
   (`store.locator_invalid`) and present (`store.blob_missing`) with its hash
   (`store.hash_mismatch`, re-hashed). Only the story's cast voices and narrator voice
   may resolve without bytes. A blob that cannot be read (its mode, its folder's mode,
   an I/O error) is a `store.blob_missing` problem for that locator; the check never
   raises it.

Each `Problem` has `rule`, `status`, `path` (in the story document), `board_id`,
`board_number`, `legacy_shot` (from the board's `origin`), `field` (in the board),
and `asset_version_id` and `locator` for blob problems. It prints as
`board B07 (brd_..., legacy shot 7) field /cues/0/asset_version_id: store.blob_missing
(failed): ...`. `ensure_buildable(...)` raises `PreflightError` (a `ContractError`
holding the report) when anything blocks; a build calls it before its first renderer
call. On the nine-board r4 fixture it takes about 20 ms; the store is only read.

## Codes

| Code | Status | Source |
|---|---|---|
| `store.locator_invalid` | invalid | contract section 8; also a `sha256` or `expected_sha256` that is not 64 lower-case hex digits, since it cannot name a locator |
| `store.collision` | failed | contract section 8; also a staging file another writer linked, removed or made writable, and a final name or folder replaced during a publication |
| `id.malformed`, `id.type_mismatch` | invalid | contract section 2 (production and run IDs) |
| `store.hash_mismatch` | failed | **proposal**: bytes are not the expected hash and size, or what a record names is not a regular file |
| `store.blob_missing` | failed | **proposal**: no file where a record or story needs one (in the pre-build check, also one that cannot be read) |
| `store.record_invalid` | invalid | **proposal**: a stage name, output set (none, or more than 256) or record file is malformed |
| `store.media_type_unsupported` | invalid | **proposal**: no extension for the media type |
| `asset.unresolved` | invalid | **proposal**: the library did not resolve a referenced version |

## Proposals beyond the contract

- Stage names: 1 to 128 of `A-Z a-z 0-9 _ -` (no dot). Output names: 1 to 128 of
  `A-Z a-z 0-9 _ . : -`. A stage has 1 to 256 outputs (`MAX_OUTPUTS`).
- The record is `studio.stage-record/v1` canonical JSON with no time or writer.
- Published files are read-only (`0444`).
- A story reads blobs only from the library and its own production's folder.
- The doctor takes the caller's referenced locators; without them, library blobs are
  orphans.
