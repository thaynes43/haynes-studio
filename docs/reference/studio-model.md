# Canonical storyboard model

`haynes_studio.canonical` (story
[404](https://work.haynesnetwork.com/work_packages/404), epic
[372](https://work.haynesnetwork.com/work_packages/372)): productions, stories, boards,
the story timing summary, the method matrix and the legacy import map, built against
[contract v1](../contracts/studio-contracts-v1.md) sections 1 to 6, 10 and 15. It has no
files, services, database or command line in it; the `studio legacy import` command
([studio-cli.md](studio-cli.md)) is the only caller that reads or writes files.

## Schemas

Draft 2020-12 files shipped as package data in `src/haynes_studio/schemas/`. They are the
normative form; the contract's examples are their fixtures.

| Type | File | Validator |
|---|---|---|
| `studio.production/v1` | `studio.production.v1.schema.json` | `validate_production` |
| `studio.story/v1` | `studio.story.v1.schema.json` (embeds boards) | `validate_story` |
| `studio.board/v1` | `studio.board.v1.schema.json` | `validate_board` |
| `studio.story-timing/v1` | `studio.story-timing.v1.schema.json` | `validate_story_timing` |
| `studio.method-capabilities/v1` | `studio.method-capabilities.v1.schema.json` | `validate_method_capabilities` |
| `studio.legacy-import/v1` | `studio.legacy-import.v1.schema.json` | `validate_legacy_import` |
| shared `$defs` | `studio.defs.v1.schema.json` | (IDs, times, principals, cues, notes) |

The files reference each other by `$id` (`https://haynes-studio.invalid/schemas/...`, a
name that is never fetched); `haynes_studio.schemas` registers them together.

## Validators

`validate_<type>(document, context=...)` returns a sorted list of violations
(`rule`, `path` as a JSON Pointer, `message`, `status`); empty means valid.

| Context | Meaning |
|---|---|
| `read` | a document as the server returns it; `derived` allowed |
| `write` | as a client sends it; `derived` is `schema.unknown_field` |
| `queue_run` | the draft is about to be built: adds `voice.absent`, `voice.stale`, `photo.absent`, `asset.generating`, and `method.unavailable` as `unavailable` |

Each rule is checked in one place. The schema carries the field rules through `x-studio`
annotations; the code checks what needs several fields, and only on parts the schema
accepted. Statuses: `invalid`, `unavailable` (`method.unavailable` at `queue_run`) and
`warning` (`method.unavailable` on read and write, `format.length_exceeded`).

| Rule | Checked by |
|---|---|
| `schema.unsupported` | code, first: another type or major stops validation |
| `schema.unknown_field` | schema (`additionalProperties: false`); `derived` on write in code |
| `schema.invalid` | schema default; code for a later line without a gap, a spoken board without lead or tail, a silent board with lead, tail or voice, a reversed trim, a note that is not NFC |
| `id.malformed`, `id.type_mismatch` | schema (`$defs/<prefix>_id`) |
| `time.not_integer_ms`, `time.negative`, `time.tail_too_short`, `time.duration_is_derived` | schema |
| `time.hold_out_of_range` | schema (bounds); code (a silent board without a hold) |
| `time.hold_on_spoken_board`, `time.first_line_gap` | code |
| `method.unknown`, `cue.type_unknown` | schema |
| `method.s2v_needs_line`, `method.s2v_needs_onscreen_speaker`, `method.layered_needs_cast`, `method.unavailable` | code |
| `asset.capability_mismatch` | code, with capability facts |
| `cue.anchor_line_missing`, `cue.slot_not_on_board` | code |
| `cue.out_of_range` | code, on a timed board (`start * 48 < frames * 2000`, as story 378) |
| `note.text_only` | code |
| `voice.speaker_not_in_cast` | code, against the story's cast (a lone board needs `story_cast`) |
| `voice.absent`, `voice.stale`, `photo.absent`, `asset.generating` | code, at `queue_run`, with facts |
| `format.length_exceeded` | code, a warning, with a format length (D45) |
| `ref.unknown`, `ref.duplicate`, `story.board_order` | code; **proposals**, not yet in the rule index |
| `legacy.import_map_mismatch` | the importer; **proposal** |

## Facts

What a document cannot show by itself is passed in as `Facts`
(`haynes_studio.canonical.facts`): each voice version's measured takes (line ID to
`duration_ms`) and whether its signature still matches the board, whether each photo
version matches, which boards have a voice or photo job running, and each asset
version's capabilities. Stories 382 and 405 supply them. With no facts, every voice a
board names is `absent`, so `queue_run` fails closed.

## Derived values

`haynes_studio.canonical.derive`, pure functions on top of `haynes_studio.timebase`:

- A spoken board is `timed` only with a current voice version whose takes cover its
  lines exactly; `content_ms = lead + takes + gaps + tail`,
  `frames = (content_ms * 24 + 999) div 1000`, the remainder in the tail (TIME-3).
- A silent board is timed by its hold (TIME-4).
- `film_start_frame` is the sum of earlier boards' frames, and `None` from the first
  untimed board on (TIME-7).
- `voice_state` is `not_needed`, `generating`, `absent`, `stale` or `current`;
  `photo_state` is `generating`, `absent`, `stale` or `current`.
- A story's `derived` counts timed boards; its `frames` and `duration_ms` (floor) are a
  lower bound while `untimed_boards > 0`.
- `timing_summary(story, facts, format_length)` returns `studio.story-timing/v1`; its
  build blockers are exactly the story's `queue_run` violations.
- `with_derived(story, facts)` returns the story as a read returns it.

The contract's story example and timing summary are reproduced exactly by tests.

## Legacy import

`import_manifest(manifest, speech, manifest_label, operator, now, existing=None)` maps
one legacy manifest (story 378's model) to one story and an import map. IDs come from
`existing` when given, else they are minted (`haynes_studio.canonical.ids.Minter`,
monotonic prefixed ULIDs). The returned map records every ID used, so a second import
returns the same story. A map from another title, draft revision, production or
manifest file is refused (`legacy.import_map_mismatch`).

| Legacy | Canonical (import choices beyond the contract are proposals) |
|---|---|
| shot *n* | board `number` *n*, `origin.source_key` `legacy:<job>:shot:<id>`, title `Shot <id>` (proposal) |
| line *k* | line, `source_key` `legacy:<job>:shot:<id>:line:<k>`; gap 300 written when absent |
| `sfx[i]`, `moves[i]`, `camera` | `sound`, `move` (absent `dur`, `dx`, `dy`, `angle` as 0; 3 steps), `camera` (absent `over` as 400 ms) cues, keys `...:sfx:<i>`, `...:move:<i>`, `...:camera` |
| `note` | one note, key `...:note` |
| `dolls`, `layout`, `foreground` | `cast` in draw order, `layout.preset`, `layout.foreground` (absent as true) |
| method | D38 defaults with no format: `layered` + `s2v` with lines, `layered` + `i2v` without |
| photo | inputs are the board's stills and the set; no current version (E0 keyframes are not read) |
| seeds | `{}` (the server assigns them, section 4) |
| stills, set, sounds, beds, stock voices, takes | asset version IDs under keys `legacy:<job>:still:<path>`, `:set:<path>`, `:sfx:<name>`, `:bed:<name>`, `:voice:<voice>`, `:speech:shot:<id>`, recorded in the map's `story_records`; story 382 creates the versions |
| `master`, line level | `mix` (`line_rms_dbfs` -22, the legacy constant) |

The map's draft board list is `boards_from_r<draft_from_revision>` (the contract's
`boards_from_r4`, generalized; proposal), with optional `source_key`, `cues` and `notes`
per board.
