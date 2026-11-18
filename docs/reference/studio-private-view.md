# Private viewing of a studio delivery

**Source and local tests:** story
https://work.haynesnetwork.com/work_packages/863. **Expected, not installed:** the
coordinator's first authorized use after merge. **Accepted:** Tom's verdict is
separate. The worker made no cluster call or live run.

From a session with the established Wan API exec route:

```sh
uv run studio private-view RUN_ID --store /path/to/store --production PRD_ID \
  --job a-new-production-name --out /path/to/new-result-folder \
  --title 'A private viewing' --operator-session SESSION \
  --operator-harness Codex --operator-model gpt-6.1-sol --check-only
```

Remove `--check-only` for an authorized attempt. The link plays the **phone proxy**;
add `--master` to play the master. The result prints the selection, both file hashes,
the proposed or linked ledger, and the private URL. No account, public platform,
schedule or inference is involved. This command does not imply go-live approval.

**Attribution (the contract's P-50), story
[864](https://work.haynesnetwork.com/work_packages/864):** require the same complete
[operator flag set](studio-cli.md#operator-flags)
as builds (the human pair may replace the agent triple above). Both the viewer's ledger
and the local `production.json`'s embedded ledger record the CLI actor under
`provenance.created_by`. This identifies who placed the private viewing independently
of who queued the build. It grants no access and is not an approval; the original run
and delivery are unchanged. The function `put_private_view` requires `by: Principal`.

`JOB` is 3–64 ASCII lowercase letters, digits or hyphens, beginning with a letter or
digit. `OUT` must be a new folder outside the store, with an existing parent. An
existing folder, file or ledger is refused, even with identical bytes. There is no
resume: use a new job and output folder for a new attempt.

## Order and boundaries

1. `read_delivery` verifies the completed delivery and re-hashes its master and
   proxy. `RunRecords.latest()` reads the named `run` output of contiguous numbered
   stages. Its schema, `succeeded` state, run ID, delivery ID, output hashes, frames,
   fps and studio provenance must agree with the delivery. Delivery is fixed at
   **24 fps** by [the time contract](../contracts/studio-contracts-v1.md#3-the-time-contract),
   so the run must report 24; the delivery is not a source of a variable rate. The
   actual named blob is read and hashed again. A later-looking file or another JSON
   output is never used.
2. Build the ledger and validate it with the legacy route's `check_ledger` (explicit
   exceptions, including under Python `-O`) and `record_from_document`. Remote
   read-only preflight checks more than ten times the files' total size free, unused
   job and ledger names, and existing, nonsymlink directory parents. **Check-only
   stops here**, prints the full plan, and creates no local or remote file.
3. Create `OUT`. Recheck remote space and parent identities, then reserve
   `/workspace/output/productions/JOB` with exclusive `mkdir`. Every remote step
   traverses directories with `O_DIRECTORY | O_NOFOLLOW`, checks device/inode
   identities, and uses held directory descriptors. After opening the newly made
   folder, require it to be empty and owned by the effective uid before recording
   its identity. Copies never recreate a moved folder or adopt its replacement.
4. Copy exactly `final.mp4`, `proxy.mp4`, `run.json`, and `delivery.json`. Each streams
   to an anonymous `O_TMPFILE` inode in the reserved folder with mode explicitly set
   to `0o644`, is fsynced and hashed, then gets an exclusive hard link from its
   descriptor to its final name. No caller-controlled symlink is followed. Each
   final asset has one link, compatible with the legacy asset reader. A failed
   unfinished copy has no final name.
5. Reopen every final asset in place with `O_NOFOLLOW`, require a regular file and
   its expected bytes/hash. Validate the exact ledger bytes again with both local
   validators. Stage them create-only in `/workspace/jobs/.private-view-ID/`, keeping
   the ledger's device/inode, hash and recovery folder identity. The newly made
   recovery folder is `0o700`; after opening it, require it to be empty and owned by
   the effective uid before writing. Immediately before the served link, the remote
   route checks the staged ledger, reopens and hashes all four assets again, and
   requires `output` to be `productions/JOB/final.mp4` or
   `productions/JOB/proxy.mp4` with that file's verified bytes/hash. Every ledger
   asset path must name one of this job's four files under
   `/workspace/output/productions/JOB/`, with that file's verified bytes/hash.
   Recheck the production namespace. It hard-links the verified ledger descriptor,
   explicitly set to `0o644`, create-only to `/workspace/jobs/ID.json`, then checks
   the namespace again. A lost response still has the prepared identity for undo.
6. `LedgerReader.get` must return the exact ledger. Inside the API container, hash
   the bytes of `GET /videos/ID/file`; require HTTP 200, `video/mp4` and the selected
   file's bytes/hash. `LedgerReader.list` must include this ID with no unreadable
   entries. Check the namespace and all four files once more.
7. Write `OUT/production.json` through a complete temporary file and exclusive link.
   It records the ledger, four file sizes/hashes, playback choice, run/delivery and
   production identities, read-back results, URL and remote recovery identity.

The route is fixed Python source with separate argv data and stdin bytes, through
`kubectl exec -i -n ai deploy/wan-video -c api -- python3 -c ...`. Nothing goes
through a shell. The package imports nothing from `poc/` and changes no Wan service.

## Failures and retained artifacts

After a link attempt, any failure triggers withdrawal. Reopen the served ledger
without following symlinks and require the **prepared device/inode**, then recheck
its identity immediately before a same-volume `renameat2(RENAME_NOREPLACE)` into
`/workspace/jobs/.private-view-ID/withdrawn`. Stat the moved name without following
links and compare it with the receipt. If another writer swapped the served name
after the last check, restore the moved replacement using `RENAME_NOREPLACE` and
raise, reporting the restoration. If restoration fails, report the retained
`withdrawn` path and the restoration error; never overwrite a newly occupied served
name. An absent name is reported, and a replacement detected before the rename or
an existing withdrawal target is left untouched. Failure to withdraw is explicit:
`served_name_may_remain: true`.
Corruption of this attempt's own ledger does not prevent withdrawal of its inode.
There is no deletion, overwrite, retry or alternate access route.

Failure output and, where writable, `OUT/production.json` say what remains: the
remote production folder (possibly partially copied), unserved ledger staging and
withdrawal paths, receipt, error and local record path. Before preparation, only
the production folder and any completed copies may exist. The local record's
hidden temporary hard link is retained. Successful attempts retain the staged
ledger as recovery evidence too. Unnamed unfinished temporary inodes close without
a served name; existing volume files are never cleaned up.

Proposed new error codes: `private_view.invalid`, `private_view.remote_failed`,
`private_view.readback_failed`, `private_view.withdraw_failed`. Store and delivery
validation also retain their existing codes. CLI failures return 1; local OS/usage
errors use the CLI's existing status 2.

The remote runtime requires Linux, procfs, libc `linkat`/`renameat2`, and a filesystem
supporting `O_TMPFILE`, hard links and `RENAME_NOREPLACE`. This is **locally tested,
remote support unverified**. Unsupported operations fail without a fallback. The
[Linux open](https://man7.org/linux/man-pages/man2/open.2.html),
[link](https://man7.org/linux/man-pages/man2/linkat.2.html), and
[rename](https://man7.org/linux/man-pages/man2/rename.2.html) manuals describe these
primitives. This CLI keeps the four local input blobs in memory during the attempt;
there is no media decode, encode or GPU work.

Ownership checks cover the attempt through its final read-back. They do not lock
out another volume writer after exit or change the API to enforce hashes on future
plays. A process killed after linking cannot run withdrawal or finish its local
record; its staged ledger remains for an authorized operator. Recovery is a separate
operation; this command never resumes or purges an earlier attempt.

## Local evidence

`uv run pytest tests/private_view` executes the **same fixed remote source** against
a temporary root through a fake exec runner. Only HTTP and the existing read-only
ledger service boundaries are doubled; no `kubectl` process or socket is opened.
The new race tests also call the remote step in-process: a `rename_only` wrapper
swaps the served name after the final stat, and an `os.mkdir` wrapper substitutes a
nonempty directory before `reserve` or `prepare` can open it. They verify restoration
of the replacement inode (including a symlink) and refusal without writing into the
substituted folder. Additional cases refuse foreign uid ownership and mismatched
ledger paths, sizes and hashes before linking, and check modes under a restrictive
umask.

The cases cover both playback choices, named run selection, mismatched and unfinished
runs, changed local media, all three PR 70 folder substitutions, parent/file symlinks,
changed final bytes, create-only conflicts, read-back errors, unreadable listing,
lost link replies, identity-bound withdrawal, no-overwrite quarantine, bad names,
argument/code separation and read-only check-only output. The coordinator supplies
the separate adversarial review on the final PR head before merge.
