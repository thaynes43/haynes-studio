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
to PostgreSQL or publishing any bytes. The snapshot and delivery media are
published create-only. The catalog registers the asset versions pinned in the
snapshot from their archived documents. Those documents describe source assets
whose bytes live outside this delivery archive.

The Winter Menu's quieter-gavel archive has five files. It contains the
historical run, recovery delivery, private-view ledger, master and proxy.
Its original snapshot, full asset versions and delivery document were lost.
`--recovered` checks the two MP4s against the receipt, run, recovery record and
ledger. It creates a story entry for playback with an empty board list, records
the same run and delivery IDs, and retains the historical snapshot locator and
hash in the run document. `runs.snapshot` stores JSON null and `runs.frozen_library`
stores an empty array for this layout. The registered delivery describes the
verified recovery outputs. See the [recovery evidence](../../titles/the-winter-menu/e1-build/recovery-20261121/README.md).

## Read the result

The command emits one JSON line on success with the status, production, story,
run and delivery IDs, archive counts and bytes, and the master and proxy sizes
and hashes. A repeat with the same archive directory name and receipt checks the
immutable run and delivery and re-hashes the published blobs. It exits 0 with
`already_imported`. If a published blob disappeared or changed, the command
returns an error. A conflicting identity rolls back the database transaction and
exits nonzero. Store writes happen after the database identity checks and before
commit. An interrupted write can leave complete, unreferenced blobs, which a
retry verifies and reuses. Keep them under the store's existing retention rule.
If the store reports staging leftovers on success, the JSON includes their count.

Read the delivery with `GET /v1/runs/{id}/delivery` and the two MP4s with
`GET /v1/media/{sha256}`. Media authorization follows the production that owns
the delivery. The API supports byte ranges. [Private playback](studio-api.md#private-playback)

Imported runs retain their original terminal status and have
`provenance.archive_import` in the run document. Its fields are `source_directory`
(the basename), `source_kind` (`canonical` or `recovered`), `receipt_sha256`
(the SHA-256 of the canonical JSON inventory) and `imported_at` (UTC database
time). Story [412](https://work.haynesnetwork.com/work_packages/412) can use the
presence of this field to refuse go-live approval for either layout. Imports
are ineligible for go-live.

## Database privileges

The current login must own the selected schema, as the installed
`studio_migrator` role does. The command rejects the runtime role before opening
the store even when some of its DML grants overlap. No grant or migration is
issued by this command.

| Permission | Objects used |
| --- | --- |
| Database `CONNECT` and schema `USAGE` | The configured Studio database and schema |
| `SELECT` and `INSERT` | `productions`, `media_types`, `stories`, `boards`, `assets`, `asset_versions`, `asset_sources`, `runs` and `deliveries` |
| `INSERT` | `draft_ids`, `asset_media`, `delivery_media` and `story_asset_refs` |
| `SELECT` and `DELETE` | `story_asset_refs` |
| `UPDATE (document)` | `stories`, for row locking |
| `SELECT` and `UPDATE (next_position)` | `run_lane`, to allocate a pagination position for the terminal run |
| Standard PostgreSQL function execution | Transaction advisory locks, current schema and database clock |

The command needs no access to credential tables and creates no agent grants.
