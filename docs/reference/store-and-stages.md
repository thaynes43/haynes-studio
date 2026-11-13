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
plain `str` is refused). Each step of section 8 is one method, and `on_step` is
called after each one, so a test can inject a failure there:

| Section 8 step | Method | `on_step` |
|---|---|---|
| 1. open `.staging/<random>.part` with `O_CREAT \| O_EXCL` | `_open_staging` | `open` |
| 1. stream the bytes while hashing | `_stream` | `write` |
| 2. `fsync` | `_sync_and_check` | `fsync` |
| 2. check size and hash (re-read), and the expected hash | `_sync_and_check` | `check` |
| 3. `link()` to the final path; on `EEXIST` re-hash: equal is success, different is `store.collision` | `_link` | `link` |
| 4. unlink the staging file | `_finish` | `unlink` |
| 4. `fsync` the final and staging directories | `_finish` | `fsync_dir` |

- Final paths are only ever opened `O_RDONLY | O_NOFOLLOW | O_NONBLOCK`, each folder
  on the way opened relative to the last with `O_NOFOLLOW`, so no symbolic link in the
  path is followed out of the store. A link, folder, FIFO or socket at a final path is
  a collision (and `mismatch` to `verify`). Published files are mode `0444`.
- Folders are made one at a time with `mkdir`, and the parent of every folder on the
  way is `fsync`ed, also when another writer made the folder, so a blob's name is
  durable before a record that names it. Something other than a folder where one
  belongs is `store.collision`.
- The only `unlink` is step 4's, of the store's own staging file once the final path
  holds its bytes. A refused or interrupted publication leaves its `.part` file; the
  doctor reports it.

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

## Stage commit

`commit_stage(store, production_id=, run_id=, stage=, outputs={name: StageOutput(source,
media_type, expected_sha256)})` checks the IDs, the stage name, the output names and
media types before writing anything, publishes every output into the production's
folder in name order, then writes one completion record through the ledger
(`store.complete_stage`). Readers use `completed_stage(ledger, ...)`, which returns
`None` until the record exists; with `store=` it re-hashes every blob first.

The record (`studio.stage-record/v1`, a local-adapter file) is canonical JSON of
`production_id`, `run_id`, `stage` and `blobs` (`name` to `sha256`, `bytes`,
`media_type`, `locator`). It holds no time or writer, so the same outputs always
give the same bytes. Sources and expected hashes are checked for every output before
the first is published:

- Any crash before the record's `link()` leaves no record: only orphan blobs and
  staging leftovers, which no reader trusts. From the record's `link()` on, the record
  exists and every blob it names is already published. `complete_stage` also refuses a
  record that names a blob that is not a published file of its size
  (`store.blob_missing`).
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
missing blob; publication order makes this impossible) and `unreadable` (folders it
could not list). It removes, moves and repairs nothing; removing a leftover is a user
action (D17).

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
   may resolve without bytes.

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
| `store.collision` | failed | contract section 8 |
| `id.malformed`, `id.type_mismatch` | invalid | contract section 2 (production and run IDs) |
| `store.hash_mismatch` | failed | **proposal**: bytes are not the expected hash |
| `store.blob_missing` | failed | **proposal**: no file where a record or story needs one |
| `store.record_invalid` | invalid | **proposal**: a stage name, output set or record file is malformed |
| `store.media_type_unsupported` | invalid | **proposal**: no extension for the media type |
| `asset.unresolved` | invalid | **proposal**: the library did not resolve a referenced version |

## Proposals beyond the contract

- Stage names: 1 to 128 of `A-Z a-z 0-9 _ -` (no dot). Output names: 1 to 128 of
  `A-Z a-z 0-9 _ . : -`.
- The record is `studio.stage-record/v1` canonical JSON with no time or writer.
- Published files are read-only (`0444`).
- A story reads blobs only from the library and its own production's folder.
- The doctor takes the caller's referenced locators; without them, library blobs are
  orphans.
