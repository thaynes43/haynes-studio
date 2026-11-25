# Import a finished production

`studio-api-admin import-production` brings a verified CLI archive into the Studio
database and content-addressed store for private playback. It preserves the original
production, story, run and delivery IDs. [Story 957](https://work.haynesnetwork.com/work_packages/957)

## Run the command

Mount the source archive read-only and the existing `STUDIO_STORE_ROOT` read-write.
Use the database and store shared by the API. Set `STUDIO_DATABASE_SCHEMA` to match
the API, with `studio` as the default. Supply `STUDIO_MIGRATION_DATABASE_URL` from
the existing migration credential projection. The database needs migration
`0003_studio_run_queue` or later. See [Studio API configuration](studio-api.md#environment)
and [database privileges](#database-privileges).

Pass a trusted receipt from the original archive's independent read-back. The
receipt is a JSON object keyed by flat filenames, with `bytes` and lowercase
`sha256` for each file. Keep it outside the archive and use the recorded hashes.
The [story 942 receipt](../../titles/one-more-meeting/run-evidence.json) has the
exact inventories for both archived films. The following example extracts them
from a source checkout mounted separately from the import archive.

```sh
jq -e '.archive.one_more_meeting.files' titles/one-more-meeting/run-evidence.json \
  > "$RECEIPT_DIR/one-more-meeting.json"
jq -e '.archive.winter_menu_quieter_gavel.files' titles/one-more-meeting/run-evidence.json \
  > "$RECEIPT_DIR/the-winter-menu.json"

studio-api-admin import-production "$ARCHIVE_ROOT/one-more-meeting-e1-942" \
  --receipt "$RECEIPT_DIR/one-more-meeting.json" --name "One More Meeting" --media-type short

studio-api-admin import-production "$ARCHIVE_ROOT/the-winter-menu-e1-quieter-gavel-1" \
  --receipt "$RECEIPT_DIR/the-winter-menu.json" --name "The Winter Menu" --media-type short \
  --recovered
```

The canonical layout includes `run.json`, `delivery.json`, `delivery-stage.json`,
`snapshot.json`, `asset-versions.json`, `final.mp4` and `proxy.mp4`. Include every
additional provenance JSON file in the receipt. One More Meeting includes
`transcript-run.json`, `wan-clip.json` and `wan-service-run.json`. The command
refuses missing or unlisted entries, extra media, symlinks in the archive path
or inventory, and non-regular members. It checks every byte against the receipt
and corroborates the run, snapshot, asset pins and delivery before connecting
to PostgreSQL or publishing any bytes.

The Winter Menu's quieter-gavel archive has five files. It contains the
historical run, recovery delivery, private-view ledger, master and proxy.
Its original snapshot, full asset versions and delivery document were lost.
`--recovered` checks the two MP4s against the receipt, run, recovery record and
ledger. The delivery records `recovered_container_metadata_only` with the
container-reported frame count and the bound ledger's ID and hash. The two media
records carry the hashes, sizes, frame rate and codecs checked by the command.
It creates a story entry for playback with an empty board list, records
the same run and delivery IDs, and retains the historical snapshot locator and
hash in the run document. `runs.snapshot` stores JSON null and `runs.frozen_library`
stores an empty array for this layout. The registered delivery describes the
verified recovery outputs. See the [recovery evidence](../../titles/the-winter-menu/e1-build/recovery-20261121/README.md).

## What the command writes

The command can run while the queue is in use. Workers can claim runs and callers
can enqueue while the store copies and verifies files.

1. A short PostgreSQL transaction checks the migration role and identifies a new
   import, a replay from the same archive, or a conflict. A refusal at this step
   leaves the database and store untouched. A production with the same ID must
   already have the matching archive import marker and source identity to qualify
   for replay.
2. The command publishes the master, proxy and canonical snapshot create-only,
   outside any database transaction. A failure can leave complete, unreferenced
   blobs and store staging files. A retry verifies and reuses complete blobs.
3. A short PostgreSQL transaction rechecks identities, inserts the catalog
   records and gives the terminal run a position in the shared queue. A conflict
   or failure rolls back the rows. Complete blobs from step 2 remain subject to
   the store's existing retention rule.

## Read the result

The command emits one JSON line on success with the status, production, story,
run and delivery IDs, archive counts and bytes, and the master and proxy sizes
and hashes. A repeat with the same archive directory name and receipt checks the
immutable run and delivery and re-hashes the published blobs. It exits 0 with
`already_imported` even after a production rename. A missing or changed blob or
a conflicting identity causes a nonzero exit.
If the store reports staging leftovers on success, the JSON includes their count.

Two limits to know before running it:

- **The directory name is part of the import's identity.** The marker records
  the archive directory's basename, so a repeat from a renamed or re-copied
  directory is refused with `identity_conflict` and changes nothing. Run a
  repeat from a directory with the original name.
- **An asset or version ID that already exists is a conflict.** Every pinned
  version is cataloged in the imported production's scope under its original
  IDs, and an existing asset ID, version ID or source key is refused before
  anything is published. A second archive that pins the same library version as
  an earlier import, or a version already in the installed catalog, therefore
  cannot be imported yet. Before running, compare the archive's
  `asset-versions.json` IDs with the catalog and with the other archives.
  Referencing an identical existing version instead of refusing is recorded as
  a follow-up on
  [story 957](https://work.haynesnetwork.com/work_packages/957).

Read the delivery with `GET /v1/runs/{id}/delivery` and the two MP4s with
`GET /v1/media/{sha256}`. Media authorization follows the production that owns
the delivery. The API supports byte ranges. [Private playback](studio-api.md#private-playback)

The imported story is readable and its finished delivery plays in the studio.
The archive records the pinned input versions as `recorded_without_media`. Pins
from the shared library are cataloged in the imported production's scope.
A replacement photo can be uploaded while the old photo is still selected.
The upload is saved unselected until a person or an agent with a current
revision acknowledgment selects it. To rebuild, import the inputs through
their own asset paths and pin the resulting versions in the draft. A recovered
archive also requires reconstructing the lost boards.

Imported runs retain their original terminal status and have
`legacy.archive_import` in the run document. Its fields are `source_directory`
(the basename), `source_kind` (`canonical` or `recovered`), `receipt_sha256`
(the SHA-256 of the canonical JSON inventory) and `imported_at` (UTC database
time). The existing [go-live check](go-live.md) refuses either layout through
the populated `legacy` block and returns `approval.legacy_run`.

## Database privileges

The current login must own the selected schema, as the installed
`studio_migrator` role does. The command rejects the runtime role before opening
the store even when some of its DML grants overlap. No grant or migration is
issued by this command.

| Permission | Objects used |
| --- | --- |
| Database `CONNECT` and schema `USAGE` | The configured Studio database and schema |
| `SELECT` and `INSERT` | `productions`, `stories`, `boards`, `draft_ids`, `assets`, `asset_versions`, `asset_sources`, `runs` and `deliveries` |
| `INSERT` | `media_types`, `delivery_media` and `story_asset_refs` |
| `SELECT` and `DELETE` | `story_asset_refs` |
| `SELECT` and `UPDATE (next_position)` | `run_lane`, to allocate a pagination position for the terminal run |
| Standard PostgreSQL function execution | Transaction advisory locks, current schema and database clock |

The command needs no access to credential tables and creates no agent grants.
