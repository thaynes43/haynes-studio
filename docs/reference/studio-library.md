# Asset library records

`haynes_studio.library` (story
[382](https://work.haynesnetwork.com/work_packages/382), epic
[372](https://work.haynesnetwork.com/work_packages/372)): assets, immutable asset
versions, their validators, the library operations and the resolver, built against
[contract v1](../contracts/studio-contracts-v1.md) sections 2, 7, 8, 9 and 10. It reads no
media and has no files, store, database, service or command line in it: the store
adapter is story [379](https://work.haynesnetwork.com/work_packages/379), the API story
[409](https://work.haynesnetwork.com/work_packages/409). It follows the conventions of
the [canonical model](studio-model.md) (contexts, normalized integral floats, sorted
violations, a malformed document never raises).

## Schemas

| Type | File | Validator |
|---|---|---|
| `studio.asset/v1` | `studio.asset.v1.schema.json` (holds the shared asset `$defs`) | `validate_asset` |
| `studio.asset-version/v1` | `studio.asset-version.v1.schema.json` | `validate_asset_version` |

Both are draft 2020-12 package data next to story 404's files and register with them.
Contexts `read`, `write` and `queue_run` check the same rules; neither type has a
`derived` block.

## Records

- **Asset** (`ast_`): `kind`, `name`, `scope` (`production_id`, or null for the global
  library; `story_id` and `board_id` for the board-scoped `photo` and `board_voice`),
  `labels`, `attributes`, `revision`. Labels are the only mutable field (P-21); each
  change raises `revision`.
- **Asset version** (`asv_`): `asset_id`, `number`, `kind`, `state`, `capabilities`,
  `content` (`sha256`, `bytes`, `media_type`, `locator`, optional `width` and
  `height`; null for `voice` and `board_voice`), `provenance`, `licence`, `legacy`, and
  for a board voice `voice` (takes, lead, gaps). A read returns the version joined with
  its asset's `kind`, `name`, `scope`, `labels` and `attributes`, as in the contract's
  examples; those joined fields are not version content.
- **Never change:** `id`, `asset_id`, `number`, `kind`, `content`, `provenance`,
  `capabilities`, `legacy`, `voice` (D15). `state` moves only from `candidate` to
  `promoted`. A licence changes only by an appended record (not built here).

## What a version is

`model.pin(version, asset)` is the one definition, and what a snapshot pins
(section 8):

| Kind | Pin |
|---|---|
| any kind with bytes | `content.sha256` |
| `voice` | `definition_signature`: `sha256:` of canonical JSON `{engine, stock, voice_id}`, `engine` being the TTS model |
| `board_voice` | `sha256:` of canonical JSON `{input_signature, takes: [take sha256]}`; a snapshot entry lists `input_signature` and `take_sha256` |

A take's `signature` is `sha256:` of `{engine, voice_id, text (NFC), speed}` and a board
voice's `input_signature` of `{takes: [take signature], lead_ms, gaps_ms}` (VOICE-3).
These formulas are the ones the contract's `run-snapshot.json` and board voice example
were computed with; the tests check the library reproduces them.

## Operations

Pure functions; each returns a new `Library`. Nothing is deleted (D17).

| Function | Rule |
|---|---|
| `import_version` | Keyed by `provenance.source_key`, which names one asset. The same pin returns the existing version (`created: false`); changed bytes make the next `number`; bytes seen before return their old version. The same pin with other immutable fields, or under another given ID, is `idempotency.mismatch` (a measurement the existing version does not record, `bytes: null` or no `width` and `height`, matches any value); a given ID already in use is `ref.duplicate`; a library holding only some of the asset's versions is refused (`ref.unknown`), so no number is reused. Every new version is validated in `write`. |
| `promote` | `candidate` to `promoted`, same ID and pin; a `promoted` version is returned unchanged. A board photo gets one library version, `origin: derived`, source key `promote:<board version ID>` (proposal), pointing at it. A board voice stays on its board (`asset.not_promotable`, proposal). |
| `set_labels` | Replaces an asset's labels, optionally checking `revision` (`conflict.revision`, status `conflict`). No version changes. |
| `Library.version`, `get`, `versions_of`, `by_source_key` | Pinning is by version ID. |
| `Library.latest` | Pickers only; candidates hidden unless asked. |
| `Library.search` | Section 9 filters: kind, labels (all of them), production (its own versions and the global library's), board (exactly the versions it references). |
| `Library.has_capability`, `capabilities`, `takes` | What stories 405, 426 and 427 ask, without knowing the storage. |
| `Library.facts(story=None, current_engine=None)` | Story 404's `Facts`: every version's capabilities, every board voice's measured takes, every photo. Given the story, a board's voice is stale unless its takes are the board's lines (ID, speaker, NFC text) from the voices the story casts, with the board's lead and gaps; without it every voice counts as current. Given `current_engine` (the engine a take signature names now: the TTS model's digest once one is recorded, else its name), a board voice any of whose takes is signed with another engine is stale, with or without the story (VOICE-9, story 849; the parameter, and applying it without a story, are proposals); without it the engine is not compared. Photo currency is story 407's. |

## Validation

| Rule | Checked by |
|---|---|
| `schema.unsupported`, `schema.unknown_field`, `id.malformed`, `id.type_mismatch` | schema (as story 404) |
| `prov.external_incomplete` | schema: an `uploaded` version needs the full D42 `external` marker (`externally_generated: true`, agent key, session and harness, `paid_api: false`, `server_computed_sha256: true`), a `model` and a `prompt` or `prompt_ref` |
| `prov.licence_missing` | schema: a `licence` object with all seven fields |
| `store.locator_invalid` | schema: the section 8 grammar `library/sha256/<h[0:2]>/<h>.<ext>` or `productions/<prd_id>/sha256/<h[0:2]>/<h>.<ext>`, `ext` one of `mp4 wav png jpg webp json`, no control characters; code: the file name is the content's `sha256`, the folder its first two digits, the extension the media type's, the production folder the version's own (a global version uses `library/`; proposal) |
| `voice.not_stock` | schema: a voice has `attributes.stock: true` and no bytes; code: its `voice_id` is a recorded stock voice of its model, the generator agrees, no `source_sample_sha256`, every board voice take uses a stock voice, and (proposal) its origin is `declared` |
| `asset.capability_mismatch` | code: capabilities fit the kind and the media type (tables below), and an opaque photo or plate is never also a layer (review M6) |
| `ref.duplicate` | code: labels, a board voice's line IDs |
| `schema.invalid` (code, proposal) | `legacy.source_key` differs from `provenance.source_key` |
| `schema.invalid` | schema: each kind's and state's shape (a board-scoped kind has a board scope and state `board`; a voice and a board voice have no bytes; other kinds do; `character_card` is reserved for E2; a library `photo` is `derived`), a licence's `commercial_use` is `allowed`, `conditional`, `noncommercial` or `unknown` (section 7, P-23), a checked one (any but `unknown`) names `name`, `checked_at` and `checked_by`, and a `conditional` one keeps its conditions in `note` (proposal, story 849); code: a board voice's offsets follow TIME-2, `speech_end_ms` is the last take's end, a `samples` duration follows TIME-1 |

Stock voices (VOICE-1, P-22) are the ones this repository records:
`Kokoro-82M v1.0` `af_bella`, `af_heart`, `af_nicole`, `bf_emma` (the r4 ledger) and
`am_puck` (OP341). Any other voice is refused until it is recorded
(`model.STOCK_VOICES`); the server's full list comes from a Wyoming `Describe`.

Capabilities per kind (proposal; `model.KIND_CAPABILITIES`): `cast`, `costume`,
`prop`: `rgba_cutout`, `keyed_layer`, `mask`, `opaque_photo`; `set`: `opaque_plate`,
`rgba_cutout`, `keyed_layer`, `mask`; `motion`: `motion_clip`, `set_loop`,
`keyed_layer`, `mask`; `sound`: `sound_effect`, `sound_bed`; `voice`: `tts_voice`;
`board_voice`: `board_voice`; `photo`: `opaque_photo`. Media types per capability
(`model.CAPABILITY_MEDIA`): a JPEG is never an `rgba_cutout`, clips are MP4, sounds WAV.

## Resolver

`resolve(document, library, exists)` takes a `studio.story/v1` (boards embedded) or
`studio.board/v1` document and resolves every asset version it names, by ID, to its
record, pin, `sha256` and locator. `exists(locator, sha256)` is injected (the store, or
a synthetic one in tests) and asked once per pair; definition-only versions ask
nothing. Problems: `ref.unknown`, `asset.kind_mismatch` (proposal: a cast voice is a
`voice`, a board voice a `board_voice`, sounds and beds `sound`, a board cast entry a
`cast`, the set a `set`, a board photo a `photo`), `asset.capability_mismatch` (a
layered board's cast entry without `rgba_cutout` or `keyed_layer`) and
`asset.scope_mismatch` (proposal: a board's voice or photo from another board, or a
version of another production than the story's) and `asset.bytes_missing` (proposal).
A story without embedded boards is `schema.invalid` at `/boards`. Each `Resolved` gives
its run snapshot entry (`snapshot_entry()`: `sha256`, or `definition_signature`, or
`input_signature` and `take_sha256`).

## The Winter Menu library

`winter_menu.build_winter_menu_library(story, import_map, sources, licences=, by=, now=)` builds a
version for every `asset_version` in the import map's `story_records`, under the same
source keys and version IDs, from `load_public_sources(title_dir, manifest, evidence)`:
the manifest, `speech.json`, `timeline.json`, `production.json` and `prompts.json`. No
media is read. Stills are `cast` versions with `rgba_cutout` (chroma-keyed cutouts),
the set an `opaque_plate`, sounds `sound_effect` or `sound_bed`, voices global stock
`voice` definitions, and each spoken board a `board_voice` with its takes. Hashes and
byte counts come from the ledger and the timeline, cross-checked with `prompts.json`
(`legacy.evidence_mismatch`, proposal, if they disagree). Locators are in the
production's folder. Each licence comes from the
[model licence register](model-licences.md); a model it does not name stays `unknown`
with the reason. The register writes a conditional term `unknown` in its licence object
and `conditional` in the entry's `outputs_commercial_use`; the lookup gives
`conditional` with the register's note (P-23, story 849), so the Winter Menu's sounds
(Stable Audio) are `conditional`. A licence is not part of a pin: no version ID or pin
changes with it. All four revisions resolve completely; r4 is timed at 1087 frames with
the library's facts.

Gaps (`WinterMenuLibrary.gaps`): the bed's byte count (its hash is in `timeline.json`
only), the sound model (named only inside the service text), the Kokoro model digest,
and take sample counts and rates (`speech.json` records `duration_s`); every licence
is recorded, so none is a gap. Legacy takes are signed
with speed 1.0: `poc/studio.py` sent no speed, so the server default applied, as the
contract's example records.

Proposals in the builder: names and labels, a stock voice's `legacy.path` (the
manifest), the media type from the file extension, and the capabilities (chroma-keyed
cutouts are `rgba_cutout`, the set an `opaque_plate`). Stock voices are keyed per
legacy job, as story 404's import names them, so importing several revisions into one
library gives one voice asset per job.

## The private import (stories 425 and 428)

When the originals are recovered, import the same records with the real bytes:
publish each file through the store (story 379), which hashes and measures it, then
call `import_version` with the store's `sha256`, `bytes` and locator under the same
source key. Bytes equal to the public hash return the existing version (`created:
false`), the bed included: a measurement the public files lack (the bed's `bytes`,
every still's `width` and `height`) matches the store's and stays unrecorded on
version 1 (versions never change). Different bytes become version 2 and leave version
1 pinned. Run the resolver with the real store's `exists` before any build.
