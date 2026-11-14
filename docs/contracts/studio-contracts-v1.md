# Studio contracts v1

Story [423](https://work.haynesnetwork.com/work_packages/423) (E1.9, review R01), epic
[372](https://work.haynesnetwork.com/work_packages/372). Base: `main` at `aa73c4e`.
**Status: ratified by the E1 coordinator on 2026-11-13, at the review of PR 37, as the
contract E1 is built against.** That is the coordinator's technical agreement, not Tom's
acceptance: every `P-nn` stays a proposal Tom may overrule. Tom answered `Q-01` to `Q-04`
on 2026-11-13 (D49 to D52); [section 16](#16-held-owner-questions) records each answer.
Stories [378](https://work.haynesnetwork.com/work_packages/378),
[404](https://work.haynesnetwork.com/work_packages/404),
[424](https://work.haynesnetwork.com/work_packages/424) and later E1 to E9 stories build
against the commit that ratifies it. Examples are in [`examples/`](examples/); the
[README](README.md) explains their format.

**Amended 2026-11-13 by the contract owner (the E1 coordinator)** with Tom's rulings D49
to D57 and with what the merged E1 stories built: 378, 379, 380, 381, 382, 404, 405, 425
and [809](https://work.haynesnetwork.com/work_packages/809). Each story's reference page
under [`docs/reference/`](../reference/) has the detail; where a story chose beyond this
text and the coordinator accepted it at review, the choice is a proposal here
([section 17](#17-proposals)). Where this text and the merged code still differ, the
difference is named in place.

**Amended again on 2026-11-13 by the contract owner** with what the next stories built or
found: [427](https://work.haynesnetwork.com/work_packages/427) (whole-frame adapter, PR
54), [457](https://work.haynesnetwork.com/work_packages/457) (motion clip records, PR 55),
the lock of scipy and OpenCV (PR 56),
[841](https://work.haynesnetwork.com/work_packages/841) (film sound and master, PR 57),
[840](https://work.haynesnetwork.com/work_packages/840) (voice audition, PR 59),
[426](https://work.haynesnetwork.com/work_packages/426) (layered adapter, PR 60) and
[849](https://work.haynesnetwork.com/work_packages/849) (contract catch-up in code, PR 61).
Their choices beyond this text are P-36 to P-40. The contract owner decided five of their
held questions (Q-427-1, Q-427-2, Q-457-1, Q-426-1, Q-426-2) as proposals Tom may
overrule. Tom decided nothing new in this batch; Q-840-01, Q-840-02 and Q-841-01 are open
for him ([section 16](#16-held-owner-questions)).

**Amended a third time on 2026-11-14 by the contract owner** with five more merged
stories: [842](https://work.haynesnetwork.com/work_packages/842) (Wan clip clients, PR
58), [406](https://work.haynesnetwork.com/work_packages/406) (build from boards and the
command line, PR 64), [857](https://work.haynesnetwork.com/work_packages/857) (the
proxy's audio length and tracks for legacy voices, PR 67),
[846](https://work.haynesnetwork.com/work_packages/846) (private input import, PR 65)
and [851](https://work.haynesnetwork.com/work_packages/851) (live clip sources, PR 66).
Their choices beyond this text are P-41 to P-45. The contract owner decided Q-406-1,
Q-406-2 and Q-846-01 to Q-846-03 and the other-family review findings on these PRs, as
proposals Tom may overrule. Tom decided nothing new; the three questions above stay open
for him.

**Amended a fourth time on 2026-11-14 by the contract owner** with the first live build,
story [428](https://work.haynesnetwork.com/work_packages/428) (records, PR 69; its six
one-off drivers are held in PR 70), and its six small fixes, story
[860](https://work.haynesnetwork.com/work_packages/860) (PR 71). The film was delivered
privately; **Tom's verdict is pending**. The choices beyond this text are P-46 to P-49.
The contract owner decided Q-428-2 and Q-428-3, O-860-1, the reading of the command
line's operator (O-428-1) and a practice on GPU heat, each a proposal Tom may overrule.
Tom decided nothing in this batch. The heat practice rests on a relayed message that
could not be verified, so confirming it is open for him (Q-428-6), with Q-428-4, Q-428-5
and the differences he weighs with his verdict ([section 16](#16-held-owner-questions)).

Every rule carries its source:

| Label | Meaning |
|---|---|
| **D*n*** | Tom's decision in [proposal 0003](../proposals/0003-studio-plan.md). Later rulings beat older prose. |
| **Evidence** | An E0 measurement, with its file under [`titles/the-winter-menu/video-e0/`](../../titles/the-winter-menu/video-e0/). |
| **Legacy** | What the PoC code or a Winter Menu manifest does today (file named). |
| **Proposal P-*nn*** | This contract's choice, with the alternative it rejects. Not Tom's decision. The coordinator ratified each at review as the working choice; Tom may overrule any. |
| **Q-*nn*** | An owner choice only Tom can make. The question, its options, Tom's answer and the D-number that records it are in [section 16](#16-held-owner-questions). |
| **Coordinator's reading** | How the contract owner applies a ruling of Tom's where his words leave the detail open. Not Tom's words; he may correct it. |

E0's three deferrals (NFS write contention, AI upscaler quality, Foley listening verdict)
are unmeasured. Nothing below depends on a value for them.

## 1. Vocabulary and the legacy mapping

### Canonical terms

| Term | Meaning | Source |
|---|---|---|
| Production | A themed collection, for example Yellowbirds. Not one video. | D28, review H1 |
| Media type | A kind a production has enabled: `short` (9:16) or `video` (16:9). Identified by `(production_id, kind)`; it has no ID of its own. | D28 |
| Story | One video: an ordered list of boards in one media type. Not a tracker work package. | D27, D28 |
| Board | One intended clip, with a stable ID, lines, timing, voice, photo, method, cast, cues and notes. | D27, D38 |
| Line | One spoken line on a board: stable ID, speaker slot, text. | D27 |
| Cue | A typed, executable instruction on a board or story (sound, move, camera, bed). | [section 6](#6-direction-and-executable-cues) |
| Note | Free-text direction. Never executed. | D35, D38 |
| Asset / asset version | A library item / one immutable version of it, pinned by ID. | D15, D16 |
| Run | An immutable snapshot of a story queued for building, and its outputs. | D30 |
| Delivery | A run's verified master and phone proxy in the store. | review H5 |
| Go-live approval | Tom's sign-off on one finished run's exact master. The only formal approval. | D29 |
| Publication (drop) | A recorded manual release after go-live. E9 work; reserved here. | D43 |
| Candidate | A run presented for a target account. E9 work; no entity in v1. | 0003 product model |
| `revision` | An entity's optimistic-concurrency counter. Not a script revision. | P-02 |

### Legacy terms and where they go

The four Winter Menu manifests and their evidence are read-only inputs. A legacy adapter
maps them; nothing rewrites a legacy file, writes a legacy ledger or reuses a legacy ID as
a canonical ID. Worked map: [`legacy-import-map.json`](examples/valid/legacy-import-map.json).

| Legacy name (file) | Legacy meaning | Canonical target |
|---|---|---|
| `titles/<slug>/`, manifest `title` | One video's working folder | Story `title`. The production (Yellowbirds) and media kind (`short`, from 1080x1920) are import parameters; no manifest names them. |
| manifest `story` ([manifest-r4.json](../../titles/the-winter-menu/manifest-r4.json)) | A tracker URL (work package [371](https://work.haynesnetwork.com/work_packages/371)) | `origin.tracker`. **Not** a domain story. |
| manifest `revision` (absent in r1 = 1; 2, 3, 4) | A whole-script revision | One imported run per revision, `status: imported`, `legacy.revision`. |
| manifest `job` (`the-winter-menu-r4`) | Job folder name, also `productions/<job>/` on the Wan PVC | `legacy.job` on the imported run. Never an ID. |
| manifest `job_dir` (`~/studio-jobs/...`) | Private, non-portable input path | Not imported. Story [425](https://work.haynesnetwork.com/work_packages/425) built the private-input [recovery map](../reference/legacy-recovery-map.md), which lists every input with its expected hash and marks every private locator unverified. |
| ledger `id`, `kind: edited_production` ([deliver.py](../../poc/deliver.py), `evidence*/production.json`) | One delivered video, 32 hex chars | Delivery `legacy.ledger_id`; the delivery gets a new `dlv_` ID. |
| "production" in `productions/<job>/` | One delivered video | Delivery, not a production. |
| `edit/`, `edit-2/` ... | One attempt inside a job | Not modelled; the delivered attempt is the ledger's `output` path. |
| `shots[]`, `id` 1..n | Positional clips of one revision | Boards with new stable IDs. Shot IDs are not stable across revisions (r1 shot 4 is D's line, r4 shot 4 is A's), so no board identity is inferred between revisions. The story draft takes r4's boards; r1 to r3 boards live only in their imported runs' snapshots. |
| `line` / `lines[]`, `doll`, `text` | Ordered spoken lines | `lines[]` with stable IDs; `doll` becomes `speaker`. |
| first line `start` | Seconds from shot start to the first line | `timing.lead_ms` |
| later line `gap` (default 0.3 in `edit.resolve_lines`) | Seconds after the previous line ends | `gap_before_ms`, written explicitly on import (300 when absent). |
| `tail` | Seconds after the last line | `timing.tail_ms` |
| `duration` on a shot with no lines | Silent shot length | `timing.hold_ms` |
| `duration` on a shot with lines | Silently wins over the lines in `edit.timeline` | Refused: `legacy.duration_with_lines`. No Winter Menu manifest has it. |
| `dolls {slot: cutouts/x.png}` | Which still each slot uses, in draw order | `cast[]` of `{slot, asset_version_id}` in the same order. |
| `layout`, manifest `layouts` | Placement presets in delivery pixels | `layout.preset`; presets copied to story `layouts`. |
| `foreground: false` | Hide the foreground log | `layout.foreground` |
| shot `sfx[] {cue, at \| after_line + offset}` | Placed sound effects | `sound` cues; the line index becomes a line ID. |
| manifest `sfx.<name> {file, trim, gain_db, source, rejected[]}`, `beds.<name> {file, gain_db, source}` | A generated sound, its trim and its level. `gain_db` is a **target RMS level** in dBFS, not a gain: `edit.audio` scales the clip to it after trimming | `sound` asset version (file hash from `timeline.json`, provenance from `source`: service, job, seed, seconds, steps, prompt). `trim` and the level move onto each cue as `trim_ms` and `level_rms_dbfs`. `rejected[]` entries are not imported in v1: the import map only describes them (`hidden_candidates`), the importer makes no record of them, and a `sound` version needs bytes (story 382), so how a byte-less candidate is kept is open. |
| `moves[]` | Scripted whole-doll moves | `move` cues |
| `camera {zoom, over, center}` | Push-in, ease-out over `over` seconds | `camera` cue |
| `beds` | Looped ambience under the film | Story `beds[]`, film clock |
| `note` | Free text | `notes[]` |
| `cast {slot: {name, voice}}` | Character name and Kokoro stock voice | Story `cast[]`; voice becomes a global `voice` asset version, keyed `legacy:<job>:voice:<voice_id>` (story 404), so each imported title adds its own voice assets. The legacy voices are not the target: new voices are auditioned (D53). |
| `set` (`image`, `foreground_edge`, `foreground_feather`, `fire`, `note`) | Set still, log edge, procedural fire | Story `set`; `fire` kept as `legacy_fire` (the rigid renderer only; Wan animates fire); `note` kept as text. |
| `motion` (idle, hop, tilt, shuffle) | Talk bounce and wobble style | Story `motion_style` |
| `frame {width, height, fps}` | Delivery size | The media kind's profile; 1080x1920 at 24 fps is `short`. |
| `master`, `asr_tolerances`, `asr_tolerances_note` | Loudness target, transcript tolerances | Story `mix`, story `checks` |
| `timeline.json` (`total_s`, `shots[] {shot, start_s, end_s, frames}`, `audio[] {kind line, sfx or bed, start_s, end_s, sha256, ...}`, `premaster_headroom_db`, `master_gain_db`) | Recorded timing (`start_s` 4 decimals, audio 3) | The imported run's timing record, read-only; the fixture story 378 compares against (TIME-12). |
| `shots.json`, `validation.json` (including `human_review`), `dialogue-transcript.json` | Render and check records | Imported run stage and check records, verbatim and read-only. `human_review` is a historical gate note, not a go-live approval. |
| ledger `preset`, `provenance {..., human_approval}`, `assets[]`, `created_at` | How the delivery was made, and every delivered file | Delivery `legacy` block: `preset` and `provenance` verbatim, `assets_ref` to the evidence file; `created_at` as ISO time ([example](examples/valid/delivery-legacy-r4.json)). |
| `speech.json` `service` | The TTS service | `board_voice` provenance `engine` |
| `provenance` (free text), `revision_note` | Notes | Imported run notes; `revision_note` becomes feedback in E9.3. |
| `speech.json` lines `{shot, k, file, duration_s, sha256}` (`k` is absent in r1 and r2, where every shot has one line; read as 0) | One WAV per line | Takes inside a `board_voice` asset version, with offsets ([example](examples/valid/asset-version-board-voice.json)). The legacy track was never assembled: `track: null`, so the version is stale for a build and `studio voice` assembles a new one (section 10, story 857). |
| `prompts.json`, `cutouts/` | Image provenance, keyed RGBA stills | `cast` asset versions with provenance ([example](examples/valid/asset-version-cast.json)) |
| E0 `keyframes.json` | Composed first frames per shot | Imported `photo` versions on the r4 boards |
| E0 Wan `job_id`, clip records | Engine jobs and clips | `engine_job_id` in provenance; clips become run artifacts or `motion` assets (story [457](https://work.haynesnetwork.com/work_packages/457)). |
| Rigid cutout puppetry (`poc/edit.py`) | The renderer of r1 to r4 | `method: {legacy: rigid_cutout}` on imported runs only. Not a canonical method (D6). |

Re-import is idempotent: every imported record carries a `source_key` such as
`legacy:the-winter-menu-r4:shot:8`, unique per record type, and a second import returns
the existing IDs (P-01).

The legacy adapter has four rule codes of its own (story
[378](https://work.haynesnetwork.com/work_packages/378)): `legacy.invalid` (a legacy
manifest that is not strict JSON, or fails its schema in a way no specific rule names),
`legacy.reference` (a repeated shot id, a sound that is not in the `sfx` table, an
`after_line` beyond the shot's lines), `legacy.speech_mismatch` (a `speech.json` that
does not pair with the manifest's lines) and `legacy.timeline_mismatch` (a computed
timeline that differs from a recorded `timeline.json` by more than TIME-12 allows). The
import (story [404](https://work.haynesnetwork.com/work_packages/404)) adds
`legacy.import_map_mismatch`: an existing import map from another title, draft revision,
production, media kind, manifest file or `speech.json`; the importer also reports it for
a manifest whose frame size matches no media kind. An import map may also carry, as optional
fields, a `source_key` per board and line, the `cues` and `notes` of each board, and
`story_records` (beds and asset versions), so that a second import returns every
identifier of the first. [`legacy-import-map-r4-full.json`](examples/valid/legacy-import-map-r4-full.json)
is such a map: r4 imported with it mints nothing and reproduces every identifier of
[`story-winter-menu-r4.json`](examples/valid/story-winter-menu-r4.json); only the fields
a manifest cannot give differ (board titles, photos, seeds). Source keys name the record
type, after `legacy:<job>:`: `shot:<id>`, `shot:<id>:line:<k>`, `shot:<id>:sfx:<i>`,
`shot:<id>:move:<i>`, `shot:<id>:camera`, `shot:<id>:note`, `still:<path>`,
`set:<path>`, `sfx:<name>`, `bed:<name>`, `voice:<voice_id>` and `speech:shot:<id>`; the
story itself is `legacy:<title>`. The asset library (story 382) adds `legacy.evidence_mismatch`: two
public records (ledger, `timeline.json`, `prompts.json`) disagree on a hash or byte
count.

## 2. Schema versions and identifiers

### Schema names

Every document carries `"schema": "studio.<type>/v<major>"`. Types in v1: `production`,
`story`, `board`, `asset`, `asset-version`, `job`, `run`, `run-snapshot`, `delivery`,
`go-live-approval`, `story-timing`, `legacy-import`, `method-capabilities`, and the test
wrapper `invalid-case`. Error responses use the envelope in
[section 12](#12-api-ui-and-mcp-boundaries) and have no `schema` field.

- Adding an optional field keeps the major version. Removing, renaming or changing the
  meaning of a field bumps it. A reader rejects an unknown major
  (`schema.unsupported`).
- Write requests reject unknown fields (`schema.unknown_field`), so a typo from an agent
  fails instead of vanishing (P-02). When a specific rule covers a field (a typed
  `timing.duration_ms`, cue fields inside a note), the validator reports that rule instead.
  A missing or mistyped field that no specific rule covers is `schema.invalid`.
- References inside a document have three general codes, used where no specific rule
  exists (`cue.anchor_line_missing`, `cue.slot_not_on_board`,
  `voice.speaker_not_in_cast` and `id.type_mismatch` win): `ref.unknown` (a layout
  preset, story, media kind or cast slot that does not exist), `ref.duplicate` (an
  identifier, cast slot, board number or source key used twice) and `story.board_order`
  (a story's boards and its `board_order` disagree).
- A JSON number with an integral value (`1900.0`) is the integer 1900, as JSON Schema
  and JavaScript read it. A document nested deeper than 64 levels is refused.
- Fields under `derived` are computed by the server, returned on reads and rejected on
  writes.
- The legacy manifest has no `schema` field. Story 378 documents it as
  `legacy.manifest/v1`, detected by shape (`shots`, `frame`, `job`), covering r1 to r4.
- JSON Schema files (draft 2020-12) are the normative form, owned by 378 (legacy) and
  404 (canonical). This document and its examples are what those files must agree with.
- Records a build keeps beside its media are artifacts, not API types, and are not in the
  list above: `studio.stage-record/v1` (section 8), `studio.whole-frame-clips/v1`,
  `studio.s2v-clip/v1`, `studio.keyed-frames/v1` (section 4), `studio.mix-placement/v1`
  and `studio.check-result/v1` (section 8).

### Identifiers (P-01)

`<prefix>_<ULID>`: a type prefix, an underscore and a 26-character ULID in upper-case
Crockford base32 (first character `0` to `7`; no `I`, `L`, `O` or `U`).

```
^(prd|sty|brd|lin|cue|nte|ast|asv|job|run|dlv|apr|key|fmv|pub|fbk)_[0-7][0-9A-HJKMNP-TV-Z]{25}$
```

| Prefix | Entity | Prefix | Entity |
|---|---|---|---|
| `prd` | production | `job` | asynchronous job (voice, photo, asset) |
| `sty` | story | `run` | run |
| `brd` | board | `dlv` | delivery |
| `lin` | line | `apr` | go-live approval |
| `cue` | cue | `key` | agent key |
| `nte` | note | `fmv` | format version (E9.2, reserved) |
| `ast` | asset | `pub` | publication (E9, reserved) |
| `asv` | asset version | `fbk` | feedback (E9.3, reserved) |

- IDs are made by the server or the CLI, never typed by people, and never reused.
  Errors: `id.malformed`, `id.type_mismatch`.
- Display codes are not IDs: board `S01-B03` (mockup), run `Run 02` (per-story `number`
  from 1), asset version `v3` (per-asset `number` from 1).
- A principal is one of `{kind: human, iss, sub}` (from a verified OIDC token, never an
  email or display name), `{kind: agent, key_id}`, `{kind: worker, worker_id}` or
  `{kind: cli, command, operator}`, where `operator` is a human principal. v1 adds
  `{kind: agent_session, session, harness, model}` for work an agent did in its own
  dev-env session without a studio key, such as checking a licence (P-24). It records
  who did the work and grants nothing. The principal schema accepts it wherever a
  principal goes since story 849: its three fields are non-empty strings and it has no
  other (P-40). The licence register's entries still name their checking session
  `{kind: worker, worker_id: "dev-env agent session <name>"}`, as recorded at the check
  (story 809).
- **The command line's operator when an agent session runs it (O-428-1; the contract
  owner's decision, a proposal Tom may overrule, P-48).** The command line takes only a
  human operator, so story 428's agent session recorded itself as `{kind: human, iss:
  "https://agent-session.invalid/dev-env", sub: "agent-session:<session>"}`. That
  reading stands for the E1 records already written: the stand-in issuer, which no
  sign-in can issue, marks each of them as an agent session's work. Such a record is
  never presented as a person's act. The command line gets an `agent_session` operator
  later (story [864](https://work.haynesnetwork.com/work_packages/864), contract text and
  schema first).
- Hashes: a field named `sha256` is the lower-case hex SHA-256 of stored bytes. A field
  named `*signature` is `sha256:` plus the hex SHA-256 of canonical JSON
  ([section 4](#4-cache-clocks-and-invalidation)).
- External IDs (Wan job IDs, legacy ledger IDs, ComfyUI prompt IDs) are attributes, never
  canonical IDs.
- **Rejected:** UUIDv4 (no time order, poor index locality); database integers (leak
  counts, collide between the offline CLI and the server); bare ULIDs (a story ID passed
  as a board ID would only fail at lookup).

### Story and board fields

Full instances: [`story-winter-menu-r4.json`](examples/valid/story-winter-menu-r4.json)
(the r4 script as one story of nine boards, no line, cue or layout lost).

| Story field | Type | Rule |
|---|---|---|
| `id`, `production_id`, `media_kind` | IDs, `short` or `video` | the media kind must be enabled on the production |
| `title`, `revision` | text (1 to 80 characters, mockup), integer | `revision` goes up on every write to the story or to any of its boards, lines, cues, notes or order, so `queue_run` sees one draft version |
| `format_version_id` | `fmv_` or null | null: no format, so no length warning |
| `cast[]` | `{slot, name, voice_version_id}` | slot `a` to `z`, unique; voice is a `voice` asset version |
| `narrator_voice_version_id` | `asv_` or null | needed by any narrator board |
| `set` | `{asset_version_id, motion_asset_version_id, foreground_edge_px, foreground_feather_px, legacy_fire}` | `legacy_fire` is read only by the rigid renderer |
| `layouts` | name to preset | Legacy pixel presets; boards name one |
| `motion_style`, `mix`, `checks`, `beds[]` | objects | sections 6 and 10 |
| `board_order` | board IDs | the order; every board exactly once |
| `boards[]` | board documents | exchange and snapshot form only; the API serves boards separately |
| `origin` | `{source_key, legacy_revision, tracker, manifest}` or null | |
| `derived` | `board_count`, `next_board_number`, `timed_boards`, `untimed_boards`, `frames`, `fps`, `duration_ms` (floor), `warnings` | read-only |

| Board field | Type | Rule |
|---|---|---|
| `id`, `story_id`, `number`, `revision` | IDs, integers | `number` is a per-story creation sequence (display `B03`), never reused or renumbered on reorder |
| `title` | text, 1 to 100 characters | mockup limit |
| `lines[]` | `{id, speaker, text, gap_before_ms}` | ordered; at most 256 (story 405's bound, `schema.invalid`); text 1 to 1200 characters (mockup); TIME-2; speaker per VOICE-1 |
| `timing` | `{lead_ms, tail_ms, hold_ms}` | spoken: lead and tail, hold null; silent: hold only (TIME-3 to TIME-5); lead and each gap at most 120 000 (TIME-5, in the board schema since story 849) |
| `voice` | `{style, current_version_id}` | style `cast` or `narrator`, null on a silent board |
| `photo` | `{current_version_id, prompt, input_asset_version_ids}` | prompt up to 1800 characters; inputs are the composer's assets |
| `cast[]` | `{slot, asset_version_id, motion_asset_version_id}` | draw order; one still per slot (expression); the optional motion pin names the doll loop the slot plays (section 9, story 457) |
| `layout` | `{preset, foreground}` | preset must exist in story `layouts` |
| `method` | `{layer, motion}` | section 5 |
| `seeds` | `{"s2v:<slot>": int, "i2v:frame": int}` | section 4 |
| `cues[]`, `notes[]` | section 6 | |
| `drafted_by` | principal | an agent principal shows the mockup's "Agent draft" badge; whether an `agent_session` drafter shows it is open (no code computes the badge yet) |
| `origin` | `{source_key, legacy_revision, legacy_shot, manifest}` or null | |
| `derived` | `timing_state` (`timed`, `untimed`), `content_ms`, `frames`, `film_start_frame`, `voice_state` (`not_needed`, `absent`, `generating`, `current`, `stale`), `photo_state` (`absent`, `generating`, `current`, `stale`) | read-only; absent and stale assets are explicit, never inferred from nulls |

A job (`studio.job/v1`, story [405](https://work.haynesnetwork.com/work_packages/405)) is
`{id, kind (voice, photo, asset_candidate), target_id, input_signature, status (queued,
running, succeeded, failed, cancelled), result_version_id, result_is_current, error,
created_by, created_at, updated_at}`, plus a `voice` block on a voice job: the input it
must make (`production_id`, `story_id`, `name`, `engine` (the signing name), `model`,
`lead_ms`, `gaps_ms`, and
`lines` of `{line_id, speaker, text, voice_version_id, voice_id, signature}`), so the
worker never reads the draft as it was at queue time. A voice or photo job targets a
`brd_` ID. `result_version_id` and `result_is_current` are set only when `succeeded`;
`error` is `{code, message}`, only when `failed`. The validator recomputes every take
signature and the `input_signature` from the `voice` block. States move `queued →
running | cancelled` and `running → succeeded | failed | cancelled`; any other move is
`job.transition` (status `conflict`), and an in-flight job is never cancelled because
its board changed. A job that finishes after its inputs changed is `succeeded` with
`result_is_current: false` (VOICE-4). Examples: [queued](examples/valid/job-voice-queued.json),
[succeeded and stale](examples/valid/job-voice-succeeded-stale.json) (r4 board 8, its lead
edited while the job ran).

### Mockup fields

Every field of the [v6 mockup](../design/studio-ui-mockup/index.html) and where it lives.

| Mockup | Contract |
|---|---|
| `productions`, `productionMedia`, `mediaTypes` | productions and their `media_types`; kinds `short` 9:16, `video` 16:9 |
| story `{id, title, production, media, boards, selected, nextBoard}` | story `id`, `title`, `production_id`, `media_kind`, `board_order`; `selected` is a user selection; `nextBoard` is `derived.next_board_number` |
| board `id` and code `S01-B01` | `brd_` ID; display code from `number` |
| `title`, `lines[{id, speaker, text}]` | the same, with stable `lin_` IDs and `gap_before_ms` |
| `duration` | `derived.frames` / 24; never typed (D33) |
| `hold` | `timing.hold_ms` |
| `voiceStyle` (`cast`, `narrator`) | `voice.style` |
| `voice {version, seconds, busy, dirty, input}` | `voice.current_version_id` (its `number`), `derived.content_ms`, `derived.voice_state` (`generating`, `stale`), take and version signatures |
| `prompt`, `assets`, `photoInput` | `photo.prompt`, `photo.input_asset_version_ids`, and the photo version's `provenance.generator` inputs |
| `photo` (version number), `photoDirty`, `photoBusy` | `photo.current_version_id` (its `number`), `derived.photo_state` `stale`, `generating` |
| `layer` (`layered`, `whole`), `motion` (`s2v`, `i2v`) | `method.layer` (`layered`, `whole_frame`), `method.motion` |
| `cue` string, `notes[]`, `noteDraft` | `notes[]`; a draft note is client state |
| `agent` | `drafted_by.kind == "agent"` |
| asset `{id, name, kind, doll, labels}` | asset `kind`, `name`, `attributes.character_slot`, `labels` |
| `gen {name, kind, prompt, busy, result {promoted}}` | `generate_asset_candidate` job; candidate version; `promote_asset_version` |
| run `{number, story, status, boards, duration, estimate, progress, created, approved}` | run `number`, `story_id`, `status` (`done` is `succeeded`), `snapshot`, `outputs.frames`, `estimate`, `progress`, `queued_at`; `approved` comes from go-live approvals |
| `mediaFilters {publication, approved}` | `list_stories` query `publication` (`published` or `unpublished`) and `approved=true`, alone or combined (D31) |
| `assetScope`, `assetStory`, `assetBoard`, `assetKind`, `search`, `panels`, `scroll`, `last`, `reviewContext` | user selections (D32, D34); theme stays local |
| create form `name` (production, story) | `name` and `title`, 1 to 80 characters |
| `compare {left, right}` | `compare_runs` |
| `userName` | display name from the OIDC claims, display only |
| timecode at 25 fps | 24 fps (section 3) |

## 3. The time contract

### Units

| Quantity | Unit | Source |
|---|---|---|
| Authored offsets and durations (`*_ms`) | integer milliseconds | P-03 |
| Delivery picture | integer frames at **24 fps** | `short`: Legacy (`frame.fps` in all four manifests, [validation.json](../../titles/the-winter-menu/evidence-r4/validation.json)); `video`: P-20. The mockup's 25 fps is a prototype default (review M2). |
| Mix audio | integer samples at **48 000 Hz** (2000 per delivery frame, 48 per ms) | Legacy (`RATE` in `poc/studio.py`) |
| Speech-to-video source | integer frames at **16 fps**, chunks of 77 frames | Evidence ([findings.md](../../titles/the-winter-menu/video-e0/findings.md), `poc/s2v.py`) |
| Image-to-video source (TI2V-5B) | 121 frames at 24 fps (5.04 s) | Evidence ([findings.md](../../titles/the-winter-menu/video-e0/findings.md)) |
| Measured voice | integer samples at the take's rate (Kokoro: 24 000 Hz) | Legacy (`poc/speech.py`) |

Floats never carry time. Display seconds are `frames / 24` rounded to 3 decimals, for
display only.

### Rules

- **TIME-1 Measured duration.** A take's `duration_ms = ceil(samples * 1000 / rate)`,
  so a line is never shorter than its audio (P-03). Legacy imports keep the recorded
  `duration_s` (3 decimals) as `duration_ms` with `duration_source: legacy_duration_s`.
- **TIME-2 Line offsets.** `start[0] = lead_ms`; `start[i] = end[i-1] + gap_before_ms[i]`;
  `end[i] = start[i] + duration_ms[i]`. The first line has `gap_before_ms: null`
  (`time.first_line_gap`).
- **TIME-3 Spoken board length.** `content_ms = lead_ms + sum(duration_ms) +
  sum(gap_before_ms) + tail_ms`; `frames = ceil(content_ms * 24 / 1000)`, computed in
  integers as `(content_ms * 24 + 999) div 1000`. The rounding remainder (under one frame)
  lands in the tail. Legacy (`edit.timeline`, `math.ceil(d * fps)`).
- **TIME-4 Silent board length.** `frames = ceil(hold_ms * 24 / 1000)`, with
  `100 <= hold_ms <= 120000` (`time.hold_out_of_range`; a positive hold is story 404's
  acceptance, the bounds are the mockup's hold field, P-04). A spoken board has no hold (`time.hold_on_spoken_board`), and nobody types
  a board duration (`time.duration_is_derived`, D33).
- **TIME-5 Pads.** `tail_ms >= 250` (`time.tail_too_short`; Legacy assertion "lines must
  end at least 0.25 s before the cut"); `lead_ms >= 0` and `gap_before_ms >= 0`
  (`time.negative`). `lead_ms` and each `gap_before_ms` are at most 120 000, the longest
  hold of TIME-4, and a board has at most 256 lines (`schema.invalid`, as story 405
  reports them; no specific rule names these bounds). These are story 405's bounds, which
  the contract owner moved here from the voice job: its voice request,
  job and builder refuse more before any speech call. The board schema checks them too
  since story [849](https://work.haynesnetwork.com/work_packages/849): `schema.invalid`
  at `/timing/lead_ms`, `/lines/<i>/gap_before_ms` or `/lines`, on a board and on every
  board a story embeds. New boards
  default to lead 500, gap 300, tail 700 (P-04: r4's single-shot values and the legacy gap
  default). The mockup's 0.25 s pad is not adopted (review M2). Authored values must be
  integers (`time.not_integer_ms`).
- **TIME-6 Untimed boards.** A spoken board without a current voice version has
  `timing_state: untimed` and no frames. The story total is then a lower bound
  (`complete: false`), and Build is refused (`voice.absent`, `voice.stale`).
- **TIME-7 Film placement.** Board *k* starts at film frame `F[k] = sum(frames[j], j < k)`.
  Line *i* on board *k* starts at mix sample `F[k] * 2000 + start[i] * 48`. Exact
  integers; no rounded seconds in between.
- **TIME-8 Board-specific clips.** For a clip made for one board (an S2V layer, a
  whole-frame I2V clip), delivery frame *n* of the board (board clock, from 0) shows source
  frame `floor(n * fs / 24)`; for 16 fps that is `floor(2n / 3)`. A board of *F* frames
  needs `floor((F - 1) * fs / 24) + 1` source frames. Extra source frames are trimmed and
  recorded. A shorter clip fails the stage (`time.source_short`); the legacy compositor
  silently held the last frame, which this contract does not allow (P-05). Legacy
  (`DollClip.frame_at` in `poc/layered_film.py`). A library timed clip (section 9) plays
  from its record's trim start: frame *n* shows `trim_start + floor(n * fs / 24)`.
  **Chains (story 427, P-36).** A whole-frame board longer than one clip is a chain of
  whole clips of *L* frames. Each clip after the first starts on the previous clip's last
  frame, repeats it as its own frame 0, and that frame is dropped: *n* clips of *L* frames
  give `n(L - 1) + 1` source frames. A board asks for one clip when it needs at most *L*
  frames, else `1 + ceil((needed - L) / (L - 1))`. With E0's `L = 121` a chain is at most
  3 clips, 361 frames, 15.04 s (Q-427-2, the contract owner): a longer board is refused
  (`wholeframe.chain_limit`; `cache.key_input_invalid` in the plan) and is split or made
  layered. Nothing is stretched. The requested lengths change only at 122 and 242 frames,
  so a hold or tail edit inside a chain keeps its clips.
- **TIME-8a Loops.** Reusable `motion` assets (doll loops, set loops) play ping-pong under
  boards of any length: board frame *n* shows source frame
  `trim_start + pingpong(n + phase, N)`, with period `2N - 2` and the phase from
  [section 4](#4-cache-clocks-and-invalidation). They are never "short". Loops are 24 fps;
  each pinned record gives its own `N` and trim start (E0's are 121 frames from 0), and
  the build takes them from the record, not the toolchain (story 426). Legacy
  (`pingpong()` in `poc/layered_film.py`, which indexed by film frame).
- **TIME-9 Speech-to-video request.** Each on-screen speaker gets a drive track of exactly
  `F / 24` seconds: her lines at their offsets, silence elsewhere. Requested length
  `L = 4 * ceil(F / 6) + 1` (that is, the `F / 24 * 16` source frames rounded up to a
  multiple of 4, plus 1; the formula is normative); if `L > 77`, `L = 77 * ceil(L / 77)`.
  `L` must be at least the frames TIME-8 needs; a profile whose source fps `L` cannot
  cover (the formula is sized for 16 fps) is refused before the source is asked
  (`layered.unsupported`). The drive track is assembled at the takes' own rate (24 000 Hz
  for Kokoro), so it is exactly `F * 1000` samples there and nothing is resampled (story
  426, P-39); takes that cannot make an exact track are `layered.drive_invalid`. "Exactly"
  is to one sample: where `F * rate / 24` is not whole (16 kHz and `F` not a multiple of
  3), the Wan clip client accepts the floor or the ceiling (story 842). The engine
  delivers a fixed number of frames over `L`: E0's 11 speech clips, and the client's check,
  give `L + 1`, `L + 4` and `L + 7` for 1, 2 and 3 chunks, which TIME-8 trims; any other
  count is refused (`adapter.response_invalid`, section 8). Legacy (`poc/s2v.py` with pad
  0, as the layered S2V film used it).
- **TIME-10 Cues.** A cue's resolved start lies in `[0, board length)`
  (`cue.out_of_range`); on an untimed board the check runs at `queue_run`. A sound may run
  past the cut and is cut at film end; both are recorded. Legacy (`edit.audio`) cut it
  100 ms after film end (its mix buffer's spare tenth of a second), so a recorded legacy
  sound end may exceed the film's length; no Winter Menu sound does. The mixer (story
  841) cuts it at the film's last sample, not faded, and records `cut_at_film_end` and
  `cut_samples`; whether it should fade at the cut is Q-841-01, open for Tom. The mix key
  has no board boundaries, so the mixer checks this rule with the story beside the key.
- **TIME-11 Conservation.** Sum of board frames = film frames = decoded master frames;
  master duration = frames / 24; mix length = frames x 2000 samples; every line ends at
  or before `content_ms - tail_ms` of its own board. Any mismatch fails the run
  (`time.conservation`, story 380, for segment, board and film frames). AAC in MP4
  records its length at the encoder's granularity, so a master's audio passes within one
  AAC frame (1024 samples, 21 ms) of `frames x 2000`, recorded and decoded, and must run
  on from sample 0 with no hole; the phone proxy's audio is exact (story 381). The PoC's
  own masters are a few samples short (32 for 1087 frames): story 841 found the cause in
  the MP4 movie timescale, whose default of 1000 rounds the recorded length down to a
  whole ms (45 291.67 ms recorded as 45 291 ms). The mixer's masters use a timescale of
  48 000 (P-38), so their recorded audio is exactly `frames x 2000`; only the decoded
  count needs the one-AAC-frame allowance, for the encoder's padding. The delivery check
  still allows one AAC frame on both for the master. The proxy had the same cause: at
  timescale 1000 a film whose frame count is not a multiple of 3 (r4's 1087 among them)
  recorded fewer samples than it holds and its exact check refused it. Since story 857 the
  proxy is muxed at 48 000 too, so its recorded audio is exactly `frames x 2000`.
- **TIME-12 Legacy adapter.** Imported runs keep their recorded values. Canonical
  arithmetic reproduces every r4 frame count (table below); story 378 checks r1 to r3.
  Legacy rounded shot starts to 0.1 ms before placing samples, so legacy and canonical
  sample placements differ by up to 3 samples (0.06 ms). A check against a recorded
  `timeline.json` needs more room: the record rounds line and sound times to 3 decimals
  and takes line ends from the resampled audio, not `duration_s` (up to 0.667 ms on the
  Winter Menu). Such cross-checks allow 1 ms for line, sound and bed times; frames are
  exact, and shot times are exact at the record's 4 decimals.

### Worked example: The Winter Menu r4

From [`manifest-r4.json`](../../titles/the-winter-menu/manifest-r4.json),
[`speech.json`](../../titles/the-winter-menu/evidence-r4/speech.json) and
[`timeline.json`](../../titles/the-winter-menu/evidence-r4/timeline.json), with S2V
lengths from [`clip-records-s2v.jsonl`](../../titles/the-winter-menu/video-e0/clip-records-s2v.jsonl).
All frame counts match the recorded timeline.

| Board | lead | sum of takes | sum of gaps | tail or hold | content_ms | frames | film start | S2V `L` requested | source frames needed | returned |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 500 | 5163 | 0 | 700 | 6363 | 153 | 0 | 154 (2 chunks) | 102 | 158 |
| 2 | 500 | 2688 | 0 | 700 | 3888 | 94 | 153 | 65 | 63 | 66 |
| 3 | 500 | 4864 | 0 | 700 | 6064 | 146 | 247 | 154 | 97 | 158 |
| 4 | 500 | 2475 | 0 | 500 | 3475 | 84 | 393 | 57 | 56 | 58 |
| 5 | 400 | 2432 | 0 | 600 | 3432 | 83 | 477 | 57 | 55 | 58 |
| 6 | 400 | 4309 | 0 | 350 | 5059 | 122 | 560 | 154 | 81 | 158 |
| 7 | (silent) | | | hold 1900 | 1900 | 46 | 682 | (I2V) | | |
| 8 | 1900 | 5377 | 2350 | 800 | 10427 | 251 | 728 | 231 (3 chunks) | 167 | 238 |
| 9 | 1900 | 981 | 0 | 1600 | 4481 | 108 | 979 | 73 | 72 | 74 |
| | | | | | | **1087** | | | | |

1087 frames / 24 = 45.2917 s, the recorded `total_s`; `validation.json` decoded 1087.

Board 1: `(6363 * 24 + 999) div 1000 = 153`. S2V: `ceil(153 / 6) = 26`, so
`L = 4 * 26 + 1 = 105 > 77`, giving `77 * 2 = 154`; frame 152 shows source frame
`floor(304 / 3) = 101`, so 102 source frames are used and 56 trimmed.

Board 8 lines (ms from board start): B 1900-2903, A 3203-4014, C 4214-5089,
D 5339-5851, B 6551-7575, B 8475-9627; plus tail 800 = 10427. The gavel cue is anchored
50 ms after "Motion carried." (line 5): 7625 ms, so mix sample
`728 * 2000 + 7625 * 48 = 1822000`, 37.958 s, as recorded.

### Format length (D45)

A story longer than its format's length range gets a warning
(`format.length_exceeded`, severity `warning`); Build stays allowed. Platform maxima
are checked at release preparation (E9.4), never before Build. Example:
[`story-timing-summary.json`](examples/valid/story-timing-summary.json) (format numbers
there are illustrative; formats arrive with story
[447](https://work.haynesnetwork.com/work_packages/447)).

## 4. Cache clocks and invalidation

### Clocks

| Clock | Origin | May drive |
|---|---|---|
| Board clock | frame 0 / 0 ms of the board | **All picture.** Clips, layers, bounce, moves, camera. |
| Film clock | frame 0 of the run | Concatenation, mix placement, beds, master. **Never picture.** |
| Source clock | frame 0 of a generated clip | Mapped to the board clock by TIME-8. |
| Wall clock | none | Nothing. Timestamps are provenance, not inputs. |

Legacy used the film clock for picture in two places: the procedural fire
(`edit.Fire`, an RNG drawn in film order) and the layered set loop and doll clips
(ping-pong by film frame plus `37 * k`). Either makes an early duration edit change every
later board's pixels (review H3). The canonical renderer uses the board clock (P-06):

- Looping layers start at phase `int(sha256(board_id + ":" + slot)[:8], 16) mod period`,
  stable across edits and reorders.
- Procedural randomness is a pure function of `(seed, board_id, index)`; no RNG state
  carries from one board to the next. The seed is the toolchain's procedural seed
  (story 380), and the segment key carries a 64-bit stream number derived from it and
  the board ID, never the ID itself. A board's `seeds` has no entry for procedural
  effects, so v1 has no per-board re-roll of them.
- Generation seeds are explicit on the board (`seeds`: `s2v:<slot>`, `i2v:frame`). The
  server assigns a missing seed by writing it to the board (a new revision), so two runs
  of one draft use the same seeds. A re-roll is a seed edit.
- Visible effect: a set loop restarts at each cut. Rejected alternative: a film-clock
  option per story, which costs selective reuse for every later board.
- Legacy-mode rendering (378, 425) keeps the film clock so it reproduces legacy output.

### Cache keys

`key = "sha256:" + hex(sha256(canonical_json(inputs)))`. Canonical JSON: UTF-8, keys
sorted, no whitespace (`separators=(",", ":")`), no NaN or Infinity, all times integers;
floats (gains, zoom, angles) in shortest round-trip form. Inputs are content hashes of
input bytes, never IDs, plus the artifact kind, the adapter or profile version and the
toolchain digest (P-07). As built (story [380](https://work.haynesnetwork.com/work_packages/380),
[reference](../reference/cache-and-splice.md)): every key document carries `kind` and
`scheme: studio.cache-key/v1`; an integral float is the integer it equals and texts are
NFC before hashing; a key document that holds a studio identifier anywhere, or a value
that is not a hash, integer, text or finite JSON value, is refused
(`cache.key_input_invalid`).

| Artifact | Clock | Key inputs |
|---|---|---|
| Voice take | none | TTS model digest, voice ID, NFC text, speed, sample rate |
| Board voice track | board | take hashes, lead, gaps, mix rate, assembler version (no tail) |
| S2V drive track | board | speaker, **that speaker's takes on the board, each as its hash and start in ms (board clock)**, board frames, fps, rate (the takes' own, 24 000 for Kokoro: story 426), assembler version (P-25) |
| S2V clip | source | drive track, start still (the speaker's cast still's loop's start image: story 426), prompt, negative prompt, seed, profile (model files, LoRA, steps, cfg, size, chunk, source fps), adapter version. A library timed clip made from the same drive track with the board's seed takes its place (Q-426-2) |
| Doll clip or set loop (library `motion`) | source | the image the engine animated (the record's `source.image_sha256`; for E0 the doll on green, not the cutout), prompt, seed, profile (which names the adapter). Made by an asset job, never by a build (Q-457-1); the build reads the key from the pinned record (`keys.clip`). It has no negative prompt; the record's identity carries it (P-37) |
| Whole-frame I2V clip(s) | source | photo, prompt, seed, profile (which names the adapter, `studio.i2v/1`), requested clip lengths (set by the frames needed and the chain policy of TIME-8, story [427](https://work.haynesnetwork.com/work_packages/427)). A chain is one artifact |
| Keyed and decal frames | source | clip, key thresholds, protect boxes, still (the clip's start image, as Legacy `DollClip.cache_dir` hashed it), decal box, decal version, keyer as `<record's keyer>@<build>` (the numpy, OpenCV, Pillow, scipy, PyAV and libavcodec versions). The keying inputs are the pinned loop record's; the decal floor is not an input (P-39) |
| Board picture segment | board | method, layout preset values, cast stills, clip and keyed hashes, phases, how each layer plays (loop or timed, trim, source fps, decal floor), set plate and set loop with its phase, a whole-frame board's clip, motion style (every layered board), voice envelope when any line is spoken, who speaks when (each line's speaker and span), move and camera cues resolved to ms, frames, frame size, fps, foreground edge, procedural stream, compositor digest, encoder settings and build (P-26). A spoken whole-frame board's segment carries the voice envelope and who speaks when too, though its renderer draws nothing from them |
| Film picture | film | ordered segment hashes, each with its frame count, splicer |
| Mix | film | ordered voice tracks with `F[k]` and line spans, sound cues resolved to samples (sound hash, trim, level), beds, line RMS, loudness and true-peak targets, frames, rate, mixer digest (every number of the mixer, its fades included, and the filter build: story 841). It has no board boundaries and no take sample counts |
| Master / proxy | film | picture + mix + mux settings (container, video copy, codec, bit rate, layout, rate, faststart, movie timescale, threads, encoder build: story 841) / master + proxy profile; both name the encoder build |
| Check result | none | artifact hash, check version, thresholds; a transcript check also the story's tolerances and the script's hash; a sound check's thresholds carry the story's targets and `frames x 2000`, its version the filter build (story 841) |

**P-25 (H-1, the contract owner, 2026-11-13).** A drive track is keyed on its own
speaker's takes at their starts, as `cache.keys.s2v_drive_track_key` does: a line edit
then rebuilds the edited speaker and, when a take's length changes, every speaker with a
later line, as the invalidation table says. Rejected: the whole board voice track as the
input, which rebuilds every speaker's S2V clip on any line edit.

**P-26 (H-2, the contract owner, 2026-11-13).** Segments are encoded so the same frames
give the same bytes in one build: libx264 `fast`, CRF 18, `yuv420p`, 2 threads in
**sliced-thread** mode, no B-frames, a keyframe every 48 frames (2 s), the first frame an
IDR. These settings, the thread count and mode, and the encoder build (the PyAV and
libavcodec versions; the PyAV wheel bundles FFmpeg and x264) are segment key inputs.
x264's default frame threading, which legacy used through `ffmpeg -threads 2`, gave 3
different byte streams in 25 encodes of one segment; sliced threads gave 1 (story 380).
Encoded bytes are never compared across builds; tests compare decoded frames. The film
picture is a stream-copy splice of the segments, each starting on a keyframe
(`splice.incompatible` otherwise). Rejected: frame threads (a full render could not
reproduce a cached segment); one thread (as reproducible in the same measurement, but it
gives up the second thread). Story 428 measures the cost.

**P-27 (H-3, the contract owner, 2026-11-13).** A cached artifact is a completed stage
named `<kind>-<key hex>` with two outputs: the artifact, and `inputs`, the key document
itself, whose hash is the key. Lookup searches the current run, then earlier runs,
newest first; a hit is re-hashed and writes nothing in the current run; a damaged entry
fails closed (`cache.entry_invalid`) and nothing repairs or skips it (D17). Cached
artifacts are per production. The product's lookup is one Postgres query by stage name
in story [434](https://work.haynesnetwork.com/work_packages/434). Rejected: one reserved
cache run per production, which invents a run that is not a run.

A renderer plugs in behind one interface (story 380's `SegmentRenderer`) and draws only
from the segment key's inputs. A renderer that gives more or fewer frames than the board
has fails `render.frame_count`; a frame that is not 8-bit RGB of the board's size fails
`render.frame_invalid`; a segment that does not hold its board's frames fails
`time.conservation`.

**Renderers and records as built (stories 427, 457, 426 and 841).**

- Two renderers exist: `WholeFrameRenderer` (story 427,
  [reference](../reference/whole-frame-adapter.md)), compositor
  `studio.wholeframe/1+pillow-<version>`, and `LayeredRenderer` (story 426,
  [reference](../reference/layered-adapter.md)), compositor
  `studio.layered/1+pillow-<v>+numpy-<v>`. Each reads only the segment key document and
  refuses an input it does not draw. Story 380's `Toolchain` names one compositor per
  build, so a story with both methods needs one per method (story 406).
- A layered board is planned from pinned library `motion` records (section 9): an idle
  doll's clip is its loop's bytes, with the record's clip key, `N`, fps and trim and the
  board's own phase, and no source is asked for it. A blocking motion problem stops the plan with the
  resolver's own code (`motion.clip_absent` for a cast still without a loop), not
  `cache.key_input_invalid`. The toolchain's doll motion and keying fields are story
  380's placeholders: they key only a plan made without motion records, which the
  layered renderer refuses (`layered.unsupported`).
- A motion record's `keys` (`clip`, `keyed`, `identity`) come from one pure function,
  `motion_identity` (story 457). The identity adds what neither key covers: use,
  subject, the still the clip stands in for, the clip's bytes, frames, fps, size, trim,
  negative prompt, the drive track's board frames and the decal floor. The plan's keyed
  key is the record's `keys.keyed` with the build added to its keyer, and a stage refuses
  a key made for another build. Stored keys were computed under `studio.cache-key/v1`, so
  a scheme bump would make every stored record fail `motion.identity_mismatch`: a bump
  needs a migration rule first, which is not written yet.
- Besides the `<kind>-<key hex>` entries of P-27, two stages are named by content and
  committed just before the entry that names them, in the same run, so every blob is
  listed by a completed record: `whole_frame_media-<clip set SHA-256>` (a whole-frame
  clip set's clips and chained start images) and `s2v_clip_record-<clip SHA-256>` (an
  S2V clip's provenance record, `studio.s2v-clip/v1`). A hit reads them in the entry's
  run. The whole-frame clip set (`studio.whole-frame-clips/v1`) is the artifact the
  segment key's whole-frame clip names; the keyed frames are one APNG holding the
  `studio.keyed-frames/v1` record (P-39). The mix's placement record is cache kind
  `mix_placement` under the mix key's inputs (section 8).

### Invalidation set per edit

"Reused" means the key is unchanged, so the cached artifact is used. The table is the
expected result of the keys; tests in story [380](https://work.haynesnetwork.com/work_packages/380) assert it.

| Edit | Pre-build assets | Board *k* picture | Other boards' pictures | Film picture, mix, master, proxy |
|---|---|---|---|---|
| Line text, line added or removed | new voice version; TTS only for changed takes | every S2V clip whose drive track changes: the edited line's speaker, plus every speaker with a later line when a take's duration changes; all S2V clips if frames change; segment | reused | rebuilt |
| Line speaker | takes of that line | S2V clips of old and new speaker, plus every speaker with a later line when the new take's duration differs; all if frames change; segment | reused | rebuilt |
| Lead or gap | new voice version, no TTS | S2V clips of every speaker with a line after the edited point (a lead edit moves all); all S2V clips if frames change; segment | reused | rebuilt |
| Tail | none | only if frames change: S2V clips and segment; a spoken whole-frame board's I2V clips reused while the requested clip lengths are unchanged | reused | rebuilt if frames change, else reused (no key changes) |
| Hold (silent board) | none | only if frames change: segment; whole-frame I2V clips reused while the requested clip lengths are unchanged | reused | rebuilt if frames change, else reused (no key changes) |
| Reorder boards | none | reused | reused | rebuilt (film offsets move) |
| Add or remove a board | that board's | that board's | reused | rebuilt |
| Method (layer or motion) | none | clips and segment | reused | picture only |
| Seed | none | that clip and its keyed frames (the drive track is reused; a library timed clip made with the old seed is no longer used, so the build makes one: Q-426-2); segment | reused | picture only |
| Cast still version | a layered board using it gets a recomposed photo (D51); a whole-frame board's photo inputs are marked changed where they name it | the new version's own pinned loop (`motion.clip_absent` without one): an idle doll's clip and keyed frames, and a speaker's S2V clip from that loop's start image, with its keyed frames; segments of every board using it | same rule on those boards | picture only |
| Board photo version | none | whole-frame: I2V clip and segment; layered: reused, because its photo is derived from its layers and is no build input (D51) | reused | whole-frame: picture only; layered: reused |
| Layout preset values | a layered board using it gets a recomposed photo (D51) | segments of boards using it | same | picture only |
| Move or camera cue | none | segment | reused | picture only |
| Sound cue, bed, level, loudness target | none | reused | reused | mix, master, proxy only |
| Note or title | none | reused | reused | reused (the snapshot differs; artifacts do not) |
| Story motion style | none | every layered segment | every layered segment | picture only |
| A cast slot's voice | every take of that speaker | per board as "line text" | same | rebuilt |
| Toolchain or profile digest | as used | every artifact that tool made. Doll loops and keying come from pinned records, so the toolchain's doll motion and keying fields change no key of a layered plan; a record keyed by another keyer, or a new build of a keying library, re-keys every layer keyed with it (story 426) | same | rebuilt downstream of what that tool made |
| Media kind frame size or fps | layered boards get recomposed photos (D51) | frame size at another aspect: every generated clip (S2V, whole-frame), an S2V clip's keyed frames and every segment; an idle doll's pinned loop and its keyed frames are reused (sprites the layout places, story 426); a set loop of the old aspect is refused (`layered.unsupported`). At the same aspect: segments only. Drive tracks reused. fps: both kinds deliver 24 fps (P-20), so another fps is refused | the same | picture only |

"Picture only" means the film picture, the master, the proxy and the checks rebuild,
and the mix keeps its key: it has no picture input. Story 380's tests assert the keys
of every row.

Two consequences of the merged keys are open for the contract owner: a voice edit that
keeps a spoken whole-frame board's frames re-encodes its segment, whose picture cannot
change (it costs no GPU), because that segment carries the voice inputs; and a frame size
change at the same aspect keeps the layout preset's pixel values (each doll's height and
bottom; only `x` is a fraction), which carry no frame size, so the layered renderer would
draw the dolls at the old scale.

**A layered board's photo is derived (D51; coordinator's reading of Tom's answer to
Q-03).** For a layered board the reference photo is the deterministic composite of the
build's own layers, composed from the same inputs the build places: the set, the
board's cast stills in its layout, and the framing (`poc/keyframes.py` composed the E0
keyframes from the set still, the placed cutouts, the foreground and the camera
framing). It is made by no image model, costs no GPU and is never a build input. So
when a cast still version, the set or the layout changes, the photo of every layered
board that uses it becomes `stale` and a new photo version is composed from the new
inputs; the old version stays (D15). No picture key changes because of the photo
itself: the edit already changed the segments of the boards it touches. The exact
composite inputs are stories [426](https://work.haynesnetwork.com/work_packages/426) and
[407](https://work.haynesnetwork.com/work_packages/407)'s, which build it as a
requirement, with no preview-only phase. Prompt-generated photos are for whole-frame
boards, where the photo is the I2V start image.

The historical target "under two minutes on two threads" is not part of this contract.
Layered v2 took 408 s on the 24-vCPU worker; story
[428](https://work.haynesnetwork.com/work_packages/428) records real timings (review H3).

## 5. Method capability matrix

A method is exactly one layer (`layered`, `whole_frame`) and one motion (`s2v`, `i2v`)
(D38). Defaults: a board with lines gets `s2v`, without lines `i2v` (D38); the layer
default comes from the format, and for the doll format it is `layered` (D23, D24). With no
format, `layered` (P-08). Machine form:
[`method-capabilities.json`](examples/valid/method-capabilities.json).

| Layer \ motion | `s2v` | `i2v` |
|---|---|---|
| `layered` | **Buildable.** Evidence: the full layered S2V film, 11 S2V clips over layered 5B clips ([findings-s2v.md](../../titles/the-winter-menu/video-e0/findings-s2v.md)); Tom's verdict, D24. Profile: Wan2.2 S2V-14B fp8 + wav2vec2, lightx2v 4-step LoRA, cfg 1, one 3090, 16 fps, 576x1024, 77-frame chunks. Adapter: [426](https://work.haynesnetwork.com/work_packages/426). | **Buildable.** Evidence: layered films v1 and v2 ([findings-layered.md](../../titles/the-winter-menu/video-e0/findings-layered.md)); Tom's verdict, D23. Profile: Wan2.2 TI2V-5B, 121 frames, 24 fps, 576x1024, doll on green, keyed, with decal. Adapter: 426. |
| `whole_frame` | **Unavailable.** See below. | **Buildable.** Evidence: the 15-clip whole-frame film ([findings.md](../../titles/the-winter-menu/video-e0/findings.md)); D22: not rejected. Known drift in groups and three-quarter poses; chaining compounds it. Adapter: [427](https://work.haynesnetwork.com/work_packages/427): chains of at most 3 clips, no stretch (TIME-8). |

How each buildable cell uses its inputs:

- **Layered + S2V:** every on-screen speaker gets one S2V layer from her drive track
  (TIME-9). The build makes it from her cast still's loop: the loop's start image is the
  clip's start image, and the clip is keyed with the loop's keying, protect boxes
  included, and gated at the default floor 0.8 (Q-426-1, the contract owner); her loop
  must be the S2V profile's size, since its boxes are in its pixels. A library timed clip
  of her still is used instead only when it was made from this board's own drive track
  with the board's `s2v:<slot>` seed (Q-426-2, the contract owner); otherwise the build
  makes a new one. Every other cast member plays her pinned doll loop (a library `motion`
  asset, TIME-8a). The set is the story's pinned set loop, else the one promoted loop of
  the set still, else the static plate. Seeds `s2v:<slot>`.
- **Layered + I2V:** every cast member plays her pinned doll loop; talk bounce comes from
  the board voice envelope (Legacy `edit.motion`).
- **Layered, either motion:** every cast entry needs a loop, a speaker's included, or the
  board is refused (`motion.clip_absent`). A loop is made by an explicit asset job
  before Build, as voices are (P-12); Build never generates one (Q-457-1, the contract
  owner). Every doll, a speaker's S2V layer included, gets the idle wobble, the talk
  bounce and its moves, as in the PoC's S2V film; the contract owner kept this, and Tom
  sees it at the demo.
- **Whole-frame + I2V:** the start image is the board's current photo version
  (`photo.absent` without one). Seed `i2v:frame`; clip *k* of a chain uses seed
  `i2v:frame + k` and starts on clip *k - 1*'s last frame (TIME-8, P-36). Move and camera
  cues are refused (`wholeframe.unsupported`; for camera cues, Q-427-1).
- **Layered, either motion:** the board's photo is the composite of these layers (D51,
  [section 4](#4-cache-clocks-and-invalidation)); the build never reads it. Story 426
  composes it from named inputs: the set still, the board's cast stills in draw order,
  the layout preset's values, the foreground edge when the board shows it, and the
  framing at the last camera cue's end (`zoom_to`, `center_px`); a PNG at the frame size
  with no metadata, from no image model, clip or motion record. A note or a seed changes
  neither the photo nor its input signature, which story 407 compares for `photo_state:
  stale` (P-39).

**Whole-frame + S2V, reconciled.** `findings.md` records one whole-frame S2V clip
(`s2-s2v-b`: the shot-2 keyframe with set, one doll, 20-step path on both GPUs, 49 frames,
724 s), and it was the only S2V clip that existed when Tom said "speech-to-video looked
great" (D22, 2026-11-03; the layered S2V film came on 2026-11-04). The review
(H4) and story 427 treat the combination as unproved. Both hold: E0 showed the model can
animate a whole frame from speech once, but never assembled one into a delivered film,
never ran it on the lightning profile now used for S2V, and left open what drives a frame
with several speakers. So the cell is a known, valid design that has no adapter:
`unavailable`, not `invalid`. A board may save it (with a warning); `queue_run` refuses it
(`method.unavailable`). It becomes buildable only through a story with its own evidence.

Validation:

| Code | Status | Rule | Source |
|---|---|---|---|
| `method.unknown` | invalid | layer or motion outside the two lists (`rigid_cutout` only on imported runs) | D38, D6 |
| `method.s2v_needs_line` | invalid | S2V on a board with no lines | D38 |
| `method.s2v_needs_onscreen_speaker` | invalid | S2V where no line's speaker is a cast slot placed on the board (for example all narrator) | P-08 |
| `method.layered_needs_cast` | invalid | layered with an empty `cast`; use whole-frame I2V for an empty set | P-08 |
| `method.unavailable` | unavailable | whole-frame + S2V; saved with a warning, refused at Build | this section |
| `asset.capability_mismatch` | invalid | a layered cast entry whose version lacks `rgba_cutout` or `keyed_layer`; a cast entry's motion pin that is not a `motion_clip` (story 457) | review M6 |

"Invalid" fails on write and needs the board changed. "Unavailable" is a valid design
the studio cannot build yet.

**Adapters as built.** Both are source and tested with fake clip sources only; no GPU or
service was called, and no claim is made about picture quality.

- **Whole-frame I2V** (story [427](https://work.haynesnetwork.com/work_packages/427),
  [reference](../reference/whole-frame-adapter.md)): the chain policy of TIME-8 (P-36). A
  clip of the board's size is used as is, one of the same aspect is scaled with
  Pillow's Lanczos as E0's assembler did, and any other aspect is refused; nothing is
  cropped or padded. The renderer accepts a spoken board's voice envelope and who speaks
  when and draws nothing from them: whole-frame I2V has no talk bounce. Codes:
  `wholeframe.unsupported` (an input, cue, profile or aspect it does not draw, a layered
  board), `wholeframe.chain_limit` (more than 3 clips), `wholeframe.clip_invalid` (a
  source's answer that is not what was asked: extra frames, an undecodable clip, another
  size, seed, length or start image, incomplete provenance); a stored clip that is
  missing, short or undecodable is `time.source_short`.
- **Layered S2V and I2V** (story [426](https://work.haynesnetwork.com/work_packages/426),
  [reference](../reference/layered-adapter.md)): a port of `poc/layered_film.py`,
  `poc/cutout.py`, `poc/decal.py` and `poc/keyframes.py`, on the board clock (P-06); the
  PoC's film-clock loops and its held last frame are not ported. Keyed frames come from
  the pinned record's keying (key thresholds `{lo, hi}`, protect boxes, decal box and
  version `erase-v2`), with OpenCV at 2 threads. The **decal gate is a check**, not part
  of the key: the floor is the layer record's `decal_min_ecc`, else 0.8, applied on every
  use over the source frames the board shows; a track below it fails the segment before
  any frame (`layered.decal_weak`) with its check result `layered.decal_gate`, and the
  weak artifact stays cached but is never drawn. A library clip's record may carry its
  own lower floor (`decal_min_ecc`), as six E0 speech clips did. Codes:
  `layered.unsupported`, `layered.layout_invalid` (a slot the preset does not place, a
  crop outside 0..1, a doll more than 240 px off the frame), `layered.drive_invalid`,
  `layered.clip_invalid` (a source's answer or a stored artifact that is not as asked),
  `layered.decal_weak`.
- **The off-frame limit on keyed frames (Q-428-2; the contract owner's decision, a
  proposal Tom may overrule).** The port applies `poc/edit.py`'s 240 px limit for still
  cutouts to keyed frames too (`layered.layout_invalid`); E0's layered film had no such
  limit. It stays for E1. In the first live build r4's `closeup` preset put D 9 px past
  it on board 7, so the demo's draft moved that slot's `x` from 0.56 to 0.55 (11 px; only
  board 7 uses the preset). The limit is revisited with the layout editor. Rejected: no
  limit for keyed frames, as E0's film had.
- **A weak lettering track on a clip the build made (Q-428-3; the contract owner's
  decision, a proposal Tom may overrule).** It is answered by a re-roll: a draft seed
  edit gives a new clip under a new key, and the weak clip stays in the store. No agent
  lowers a floor. A person's override stays `record_check_override` (stories
  [410](https://work.haynesnetwork.com/work_packages/410) and
  [450](https://work.haynesnetwork.com/work_packages/450)), and the command line has no
  override path. In the first live build the gate refused 3 of 14 clips at 0.8 (board 1
  twice, board 9 once), the same two boards E0's own clips failed; the re-rolls cost 21.3
  GPU minutes. Whether the build should re-roll by itself is Q-428-5, open for Tom.
- Each adapter's `check_board` reports its refusals before any clip is made (the frame
  and S2V sizes included for layered boards); story 406 runs it at `queue_run`. Until
  then a whole-frame board with a camera cue fails at render, after its clips were made,
  and they stay cached for the corrected board.

## 6. Direction and executable cues

| | Note (direction) | Cue (executable) |
|---|---|---|
| Shape | `{id, text}`; text 1 to 200 characters, NFC, no control characters (mockup limit) | Typed object, validated per type |
| Who edits | People and agents (D35, D38) | People and agents |
| Read by the renderer | Never | Always |
| Cache input | No; a note edit invalidates nothing | Yes |
| Interpretation | None. Never executed, templated, parsed into commands or fetched | Exactly its fields |

Cue types (P-09):

| Type | Where | Fields |
|---|---|---|
| `sound` | board | `asset_version_id` (kind `sound`), `anchor`, `trim_ms [from, to]`, `level_rms_dbfs` (target RMS after trim, Legacy `edit.audio`) |
| `move` | board | `slot`, `anchor`, `duration_ms` (0 = instant), `dx_px`, `dy_px`, `angle_deg`, `steps` (legacy 3 held steps) |
| `camera` | board | `anchor`, `duration_ms`, `zoom_from`, `zoom_to`, `center_px [x, y]`, `easing` (`ease_out_cubic`) |
| `bed` | story | `asset_version_id`, `level_rms_dbfs`, `clock: film` |

- Mixer behaviour is part of the mixer's version (a cache input), Legacy `edit.audio`:
  sound cues fade in over 10 ms and out over 50 ms; a bed loops with 1 s crossfades and
  fades in over 0.5 s; lines fade 5 ms at each edge. As built (story 841, all linear
  fades): the limiter's look-ahead delay is compensated, which legacy left in (its
  masters' sound ran 95 samples, 1.98 ms, late); a sound past the film's end is cut at
  the last sample (TIME-10); a line's level and fades apply to its span, so the fade out
  ends at the span's end, up to 23 samples (24 kHz) after a take that is not a whole ms;
  a sound shorter than its 50 ms fade out, a bed of 2 s or less and a fade under 1 ms are
  refused (`mix.input_invalid`); a silent programme gets no loudness gain (P-38).
- An anchor is `{at_ms}` from board start, or `{after_line_id, offset_ms}`; the line must
  be on the same board (`cue.anchor_line_missing`), and the resolved start must lie inside
  the board (`cue.out_of_range`, TIME-10). A `move` names a slot placed on the board
  (`cue.slot_not_on_board`). Legacy line indexes become line IDs
  on import. Moves add up in order, as in Legacy `edit.motion`.
- Picture cues as the renderers draw them: the layered renderer draws moves and at most
  one camera cue per board, each starting at its resolved anchor (the PoC's camera
  started at the shot's first frame), with exact pose times; a second camera cue is
  `layered.unsupported` (P-39). A whole-frame board's move or camera cue is refused
  (`wholeframe.unsupported`): camera cues there are refused for now and drawn once the
  layered camera code is shared (Q-427-1, the contract owner).
- An unknown type is rejected, never ignored (`cue.type_unknown`). A note carrying cue
  fields is rejected (`note.text_only`).
- An agent may read notes and propose cues as an ordinary board patch (D40); the cue is
  then visible and editable like any other.
- Prompts (photo prompt up to 1800 characters, per the mockup; motion prompts) are opaque
  model inputs: cache inputs, passed as data, never a shell, template or URL.
- Words like "approved" in a note have no effect; approval is a record
  ([section 11](#11-go-live-approval-identity-boundary-only)).
- The mockup's cue strings ("Sting · slow push-in") are notes. The legacy importer
  produces real cues from `sfx`, `moves` and `camera`.

## 7. Provenance, licences and public credits

### Asset versions

`provenance` on every asset version
([cast](examples/valid/asset-version-cast.json),
[external photo](examples/valid/asset-version-photo-external.json)):

| Field | Content |
|---|---|
| `origin` | `generated`, `uploaded`, `imported`, `declared` (definition-only, such as a stock voice) or `derived` |
| `generator` | `role` (`image`, `video`, `voice`, `sound`, `writer`, `composite`), `engine`, `model`, `files_sha256` (model weight digests), `workflow_sha256`, `seed`, `prompt` or `prompt_ref`, `params`, `source_asset_version_ids`, `engine_job_id`, `hardware` |
| `external` | null, or for an agent upload (D42): `externally_generated: true`, `agent {key_id, session, harness}`, `paid_api: false`, `declared_by`, `server_computed_sha256: true` |
| `created_by`, `created_at` | principal and time |

An upload without the external marker, agent, model or prompt fails
(`prov.external_incomplete`). The studio holds no paid API key (D42).

### Licences

Every asset version, every run engine and every engine file has a `licence` object, even when unchecked
(`prov.licence_missing`): `name` (SPDX or vendor), `url`, `commercial_use` (`allowed`,
`conditional`, `noncommercial` or `unknown`), `attribution_required`, `checked_at`,
`checked_by`, `note`. A licence moves from `unknown` to a checked value by an appended
record; content and provenance never change. The terms of every engine and model file
the studio uses are in the licence register,
[`model-licences.json`](../reference/model-licences.json) with
[its page](../reference/model-licences.md) (story 809, checked 2026-11-13, D48); a
version, engine or file takes its licence object from there, and the examples do. A
licence object records the model's terms for what it makes, not the studio's own rights,
which are reserved ([RIGHTS.md](../../RIGHTS.md)).

- **What a licence blocks: nothing, while the use is research and personal (D49, Q-01
  answered 2026-11-13).** Licence values are recorded as facts. No value blocks Build,
  a run or a private delivery. *Coordinator's reading:* a go-live is not blocked by a
  licence value either, but it still needs Tom's own approval
  ([section 11](#11-go-live-approval-identity-boundary-only)), and the release checks
  show him the recorded terms at that point. If commercial use is ever planned, the
  question reopens before any such release, and the register says which engines it
  touches.
- **`conditional` (P-23).** A term that allows commercial use only under conditions
  (registration, a revenue limit; Stable Audio 3) is `conditional`, with the conditions
  in `note`. A research- or evaluation-only term (Qwen-Image 2.1, ControlFoley's CLIP
  encoder) is `noncommercial`, with a note that it is narrower. The asset-version schema
  accepts `conditional` since story 849: it is a checked value, like `allowed` and
  `noncommercial` (`name`, `checked_at`, `checked_by`), and needs a non-null `note`
  with its conditions (P-40). The register's licence object for such a term still says
  `unknown`, as recorded at its check; the library's lookup gives `conditional` for an
  entry whose `outputs_commercial_use` is `conditional` and whose object says
  `unknown`, keeping the note word for word, so the Winter Menu's sound versions now read
  `conditional` (story 849).
- **`checked_by`** is a principal. An agent that checked terms in its own session names
  itself as an agent-session principal (P-24, section 2).

### Runs

`provenance` on every run ([example](examples/valid/run-succeeded.json)):

- `toolchain`: studio commit, image digests, Python version, ffmpeg version and build,
  adapter versions. A service adapter's version is its pin set: the SHA-256 of each
  pinned snippet and graph it sends ([legacy adapters](../reference/legacy-adapters.md)).
  A service call fails with a coded error whose message keeps only a redacted stderr
  tail (story [425](https://work.haynesnetwork.com/work_packages/425)):
  `adapter.request_invalid` (a field refused before anything runs),
  `adapter.pin_mismatch` (a changed snippet or graph, never sent),
  `adapter.command_failed`, `adapter.timeout`, `adapter.response_invalid`,
  `adapter.not_found` and `adapter.busy` (a second call in one process, or a ComfyUI
  prompt that may still be in flight: do not resubmit). The Wan clip client (story 842,
  section 8) adds `adapter.job_failed` (a job that ended other than `succeeded`),
  `adapter.competing_work` (foreign engine work seen) and `adapter.journal_failed` (its
  journal could not be read exactly or written); the private import's volume reads
  (story 846, section 9) add the nine `adapter.source_*` refusals and
  `adapter.volume_unexpected`.
- `engines[]`: `key`, `role`, `name`, `files[]` (each `name`, `sha256`, `licence`),
  `licence` (the most restrictive of its files), `profile`, `hardware`.
- Every generated clip records `engine`, `engine_job_id` and `files_sha256` (at least one
  model file, each by SHA-256) from the engine's own record (the Wan ledger), never from
  configuration; a clip without them is refused (`wholeframe.clip_invalid`,
  `layered.clip_invalid`). The whole-frame clip set and the S2V provenance record carry
  them per clip (stories 427 and 426, section 4).
- `inputs_externally_generated`: asset versions with the D42 marker, for the E9
  disclosure check.
- `usage`: frontier tokens recorded per production (D8, D40); `null` means unknown,
  never zero.
- `public`: `ai_generated: true` always (D43) and `credits[]` of `{engine_key, text}`,
  where each `engine_key` names an engine with role `video`, `voice` or `sound` and the
  text names it and the hardware it ran on (D44: "the local video and
  voice models and the 3090s"). Image, writer and composite engines, and people, never
  appear (`credit.outside_video_sound`); they stay in private provenance (review C3).
- **As built (story 406).** A build matches each engine to the licence register by the
  clip profile's model and the file names the engine reports, or by the generator's
  recorded model name; an engine with no entry is `unregistered-...` with an `unknown`
  licence and the reason. An engine's licence is the most restrictive of its entry and
  its files, in the order `noncommercial`, `unknown`, `conditional`, `allowed`. The run
  schema accepts a null licence for a `writer` engine only, as the
  [run example](examples/valid/run-succeeded.json)'s frontier agent has, where this
  section says every run engine has one (P-42). A credit reads `<Video|Voices|Sound>:
  <engine name>`, with `on <hardware>` only when the engine reported its hardware: the
  register holds no public hardware label, so D44's "the 3090s" is not in a credit yet.
  Files are matched by the names the engine reports: the Wan client reports its graph's
  model files with the register's SHA-256, not re-hashed on the volume (story 842), and
  the whole Wan record is kept on each clip's provenance as `extra.wan` (story 851). A
  file the graphs of two engines load has one register entry per engine with the same
  facts (story 860, P-47): the speech-to-video graph also loads the umT5 text encoder,
  which the register listed only under image-to-video, so story 428's records read the
  `wan-s2v` engine as `unknown`, as they were written; the next run reads it `allowed`.

Media on NFS is not backed up (D47). Provenance in Postgres must therefore be complete
enough to regenerate: inputs by hash, prompts, seeds, model digests and profiles. A
regenerated artifact is a new version with a new hash (GPU output is not bit-exact);
nothing silently repoints a lost hash. The Winter Menu's fire bed, which the PoC never
copied to the Wan volume, is made again by the in-cluster sound model as a new `sound`
version; its old hash stays as recorded (D54).

## 8. Runs, deliveries and the store

### Runs (D30)

- `queue_run` takes the story's `revision` (stale: `conflict.revision`) and an
  `Idempotency-Key`. Preconditions:
  every spoken board has a current voice (`voice.absent`, `voice.stale`); every
  whole-frame board has a current photo (`photo.absent`); no board method is invalid or
  unavailable; no voice or photo job is in flight for an included board
  (`asset.generating`).
- Before its first renderer call a build runs the pre-build check (story
  [379](https://work.haynesnetwork.com/work_packages/379),
  [reference](../reference/store-and-stages.md)): the `queue_run` validation, then every
  referenced asset version resolved by the library (`asset.unresolved`) and every blob
  the build reads at a valid locator in the library or the story's own production
  (`store.locator_invalid`), present (`store.blob_missing`) and re-hashed
  (`store.hash_mismatch`). Only the story's cast and narrator voices resolve without
  bytes. Each problem names the board, its display code, the legacy shot and the field.
  As built by story 406, the check also runs each board's adapter check
  (`wholeframe.check_board`; `layered.check_board` with the frame and S2V sizes and the
  motion resolver's problems), takes the cast entry's motion pin as a reference, and
  builds its voice facts naming the current engine, so a voice signed with another is
  `voice.stale` (VOICE-9). A story whose references cannot be pinned makes no run; every
  other refusal is a `failed` run, before any clip.
- The snapshot is the story and its boards by value plus every resolved asset version,
  pinned by content hash, or by `definition_signature` for definition-only versions
  (`voice`), or by `input_signature` and take hashes for `board_voice` versions. It holds
  no run ID or time, so the same draft always gives the same hash. It is stored as a
  canonical-JSON blob ([run-snapshot.json](examples/valid/run-snapshot.json);
  the file is pretty-printed, its hash is over the canonical form). The run row stores the
  blob's `sha256`. Draft edits never change a queued, running or finished run. As built
  (`studio.run-snapshot/v1`, story 406): the boards carry no `derived` block, the motion
  loops the resolver chose are pinned too (a loop found by search is an input), and
  `toolchain_request.studio` is recorded. A library timed clip is chosen during the plan,
  from the drive track the plan computes, so it is recorded in the run's board stage
  with its version ID, not in the snapshot.
- States: `queued` (with `wait_reason`: `lease_busy`, `gpu_unavailable` when talosw01 is
  down, D41) → `running` → `succeeded`, `failed` or `cancelled`. `held` is a safety stop
  (unknown work on the Wan lease, an ambiguous external job) that resumes only after
  reconciliation, never by blind resubmission (story
  [410](https://work.haynesnetwork.com/work_packages/410)). `imported` marks legacy runs.
  Terminal states are immutable. Every transition records time, actor and reason. As
  built: a build records `held` (from `running`, `finished_at` null) for **every**
  refusal of the Wan clip client, a busy lease and hot GPUs included (story 851), and
  nothing in the build moves a held run on; a later build is a new run. A service-phase
  run ends `cancelled` with reason "service phase complete", because a run is never
  `succeeded` without a delivery (Q-406-1, the contract owner); one whose transcript
  check failed ends `failed`. *Note for E3, not a decision:* the API (stories 410 and
  434) may instead requeue a run that never reached a submission (`queued`,
  `wait_reason: lease_busy`).
- An estimate comes back on queue, with a range, its basis and `uncertain: true` (D27).
- Check overrides (for example a decal min-ECC below 0.8 that looks right by eye, as in
  E0) go through `record_check_override` and are recorded per artifact with actor and
  reason, never silently; release checks cannot be overridden
  ([findings-layered.md](../../titles/the-winter-menu/video-e0/findings-layered.md)).
  The decal gate is the check `layered.decal_gate` (section 5); the layered renderer
  keeps its results in `renderer.checks` and does not commit them as stages, so story 406
  records them, and each renderer's `reports`, with the run; a reused segment's results
  are listed too (story 860). Neither the command line nor the API has the override yet,
  so a weak track on a clip the build made is re-rolled (Q-428-3, section 5).

### Builds (as built, story 406)

`studio build` ([reference](../reference/studio-build.md)) builds a story from its boards
on the local store. Story 428 ran the first live build
([below](#the-first-live-build-story-428)).

- **The run record** (`studio.run/v1`) holds the fields of the
  [examples](examples/valid/run-succeeded.json) plus `phase`, `transitions` (each status
  change with `from`, `to`, `at`, `by`, `reason`) and `error` (`code`, `message`,
  `board_id`, `board_number`, `stage`, and the pre-build or held problems). Each board's
  stage lists its method, frames, film start, clips (made or reused, each with its
  record's frames, fps, seed, engine, engine job, model files and trim, or a library
  version ID), segment and its key, compositor, every planned artifact with `made` and
  its seconds, the renderer's report and decal checks. The run's `checks` hold the seven
  sound checks, the transcript check and the delivery's frame count. On the local store
  each version of the run document is a completed stage (`run-0001` with the snapshot
  blob, `run-0002`, ...): a create-only name makes each write a compare-and-set, and a
  move another writer made first, or a write to a terminal run, is `run.transition`. The
  run `number` is one more than the production's runs (P-42). The `run` and
  `run-snapshot` examples validate.
- **Stopped runs and reused segments (story 860, P-47).** A run that stops (`failed`,
  `cancelled` or `held`) keeps the board stages it completed before the stop, each as a
  succeeded run lists it; a board whose segment was not answered is not listed. A board
  stage of a reused layered segment lists its decal gate results too, read from the
  keyed-frames records the cache holds at the floor the segment key holds: they are
  reported, and the gate is not run a second time, so only a segment rendered in the run
  can fail it. A run check may name its `slot` (an optional field of the run schema). Known
  limits: with `--workers N` a board after the failing one can be listed, when its
  segment was found cached or another worker rendered it; and a refused board's own
  finished work (story 428's board 1 keyed frames before `layered.decal_weak`) is in the
  store but in no stage, since the record has no place for a partial stage.
- **Order.** The pre-build check and the snapshot; the run `queued`, then `running`.
  Then a **local pass**: the whole story is planned with clip sources that only record
  what they would send, so every drive track is made, every speaker's library timed
  clip resolved, every seed checked and each clip request built and checked. Then, in a
  full build and the service phase, **the mix and its four mix checks**. Only then is a
  clip source asked, once per missing clip. An error in either pass fails the run with
  its own code and nothing has been asked of a clip source. Known limit: keying, the
  decal gate and renderer refusals need the clip or heavy CPU, so they can still stop a
  run after that board's clip was requested, as can the licence and credit parts of the
  success record.
- **Checks and delivery.** Every check passes before `deliver`, or the run fails with
  `build.check_failed` and nothing is delivered. The run is `succeeded` only after
  `read_delivery` re-reads a delivery holding the plan's master and frames
  (`build.delivery_unverified` otherwise). A failed run names any delivery it published;
  a failure the store cannot record is `build.run_unrecorded`, a non-zero exit, never
  success. `deliver` makes its own proxy, so the plan's proxy key names no cached
  artifact and an unchanged story's next run encodes its proxy again.
- **Phases.** `all` (no flag) makes everything and delivers. `--phase service` makes what
  needs a service: drive tracks, clips, the transcript check of a master the cache holds,
  and the mix with its checks; everything else is looked up, never made.
  `--offline` asks no service and uses no recognizer: a clip or transcript check missing
  from the cache is `build.offline_missing`. `--workers N` renders the missing segments in
  up to N processes, each at two threads; two workers give the same frames as one.
- **Where a live build runs (Q-406-2, the contract owner).** Until the NFS store adapter of
  story [434](https://work.haynesnetwork.com/work_packages/434), a live build runs its
  service phases from a session pod (which reaches Kokoro, Whisper and the Wan API) and
  its offline phase on `ai/studio-render`, with the store copied between them. The
  worker cannot run the package yet: on 2026-11-14 it ran Python 3.13 with media
  libraries outside the lock, and the keyer's and encoder's builds are key inputs. So
  story 428 ran its offline phase in the session pod at two threads under its work order,
  and the worker waits for a haynes-ops change
  ([862](https://work.haynesnetwork.com/work_packages/862)).
- **Live clip sources (story 851).** The service phase's clips come from the Wan clip
  client below, one per store root on the journal `<store root>/wan-journal.jsonl`,
  made on the first clip request. A job the journal holds is settled first: `recover` for
  the same request, `build.wan_unsettled` (held) for another. Every client refusal ends
  the run `held` and nothing more is sent. Each clip of a whole-frame chain is kept as
  soon as it is collected and checked (cache kind `wan_chain_clip`, keyed by the clip
  request), so a stopped or crashed chain is not rendered again from clip 0. A profile
  the client does not make is `build.live_unsupported` and a request it would refuse
  `adapter.request_invalid`, both before any clip. `--wan-story <tracker URL>` names the
  story the Wan ledger records each job under. `--dry-run` (service phase only) runs the
  local pass, the request checks and the mix, lists the clip jobs it would request with
  an estimate from E0's jobs of the same shape, contacts no service, and ends the run
  `cancelled`.

### The Wan clip client (as built, story 842)

`WanClipClient` ([reference](../reference/legacy-adapters.md)) makes Wan2.2 TI2V-5B
image-to-video clips (20 steps, 24 fps) and Wan2.2 S2V-14B speech-to-video clips on the
lightning profile (4-step LoRA, cfg 1, one GPU, 16 fps, chunks of 77 seeded `seed + k`).
It ports the sanctioned E0 route of `poc/wan.py` and `poc/s2v.py`: inside the Wan API
container a pinned snippet imports the installed `api` module and runs the API's own
`generate()`, so every job holds the API's compute lease (shared with the HTTP API and
the Foley sidecar), its watchdog, ledger and telemetry. The in-pod snippets are the
PoC's bytes; nothing is deployed or changed. Its guards, in order:

- pins and the graph checked before any command; one job per process (`adapter.busy`);
- nothing while the API is busy or holding, while the engine queue shows any work (both
  of its lists required), or while the two approved GPUs (by UUID) are not under 62 C and
  at most 5 % busy: waited for read-only up to 1800 s, and probed again just before
  submission; then the admission readback of `/health`, the lease (busy is a refusal,
  never a wait) and the API's own GPU and queue checks;
- inputs created once under `/workspace/input/studio-e0/<16 hex>`, never overwritten;
  engine reads retried read-only, a submission never;
- foreign engine work seen during a job latches a halt, extended and never replaced,
  until a person calls `clear_halt()` (`adapter.competing_work`; the checked clip is kept
  on the error);
- a job that did not succeed is `adapter.job_failed`; the clip is fetched read-only (a
  redirect refused), its hash and size checked against the pod's and the ledger's, and it
  must decode to exactly its frames and rate: an image-to-video clip its requested length
  at 24 fps, a speech-to-video clip TIME-9's fixed over-delivery at 16 fps, both at the
  requested size (`adapter.response_invalid` otherwise);
- no snippet deletes, moves, interrupts or overwrites anything. The installed
  `generate()` removes or interrupts its own prompt when its own job fails; that is the
  API's behaviour, unchanged.

**The journal.** The client requires one: an append-only JSON-lines file, opened with a
`created` line and never rewritten, truncated or deleted, held for a whole `render` or
`recover` by a lock on its `.lock` sibling and on the journal file itself. A job is
journalled before the first probe and blocks every later call, in any process on that
journal, until it is settled: its ledger reads `failed` (and, if its prompt was
accepted, a probe shows the engine queue empty), its clip is fetched and checked, a
refusal certainly submitted nothing, or a person calls `clear_in_flight()` after checking
the service. A lost answer is never resubmitted. A journal that is missing beside its lock
file, empty, headerless or replaced during a call is `adapter.journal_failed`, and nothing
more is probed, uploaded or submitted. **What it protects against:** forgetting, after a
crash, a timeout, a lost answer, a restarted build, a second process, or a second name for
the same file. **What it does not:** tampering. Whoever can write in the run directory can
already clear it with `clear_in_flight()`, and overwriting it with another valid journal is
the same act by other means, which the client does not detect. What holds without the
journal: the client never submits while the API is busy or holding, while the engine queue
shows work, or while the GPUs are not cool and idle, and the API's own compute lock inside
`generate()` still lets one job run at a time. Known limits: a client given another
journal path cannot see the first (builds use one per store root; a lease across agents is
dev-env work, [839](https://work.haynesnetwork.com/work_packages/839)); heat that starts
inside `generate()` is not seen, since the ported snippet stays the PoC's bytes.

**`recover(request, job_id)`** collects a finished job's clip after a lost answer or a
failed fetch, read-only, never a second render. The ledger must be this request's job:
the job carries the `graph_sha256` of the graph it ran (a difference from the PoC's job),
and its story, preset, seed and input names and hashes must match. E0 ledgers have no
`graph_sha256` and are refused; their clips come in through the private import
(section 9). The record says `recovered: true`.

### The first live build (story 428)

Story [428](https://work.haynesnetwork.com/work_packages/428) built The Winter Menu on
2026-11-14 with the studio's own code, privately, from the command line, on the two
3090s ([run log](../../titles/the-winter-menu/e1-build/run-log.md)). An agent session
ran it for the coordinator, each GPU step after a written go. **State: delivered
privately; not accepted; Tom's verdict is pending.**

- **Inputs.** `studio legacy import` of r4, then the private import read-only: 132 rows
  verified, 24 absent, 0 mismatch; 79 hashes read from the Wan volume, 105 MB, each from
  its first source. All 482 earlier files on the volume hashed the same afterwards. The
  new fire bed (D54), one sound-model job, is byte-identical to the r4 bed and was
  imported as a new version with its own provenance. `studio voice` made the 8 board
  voices with no speech request: every take was held. The draft used E0's seeds, as no
  server assigns seeds yet; no E0 clip could be reused, as E0's drive tracks are 48 kHz
  and the build's are 24 kHz.
- **Clips.** 14 speech-to-video clips (11, then 3 re-rolls), one at a time through the
  Wan clip client and the API's lease: each 576x1024 at a measured 16 fps with TIME-9's
  over-delivery. **125.5 GPU minutes** of 150 (the clips' wall time, cool waits
  included). No refusal, no held run, nothing resubmitted; the journal ends with every
  job settled and no halt. Each job ran on one card while the other idled, and a job that
  followed a hot one first waited 84 to 146 s for its card to cool under 62 C.
- **Picture.** The offline phase ran in the session pod (see above). It refused three
  boards: boards 1 and 9 `layered.decal_weak`, board 7 `layered.layout_invalid`. Under the
  contract owner's answers (Q-428-2, Q-428-3, section 5) the draft moved board 7's
  close-up by 11 px and re-rolled board 1 (seed 610, still weak, then 611) and board 9
  (seed 620); all nine boards then passed.
- **Delivery.** The transcript check passed with the story's tolerances. Run
  `run_01M7C56SZ6TAHTJSW413RFZYQP` `succeeded` with delivery
  `dlv_01M7C576EAX9NY1S0JHFYW2QQS`: 1087 frames, a master of 60 562 847 bytes and a phone
  proxy of 12 986 068 bytes, both re-read. For private viewing a one-off driver over
  `poc/deliver.py`'s route copied the master, proxy, delivery document and run record
  create-only onto the Wan volume and linked one ledger,
  `d009d61541774a429fcabfeedadd8b51` (home network only). The driver is held in PR 70,
  and a studio command for this is story
  [863](https://work.haynesnetwork.com/work_packages/863).
- **One edit.** The board 8 gavel cue went from -20 to -23 dBFS RMS. The next build, run
  `run_01M7C5CJA7XKBCRPM0ZRP2P5RS` (`succeeded`), made the mix and its checks, the master
  and its checks, the transcript check, the proxy and the delivery, and no clip, drive
  track, keyed frame, segment or film picture: the section 4 row "Sound cue, bed, level,
  loudness target", as built.
- **Differences from r4 and E0** that Tom weighs with his verdict: one speech prompt for
  every doll where E0 described each doll in her own (Q-428-4), board 7's close-up moved
  11 px, board 1's clip from seed 611 and board 9's from seed 620.
- **Heat.** The working card peaked at 87 to 89 C in every job, 89 C in 8 of the 14;
  E0's recorded range was 84 to 88 C. **The practice (P-49; the contract owner's, a
  proposal Tom may overrule):** the coordinator sets no temperature stop line of its own
  in GPU work orders; each job's peak is recorded, and the guards are the API's lease,
  the client's cool-idle start check and the unknown-work checks. The 88 C line set during
  story 428 was the coordinator's own caution, not a platform limit. The recorded reason
  is a relayed message (story 428, comment 8409): a message from session
  `haynes-ops-1111-144013` whose text says it relays Tom's word, through Meatball, that
  89 C is acceptable. The coordinator could not verify who sent it and did not hear Tom,
  so it is not Tom's ruling and has no D-number. Confirming it is Q-428-6, open for Tom.

### Mix, master and sound checks (as built, story 841)

[Reference](../reference/studio-mix.md). Source and tested with synthetic audio and
picture only.

- The mix is a pure function of the mix key document and the bytes its hashes name:
  48 000 Hz stereo 24-bit PCM of exactly `frames x 2000` samples, kept as float32 until
  one 24-bit quantization (no 16-bit premaster). Each line is cut from its board voice
  track at its span, resampled to exactly `(end_ms - start_ms) * 48` samples, leveled
  and faded (section 6, VOICE-7) and placed by TIME-7; then the headroom step (a peak
  over 0.5 scales the mix to 0.5), loudness by libavfilter `ebur128` (BS.1770 gated) and
  `alimiter` at `10^((true_peak_dbtp - 1) / 20)`, delay compensated. A true-peak target
  whose limit falls outside the limiter's 0.0625 to 1 (below about -23.1 dBTP) is
  `mix.input_invalid`. Filters run at 2 threads.
- The **placement record** (`studio.mix-placement/v1`, cache kind `mix_placement`) says
  what went where, in samples and board-clock ms, with hashes, gains, cuts, the headroom
  step, the measured loudness and the master gain. It holds no identifiers;
  `label_placement` adds the run's board, line, cue and bed IDs.
- The **master** stream-copies the film picture's H.264 packets and encodes the mix as
  AAC-LC stereo, 48 kHz, 192 kbit/s, with `+faststart` and an MP4 movie timescale of
  48 000, so its recorded audio is exactly `frames x 2000` (TIME-11). It is checked with
  story 381's `inspect` at the picture's size before it is cached; a mix of the wrong
  length is `time.conservation`, another failure `mix.master_invalid`.
- Seven **sound checks**, each a check result (`studio.check-result/v1`) keyed by
  `check_result_key`, version `1/<filter build>`. These are check names, not rule codes.
  A failing check is data; `FilmSound.ensure_passed()` raises `mix.check_failed` naming
  each one.

| Check | On | Passes when |
|---|---|---|
| `mix.length` | mix | 48 000 Hz, 2 channels, 24-bit, exactly `frames x 2000` samples |
| `mix.loudness`, `master.loudness` | mix, decoded master | integrated loudness within 1.5 LU of the story's `master_lufs` (legacy `validate`) |
| `mix.true_peak`, `master.true_peak` | mix, decoded master | true peak at most `true_peak_dbtp + 1` dBTP, read with 200 ms of silence after the programme (legacy: an absolute -2.5 at r4's -3.5; relative here, P-38) |
| `mix.clipping`, `master.clipping` | mix, decoded master | no sample at full scale (legacy `validate`) |

- The sound checks' thresholds depend on the story, so they are not in the toolchain's
  `checks`; `film_sound` keys them. A run takes `sound_toolchain(toolchain)`, which names
  this mixer and mux: story 380's `Toolchain` defaults for both are placeholders the
  builder refuses (`cache.entry_invalid`). Story 406 wires both calls.

### Deliveries

`studio.delivery/v1` ([new](examples/valid/delivery.json),
[legacy r4](examples/valid/delivery-legacy-r4.json)): master (H.264 `yuv420p` and AAC
48 kHz in MP4, one video and one audio stream, the media kind's frame size at 24 fps) and
phone proxy (H.264, 720x1280 for `short`, 1280x720 for `video`), each with `sha256`,
`bytes`, `frames`, codecs and `locator`, plus `verification` (decoded frames equal
expected, hashes re-read). The proxy's decoded frames are its `frames`, which must equal
the master's.

- **Proxy size (P-10, amended by the contract owner on 2026-11-13, Q-381-01).** A proxy
  is strictly under `25 000 000 × max(frames, 1440) div 1440` bytes: 25 000 000 bytes per
  minute of film, and never less than 25 000 000. The proxy encoder (libx264 `veryfast`,
  CRF 23 capped at 2 500 kbit/s, AAC-LC 128 kbit/s, MP4 movie timescale 48 000 since
  story 857, TIME-11) keeps any picture inside it. Whether
  the proxy's picture is good enough on a phone is story 381's Q-381-02, answered when
  Tom watches the first real delivery at the demo (the coordinator's review of PR 51).
- **As built (story [381](https://work.haynesnetwork.com/work_packages/381),
  [reference](../reference/studio-delivery.md)).** `deliver` decodes every frame of the
  master and the proxy and checks them before anything is written; it then publishes
  master, proxy and the delivery document (a canonical-JSON blob) and completes one
  stage `delivery` listing all three. One delivery per run: the same master again
  returns the delivery unchanged, another master is `store.collision`. Codes:
  `delivery.master_invalid` (the master failed a check; nothing written),
  `delivery.proxy_invalid`, `delivery.master_changed`, `delivery.not_verified`,
  `delivery.record_invalid` and `delivery.legacy_mismatch`. Where the product keeps the
  delivery document (a Postgres row) is story 434's.
- **Legacy deliveries** use adapter `legacy_wan_ledger`, read-only: `writable: false`, no
  proxy, a `legacy_path` instead of a locator, and `verification.source`. The contract
  allows reading a ledger through the Wan API and reading ledger and asset files in place
  from the API container, after checking paths and hashes, with no write, rename or
  delete path. Story 381 built only the mapping of a recorded ledger and its evidence
  documents; it reads no file, and a legacy delivery's codecs come from the PoC's
  encoder settings (`poc/edit.py`), not a decode.

### Store layout (D39)

Root: the gasha01 share `hdd-nfs-repl/data/studio`, mounted at `/studio` on
studio-render. Media is addressed by content hash, one folder per production plus a
library folder (P-11):

```
<root>/library/sha256/<h[0:2]>/<h>.<ext>
<root>/productions/<production_id>/sha256/<h[0:2]>/<h>.<ext>
<root>/productions/<production_id>/records/<run_id>/<stage>.json   (local adapter only)
<root>/.staging/<random>.part
<root>/.probe/
```

`ext` is one of `mp4`, `wav`, `png`, `jpg`, `webp`, `json`, chosen from the validated media type.
A locator is the relative path; anything else, including `..` or an absolute path, fails
(`store.locator_invalid`). Duplicate bytes in two production folders are allowed.

### Atomic, create-only publication

Both adapters (`local` for the CLI and tests, `nfs` for the product) publish one file
like this:

1. Open `<root>/.staging/<random>.part` with `O_CREAT | O_EXCL`; stream the bytes while
   hashing.
2. `fsync`; check size and hash (and the expected hash, if the caller gave one).
3. `link()` the staging file to the final path. On `EEXIST`, re-hash the existing file:
   equal means success (idempotent retry); different fails with `store.collision` and
   overwrites nothing.
4. Unlink the staging file; `fsync` the directory (local adapter).

Never `rename()` over a path and never open a final path for writing. A multi-file stage
publishes all its blobs, then one completion record listing every hash (a Postgres row in
the product, a create-only `records/` JSON file in the local adapter). Readers trust only
completed stages. Blobs become durable before the row commits, so an orphan blob is
possible and harmless, and a row never points at a missing blob (story
[379](https://work.haynesnetwork.com/work_packages/379)).

The NFS adapter runs a probe in `.probe/` at startup (exclusive create, `link` with
`EEXIST`, `fsync`) and refuses to start if any fails; there is no rename fallback. NFS
throughput and contention with nas01 are unmeasured, so nothing assumes a figure; story
428 logs actual IO.

### Stage records and store codes (as built, story 379)

The local adapter's completion record is `studio.stage-record/v1`: canonical JSON of
exactly `schema`, `production_id`, `run_id`, `stage` and `blobs` (`name` to `sha256`,
`bytes`, `media_type`, `locator`), with no time and no writer, so a retried or
concurrent commit of the same outputs is an idempotent `EEXIST` and one with other
outputs is `store.collision` (P-28). It is a local-adapter file, not an API type; the
product's record is a Postgres row (story 434).

- Stage names are 1 to 128 of `A-Z a-z 0-9 _ -`; output names 1 to 128 of
  `A-Z a-z 0-9 _ . : -`; a stage has 1 to 256 outputs. Published files are mode 0444.
  The media type picks the extension (`video/mp4` mp4, `audio/wav` wav, `image/png`
  png, `image/jpeg` jpg, `image/webp` webp, `application/json` json); the store does not
  sniff bytes. A story reads blobs only from `library/` and its own production's folder.
- Codes: `store.hash_mismatch` (bytes are not the expected hash and size, or what a
  record names is not a regular file), `store.blob_missing` (no readable file where a
  record or story needs one), `store.record_invalid` (a malformed stage name, output set
  or record file) and `store.media_type_unsupported` (no extension for the media type).
- A symbolic link, folder, FIFO or socket at a final path is `store.collision`, and
  nothing is followed. Folders are made one at a time and the parent of each is
  `fsync`ed, including a folder another writer made; story 434 confirms how NFS honours
  a directory `fsync` before relying on that order.
- The store is not a security boundary against a process that can already write inside
  its root. It never publishes outside the root or over another file, and a reader that
  verifies gets the bytes a record names or an error. Three gaps stay open, as the
  [reference](../reference/store-and-stages.md) states under "What the store promises,
  and what it does not": a blob replaced during the last check before a record's link,
  the last `unlink` of a publication, and an existing final file whose outside names a
  writer hides around the link-count samples.

### No purge (D17)

Nothing deletes blobs, staging leftovers, runs or versions automatically. A
`store doctor` command may report orphans and staging leftovers; removing them is a
user action. Beside the D39 layout the store root holds two files of the Wan clip
client, `wan-journal.jsonl` and `wan-journal.jsonl.lock`; since story 860 the doctor
reports them under their own heading, `journal` (present or absent, kind and size, each
by one `lstat`), never as unexpected, and never opens, locks, moves or rewrites them. A
link or a folder under either name makes the report unclean (P-47). User deletion, when built, tombstones records; approved or published runs,
and every asset version their snapshots reference, cannot be tombstoned. Removing bytes is
out of scope for E1 to E3 (P-11). On the Wan PVC (`ai/wan-video`), legacy delivery
ledgers (`edited_production`) and `/workspace/output/productions/` are never written
(review H5). Engine jobs run through the Wan API's own `generate()` create their own
ledgers and outputs, and the clip client creates its inputs once under
`/workspace/input/studio-e0/` (story 842). The private import only reads the volume
(story 846).

## 9. The library and version IDs

- **Asset** (`ast_`): `kind`, `name`, `labels`, `attributes` (for example
  `character_slot`, `expression`), `scope` (`production_id`, or null for the global
  library). The library is scoped by labels (D16); labels are mutable metadata on the
  asset, outside version content (P-21).
- **Asset version** (`asv_`): `asset_id`, `number` (1, 2, ... per asset), `content`
  (`sha256`, `bytes`, `media_type`, size, `locator`, or null for definition-only kinds),
  `provenance`, `licence`, `capabilities`, `state`. Content, provenance and capabilities
  never change (D15).
- **Kinds:** `cast`, `costume`, `set`, `prop`, `sound`, `motion` (doll loops, set loops
  and timed speech-to-video clips made for one board), `voice` (a stock TTS voice; no
  bytes), `character_card` (reserved for E2), plus board-scoped `photo` and
  `board_voice`.
- **Capabilities:** `rgba_cutout`, `keyed_layer`, `mask`, `opaque_photo`, `opaque_plate`,
  `motion_clip`, `set_loop`, `tts_voice`, `sound_effect`, `sound_bed`, `board_voice`. An
  opaque photo is not a render-ready layer (review M6).
- **States:** `candidate` (generated, hidden from pickers), `promoted` (explicit and
  idempotent), `board` (board-scoped photo or voice). Promoting a board photo creates a
  library version with `origin: derived` that points at the board version: kind
  `photo`, production scope, state `promoted`, source key `promote:<board version ID>`,
  so a second promotion returns it. A board voice stays on its board
  (`asset.not_promotable`). Rejected candidates stay, hidden (D17).
- **Pinning:** boards and snapshots name asset version IDs, never "latest"; only pickers
  resolve "latest". The motion resolver (below) is where the merged code departs from
  this: a cast entry without a motion pin resolves to the one promoted loop of its still
  when the build plans, so promoting a second loop makes the board ambiguous
  (`motion.clip_ambiguous`) until it pins one. Whether the server writes the resolved pin
  onto the entry, as it writes missing seeds, is open for the contract owner.
- **Import:** keyed by `provenance.source_key`, one asset per key
  (`asset.source_key_required` without one). The same bytes with the same `source_key`
  return the existing version; changed bytes make the next `number`; bytes seen before
  return their old version. The same pin with other immutable fields is
  `idempotency.mismatch`, except that a measurement the existing version does not record
  (`bytes: null`, no `width` and `height`) matches any value. `content.bytes` may be null
  only on an `imported` version whose public records hold no byte count (the r4 fire
  bed).
- **Filters:** kind, labels, production, board. The board filter is the set of versions
  that board references (D32, D34).
- **As built (story [382](https://work.haynesnetwork.com/work_packages/382),
  [reference](../reference/studio-library.md)).** Examples:
  [asset](examples/valid/asset-cast.json),
  [asset version](examples/valid/asset-version-cast.json),
  [capability mismatch](examples/invalid/asset-capability-mismatch.json). Capabilities
  fit the kind and the media type, and an opaque photo or plate is never also a layer
  (`asset.capability_mismatch`; the table per kind is P-29). The resolver names every version a story or board
  references: `ref.unknown`, `asset.kind_mismatch` (a cast voice that is not a `voice`,
  a board cast entry that is not a `cast`, and so on), `asset.scope_mismatch` (another
  board's voice or photo, or another production's version), `asset.bytes_missing`. A
  version's locator is in its own production's folder or, for a global version,
  `library/`. Stock voices are the ones this repository records for their model, refused
  otherwise (`voice.not_stock`), with origin `declared`; auditioning another stock voice
  (D53) records it first.
- **Board voice bytes:** a `board_voice` version has no `content`. Its assembled
  `voice.track` has the content shape, locator included (null on a legacy import); its
  takes carry `sha256` only and are found by hash at
  `productions/<production_id>/sha256/<h[0:2]>/<h>.wav` (story 405). That is where the
  private import publishes legacy takes (story 846) and where `studio voice` reads them
  back (story 857); a take has no locator of its own.
- **Motion records (story [457](https://work.haynesnetwork.com/work_packages/457),
  [reference](../reference/motion-clips.md)).** A `motion` version may carry a `motion`
  block, immutable content like a board voice's `voice` block, allowed on no other kind
  (`schema.invalid` at `/motion`). It is optional, so older motion versions stay valid,
  but one without it cannot be played (`motion.record_missing`). Fields: `use` (`loop`,
  TIME-8a, or `timed`, made for one board's speech, TIME-8); `subject` (`doll`, keyed,
  capability `motion_clip`; or `set`, opaque, `set_loop`; never both); `still_sha256`
  (the cast still or set the clip stands in for, absent when no record ties it to one);
  `frames`, `fps`, `width`, `height`; `trim` (`{start, frames}`: a loop's `N`, or a timed
  clip's TIME-8 frames from 0); `playback` (fixed by use and trim); `source` (the image
  the engine animated, prompt, negative prompt, seed, profile, a timed clip's adapter,
  the engine job); a timed clip's `drive_track` (`{sha256, board_frames}`); a doll
  clip's `keying` (keyer, key thresholds, protect boxes, decal box and version, optional
  `decal_min_ecc`); `keys` (`clip`, `keyed`, `identity`, section 4); `note`. A loop's
  clip key is the doll clip row's; a timed clip's is the S2V clip key, since the loop key
  has no drive track. A version with a block **pins its identity**, not its bytes: the
  same record imported again is the same version, and the same clip keyed another way is
  the next version of its asset (P-37).
- **Board resolution.** A cast entry may pin its doll loop with the optional
  `motion_asset_version_id`; without a pin, the one promoted doll loop whose
  `still_sha256` is the entry's still, in the production or the global library. The set
  uses the story's `set.motion_asset_version_id`, else the one promoted set loop of the
  set still, else none: a static plate (P-37). Called on its own, the resolver skips a
  speaker on an S2V board; the layered adapter resolves every board as layered I2V, so
  every cast entry, a speaker's included, has its loop (P-39), and a speaker's timed clip
  comes from her drive track (section 5). A resolved clip is returned only without a
  blocking problem, so it is always playable. Codes, all
  `invalid`: `motion.record_missing`, `motion.clip_absent` (no pin and no promoted clip of
  that still), `motion.clip_ambiguous` (several), `motion.timed_not_loop` (a timed clip
  pinned where a loop plays), `motion.still_mismatch` (the pin stands in for another
  still), `motion.keying_missing` (a doll clip with no keying), `motion.identity_mismatch`
  (a recorded key the inputs do not give: a corrupt record), `motion.drive_track_mismatch`
  (a timed clip made for another board length); with `ref.unknown`,
  `asset.kind_mismatch`, `asset.scope_mismatch` (a pin of another production),
  `asset.capability_mismatch` (a set loop pinned for a doll or the reverse; story 404's
  validator reports it at `/cast/<i>/motion_asset_version_id`), `asset.bytes_missing` and
  `store.hash_mismatch`. The pre-build check's reference list does not include the cast
  entry's motion pin yet (story 406); the resolver checks its bytes meanwhile.
- **E0's clips** are imported from public text by source key
  `legacy:winter-menu-video-e0:<loop|set-loop|s2v>:...`: 7 promoted and 3 candidate doll
  loops, 1 set loop (pinned only: no record ties it to a set still), and 11 promoted
  timed clips; the 13 whole-frame I2V clips and the whole-frame S2V test are not motion
  assets. Values no public record holds are left out, never guessed (the reference
  lists them); the private import brings their bytes in.
- **Private input import (story [846](https://work.haynesnetwork.com/work_packages/846),
  [reference](../reference/private-input-import.md)).** `python -m
  haynes_studio.importer` reads The Winter Menu's private inputs that the public records
  name, **read-only at the source**: delivered copies through story 425's ledger reader,
  E0 clips through their Wan job ledgers and E0 uploads by hash, the last two through
  two new pinned snippets that open every folder and the file with `O_NOFOLLOW` after an
  `lstat`, refuse links, hard links and non-regular files, limit the size, check the hash
  in the pod and open nothing for writing. Per distinct hash: a blob the store already
  holds is re-hashed by the import itself and not read again; otherwise the sources are
  tried in row order, a refusal (`adapter.source_*`) moving on to the next and anything
  else (`adapter.volume_unexpected`, a timeout, a denial, a store error, `import.failed`)
  stopping the whole import; the records are checked against the bytes (each must
  return its existing version) before a create-only publish; and every locator is
  verified again before the hash is called verified. Hashes with no library version
  (takes, keyframes, start images) go to the production's content-addressed folder.
  Every recovery-map row and E0 record line is reported in one of **three statuses**:
  `verified`, `absent` or `mismatch`; a row not read on purpose is `absent` with its
  reason, not a fourth status (Q-846-01, the contract owner). The E0 drive tracks are read
  too (Q-846-02, the contract owner). The r1 ComfyUI renders are not imported and lapse
  around 2026-12-03 (Q-846-03, the contract owner); the fire bed is `absent` (D54).
  Story 428 ran it once, live: 132 rows verified, 24 absent, 0 mismatch (section 8).

## 10. Pre-build voice policy (D33)

- **VOICE-1** Voices are stock TTS voices only, Kokoro-82M v1.0 stock IDs today (P-22;
  `voice.not_stock`). AGENTS.md forbids a real person's voice, and story 405 excludes
  cloning; stock-only is this contract's way to guarantee both. Each cast slot names
  a `voice` asset version; narrator lines use the story's narrator voice. Speakers are
  cast slots, or `narrator` on a board whose style is narrator
  (`voice.speaker_not_in_cast`). The Winter Menu's legacy voices are not the target
  (D53): new voice work auditions other Kokoro stock voices and settings per character,
  and other local text-to-speech models, and Tom picks from private samples. Any model
  it adds keeps this rule: stock voices only, no cloning. The first audition (story
  [840](https://work.haynesnetwork.com/work_packages/840),
  [run log](../../titles/the-winter-menu/voice-audition/run-log.md)) delivered one
  private reel per cast slot, six Kokoro stock voices each with the r4 voice first; Tom's
  pick per slot is Q-840-01, open. The recorded stock list holds five Kokoro voices; a
  voice Tom picks is recorded there before the library or a voice job accepts it, and
  the voice plan refuses any other before a request (`voice.not_stock`). That matters
  because the Kokoro service answers an unknown voice name with `af_heart` instead of
  refusing it. The service takes no setting per request (one server-wide speed, 1.0), so
  speed or delivery per line needs another service (Q-840-02, open). The
  [desk review](../../titles/the-winter-menu/voice-audition/desk-review.md) recommends
  two local models to try next; that is the worker's recommendation, not a decision.
- **VOICE-2** A board voice version holds one take per line (with `signature`, `sha256`,
  `samples`, `duration_ms`, `offset_ms`) and the assembled track. It is made while
  editing, before any Build, and can be played and regenerated. The track stays at the
  takes' own rate (24 000 Hz for Kokoro), 16-bit mono PCM, and ends at `speech_end_ms`
  (the tail is not voice); the mix converts to 48 000 Hz (VOICE-7). Take *i* starts at
  sample `offset_ms * rate div 1000`.
- **VOICE-3** Take signature: `sha256:` plus the SHA-256 of canonical `{engine, voice_id,
  text (NFC), speed}`, where `engine` is the TTS model's digest once one is recorded and
  its name (`Kokoro-82M v1.0`) until then, and `speed` is the float `1.0` (the Kokoro
  client sends no speed, so the server default applies; legacy takes recorded none; the
  service's one speed is `KOKORO_SPEED=1.0`, story 840). Kokoro is deterministic: story
  840's first take was byte-identical to the r4 take of the same voice and text, so a
  retry after a transcript mismatch gives the same bytes.
  Version `input_signature`: `{takes: [take signature], lead_ms, gaps_ms}`, one gap per
  later line. What a snapshot pins for the version: `{input_signature, takes: [take
  sha256]}`. A stock voice's `definition_signature`: `{engine, stock, voice_id}`, with
  the model name as `engine`. These are the library's functions (stories 382 and 405)
  and the examples' values. Only takes whose signature changed go back to TTS; a lead or
  gap edit only re-assembles. Takes are reused from any version of the same board,
  newest first, never across boards.
- **VOICE-4** A voice job records the signature it started from. When it finishes, its
  result is always kept as a version, but becomes the board's current voice only if the
  board's signature still matches; otherwise it is kept as stale. Nothing is overwritten
  (story [405](https://work.haynesnetwork.com/work_packages/405)).
- **VOICE-5** Board length comes from the measured takes (TIME-1 to TIME-3), never a
  typed number.
- **VOICE-6** Build requires a current voice for every spoken board; voices are never
  generated inside a run, because the snapshot must be complete at queue time (P-12). The
  UI may offer "generate missing voices, then queue".
- **VOICE-7** Mix: each take normalized to the story's `line_rms_dbfs` (Legacy -22 dBFS)
  with 5 ms edge fades, then loudness -20 LUFS and true peak -3.5 dBTP (r4 values); a
  format may change them later. The limiter's look-ahead delay is compensated, so every
  line sounds at its TIME-7 sample (story 841, section 8).
- **VOICE-8** The transcript check (ASR with the story's tolerances) is a technical check
  recorded on the run. It is not a gate (D29).
- **VOICE-9 Engine currency (D53, story 405's Q-405-01, answered 2026-11-13).** Once a
  TTS model digest is recorded, every board voice signed with another engine is stale
  (`voice.stale`), so The Winter Menu's legacy voices must be voiced again before its
  next build. No digest is recorded today, so nothing is stale for this reason yet. The
  library's currency (`Library.facts`) compares lines, speakers, cast voices, lead and
  gaps, and since story 849 also the engine when its caller names the current one
  (`current_engine`): a board voice any of whose takes is signed with another engine is
  stale, with or without a story. With none named nothing changes (P-40). The caller
  that names it is story [406](https://work.haynesnetwork.com/work_packages/406)'s
  pre-build check, not yet merged; until it is, no build path compares the engine, which
  changes nothing while no digest is recorded.
- **As built (story 405, [reference](../reference/studio-voice.md)).** A take is 16-bit
  mono PCM at 8000 to 48 000 Hz (`voice.format_mismatch`) and at most 120 000 ms; lead and
  gaps together, and the track, at most 600 000 ms; a board voice at most 256 lines; each
  refused before any buffer is sized and, where it can be known, before any speech call
  (`schema.invalid`). A silent board has no voice (`voice.not_needed`); a line the speech
  client would refuse (blank, over 1000 characters) is `voice.request_invalid` at request
  time; a job signed for another engine is `voice.engine_mismatch`. A failed job makes
  no version, so a retry speaks its new takes again.
- **A board voice without an assembled track is stale for a build** (the contract
  owner's decision, built by story [857](https://work.haynesnetwork.com/work_packages/857)).
  The picture's envelope and the mix read the track, and a legacy import's board voices
  have `track: null`. With a story, `Library.facts` calls such a voice stale, so
  `queue_run` reports `voice.stale`, `derived.voice_state` is `stale` and the board is
  untimed; without a story nothing changes. `studio voice` plans such a board as an
  assembly: each take of the trackless version that the store holds is reused after its
  hash is checked, and only a take it does not hold is spoken, one call per signature. The
  new version goes on the asset `board-voice:<board_id>`; the legacy version and its asset
  are never rewritten. A take of a version that has a track must still be held
  (`asset.bytes_missing`). r4 as imported is therefore stale on its 8 spoken boards until
  `studio voice` runs.
- **What a legacy import's own documents say (O-860-1; the contract owner's decision, a
  proposal Tom may overrule, P-47).** The import's stored story and its map keep their
  own derived values, the ones the legacy takes give (every spoken board `current`,
  1087 frames). Only the import's printed summary and the library's facts speak for a
  build: since story 860 the summary says `for a build: 8 of 9 boards untimed
  (voice.stale ...)`, as `Library.facts` does, and also gives the legacy takes' 1087
  frames. Stored documents are not changed. So the
  [r4 story example](examples/valid/story-winter-menu-r4.json), which records
  `voice_state: current` and 1087 timed frames, stays as the import's own document. The
  [run snapshot example](examples/valid/run-snapshot.json) still pins the 8 legacy board
  voices with no track, a snapshot `queue_run` now refuses. It is not re-pinned, because
  the public records cannot rebuild an honest replacement: the real snapshot of story
  428's delivered run (`3bf340d3...`, story revision 3) is the voiced draft taken by
  value, and that draft, with the IDs minted at its import (its notes and picture cues
  among them), is in no public record. A library test also ties this example to the
  import of the public r4 files.

## 11. Go-live approval identity (boundary only)

E1 implements none of this; story [412](https://work.haynesnetwork.com/work_packages/412)
does. Example: [`go-live-approval.json`](examples/valid/go-live-approval.json).

- Go-live is the only formal approval (D29). It binds one finished run: `run_id`,
  `run_snapshot_sha256`, `delivery_id`, `master_sha256`. It never moves to another run
  (`approval.not_exact_run`), and an older finished run stays approvable after the draft
  changes (review M4).
- The approver is a human OIDC principal `(iss, sub)` on the go-live allowlist: Tom
  (D29). Agent keys never approve (`approval.approver_not_permitted`). The allowlist lives
  in deployment configuration in haynes-ops (P-13). Approving needs a sign-in no older
  than 15 minutes (`auth_time`), otherwise the user signs in again (P-13).
- Preconditions: run `succeeded`, built by the studio's own engine; an `imported` legacy
  run never goes live (D52, Q-04 answered 2026-11-13); delivery verified; release checks
  recorded with the approval (AI label on the platform setting and the description line,
  D43; rights; licences as recorded, which block nothing while the use is research and
  personal, D49; D44 credits). Which code refuses an approval of an imported run is
  story 412's to name.
- An approval is never edited. A withdrawal and each publication are appended records that
  point at it; the approval's `derived.state` (`active`, `withdrawn`) is computed from
  them. Approval publishes nothing; a publication is recorded after Tom's manual upload
  (D43).

## 12. API, UI and MCP boundaries

### Boundaries (D41)

- **studio-api** is the only writer of records (Postgres `studio` database) and of store
  blobs. It is stateless, with at least two replicas.
- **Web UI** is a static app. All data goes through studio-api; it has no database or
  store access. Media streams through authenticated `GET /v1/media/{sha256}` with Range
  support; the server serves a hash only if a production in the caller's scope references
  it, and answers `not_found` otherwise, so a known hash grants nothing. Per-user
  selections persist through the API (D32).
- **MCP server** is a separate process that calls studio-api with the agent's key. It
  returns compact JSON and no media bytes by default. It has no approval, publication,
  shell or raw-graph tool, and nothing that deletes media, asset versions or runs.
  Tombstoning a draft board is an ordinary draft edit (`studio_remove_board`).
- **Workers** (render, voice, photo) claim, heartbeat and complete work through internal
  studio-api endpoints with a worker credential (P-14). Rejected: direct Postgres access
  for workers, which puts a second authorization point next to the API.
- **Every request is authenticated**, media included; `/healthz` and `/readyz` return no
  data. People: Authentik OIDC, authorization code with PKCE, as a confidential client in
  studio-api; the session row lives in Postgres and the browser holds only an HttpOnly,
  Secure, SameSite=Lax `__Host-` cookie, with a CSRF header on unsafe methods (P-15).
  Rejected: tokens in browser JavaScript. Agents: `Authorization: Bearer <key>`, stored
  hashed, with scopes. Workers: service tokens.

### Conventions

- Writes send the entity's `revision` (`If-Match`); a stale one gets
  `409 conflict.revision` with the current revision.
- `POST` that creates a job or run takes `Idempotency-Key`; the same key with a different
  body gets `422 idempotency.mismatch`.
- Errors: `{"error": {"code", "status", "http_status", "path", "message", ...}}` with
  status `invalid` (422), `unavailable` (422), `conflict` (409), `forbidden` (403),
  `unauthenticated` (401), `not_found` (404) or `too_large` (413)
  ([example](examples/valid/error-method-unavailable.json)).
- D42 upload: raw `image/png`, `image/jpeg` or `image/webp` bytes up to 20 MiB and
  4096x4096 px, with provenance JSON; never a URL to fetch. The server reads the
  dimensions from the header before decoding (oversize fails without a full decode),
  decodes the image (undecodable fails), strips metadata (EXIF, GPS, XMP) and stores the
  stripped bytes; `sha256` is over the stored bytes and the upload's own hash goes into
  provenance (P-16).
- Lists page by cursor.

### Scopes (P-17)

| Scope | Allows |
|---|---|
| `read` | reads within the key's productions |
| `draft:write` | stories, boards, lines, cues, notes |
| `assets:generate` | voice, photo and asset-candidate jobs |
| `assets:upload` | D42 board photo uploads |
| `runs:queue` | queue and cancel runs; for a signed-in person, also record check overrides. An agent key may hold it to queue and cancel (D50, Q-02 answered 2026-11-13; coordinator's reading: the per-key scope is the mechanism and is no longer people-only). Tom's ruling is about using the GPUs, so it does not reach check overrides: a judgement by eye stays with people, and no agent key may record one until Tom says otherwise. A key holds the scope only when issued with it, for its productions. A build takes the Wan compute lease, one job at a time, with its unknown-work checks, through the Wan clip client and its journal (section 8, story 842); a lease or queue across agents is dev-env work in haynes-engineering |
| `go_live:approve` | humans on the allowlist only; never on a key |

A key lists its productions; anything else is `forbidden` (story
[429](https://work.haynesnetwork.com/work_packages/429)).

### Operations

Paths are under `/v1`. MCP tool names replace the old `patch_shot` and
`get_title_summary` (review H6).

| Operation | HTTP | MCP tool | Scope | Story |
|---|---|---|---|---|
| `get_me` | `GET /me` | | any | [409](https://work.haynesnetwork.com/work_packages/409) |
| `get_selections`, `put_selections` | `GET`, `PUT /me/selections` | | human | 409, [413](https://work.haynesnetwork.com/work_packages/413) |
| `list_productions` | `GET /productions` | `studio_list_productions` | read | 409, 429 |
| `create_production` | `POST /productions` | | human | 409 |
| `get_production` | `GET /productions/{id}` | `studio_get_production` | read | 409 |
| `enable_media_type` | `PUT /productions/{id}/media-types/{kind}` | | human | 409 |
| `list_stories` | `GET /productions/{id}/media-types/{kind}/stories?publication=&approved=` | `studio_list_stories` | read | 409, [414](https://work.haynesnetwork.com/work_packages/414) |
| `create_story` | `POST /productions/{id}/media-types/{kind}/stories` | `studio_create_story` | draft:write | 409, 429 |
| `get_story` | `GET /stories/{id}` | `studio_get_story_summary` | read | 409, 429 |
| `update_story` | `PATCH /stories/{id}` | `studio_patch_story` | draft:write | 409, 429 |
| `get_story_timing` | `GET /stories/{id}/timing` | `studio_get_story_timing` | read | 404, 409 |
| `create_board` | `POST /stories/{id}/boards` | `studio_add_board` | draft:write | 409, 429 |
| `get_board` | `GET /boards/{id}` | `studio_get_board` | read | 409, 429 |
| `update_board` (lines, timing, method, cast, layout, cues, notes, photo prompt and inputs, current photo) | `PATCH /boards/{id}` | `studio_patch_board` | draft:write | 409, 429 |
| `reorder_boards` | `PUT /stories/{id}/board-order` | `studio_reorder_boards` | draft:write | 409, 429 |
| `remove_board` (tombstone) | `DELETE /boards/{id}` | `studio_remove_board` | draft:write | 409, 429 |
| `generate_board_voice` | `POST /boards/{id}/voice-jobs` | `studio_generate_voice` | assets:generate | 405, [430](https://work.haynesnetwork.com/work_packages/430) |
| `list_board_voice_versions` | `GET /boards/{id}/voice-versions` | | read | 405, 430 |
| `generate_board_photo` | `POST /boards/{id}/photo-jobs` | `studio_generate_photo` | assets:generate | [407](https://work.haynesnetwork.com/work_packages/407), 430 |
| `upload_board_photo` (D42) | `POST /boards/{id}/photo-versions` | `studio_upload_photo` | assets:upload | 407, 430 |
| `list_board_photo_versions` | `GET /boards/{id}/photo-versions` | | read | 407, 430 |
| `get_job` | `GET /jobs/{id}` | `studio_get_job` | read | 430 |
| `search_assets` | `GET /assets?kind=&label=&production=&board=` | `studio_search_assets` | read | [382](https://work.haynesnetwork.com/work_packages/382), 409 |
| `get_asset` | `GET /assets/{id}` | `studio_get_asset` | read | 382, 409 |
| `generate_asset_candidate` | `POST /asset-jobs` | | assets:generate (human in v1) | [408](https://work.haynesnetwork.com/work_packages/408), 430 |
| `promote_asset_version` | `POST /asset-versions/{id}/promote` | | human | 408 |
| `get_media` | `GET /media/{sha256}` | | read | 409 |
| `estimate_run` | `GET /stories/{id}/estimate` | `studio_estimate_run` | read | 410, 430 |
| `queue_run` | `POST /stories/{id}/runs` | `studio_queue_run` | runs:queue | 410, 430 |
| `list_runs` | `GET /stories/{id}/runs` | `studio_list_runs` | read | 410, [419](https://work.haynesnetwork.com/work_packages/419) |
| `get_run` (status, progress, stages, checks) | `GET /runs/{id}` | `studio_get_run` | read | 410, 430 |
| `cancel_run` | `POST /runs/{id}/cancel` | `studio_cancel_run` | runs:queue | 410 |
| `compare_runs` (boards matched by stable ID) | `GET /runs/compare?left=&right=` | | read | 419 |
| `record_check_override` (with a reason; never a release check) | `POST /runs/{id}/checks/{check}/overrides` | `studio_override_check` (refused for agent keys) | runs:queue, people only | 410, [450](https://work.haynesnetwork.com/work_packages/450) |
| `get_delivery` | `GET /runs/{id}/delivery` | `studio_get_delivery` | read | 381, 409 |
| `approve_go_live` | `POST /runs/{id}/go-live-approvals` | | go_live:approve | 412 |
| `withdraw_go_live` | `POST /go-live-approvals/{id}/withdraw` | | go_live:approve | 412 |
| `record_publication` | `POST /runs/{id}/publications` | | human | [449](https://work.haynesnetwork.com/work_packages/449) |
| `claim_work`, `heartbeat_work`, `complete_work`, `fail_work` | `POST /internal/v1/work/...` | | worker | 410 |
| `login`, `callback`, `logout` | `/auth/...` | | none | 409, [432](https://work.haynesnetwork.com/work_packages/432) |
| `healthz`, `readyz` | `GET /healthz`, `/readyz` | | none | [434](https://work.haynesnetwork.com/work_packages/434) |

The legacy import is a CLI command (`studio legacy import <manifest>`), not an endpoint
in v1. E1 ends with a private command-line build of The Winter Menu on the 3090s
(story 428, D55); the API and its deployment stay in E3. The commands it uses are built:
`studio voice`, `studio build` (`--phase service`, `--offline`, `--dry-run`,
`--workers N`, `--wan-story`) and `studio run show` (story 406, section 8), and
`python -m haynes_studio.importer` (story 846, section 9).

## 13. Stack pin

Each choice is a proposal (P-18) that the coordinator ratified at review. Nothing was
installed or built to make it.

| Layer | Pin | Reason | Rejected |
|---|---|---|---|
| Python | CPython **3.12** in images; `requires-python = ">=3.11,<3.13"`; CI tests 3.11 and 3.12 | studio-render already runs 3.12 with pinned requirements ([services.md](../reference/services.md)); session pods have 3.11.2, and tests must run there without installing an interpreter. No 3.12-only syntax. | 3.13 (no runtime has it); 3.11 only (the worker runs 3.12) |
| Package | distribution `haynes-studio`, import package **`haynes_studio`** under `src/`, CLI command `studio` | `poc/studio.py` is a module named `studio` that the PoC scripts import from their own folder; a package of the same name would shadow or be shadowed | package named `studio` |
| Build and lock | `pyproject.toml` with the **hatchling** backend; **uv** with a committed `uv.lock`, `uv sync --locked` | uv is in every session pod (0.13); one cross-platform lock; hatchling builds with plain pip in image builds too | Poetry (not installed, separate lock); pip-tools (per-platform files) |
| Runtime libraries | numpy, Pillow, PyAV, scipy (keying, BSD-3-Clause), opencv-python-headless (decal, Apache-2.0), **imageio-ffmpeg** for the ffmpeg binary, all in the lock (scipy 1.16 and OpenCV 4.14 since 2026-11-13, PR 56, used by story 426's keying and decal). A story that ports PoC code adds what that code already uses (wyoming for the TTS and ASR adapters) to the lock | what `poc/` uses; session pods have no system ffmpeg | system ffmpeg |
| Tests | **pytest**, serial; markers in [section 14](#14-test-contract) | standard; serial keeps the 2-thread rule | pytest-xdist by default |
| JSON Schema | draft 2020-12 files; the `jsonschema` library checks them against the examples | language-neutral, shared with the web app and MCP | Python models as the only schema |
| API | **FastAPI** + Pydantic v2 + Uvicorn | OpenAPI with auth and errors (story 409's acceptance); typed request models; streaming responses for media | Django (stateful sessions, ORM-first); Flask (no OpenAPI or validation) |
| MCP | the official `mcp` Python SDK, streamable HTTP, as its own process | thin client over studio-api (story 429) | MCP inside the API process |
| Database | PostgreSQL 16 (`database/postgres16`, D39) through **psycopg 3** and **SQLAlchemy 2.0 Core**; **Alembic** migrations | explicit SQL for claims and fencing (`FOR UPDATE SKIP LOCKED`); a migration graph; downgrades tested on an empty database, production rolls forward | the ORM's identity map; SQLModel (couples API and table models); SQLite in tests (different locking gives false confidence) |
| Web | **TypeScript**, **React**, **Vite**, **pnpm**; static build served by an unprivileged nginx image; **Vitest** and **Playwright** | stateless static tier (D41); Node and pnpm are in session pods; component model for the v6 surfaces | Next.js (a server tier with its own auth); plain JavaScript like the mockup |
| Images | built by GitHub Actions, deployed by digest from haynes-ops | proposal 0003 Infrastructure (Code); story [433](https://work.haynesnetwork.com/work_packages/433) | |

## 14. Test contract

What story 424 implements. Proposal P-19 for the names and commands.

| Suite | Command | Needs | Where |
|---|---|---|---|
| `source` (default) | `uv run pytest` | nothing: no network, credentials, GPU, Postgres or private media | session pods and CI |
| `db` | `uv run pytest -m db` | `STUDIO_TEST_DATABASE_URL` to a disposable PostgreSQL 16; skipped with a reason when unset | CI (a `postgres:16` service container); never `database/postgres16` |
| `browser` | `pnpm test:e2e` | Playwright browsers | CI; locally where installed |
| `live` | `uv run pytest -m live --live-story=<id>` | a story that authorizes it, and its named service | never in CI; opt-in only |

- **Limits:** `STUDIO_THREADS=2`, `OMP_NUM_THREADS=2`, `OPENBLAS_NUM_THREADS=1`, ffmpeg
  `-threads 2`, OpenCV `cv2.setNumThreads(2)`, render `--workers 1`, no xdist, Playwright `workers: 1`, Vitest
  `--maxWorkers=2`; one suite at a time in a session pod. Timing tests use fake clocks,
  not sleeps.
- **Fixtures:** committed fixtures are text only: the public manifests and evidence JSON,
  and these examples. Synthetic media is generated at test time under pytest's `tmp_path`,
  outside the checkout, small (10 s or less, 360x640 unless a test needs delivery size; a
  60 s proxy fixture is allowed for 381). Service fakes (TTS, ASR, image, Wan, store)
  return deterministic synthetic bytes (TTS, ASR, image and the Wan ledger come from
  story 425; Wan compute from stories 426 and 427; the store from stories 379 and 381); frozen responses are JSON with hashes. No private
  media, real voices or tokens in CI; `check_no_media.py` stays.
- **Output:** no environment dumps, no tokens; failures print codes and paths.
- **Contract examples:** every file in `examples/valid/` must validate against the schema
  of its type, and every file in `examples/invalid/` must fail with its `rule` code and
  `expect` status, once the story that owns that type has landed its schema and validator
  (378: the legacy manifest; 404: production, story, board, timing, methods and the
  import map; 382: asset and asset version; 405: job; 381: delivery; 406: run and run
  snapshot; later stories for approvals and the error envelope, as their tracker items
  say).
  Until then story 424's harness reports the example as pending by type and never skips
  one silently. `check_syntax.py` parses the JSON under `titles/`, `poc/graphs/` and, since
  story 424, `docs/contracts/examples/`.
- **CI jobs:** `source (3.11)`, `source (3.12)`, `db`, and `browser` once the web app
  exists, plus the existing links, syntax and no-media checks. The coordinator sets
  required checks; the Claude review stays advisory.
- **Live runs** write to a new private job directory and stop at their story's caps; a
  GPU or service call needs that story's authorization.

## 15. Rule index

| Code | Status | Section | Invalid example |
|---|---|---|---|
| `schema.unsupported` | invalid | 2 | [schema-unsupported](examples/invalid/schema-unsupported.json) |
| `schema.unknown_field` | invalid | 2 | [schema-unknown-field](examples/invalid/schema-unknown-field.json) |
| `schema.invalid` | invalid | 2 | [job-succeeded-without-result](examples/invalid/job-succeeded-without-result.json) |
| `ref.unknown`, `ref.duplicate`, `story.board_order` | invalid | 2 | |
| `id.malformed` | invalid | 2 | [id-malformed](examples/invalid/id-malformed.json) |
| `id.type_mismatch` | invalid | 2 | [id-type-mismatch](examples/invalid/id-type-mismatch.json) |
| `time.hold_on_spoken_board` | invalid | 3 | [time-hold-on-spoken-board](examples/invalid/time-hold-on-spoken-board.json) |
| `time.hold_out_of_range` | invalid | 3 | [time-hold-out-of-range](examples/invalid/time-hold-out-of-range.json) |
| `time.negative` | invalid | 3 | [time-negative](examples/invalid/time-negative.json) |
| `time.tail_too_short` | invalid | 3 | [time-tail-too-short](examples/invalid/time-tail-too-short.json) |
| `time.not_integer_ms` | invalid | 3 | [time-not-integer-ms](examples/invalid/time-not-integer-ms.json) |
| `time.duration_is_derived` | invalid | 3 | [time-duration-is-derived](examples/invalid/time-duration-is-derived.json) |
| `time.first_line_gap` | invalid | 3 | [time-first-line-gap](examples/invalid/time-first-line-gap.json) |
| `time.source_short` | failed stage | 3 | |
| `time.conservation` | failed stage | 3, 4 | |
| `format.length_exceeded` | warning | 3 | [story-timing-summary](examples/valid/story-timing-summary.json) (valid) |
| `method.unknown` | invalid | 5 | [method-unknown-layer](examples/invalid/method-unknown-layer.json) |
| `method.s2v_needs_line` | invalid | 5 | [method-s2v-needs-line](examples/invalid/method-s2v-needs-line.json) |
| `method.s2v_needs_onscreen_speaker` | invalid | 5 | [method-s2v-needs-onscreen-speaker](examples/invalid/method-s2v-needs-onscreen-speaker.json) |
| `method.layered_needs_cast` | invalid | 5 | [method-layered-needs-cast](examples/invalid/method-layered-needs-cast.json) |
| `method.unavailable` | unavailable (at `queue_run`) | 5 | [method-whole-frame-s2v-unavailable](examples/invalid/method-whole-frame-s2v-unavailable.json) |
| `asset.capability_mismatch` | invalid | 5, 9 | [asset-capability-mismatch](examples/invalid/asset-capability-mismatch.json) |
| `asset.kind_mismatch`, `asset.scope_mismatch`, `asset.bytes_missing`, `asset.unresolved` | invalid | 8, 9 | |
| `asset.not_promotable`, `asset.source_key_required` | invalid | 9 | |
| `cue.type_unknown` | invalid | 6 | [cue-type-unknown](examples/invalid/cue-type-unknown.json) |
| `cue.anchor_line_missing` | invalid | 6 | [cue-anchor-line-missing](examples/invalid/cue-anchor-line-missing.json) |
| `cue.out_of_range` | invalid | 3, 6 | [cue-out-of-range](examples/invalid/cue-out-of-range.json) |
| `cue.slot_not_on_board` | invalid | 6 | [cue-slot-not-on-board](examples/invalid/cue-slot-not-on-board.json) |
| `note.text_only` | invalid | 6 | [note-text-only](examples/invalid/note-text-only.json) |
| `prov.external_incomplete` | invalid | 7 | [prov-external-unmarked](examples/invalid/prov-external-unmarked.json) |
| `prov.licence_missing` | invalid | 7 | [prov-licence-missing](examples/invalid/prov-licence-missing.json) |
| `credit.outside_video_sound` | invalid | 7 | [credit-outside-video-sound](examples/invalid/credit-outside-video-sound.json) |
| `run.snapshot_missing` | invalid | 8 | [run-snapshot-missing](examples/invalid/run-snapshot-missing.json) |
| `voice.absent`, `voice.stale`, `photo.absent`, `asset.generating` | invalid at queue | 8, 10 | |
| `store.locator_invalid` | invalid | 8 | [store-locator-invalid](examples/invalid/store-locator-invalid.json) |
| `store.collision` | failed stage | 8 | |
| `store.hash_mismatch`, `store.blob_missing` | failed stage | 8 | |
| `store.record_invalid`, `store.media_type_unsupported` | invalid | 8 | |
| `delivery.master_invalid`, `delivery.record_invalid`, `delivery.legacy_mismatch` | invalid | 8 | |
| `delivery.proxy_invalid`, `delivery.master_changed`, `delivery.not_verified` | failed stage | 8 | |
| `cache.key_input_invalid` | invalid | 4 | |
| `cache.entry_invalid`, `render.frame_count`, `render.frame_invalid`, `splice.incompatible` | failed stage | 4 | |
| `voice.speaker_not_in_cast` | invalid | 10 | [voice-speaker-not-in-cast](examples/invalid/voice-speaker-not-in-cast.json) |
| `voice.not_stock` | invalid | 10 | [voice-not-stock](examples/invalid/voice-not-stock.json), [job-voice-not-stock](examples/invalid/job-voice-not-stock.json) |
| `voice.not_needed`, `voice.request_invalid`, `voice.format_mismatch`, `voice.engine_mismatch` | invalid | 10 | |
| `job.transition` | conflict | 2 | |
| `approval.approver_not_permitted` | forbidden | 11 | [approval-not-human](examples/invalid/approval-not-human.json) |
| `approval.not_exact_run` | invalid | 11 | [approval-not-exact](examples/invalid/approval-not-exact.json) |
| `conflict.revision`, `idempotency.mismatch` | conflict, invalid | 12 | |
| `legacy.duration_with_lines` | invalid | 1 | [legacy-duration-with-lines](examples/invalid/legacy-duration-with-lines.json) |
| `legacy.invalid` | invalid | 1 | |
| `legacy.reference` | invalid | 1 | |
| `legacy.speech_mismatch`, `legacy.timeline_mismatch` | invalid | 1, 3 | |
| `legacy.import_map_mismatch` | invalid | 1 | |
| `legacy.evidence_mismatch` | invalid | 1, 9 | |
| `adapter.request_invalid`, `adapter.pin_mismatch` | invalid | 7 | |
| `adapter.command_failed`, `adapter.timeout`, `adapter.response_invalid`, `adapter.not_found`, `adapter.busy` | failed job or stage | 7 | |
| `wholeframe.unsupported`, `wholeframe.chain_limit` | invalid | 3, 5, 6 | |
| `wholeframe.clip_invalid` | failed stage | 5, 7 | |
| `motion.record_missing`, `motion.clip_absent`, `motion.clip_ambiguous`, `motion.still_mismatch`, `motion.keying_missing` | invalid | 5, 9 | |
| `motion.timed_not_loop`, `motion.drive_track_mismatch` | invalid | 3, 9 | |
| `motion.identity_mismatch` | invalid | 4, 9 | |
| `layered.unsupported`, `layered.layout_invalid`, `layered.drive_invalid` | invalid | 3, 5, 6 | |
| `layered.clip_invalid`, `layered.decal_weak` | failed stage | 5, 7, 8 | |
| `mix.input_invalid`, `mix.master_invalid`, `mix.check_failed` | failed stage | 6, 8 | |
| `build.offline_missing`, `build.check_failed`, `build.delivery_unverified`, `build.voice_track_missing`, `build.live_unsupported`, `build.internal` | failed run | 8 | |
| `build.run_unrecorded` | failed run, not recorded (non-zero exit) | 8 | |
| `build.wan_unsettled` | held run | 8 | |
| `build.dry_run_asked` | failed run (a defect: a dry run's source was asked) | 8 | |
| `run.transition` | conflict | 8 | |
| `run.unknown` | not found | 8 | |
| `adapter.job_failed`, `adapter.competing_work`, `adapter.journal_failed` | failed job; a held run in a build | 7, 8 | |
| `adapter.source_missing`, `adapter.source_link`, `adapter.source_not_regular`, `adapter.source_hard_link`, `adapter.source_too_large`, `adapter.source_outside`, `adapter.source_hash_mismatch`, `adapter.source_record_invalid`, `adapter.source_changed` | refused read (the import tries the next source) | 7, 9 | |
| `adapter.volume_unexpected`, `import.failed` | stops the import | 7, 9 | |

## 16. Held owner questions

**Q-01 to Q-04 are answered.** Tom answered all four on 2026-11-13; the section keeps its
name so links to it hold. Each entry keeps the question and its options in short, then
the answer, its date and the decision that records it in
[proposal 0003](../proposals/0003-studio-plan.md). Questions the merged stories raised
follow in a table; those still open for Tom are marked so.

**Q-01 What do unknown or non-commercial licences block at release?** Affected
`licence.commercial_use` and the release checks of stories 412 and
[449](https://work.haynesnetwork.com/work_packages/449). Options: (a) block release on
any `unknown` or `noncommercial` engine or asset in the video and sound chain; (b) block
`unknown`, warn on `noncommercial`; (c) record only. Recommended: (a).
**Answered 2026-11-13, D49:** "Switch it only if we do commercial things for now stop
harping on this licenses this is a homelab so it's just for research and personal
development". Licences are recorded as facts and block nothing while the use is research
and personal (section 7); the question reopens only if commercial use is planned.
*Coordinator's reading:* the same ruling settles story 809's Q-809-1 to Q-809-4.

**Q-02 May agent keys queue builds?** Affected the `runs:queue` scope and
`studio_queue_run`, `studio_cancel_run` and `studio_override_check` (stories 429, 430,
[454](https://work.haynesnetwork.com/work_packages/454)). Options: (a) people only in
v1; (b) a per-key `runs:queue` scope; (c) any key with `draft:write`. Recommended: (b).
**Answered 2026-11-13, D50:** "These two GPUs are dedicated to this project you are free
to use them. The think we wouldn't want later is multiple agents trying to use them at
the same time so there'd need to be some lease / queue in place but that isn't work for
you that is work for the dev-env haynes engineering project which you can simply
backlog". *Coordinator's reading:* agents may queue builds on the two 3090s, one job at
a time through the Wan compute lease; the per-key `runs:queue` scope stays the
mechanism and is no longer people-only for queueing and cancelling (section 12); check
overrides, a judgement by eye his words do not cover, stay with people; a lease or queue
across agents is
dev-env work in haynes-engineering; the shared ComfyUI image GPU keeps its household
rule.

**Q-03 For a layered board, what is the reference photo?** Affected `board.photo`, the
invalidation row "Board photo version", and stories
[417](https://work.haynesnetwork.com/work_packages/417),
[418](https://work.haynesnetwork.com/work_packages/418), 426 and 407. Options: (a) a
preview, labelled so; (b) the source, matted into layers (story
[451](https://work.haynesnetwork.com/work_packages/451)); (c) a deterministic composite
of the build's own layers, with prompt photos only for whole-frame boards. Recommended:
(a) now, (c) as a follow-up. **Answered 2026-11-13, D51:** "Why do we need a follow up
just do it as part of the requirements IF it is a requirement". *Coordinator's
reading:* it is a requirement (D26), so (c) from the start, in stories 426 and 407, with
no preview-only phase ([section 4](#4-cache-clocks-and-invalidation)).

**Q-04 Can an imported legacy run go live?** Affected the go-live preconditions
([section 11](#11-go-live-approval-identity-boundary-only)) and story 412. Options:
(a) only canonical `succeeded` runs; (b) imported runs with a verified master and
structured provenance; (c) the r4 cut only. Recommended: (b). **Answered 2026-11-13,
D52: no**, that is (a): "Nothing was built from the first pipeline that can be approved
that was a PoC to build out the stories". Only runs the studio's own engine builds can
go live.

**Questions raised by merged E1 stories**, answered, decided or held the same day. An
answer by the contract owner is a proposal Tom may overrule.

| Question | Answer | By |
|---|---|---|
| Q-405-01 Are the legacy board voices stale once a TTS model digest is recorded? | Yes: VOICE-9 | Tom, D53 |
| Q-428-1 The Winter Menu's fire bed, which is not on the Wan volume | A new version from the in-cluster sound model | Tom, D54 |
| Q-809-1 to Q-809-4 Qwen-Image lane, Stable Audio registration, ControlFoley, the `LICENSE` pointer | Unchanged for now | Tom, D49 (coordinator's reading) |
| Q-381-01 Proxy size past 60 s | 25 000 000 bytes per minute, at least 25 000 000 (section 8) | the contract owner |
| Q-381-02 Is the proxy's picture good enough on a phone? | Open: answered when Tom watches the first real delivery at the demo | Tom, later |
| H-1, H-2, H-3 of story 380 (drive track key, encoder threads, cache lookup) | P-25, P-26, P-27 | the contract owner |
| Q-427-1 Camera cues on whole-frame boards: (a) refuse, (b) draw a crop-zoom with story 426's camera code, (c) reject at write | (a) for now (`wholeframe.unsupported`), then (b) once the layered camera code is shared; story 406 runs the check before any clip is made (sections 5, 6) | the contract owner |
| Q-427-2 Whole-frame chain limit: (a) 3 clips, (b) more, (c) 2 | (a): at most 3 clips of 121 frames, 361 frames, E0's longest delivered chain; every r4 board fits (TIME-8) | the contract owner |
| Q-457-1 A layered board's cast still has no motion loop: (a) an error, (b) Build makes a candidate, (c) Build makes and promotes one | (a): `motion.clip_absent`; a loop is made by an explicit asset job before Build, as voices are (P-12); Build never generates one (section 5) | the contract owner |
| Q-426-1 Keying of a speech-to-video clip the build makes: (a) the loop's keying with its protect boxes, gate 0.8, (b) without protect boxes, (c) a separate speech keying on the record | (a) as built; the demo shows Tom the result (section 5) | the contract owner |
| Q-426-2 Reuse of E0's speech-to-video clips: (a) make new clips, (b) pin a speaker's timed clip on the cast entry, (c) import E0's drive tracks | (a): the build makes new clips and reuses a library timed clip only when it was made from the board's own drive track with the board's seed; new voices change the drive tracks anyway; story 428 measures the GPU time (section 5) | the contract owner |
| Q-840-01 The voice per cast slot, from story 840's Kokoro reels: (a) one candidate per slot, (b) keep the r4 voices, (c) wait for the next model trial | Open. The worker recommends (a) where a candidate is clearly better, else (c) | Tom, open |
| Q-840-02 Per-line speed and delivery: (a) keep the service's one speed, 1.0, (b) a studio Kokoro with per-request speed (haynes-ops), (c) per-request speed and a delivery instruction as requirements of the next voice engine | Open. The worker recommends (c), adding (b) only if Tom keeps a Kokoro voice | Tom, open |
| Q-406-1 The terminal state of a service-phase run: (a) `cancelled` with reason "service phase complete", (b) a new state for a completed phase, (c) a phase that is not a run | (a), until E3's job queue gives phases their own records (section 8) | the contract owner |
| Q-406-2 Where the live build runs: (a) all in a session pod at two threads, (b) the service phases in a session pod and the offline phase on `ai/studio-render`, the store copied between them, (c) let studio-render reach the services (haynes-ops) | (b), until the NFS store adapter of story 434 (section 8) | the contract owner |
| Q-846-01 A row the private import does not read on purpose: (a) `absent` with a reason, keeping three statuses, (b) a fourth status `not_read` | (a) (section 9) | the contract owner |
| Q-846-02 Read the E0 drive tracks too (11 more reads a layered build does not need)? | Yes: no other record of them exists outside the volume (section 9) | the contract owner |
| Q-846-03 The r1 ComfyUI renders, which a CronJob may remove around 2026-12-03 | Not imported: they matter only to regenerate a cutout, and the layered build does not need them (section 9) | the contract owner |
| Q-428-2 The off-frame limit on keyed frames: (a) keep the 240 px limit the port applies to still cutouts, (b) no limit for keyed frames, as E0's film had | (a) for E1; the demo's draft moved r4's `closeup` slot `x` from 0.56 to 0.55 (board 7 was 9 px over); revisited with the layout editor (section 5) | the contract owner |
| Q-428-3 A weak lettering track on a clip the build made: (a) a re-roll by a draft seed edit, (b) a lower floor | (a): a new clip and key, the weak clip stays in the store; no agent lowers a floor, and a person's override stays `record_check_override` (stories 410, 450) (section 5) | the contract owner |
| Q-428-4 The speech-clip prompt: the build sends one prompt for every doll, where E0 described each doll in her own. (a) Keep one prompt if the demo's dolls look right, (b) a per-cast description that the build puts into each speech prompt (a model and key change) | Open. Recommended: (a) until Tom has watched the demo | Tom, open |
| Q-428-5 After a weak lettering track: (a) the build re-rolls by itself up to twice per clip, then stops; (b) it always stops for a person | Open. Recommended: (a); each re-roll is one GPU job of 3 to 15 min | Tom, open |
| Q-428-6 Confirm the relayed word on GPU heat: a relayed message (story 428, comment 8409), not verified, says 89 C is acceptable; the coordinator's practice of no temperature stop line of its own rests on it (P-49) | Open | Tom, open |
| Tom's verdict on the first live build (story 428, delivered privately) | Open. With it he weighs the differences from r4 and E0: one speech prompt for every doll (Q-428-4), board 7's close-up moved 11 px, board 1's clip from seed 611 and board 9's from seed 620 | Tom, open |
| Q-841-01 A sound cut at the film's end: (a) hard cut at the last sample, (b) fade the last 50 ms before the cut (a new mixer version) | Open. Built as (a), the worker's recommendation; no Winter Menu sound is cut, and nothing waits on it | Tom, open |

Tom was told on 2026-11-14 that the r1 ComfyUI renders lapse around 2026-12-03;
he has not asked for them to be kept.

**Needs code or cluster work** after the first live build. None of these is a decision;
each waits on its story.

- A default speech-to-video negative prompt, and the negative prompt in the whole-frame
  clip key: story [861](https://work.haynesnetwork.com/work_packages/861), held for a
  review by another model family (unavailable until about 2026-11-19).
- The render worker at the package's lock (haynes-ops): story
  [862](https://work.haynesnetwork.com/work_packages/862), waits for Tom.
- The six one-off drivers of story 428: PR 70, held for the same review.
- A studio command for private viewing (today a one-off driver over `poc/deliver.py`; it
  writes to the shared Wan volume, so it needs that review too): story
  [863](https://work.haynesnetwork.com/work_packages/863).
- An `agent_session` operator on the command line (P-48): story
  [864](https://work.haynesnetwork.com/work_packages/864), contract text and schema first.
- A place for a refused board's partial stage in the run record: story 860's known
  limit, recorded here; it gets a story only if a build needs that time.
- The Wan API refusing a queue answer that is not two lists (haynes-ops): story
  [865](https://work.haynesnetwork.com/work_packages/865), waits for Tom.

## 17. Proposals

| ID | Choice | Rejected alternative |
|---|---|---|
| P-01 | Prefixed ULIDs; idempotent imports by `source_key` | UUIDv4, integers, bare ULIDs |
| P-02 | `studio.<type>/v<major>` schemas; unknown fields rejected on write; `derived` read-only; `revision` counter | tolerant readers; ETags from hashes |
| P-03 | Integer ms for authored time; measured takes rounded up to the ms; integer frame arithmetic | float seconds |
| P-04 | Defaults lead 500, gap 300, tail 700; hold 100 to 120 000 ms | mockup's 0.25 s pad |
| P-05 | A short source fails the stage; no silent last-frame hold | legacy hold |
| P-06 | Board clock for all picture; hashed loop phase; explicit stored seeds | film clock |
| P-07 | Cache key = SHA-256 of canonical JSON of input hashes and parameters | keys from IDs or paths |
| P-08 | Whole-frame + S2V `unavailable` (save with warning, Build refused); S2V needs an on-screen speaker; layered needs cast; `layered` default without a format | allowing unproved combinations; rejecting the design outright |
| P-09 | Four cue types; anchors by line ID; notes never executed | parsing notes into cues |
| P-10 | Phone proxy H.264, 720x1280 (`short`) or 1280x720 (`video`), strictly under 25 000 000 bytes per minute of film and never under 25 000 000 (amended by the contract owner, 2026-11-13, Q-381-01) | delivery-size proxy; a fixed 25 000 000 at any length (lower quality on long videos); no limit past 60 s |
| P-11 | D39 layout by hash; `link()` publication; NFS startup probe; tombstones only, no byte deletion in E1 to E3 | rename-based publication; deletion now |
| P-12 | Voices generated before queue, never inside a run | generating missing voices in the run |
| P-13 | Go-live allowlist of `(iss, sub)` in haynes-ops config; 15-minute sign-in freshness | Authentik group claim |
| P-14 | Workers use internal API endpoints | workers on Postgres directly |
| P-15 | OIDC confidential client in studio-api; Postgres session; `__Host-` cookie; CSRF header | tokens in the browser |
| P-16 | Upload limits 20 MiB, 4096x4096 px, PNG, JPEG or WebP; header check before decode; metadata stripped | URL fetch; storing uploads as received |
| P-17 | Scopes `read`, `draft:write`, `assets:generate`, `assets:upload`, `runs:queue` per production | one all-powerful key |
| P-18 | The stack in section 13 | as listed there |
| P-19 | Test suites, markers and commands in section 14 | per-story ad hoc suites |
| P-20 | `video` media kind 1920x1080 at 24 fps | 25 or 30 fps |
| P-21 | Labels are mutable asset metadata, outside version content | labels inside immutable versions |
| P-22 | Stock TTS voices only | any voice without a real-person check |
| P-23 | `commercial_use` value `conditional`, with the conditions in `note`; a research- or evaluation-only term is `noncommercial` with a note that it is narrower (the contract owner, after story 809) | `unknown` for a known conditional term (it hides what the register knows); a value of its own for research-only terms |
| P-24 | Principal `{kind: agent_session, session, harness, model}` for work an agent did in its own session without a studio key; it grants nothing (the contract owner, after story 809) | `{kind: worker, worker_id}` naming the session (a worker is a studio process with a service token, P-14); `{kind: agent}` without a key (an agent principal is a studio key) |
| P-25 | S2V drive track keyed on its speaker's takes and their starts (H-1, the contract owner) | the whole board voice track, which rebuilds every speaker on any line edit |
| P-26 | Reproducible segment encode: x264 sliced threads, no B-frames, 48-frame GOP, encoder build in the key; stream-copy splice (H-2, the contract owner) | frame threads (not reproducible); one thread |
| P-27 | Cache entries are stages `<kind>-<key hex>` with their key document; lookup in the current run, then earlier runs; Postgres query in story 434 (H-3, the contract owner) | one reserved cache run per production |
| P-28 | Store as built (story 379): `studio.stage-record/v1` local record with no time or writer; stage and output name grammar; at most 256 outputs; files 0444; extension from the media type, bytes not sniffed; a story reads only `library/` and its own production; the step-2 hash re-read from the synced file; `store.hash_mismatch`, `store.blob_missing`, `store.record_invalid`, `store.media_type_unsupported`, `asset.unresolved` | a record with time or writer (retries would not be idempotent); trusting the hash computed while streaming |
| P-29 | Library as built (story 382): capabilities per kind and media types per capability; a promoted board photo is a production-scope `photo`; `bytes: null` only on imported versions; a locator in the version's own production or `library/`; stock voices are the recorded ones, origin `declared`; `asset.kind_mismatch`, `asset.scope_mismatch`, `asset.bytes_missing`, `asset.not_promotable`, `asset.source_key_required`, `legacy.evidence_mismatch` | any capability on any kind; a guessed byte count, hash or licence |
| P-30 | Voice and jobs as built (story 405): the track at the takes' rate, ending at `speech_end_ms`; speed 1.0; the bounds of section 10; the job fields and state machine of section 2; generated versions on one asset per board (`board-voice:<board_id>`, a lines-keyed asset when pins collide); take reuse within a board only; `voice.not_needed`, `voice.request_invalid`, `voice.format_mismatch`, `voice.engine_mismatch`, `job.transition` | resampling the track to the mix rate; reusing takes across boards; cancelling an in-flight job when its board changes |
| P-31 | Deliveries as built (story 381): the delivery document a canonical-JSON blob in one `delivery` stage with master and proxy; one delivery per run; a shape per adapter; the proxy encoder of section 8; master audio within one AAC frame; the `delivery.*` codes | exact audio length on AAC masters (the PoC's own masters fail it); a delivery-size proxy (P-10) |
| P-32 | Cache keys as built (story 380): segments also keyed on who speaks when, the set plate and loop, a whole-frame clip and the procedural stream; motion style in every layered segment; film frame counts, mix line spans and the transcript check's script hash in their keys; clip profiles carry the media kind's aspect; `studio.cache-key/v1`; 24 fps only; `cache.*`, `render.*`, `splice.incompatible`, `time.conservation` | a segment keyed on the voice envelope alone (a line moved between two slots of one voice would reuse a stale bounce) |
| P-33 | Legacy import as built (story 404): board titles `Shot <id>`; an absent move `dur`, `dx`, `dy` or `angle` written as 0 with 3 steps, an absent camera `over` as 400 ms, an absent `foreground` as true; method `layered` + `s2v` with lines and `layered` + `i2v` without; empty `seeds`; `mix.line_rms_dbfs` -22; `method.unavailable` a warning on write and `unavailable` at `queue_run`; integral floats read as integers | leaving the renderer's assumed values implicit on canonical boards |
| P-34 | Service adapters as built (story 425): request limits (Kokoro text up to 1000 characters; image sizes multiples of 8 from 64 to 4096, prompts up to 10 000 characters; transcript WAV up to 64 MiB); a read-only ComfyUI queue check; upload names from the PNG's hash; read-only ledger `list`, `find` and `fetch_asset`; a 300-character redacted stderr tail; one render per process | the PoC's random upload names (ComfyUI overwrites by name); reading a haynes-ops checkout at run time |
| P-35 | Legacy loader as built (story 378): stricter than the PoC (`line` with `lines`, `after_line` without `offset`, `at` with `after_line`, a later line's `start`, a silent shot's `tail` and an fps other than 24 are refused); absent values stay absent in the legacy model, with only the gap and revision defaults applied and flagged; shot times compared at the record's 4 decimals | the PoC's silent defaults and precedence |
| P-36 | Whole-frame adapter as built (story 427): whole 121-frame clips chained on a shared, dropped boundary frame, `1 + ceil((needed - 121) / 120)` clips, at most 3 (Q-427-2, the contract owner); chained seeds `i2v:frame + k`; no stretch; one clip-set artifact (`studio.whole-frame-clips/v1`) with its media stage `whole_frame_media-<hash>`; a clip of the same aspect scaled with Lanczos, another aspect refused; compositor `studio.wholeframe/1+pillow-<v>`; move and camera cues refused (camera: Q-427-1, the contract owner); `check_board`; `wholeframe.unsupported`, `wholeframe.chain_limit`, `wholeframe.clip_invalid` | `ceil(n / 121)` clips (one short at 242 and 362 frames); stretching a clip (breaks TIME-8's mapping); E0's unrelated seeds per chained clip; a longer chain (drift compounds); cropping or padding another aspect |
| P-37 | Motion records as built (story 457): the `motion` block on motion versions and its code rules; the cast entry's optional `motion_asset_version_id`; a motion version pins its identity, not its bytes; a timed clip keyed with `s2v_clip_key`; the identity adds the negative prompt, the still and what neither key covers; the decal's still is the clip's start image; an unpinned set without a promoted loop is a static plate; a doll clip is `motion_clip`, a set loop `set_loop`, never both; E0 clips by source key `legacy:winter-menu-video-e0:...`; the `motion.*` codes | pinning a motion version by its bytes (the same clip keyed another way could not become a new version); the loop key for timed clips (it has no drive track); an unpinned set without a loop as an error |
| P-38 | Sound and master as built (story 841): the limiter's delay compensated (`latency=1`); MP4 movie timescale 48 000; a sound cut exactly at the film's end, not faded (Q-841-01 open); short sounds, short beds, fades under 1 ms and a limit outside 0.0625 to 1 refused (`mix.input_invalid`); no loudness gain on a silent programme; float32 to one 24-bit quantization; levels and fades on line spans; the placement record (`studio.mix-placement/v1`, kind `mix_placement`); the check result (`studio.check-result/v1`); the seven sound checks, true peak at most the target + 1 dB; mux settings a full key input; TIME-10 checked from the story beside the key; `mix.input_invalid`, `mix.master_invalid`, `mix.check_failed` | legacy's uncompensated limiter (sound 1.98 ms late, its last 95 samples lost); the default timescale 1000 (recorded audio rounded down to a whole ms); legacy's absolute -2.5 dBTP; cutting 100 ms after the film's end; a 16-bit premaster; crashing on short inputs as legacy did |
| P-39 | Layered adapter as built (story 426): keyed frames as one APNG with its `studio.keyed-frames/v1` record; the keyer keyed as `<keyer>@<build>`; the decal gate on every use, over the frames the board shows, with a check result, and a weak artifact cached but never drawn; drive tracks at the takes' rate; the S2V clip as the cached artifact with its provenance stage (`studio.s2v-clip/v1`); a speaker's start image and keying from her loop, protect boxes included, gate 0.8 (Q-426-1, the contract owner), her loop at the S2V size; a library timed clip only from the board's drive track with its seed (Q-426-2, the contract owner); every cast entry resolves a loop, speakers included; single framing read from the preset's values; one camera cue per board, starting at its anchor; exact pose times; compositor `studio.layered/1+pillow-<v>+numpy-<v>`; the D51 photo's named inputs and PNG; a plan without motion records keeps story 380's placeholders and cannot be built; speakers bounce too; the `layered.*` codes | the PoC's folder of uncropped PNGs (frames and scores can part); gating once when keying (a floor belongs to a record); 16 kHz drive tracks (cannot hold `F / 24` s exactly); keying without protect boxes, or a separate speech keying (Q-426-1 (b), (c)); pinning a speaker's timed clip, or importing E0's drive tracks (Q-426-2 (b), (c)); the PoC's camera from the shot's first frame and float pose times |
| P-40 | Contract catch-up as built (story 849): `conditional` is a checked value with a non-null `note`; the register lookup gives `conditional` only for an entry with `outputs_commercial_use: conditional` and an `unknown` object, keeping its note word for word; `current_engine` is an opt-in keyword of `Library.facts` and `voice_facts`, comparing every take, with or without a story; `agent_session` fields are non-empty strings and nothing else; the board bounds reported as `schema.invalid` with TIME-5 in the message; a fractional lead over the bound reports both `time.not_integer_ms` and `schema.invalid` | a `conditional` without its conditions; rewriting the register's values in code; comparing the engine on every call before any caller can name the current one |
| P-41 | Wan clip clients as built (story 842): the API's own `generate()` under its lease, the in-pod snippets the PoC's bytes; request limits (sides multiples of 32 from 64 to 1280, image-to-video length 4k + 1 up to 121, speech-to-video at most 3 chunks, prompts up to 4096 characters, inputs under 20 000 000 bytes); a required append-only journal held by a sibling lock and the file's own lock; a job blocks until its ledger, its collected clip, a certain no-submission or a person settles it; a halt latched on foreign work, extended never replaced; a second cool probe before submission; exactly two approved GPUs; exact frames and rate; `recover` by `graph_sha256` on the job; the `studio-e0` upload names and presets kept; `adapter.job_failed`, `adapter.competing_work`, `adapter.journal_failed` | the PoC's process memory (a restarted build would forget a job in flight); a missing ledger as proof that nothing ran; resubmitting after a lost answer; a tamper-proof journal (whoever can write the run directory can already clear it) |
| P-42 | Builds as built (story 406): the run fields `phase`, `transitions`, `error` and the board stage's fields; each run version a completed stage, create-only as a compare-and-set; the run number from the production's run count; a service-phase run ended `cancelled` (Q-406-1, the contract owner); the service phase makes only what needs a service, the offline phase uses no recognizer; a story that cannot be pinned makes no run, any other refusal is a failed run; the local pass and the early mix before any clip request; `deliver` makes its own proxy; the transcript check a cached check result, version 1, on 16 kHz mono; engines matched to the register, the most restrictive licence, `unregistered-...` when unmatched, a null licence for a writer engine only; credits without hardware unless reported; `Toolchain.compositor` per method layer; `build.*`, `run.transition`, `run.unknown` | a run `succeeded` without a delivery; asking a clip source before every local check has passed; a new state for a completed phase (Q-406-1 (b)) |
| P-43 | Proxy length and legacy voice tracks as built (story 857): the proxy muxed at movie timescale 48 000; with a story a board voice without a track is stale (the contract owner's decision); `studio voice` assembles it, reusing each held take after its hash check and speaking only a take the store does not hold, on the asset `board-voice:<board_id>`; a take of a version with a track must still be held; a fetch of other bytes is refused, while `studio voice`'s own fetch answers none for a blob that does not verify, so a damaged legacy take is spoken again and stays for `store doctor` | loosening the proxy's exact audio check; calling a trackless legacy voice current (the build could not use it); speaking every legacy line again |
| P-44 | Private import as built (story 846): reading the volume directly, folder by folder by descriptor with `O_NOFOLLOW`, rather than over `GET /videos/<id>/file`; `REFUSED <reason>` with exit status 3 and the nine `adapter.source_*` codes; sources tried in row order, a refusal moving on and anything else a stop; hashes with no library version in the production's folder; measured `bytes` with the recorded size on re-import; rows not read on purpose `absent` with a reason (Q-846-01); the drive tracks read (Q-846-02); `--authorized-by` and a new `--out` required; principal `cli`, command `studio private import`; the snippets under `python3 -I`; `import.failed`, `adapter.volume_unexpected` | a fourth `not_read` status; retrying a failed read another way; trusting the store's one `verify` before calling a held blob verified |
| P-45 | Live clip sources as built (story 851): the journal `<store root>/wan-journal.jsonl`, one per store; the client made on the first clip request; a journal job settled first by `recover` for the same request, else `build.wan_unsettled`; every client refusal a `held` run; each chain clip kept on collection as `wan_chain_clip`, keyed by its request; every request checked before the mix; the profile must be one the client makes (`build.live_unsupported`); `--wan-story` required outside `--offline`; `--dry-run` a recorded run ended `cancelled`; the E0 estimate rule; the whole Wan record as `extra.wan` | a journal per run (a later run would not see an earlier one's job); `failed` for a refusal that may need reconciliation; caching a chain only when whole (a stop re-rendered its first clip) |
| P-46 | The first live build's working choices (story 428): E0's seeds in the draft, as no server assigns seeds yet; one speech prompt for every doll (Q-428-4 open for Tom); the 240 px off-frame limit kept for keyed frames, with board 7's `closeup` slot moved to `x` 0.55 (Q-428-2, the contract owner); a weak lettering track answered by a re-roll by seed edit, the weak clip kept (Q-428-3, the contract owner); the offline phase in the session pod while the render worker cannot run the package | no limit for keyed frames, as E0's film had; an agent lowering a decal floor; installing into the cluster to use the render worker |
| P-47 | Six small fixes as built (story 860): a stopped run (`failed`, `cancelled`, `held`) keeps the board stages it completed; a reused layered segment lists its decal gate results, reported and never a second gate, and a run check may name its `slot`; `store doctor` reports the journal's two root files under `journal`; one register file entry per engine for a file two engines load; the import's summary reads voices as the library does, while its stored story and map keep their own derived values (O-860-1, the contract owner) | `stages: []` on a stopped run (its work in no record); running the gate again on a reused segment; an `engines` list on a register file entry (changes the register's shape and its readers); rewriting what `studio legacy import --out` stores |
| P-48 | The command line's operator when an agent session runs it (O-428-1, the contract owner): the E1 records written as `{kind: human}` under the stand-in issuer `https://agent-session.invalid/dev-env` are kept as they are: that issuer marks them, and they are never presented as a person's act; an `agent_session` operator comes later (story 864) | rewriting the records already written; letting an agent session sign in as a person |
| P-49 | GPU heat (the contract owner's practice): no temperature stop line of the coordinator's own in GPU work orders; each job's peak recorded; the API's lease, the client's cool-idle start check and the unknown-work checks as the guards. Its recorded reason is a relayed, unverified message (story 428, comment 8409), not Tom's ruling; Q-428-6 asks him to confirm it | a fixed stop line such as story 428's 88 C (taken from E0's 84 to 88 C range, not a platform limit) |

## 18. Decisions and dissent

Where sources disagree, which this contract follows and why.

| Topic | Sources in tension | Contract | Why |
|---|---|---|---|
| Format length | 0003's open question; review question 1 | Warn, allow Build; platform maxima at release (D45) | D45 answered it on 2026-11-05 |
| S2V as premium or default | findings.md ("premium shot") | Default for doll talking boards (D24) | D24 and the S2V addendum are later |
| Whole-frame S2V | findings.md E0.4 clip; review H4 and story 427 | `unavailable` | one undelivered clip is not a buildable adapter ([section 5](#5-method-capability-matrix)) |
| Delivery fps and pad | mockup 25 fps and 0.25 s | 24 fps; legacy lead and tail | the PoC delivers 24 fps; review M2 |
| Picture clock | legacy film clock (fire, layered loops) | board clock | selective cache (review H3) |
| "Story" | manifest field = tracker URL | domain story; legacy field kept as `origin.tracker` | D27, D28 |
| "Production" | ledger `edited_production`, `productions/<job>/` | themed collection; legacy production becomes a delivery | D28, review H1 |
| Approval gates | 0003 format "gate settings"; old runbook gates | go-live only | D29 |
| Store | `deliver.py` to the Wan PVC ledger; D4's RBD | D39 NFS and Postgres; legacy read-only | D39, D41, review H5 |
| Logins | D5 (no human logins) | Authentik OIDC | D41 amends D5 |
| Decal threshold | 0.8 min ECC as a gate | a check with recorded overrides; thresholds belong to E2 | findings-layered.md: ECC is a weak proxy |
| Python version | studio-render 3.12, session pods 3.11 | floor 3.11, runtime 3.12 | both must run the tests and the worker |
| Package name | `poc/studio.py` | `haynes_studio` | avoids shadowing |
| Credits | review C3 ("video/sound provenance") | video, voice and sound roles | D44 names the voice models explicitly |
| Licences at release | Q-01's recommendation (a): block on `unknown` or `noncommercial` | recorded, block nothing | D49: research and personal use |
| Layered board photo | Q-03's recommendation: a preview now, the composite later | the composite from the start | D51 (coordinator's reading) |
| Legacy cuts and go-live | Q-04's recommendation (b); D1's sign-off of r4 | canonical runs only | D52 |
| Agent builds | Q-02's interim: people only | agent keys may hold `runs:queue` | D50 (coordinator's reading) |
| Chained whole-frame clips | E0: unrelated seeds per chained clip; shot 6 held its last frame | seeds `i2v:frame + k`; a second clip, nothing held | P-36, P-05 |
| Speech clip keying | E0 keyed A's three speech clips without her loop's eye-protect box, and six clips at floors other than their loop's | the loop's keying, protect boxes included, gate 0.8 | Q-426-1 (the contract owner): one rule for every clip the build makes; a floor is a judgement of one clip |
| Limiter delay | legacy masters: sound 95 samples (1.98 ms) late, last 95 samples lost | delay compensated | TIME-7 placements hold only so (P-38) |
| Sound past the film's end | legacy: cut 100 ms after the end | cut at the last sample | TIME-10; a fade at the cut is Q-841-01, open |
| Media kind change and idle dolls | section 4's row before story 426: every clip and keyed frame rebuilds | an idle doll's pinned loop and keyed frames are reused | loops are library sprites the layout places (story 426) |
| What `held` covers | section 8: unknown work on the lease, an ambiguous external job | every refusal of the Wan clip client, a busy lease and hot GPUs included | story 851; the API may later requeue a run that never reached a submission (E3) |
| A legacy board voice | story 405's planner: current (its signatures match); story 406's build: unusable (no track) | stale for a build until `studio voice` assembles it | the contract owner's decision, built by story 857 |
| Wan ledgers and outputs | section 8 before story 842: the Wan PVC is never written | engine jobs create their own ledgers and outputs; delivery ledgers and `productions/` are never written | the sanctioned route is the API's own `generate()` (story 842) |
| Off-frame limit for keyed frames | `poc/edit.py`'s 240 px assert for still cutouts; E0's layered film checked none for keyed frames | 240 px for keyed frames too | Q-428-2 (the contract owner), until the layout editor |
| A legacy import's derived values | the import's own facts (every legacy voice current); the library's facts for a build (stale without a track) | stored documents keep the import's values; the summary and the library's facts speak for a build | O-860-1 (the contract owner) |
