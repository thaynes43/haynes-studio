# Private input import: The Winter Menu into a new store

Story [846](https://work.haynesnetwork.com/work_packages/846) (E1.19), epic
[372](https://work.haynesnetwork.com/work_packages/372), split out of story
[428](https://work.haynesnetwork.com/work_packages/428). `python -m haynes_studio.importer`
reads the private inputs the public records name, **read-only** from the Wan volume (PVC
`ai/wan-video`), publishes each distinct hash once, create-only, into a new store (story
[379](https://work.haynesnetwork.com/work_packages/379)), and imports it as its existing
asset version under its public source key (stories
[382](https://work.haynesnetwork.com/work_packages/382) and
[457](https://work.haynesnetwork.com/work_packages/457)). Bytes that are not the public
hash are refused and reported, never recorded as the old version.

**State: source and tested with fakes only.** Nothing here has read the Wan volume.
Story 428 makes the first live read, with the coordinator watching (the checklist at the
end).

| Module | What |
|---|---|
| [`adapters/wan_volume.py`](../../src/haynes_studio/adapters/wan_volume.py) | `VolumeReader`: a Wan job's output by job ID, an E0 upload by hash; `ledger_fetch_refusal` names the refusals of story 425's `LedgerReader.fetch_asset` |
| [`importer/plan.py`](../../src/haynes_studio/importer/plan.py) | `plan_import`: every row, every distinct hash and its sources, from public records only |
| [`importer/run.py`](../../src/haynes_studio/importer/run.py) | `run_import` (the import and its report), `dry_run` |
| [`importer/command.py`](../../src/haynes_studio/importer/command.py) | the command line; `__main__.py` runs it only as `python -m` |
| `fakes.FakeWanVolume` | the Wan volume on a real temporary folder; runs the three pinned read snippets themselves |

## Run it

The inputs are what `studio legacy import --out DIR` writes for r4
([studio-cli.md](studio-cli.md)): `story.json` and `legacy-import.json`. The library is
built from public files on top of `--library` when given (stories 382 and 457), so the
first run builds it and a second run on the first run's `library.json` creates nothing.

```sh
uv run python -m haynes_studio.importer --story DIR/story.json --map DIR/legacy-import.json \
  --operator-iss <issuer> --operator-sub <subject> --store ROOT --dry-run
uv run python -m haynes_studio.importer --story DIR/story.json --map DIR/legacy-import.json \
  --operator-iss <issuer> --operator-sub <subject> --store ROOT --out NEW_DIR \
  --authorized-by https://work.haynesnetwork.com/work_packages/428 [--library OLD/library.json]
```

- `--dry-run` lists every row and hash, its sources in order and its store locators, and
  with `--store` whether the store already holds it. It makes no runner, reads nothing
  from the Wan volume and writes nothing.
- A run makes the real runner (`kubectl exec`, as every client) once, needs
  `--authorized-by` (the full URL of the authorizing work package; it is recorded in the
  report, it is not itself authority) and a new `--out` folder, where it writes
  `import-report.json` and `library.json` create-only (mode `0444`).
- Exit status: `0` completed with no mismatch; `1` stopped, a read returned other bytes,
  or reads were made and none found its file (likely the wrong cluster context or
  container; the command says so); `2` a usage error, an unreadable input, or an `--out`
  that exists.
- Run it from the checkout (`--repo`, default `.`): the recovery map is rebuilt from the
  public files and must equal the committed
  [`legacy-recovery-map.json`](legacy-recovery-map.json).

## What it reads

156 rows, 101 distinct hashes: the 98 rows of the [recovery map](legacy-recovery-map.md),
the 36 lines of the three E0 clip record files ([motion-clips.md](motion-clips.md)), the
11 distinct doll-on-green start images those clips name, and the 11 drive tracks of the
timed clips. Each hash is one item, read at most once, from its sources in row order: the
first source whose bytes hash to the public SHA-256 ends the reads. 79 hashes have a
source (at most 129 reads); 22 have none.

| Role | Rows | Source | Read with |
|---|---|---|---|
| still, set, sfx, take | 78 (28 hashes) | each `wan_pvc` locator: ledger ID and recorded path | `LedgerReader.fetch_asset` (story 425) |
| render | 8 | none (ComfyUI is not read; `set-left-s221` has the set's bytes, so it is verified with the set) | |
| bed | 3 (1 hash) | none: **never delivered** to the Wan volume | |
| keyframe | 9 (7 hashes) | the `wan_upload` locator | `VolumeReader.fetch_upload` |
| doll_loop, set_loop, timed_clip | 22 | the clip record's `job_id` | `VolumeReader.fetch_job_output` |
| start_image | 11 | the upload named by the clip record's `image_sha256` | `VolumeReader.fetch_upload` |
| drive_track | 11 | the upload named by a timed clip record's `audio_sha256` (`.wav`; P-846-09) | `VolumeReader.fetch_upload` |
| not_motion | 14 | none: whole-frame clips (story 427's) and the whole-frame S2V test | |

`job_dir` locators (an earlier session's home) are never read.

## Read paths and their guards

Every file the import may read. Each read is a `Command` handed to the runner; the code
that runs in the pod is a pinned snippet ([`pinned.py`](../../src/haynes_studio/adapters/pinned.py)),
checked before each command. Tests run the snippets themselves on a real folder
(`FakeWanVolume`); unless a file is named they are in
[`tests/adapters/test_wan_volume.py`](../../tests/adapters/test_wan_volume.py).

| Read | File | Path built from | Limit | Guards | Tests |
|---|---|---|---|---|---|
| Delivered asset (story 425, unchanged) | `/workspace/output/productions/...` as its ledger `/workspace/jobs/<ledger_id>.json` lists it | a 32-hex ledger ID and a 64-hex hash; the path comes from the ledger, resolved and held under `/workspace/output/productions` | 64 MiB | see [legacy-adapters.md](legacy-adapters.md#clients); its refusals are read by their fixed messages (`ledger_fetch_refusal`); any other failure stops the import | `test_every_ledger_message_is_one_the_pinned_snippet_prints`, `test_ledger_fetch_refusals_are_named`, `test_ledger_fetch_refuses_a_ledger_that_is_a_link_not_a_delivery_or_not_json`, `test_ledger_client_checks_are_named`, `test_any_other_ledger_failure_is_not_a_refusal` |
| Job ledger (`wan_job_output_read.py`) | `/workspace/jobs/<job_id>.json` | a 32-hex job ID, checked in the client and the pod | 16 MiB | each folder below `/workspace` and the file: `lstat` (a link is `source_link`, anything but a folder or regular file `source_not_regular`), then `os.open` with `O_NOFOLLOW` (`O_DIRECTORY` for a folder, `O_NONBLOCK` for a file) relative to its folder's descriptor, and the descriptor must be the inode the `lstat` saw; an open that fails as a swap fails (`ENOENT`, `ELOOP`, `ENOTDIR`, `ENXIO`) or another inode is `source_changed`, any other error (a permission, an I/O error) a traceback, so a stop; the fixed folders (`jobs`, `output`) missing or not plain folders are `adapter.volume_unexpected`, a stop; read to the end from that descriptor; JSON object with that `id`, `state: succeeded` and a text `output` (`source_record_invalid`) | `test_a_missing_ledger_or_output_is_missing`, `test_a_ledger_that_is_not_a_succeeded_job_of_that_id_is_refused`, `test_an_unparseable_ledger_is_refused`, `test_a_symlinked_ledger_is_refused`, `test_an_oversized_ledger_is_refused`, `test_a_symlinked_folder_on_the_path_is_refused`, `test_a_missing_fixed_folder_is_the_wrong_volume_not_a_missing_file`, `test_a_missing_root_is_a_failure_not_a_refusal`, `test_a_permission_or_io_error_is_a_failure_that_stops_not_a_refusal` |
| Job output (`wan_job_output_read.py`) | `/workspace/output/<output>` | the ledger's `output`: 1 to 8 parts, each `[A-Za-z0-9_][A-Za-z0-9._-]{0,254}`, the last ending `.mp4`; one leading `/` allowed (the API writes it for an empty subfolder); else `source_outside` | 64 MiB | as the ledger, plus exactly one link (`source_hard_link`), at most the limit before and while reading (`source_too_large`), the size the ledger records when it records one (`source_hash_mismatch`), unchanged size and link count after the read (`source_changed`), SHA-256 equal to the requested hash in the pod (`source_hash_mismatch`); the client checks size and hash again | `test_a_job_output_is_read_and_hash_checked`, `test_an_output_at_the_output_root_is_read`, `test_an_output_path_that_is_not_plain_names_below_output_is_outside`, `test_a_symlinked_output_is_refused_even_to_identical_bytes`, `test_a_symlinked_folder_on_the_path_is_refused`, `test_a_fifo_or_a_folder_is_not_regular_and_never_opened`, `test_a_file_where_a_folder_belongs_is_not_regular`, `test_a_hard_linked_output_is_refused`, `test_an_oversized_output_is_refused_before_it_is_read`, `test_other_bytes_or_another_size_than_the_ledger_records_are_a_mismatch`, `test_a_file_swapped_for_a_link_after_its_lstat_is_refused`, `test_a_file_replaced_after_its_lstat_is_refused` |
| E0 upload (`wan_upload_read.py`) | `/workspace/input/studio-e0/<name>` | `<name>` = the hash's first 16 hex digits and `.png` or `.wav` (as `poc/wan.py` and `poc/s2v.py` named uploads), built by the client from the hash and checked again in the pod; no caller text | 20 000 000 bytes (`wan_upload.py`'s own limit) | the same folder walk and file checks as a job output (fixed folders `input`, `studio-e0`), then the hash | `test_an_upload_is_read_by_its_hash`, `test_a_malformed_upload_request_is_refused_before_anything_runs`, `test_the_upload_name_is_checked_in_the_pod_too`, `test_a_missing_upload_is_missing_and_a_missing_upload_folder_the_wrong_volume`, `test_a_symlinked_upload_or_upload_folder_is_refused`, `test_a_fifo_folder_hard_link_or_oversized_upload_is_refused`, `test_an_upload_with_other_bytes_is_a_mismatch` |

For all three: no write path. `VolumeReader` has only `fetch_*` and `*_command`
methods; the two new snippets are held to an allowlist of calls, every `os.open` is
`O_RDONLY | O_NOFOLLOW` relative to a folder descriptor (the `/workspace` root alone is
opened by name without `O_NOFOLLOW`: it is the mount point), and the code has no
`O_WRONLY`, `O_RDWR`, `O_CREAT`, `O_TRUNC`, `O_APPEND`, rename, link, `chmod`, truncate,
delete, `mkdir`, URL, socket or process anywhere (`test_the_snippets_only_read`,
`test_the_reader_has_no_write_method`, `test_no_read_leaves_a_file_on_the_volume_changed`).
A refusal is one stderr line, `REFUSED <reason>`, and exit status 3, with nothing on
stdout; `kubectl exec` then adds `command terminated with exit code 3`, which the client
skips (the fake volume adds it too: `test_kubectls_exit_line_after_a_refusal_is_not_the_snippets`,
`test_the_fake_volume_adds_kubectls_line_like_the_real_exec`); any other exit is
`adapter.command_failed` (`test_any_other_failure_is_not_a_refusal`). The snippets run as
`python3 -I -c` (isolated mode: the container's working folder and `PYTHON*` variables
cannot replace the standard library they import; the other clients' commands are
unchanged). A changed snippet is refused before anything runs
(`test_a_changed_snippet_is_refused_before_anything_runs`).

| Snippet | Source | SHA-256 |
|---|---|---|
| `wan_upload_read.py` | new in story 846 | `6945c756d3e2d4d15307e26d6527758a5b14740b8c3f48e4b292026395dc38a9` |
| `wan_job_output_read.py` | new in story 846 | `5a16cec45659cc6879cd17d783c8d3a2d472590f19b75ba0fefd2721dad20129` |

## The import, per hash

In plan order ([`run.py`](../../src/haynes_studio/importer/run.py); tests in
[`tests/importer/`](../../tests/importer/)):

1. **Held?** `Store.verify` (it re-hashes) at each locator the hash needs. All present:
   nothing is read or written (`test_a_second_import_reads_nothing_and_changes_nothing`).
   Some present: the others are copied from the store, not read again
   (`test_a_hash_held_in_one_scope_is_copied_within_the_store_not_read_again`). Other bytes
   at a locator: **stop** (`test_other_bytes_already_at_a_locator_stop_the_import`).
2. **Read** the sources in order. A refusal (`adapter.source_*`) is recorded and the next
   source tried (`test_the_next_source_is_tried_after_a_refusal_and_reads_stop_at_the_first_good_one`).
   Any other failure (a timeout, a `kubectl` failure or denial, `adapter.volume_unexpected`,
   an unknown message, a pin mismatch, a store error, or an error no code names:
   `import.failed`) **stops the whole import**: nothing is retried, the stopping hash keeps
   its attempts, bytes and anything already published, `stopped` holds the code, message
   and redacted stderr tail, and every row from there is reported `absent`,
   `not_read: the import stopped at <code>`
   (`test_a_failure_that_is_not_a_refusal_stops_the_import`, `test_a_timeout_stops_the_import`,
   `test_a_publication_that_fails_after_a_good_read_stops_and_keeps_what_was_read`,
   `test_an_error_no_code_names_stops_the_import_and_the_report_is_still_made`).
3. **Check the records before publishing:** each library version with this hash is
   imported again with the bytes' measured content at its own locator, its own source key
   and ID. It must return that version (`created: false`); a record the bytes contradict
   (`idempotency.mismatch`) makes the hash a `mismatch` and nothing is published
   (`test_each_record_resolves_to_its_existing_version`,
   `test_bytes_the_record_contradicts_are_refused_never_recorded`).
4. **Publish** create-only into each scope with the expected SHA-256, and check the blob.

A refused read gives a named error and no record of any kind: no blob, no version, the
store unchanged (`test_a_refused_read_is_a_named_error_and_no_record`, for a delivered
still, a clip and a start image: missing, other bytes, oversized, outside, link, not a
regular file, hard link).

The twin ([`tests/importer/twin.py`](../../tests/importer/twin.py)) is the real record
structure with every media hash replaced by the hash of synthetic bytes (no test can make
bytes with a private file's hash). On it, a full run verifies every delivered hash, reads
each once, and the r4 story then lacks only the fire bed
(`test_every_delivered_hash_is_verified_and_the_story_lacks_only_the_fire_bed`). On the
real records with an empty fake volume every row is `absent`
(`test_a_run_against_an_empty_volume_reports_every_row_absent`).

## The report

`import-report.json`, `kind: private-input-import`, `version: 1`:

| Field | Holds |
|---|---|
| `built_by`, `authorized_by`, `dry_run`, `production_id` | this story's URL, the `--authorized-by` URL, `false`, the story's production |
| `started_at`, `finished_at`, `elapsed_s` | UTC times and seconds |
| `stopped` | `null`, or the `code`, `message`, `detail` (the redacted stderr tail), `sha256` and `source` it stopped at |
| `totals` | `rows`, `hashes`, `verified`, `absent`, `mismatch` (rows) and `hashes_*` (hashes), `hashes_read`, `bytes_read` (from the Wan volume), `bytes_published` (new blobs), `by_role` (each role's three counts) |
| `rows[]` | `key` (the recovery map's, or `e0:<file>:<line>:<clip>`, or `e0:start_image:<image>`), `role`, `sha256`, `status`, `reason`, `locators` (the store locators holding it), `version_ids` |
| `hashes[]` | `sha256`, `media_type`, `status`, `reason`, `rows`, `locators`, `read_from` (the source, `{kind: store, locator}`, or `null` when nothing was read), `attempts[]` (`source`, `outcome`: `verified` or an `adapter.source_*` code, `seconds`, `bytes`, `message`), `versions[]` (`version_id`, `source_key`, `created: false`), `bytes_read`, `bytes_published` |
| `lacks` | after a run that did not stop: `story` (the library resolver's problems for the r4 story, by the store's own `exists`), `layered_loops` (`layered.pin.pin_story`'s problems per layered board, by `Store.verify`), `versions_not_held` (every library version whose bytes the store lacks) |
| `library` | `versions`, and `created_now` by the public build (`winter_menu`, `e0_motion`) |

Statuses: `verified` the store holds the public hash; `absent` it does not (`reason` says
why: the refusals' codes, `never_delivered: ...`, `not_read: ...`); `mismatch` a read
returned other bytes (`adapter.source_hash_mismatch`, in the pod or the client) or a record
contradicts the bytes (`idempotency.mismatch`). The dry run's report has `dry_run: true`
and, per row and hash, `would`: `held` (nothing to do), `copy` (held in another scope:
copied within the store), `to_read`, `not_read` (no source) or `stop` (the store holds
other bytes at its locator, or could not be read)
(`test_the_dry_run_says_what_a_run_would_copy_or_stop_at`).

**The fire bed** (`sfx/fire-s701.wav`, `0b33af45929b8cfb`) is expected `absent`,
`never_delivered`: `poc/deliver.py` copied no bed to the Wan volume. With every other
delivered hash verified, `lacks.story` is exactly one `asset.bytes_missing` at
`/beds/0/asset_version_id`. Its replacement is a new sound version made in story 428
(D54), never a repointed old one.

## Proposals

Choices beyond the contract, each open to change:

- **P-846-01** Two read-only snippets, `wan_job_output_read.py` and `wan_upload_read.py`,
  read the volume directly (not `GET /videos/<id>/file`, which story 842's
  `wan_clip_fetch.py` uses), so the read can refuse links, hard links and non-regular
  files itself; they walk every folder below `/workspace` by descriptor with `O_NOFOLLOW`,
  which also closes the "folder above swapped for a link" gap story 425's snippet records.
- **P-846-02** Refusals are `REFUSED <reason>` and exit status 3, mapped to nine named codes
  (`adapter.source_missing`, `_link`, `_not_regular`, `_hard_link`, `_too_large`,
  `_outside`, `_hash_mismatch`, `_record_invalid`, `_changed`). Story 425's fetch is read
  by its fixed messages instead, so that client does not change.
- **P-846-03** Sources are tried in the rows' order (r1's ledger first); a refusal moves to
  the next source, any other failure stops the whole import and nothing is retried.
- **P-846-04** A hash with no library version (takes, keyframes, start images, r1 to r3
  only files) is published into the production's folder at
  `productions/<prd>/sha256/<h[0:2]>/<h>.<ext>`, so a build that reads it by hash finds it.
- **P-846-05** The import re-imports each version with the store's measured `bytes` and the
  version's own recorded `width` and `height` (the store measures no pixels).
- **P-846-06** Rows not read are `absent` with a reason (`never_delivered`, `not_read`),
  so the report keeps the contract's three statuses.
- **P-846-07** A run needs `--authorized-by` with a full work package URL and a new
  `--out`; exit 1 on a stop or a mismatch.
- **P-846-08** The Principal is `cli` with command `studio private import` and the
  operator's OIDC issuer and subject.
- **P-846-09** The speech-to-video drive tracks (`studio-e0/<16 hex>.wav`, uploaded by
  `poc/s2v.py`) are read too: no record outside the volume keeps them, and a timed clip's
  motion record names its drive track's hash. A layered build makes its own drive tracks,
  so it does not need them.
- **P-846-10** A run whose reads all found nothing exits 1 (a likely wrong context or
  container), and a missing or linked fixed folder of the volume is
  `adapter.volume_unexpected`, a stop, not one `source_missing` per row.
- **P-846-11** The new snippets run under `python3 -I`.

## Known limits

- One system call separates each `lstat` from its `open`; the inode check after the open
  refuses a swap (`source_changed`), but opening a device or FIFO swapped in during that
  gap happens (read-only, non-blocking) before it is refused. A file removed and replaced
  in that gap can get the freed inode number back (ext4 reuses it at once), so the check
  passes; the hash, checked in the pod and again in the client, is the final guard.
- The `/workspace` root is opened by name and may itself be a link (the mount).
- Story 425's `wan_ledger_fetch.py` resolves the recorded asset path before its
  `O_NOFOLLOW` open, so a link that stays inside `/workspace/output/productions` is
  followed (the target must still have one link and the hash). It is that story's snippet,
  kept as it is.
- The job output's location assumes the Wan API stores outputs under `/workspace/output/`
  as its fake does; story 428 checks it first (checklist step 2).

## Checklist for story 428

Work read-only, with the coordinator watching, inside 428's own authorization.

1. **Authority before anything:** 428 authorizes `kubectl exec` into
   `ai/deploy/wan-video` container `api` for these reads, and names the store root (new,
   empty or this import's own) and its byte budget. Without both, stop. Never write the
   Wan volume, its ledger or ComfyUI; never generate anything here.
2. **Check the code against the cluster's source, not the pod:** in haynes-ops
   `kubernetes/main/apps/ai/wan-video/app/api.py`, `GET /videos/<id>/file` serves
   `/workspace/output/<output>` and a job's ledger is `/workspace/jobs/<id>.json` with
   `id`, `state` and `output`. A difference is a stop: the snippets are reviewed before
   they change.
3. **Dry run:** `--dry-run --store ROOT` must list 156 rows, 101 hashes, `to_read 132,
   not_read 24` on a new store, and read nothing. Keep its output with 428's evidence.
4. **Run once:** with `--authorized-by` 428's URL and a new `--out`. It reads each hash
   at most once, in plan order: the recovery map's hashes (r1 to r4, each from its first
   ledger that answers, r1's first; the keyframes last), then the E0 clips, then the start
   images, then the drive tracks.
5. **On `absent`:** read the row's `attempts`. `source_missing` on every source is a
   finding (record it; for the bed it is expected). `source_link`, `source_hard_link`,
   `source_not_regular`, `source_outside` or `source_changed` mean the volume is not as
   recorded: record it and leave the file alone; never relax a snippet to get past it.
6. **On `mismatch`:** the bytes are not the public hash. Nothing was published or
   imported. Record it; a replacement is a new version made by its own story, never this
   hash repointed.
7. **On a stop:** read `stopped` (its `detail` tells a denial from a traceback; a timeout;
   `adapter.volume_unexpected`: the wrong container, or the volume is not as recorded). An
   exit 1 with every row `absent` and "no read found its file" is the same kind of stop:
   check the context and container before anything else. Do not retry a denial by another
   route. After the cause is fixed, run again with the first
   run's `library.json` and a new `--out`: held hashes are not read again.
8. **Close:** `lacks.story` should be the fire bed alone; anything else is what the
   layered build would still miss. Record the report's counts by role, the store locators,
   `bytes_read` and `elapsed_s` in 428's evidence. The bed's replacement (D54) is 428's.

Never: delete, rename, overwrite or `chmod` anything on the volume or in the store; read
`job_dir` locators from another session's home without its own authorization; import
bytes under an old version that do not match its hash.
