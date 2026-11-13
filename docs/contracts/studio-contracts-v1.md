# Studio contracts v1

Story [423](https://work.haynesnetwork.com/work_packages/423) (E1.9, review R01), epic
[372](https://work.haynesnetwork.com/work_packages/372). Base: `main` at `aa73c4e`.
**Status: ratified by the E1 coordinator on 2026-11-13, at the review of PR 37, as the
contract E1 is built against.** That is the coordinator's technical agreement, not Tom's
acceptance: every `P-nn` stays a proposal Tom may overrule, and every `Q-nn` stays held
for him. Nothing here is implemented. Stories
[378](https://work.haynesnetwork.com/work_packages/378),
[404](https://work.haynesnetwork.com/work_packages/404),
[424](https://work.haynesnetwork.com/work_packages/424) and later E1 to E9 stories build
against the commit that ratifies it. Examples are in [`examples/`](examples/); the
[README](README.md) explains their format.

Every rule carries its source:

| Label | Meaning |
|---|---|
| **D*n*** | Tom's decision in [proposal 0003](../proposals/0003-studio-plan.md). Later rulings beat older prose. |
| **Evidence** | An E0 measurement, with its file under [`titles/the-winter-menu/video-e0/`](../../titles/the-winter-menu/video-e0/). |
| **Legacy** | What the PoC code or a Winter Menu manifest does today (file named). |
| **Proposal P-*nn*** | This contract's choice, with the alternative it rejects. Not Tom's decision. The coordinator ratified each at review as the working choice; Tom may overrule any. |
| **Held Q-*nn*** | An owner choice only Tom can make. Options and a recommendation are in [section 16](#16-held-owner-questions). |

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
| manifest `job_dir` (`~/studio-jobs/...`) | Private, non-portable input path | Not imported. Story [425](https://work.haynesnetwork.com/work_packages/425) owns the private-input recovery map. |
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
| manifest `sfx.<name> {file, trim, gain_db, source, rejected[]}`, `beds.<name> {file, gain_db, source}` | A generated sound, its trim and its level. `gain_db` is a **target RMS level** in dBFS, not a gain: `edit.audio` scales the clip to it after trimming | `sound` asset version (file hash from `timeline.json`, provenance from `source`: service, job, seed, seconds, steps, prompt). `trim` and the level move onto each cue as `trim_ms` and `level_rms_dbfs`. `rejected[]` entries become hidden sound candidates with provenance and no bytes. |
| `moves[]` | Scripted whole-doll moves | `move` cues |
| `camera {zoom, over, center}` | Push-in, ease-out over `over` seconds | `camera` cue |
| `beds` | Looped ambience under the film | Story `beds[]`, film clock |
| `note` | Free text | `notes[]` |
| `cast {slot: {name, voice}}` | Character name and Kokoro stock voice | Story `cast[]`; voice becomes a `voice` asset version. |
| `set` (`image`, `foreground_edge`, `foreground_feather`, `fire`, `note`) | Set still, log edge, procedural fire | Story `set`; `fire` kept as `legacy_fire` (the rigid renderer only; Wan animates fire); `note` kept as text. |
| `motion` (idle, hop, tilt, shuffle) | Talk bounce and wobble style | Story `motion_style` |
| `frame {width, height, fps}` | Delivery size | The media kind's profile; 1080x1920 at 24 fps is `short`. |
| `master`, `asr_tolerances`, `asr_tolerances_note` | Loudness target, transcript tolerances | Story `mix`, story `checks` |
| `timeline.json` (`total_s`, `shots[] {shot, start_s, end_s, frames}`, `audio[] {kind line, sfx or bed, start_s, end_s, sha256, ...}`, `premaster_headroom_db`, `master_gain_db`) | Recorded timing (`start_s` 4 decimals, audio 3) | The imported run's timing record, read-only; the fixture story 378 compares against (TIME-12). |
| `shots.json`, `validation.json` (including `human_review`), `dialogue-transcript.json` | Render and check records | Imported run stage and check records, verbatim and read-only. `human_review` is a historical gate note, not a go-live approval. |
| ledger `preset`, `provenance {..., human_approval}`, `assets[]`, `created_at` | How the delivery was made, and every delivered file | Delivery `legacy` block: `preset` and `provenance` verbatim, `assets_ref` to the evidence file; `created_at` as ISO time ([example](examples/valid/delivery-legacy-r4.json)). |
| `speech.json` `service` | The TTS service | `board_voice` provenance `engine` |
| `provenance` (free text), `revision_note` | Notes | Imported run notes; `revision_note` becomes feedback in E9.3. |
| `speech.json` lines `{shot, k, file, duration_s, sha256}` | One WAV per line | Takes inside a `board_voice` asset version, with offsets ([example](examples/valid/asset-version-board-voice.json)). The legacy track was never assembled: `track: null`. |
| `prompts.json`, `cutouts/` | Image provenance, keyed RGBA stills | `cast` asset versions with provenance ([example](examples/valid/asset-version-cast.json)) |
| E0 `keyframes.json` | Composed first frames per shot | Imported `photo` versions on the r4 boards |
| E0 Wan `job_id`, clip records | Engine jobs and clips | `engine_job_id` in provenance; clips become run artifacts or `motion` assets (story [457](https://work.haynesnetwork.com/work_packages/457)). |
| Rigid cutout puppetry (`poc/edit.py`) | The renderer of r1 to r4 | `method: {legacy: rigid_cutout}` on imported runs only. Not a canonical method (D6). |

Re-import is idempotent: every imported record carries a `source_key` such as
`legacy:the-winter-menu-r4:shot:8`, unique per record type, and a second import returns
the existing IDs (P-01).

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
- Fields under `derived` are computed by the server, returned on reads and rejected on
  writes.
- The legacy manifest has no `schema` field. Story 378 documents it as
  `legacy.manifest/v1`, detected by shape (`shots`, `frame`, `job`), covering r1 to r4.
- JSON Schema files (draft 2020-12) are the normative form, owned by 378 (legacy) and
  404 (canonical). This document and its examples are what those files must agree with.

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
  `{kind: cli, command, operator}`, where `operator` is a human principal.
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
| `lines[]` | `{id, speaker, text, gap_before_ms}` | ordered; text 1 to 1200 characters (mockup); TIME-2; speaker per VOICE-1 |
| `timing` | `{lead_ms, tail_ms, hold_ms}` | spoken: lead and tail, hold null; silent: hold only (TIME-3 to TIME-5) |
| `voice` | `{style, current_version_id}` | style `cast` or `narrator`, null on a silent board |
| `photo` | `{current_version_id, prompt, input_asset_version_ids}` | prompt up to 1800 characters; inputs are the composer's assets |
| `cast[]` | `{slot, asset_version_id}` | draw order; one still per slot (expression) |
| `layout` | `{preset, foreground}` | preset must exist in story `layouts` |
| `method` | `{layer, motion}` | section 5 |
| `seeds` | `{"s2v:<slot>": int, "i2v:frame": int}` | section 4 |
| `cues[]`, `notes[]` | section 6 | |
| `drafted_by` | principal | an agent principal shows the mockup's "Agent draft" badge |
| `origin` | `{source_key, legacy_revision, legacy_shot, manifest}` or null | |
| `derived` | `timing_state` (`timed`, `untimed`), `content_ms`, `frames`, `film_start_frame`, `voice_state` (`not_needed`, `absent`, `generating`, `current`, `stale`), `photo_state` (`absent`, `generating`, `current`, `stale`) | read-only; absent and stale assets are explicit, never inferred from nulls |

A job (`studio.job/v1`) is `{id, kind (voice, photo, asset_candidate), target_id,
input_signature, status (queued, running, succeeded, failed, cancelled),
result_version_id, result_is_current, error}`. A job that finishes after its inputs
changed is `succeeded` with `result_is_current: false` (VOICE-4).

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
  (`time.negative`). New boards
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
  (`DollClip.frame_at` in `poc/layered_film.py`).
- **TIME-8a Loops.** Reusable `motion` assets (doll clips, set loops: 121 frames at 24 fps)
  play ping-pong under boards of any length: board frame *n* shows source frame
  `pingpong(n + phase, N)`, with period `2N - 2` and the phase from
  [section 4](#4-cache-clocks-and-invalidation). They are never "short". Legacy
  (`pingpong()` in `poc/layered_film.py`, which indexed by film frame).
- **TIME-9 Speech-to-video request.** Each on-screen speaker gets a drive track of exactly
  `F / 24` seconds: her lines at their offsets, silence elsewhere. Requested length
  `L = 4 * ceil(F / 6) + 1` (that is, the `F / 24 * 16` source frames rounded up to a
  multiple of 4, plus 1; the formula is normative); if `L > 77`, `L = 77 * ceil(L / 77)`.
  `L` must be at least the frames TIME-8 needs. Legacy (`poc/s2v.py` with pad 0, as the
  layered S2V film used it).
- **TIME-10 Cues.** A cue's resolved start lies in `[0, board length)`
  (`cue.out_of_range`); on an untimed board the check runs at `queue_run`. A sound may run
  past the cut and is cut at film end; both are recorded. Legacy (`edit.audio`).
- **TIME-11 Conservation.** Sum of board frames = film frames = decoded master frames;
  master duration = frames / 24; mix length = frames x 2000 samples; every line ends at
  or before `content_ms - tail_ms` of its own board. Any mismatch fails the run.
- **TIME-12 Legacy adapter.** Imported runs keep their recorded values. Canonical
  arithmetic reproduces every r4 frame count (table below); story 378 checks r1 to r3.
  Legacy rounded shot starts to 0.1 ms before placing samples, so legacy and canonical
  line placements may differ by up to 3 samples (0.06 ms); cross-checks allow 1 ms.

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
  carries from one board to the next.
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
toolchain digest (P-07).

| Artifact | Clock | Key inputs |
|---|---|---|
| Voice take | none | TTS model digest, voice ID, NFC text, speed, sample rate |
| Board voice track | board | take hashes, lead, gaps, mix rate, assembler version |
| S2V drive track | board | board voice track, speaker, board frames |
| S2V clip | source | drive track, start still, prompt, negative prompt, seed, profile (model files, LoRA, steps, cfg, size, chunk), adapter version |
| Doll clip or set loop (library `motion`) | source | still, prompt, seed, profile |
| Whole-frame I2V clip(s) | source | photo, prompt, seed, profile, requested clip lengths (set by the frames needed and the chain policy of story [427](https://work.haynesnetwork.com/work_packages/427)) |
| Keyed and decal frames | source | clip, key thresholds, protect boxes, still, decal box, decal version (Legacy `DollClip.cache_dir`) |
| Board picture segment | board | method, layout preset values, cast stills, clip and keyed hashes, phases, motion style, voice envelope when any line is spoken, move and camera cues, frames, frame size, fps, foreground edge, compositor digest, encoder settings |
| Film picture | film | ordered segment hashes |
| Mix | film | ordered voice tracks with `F[k]`, sound cues resolved to samples (sound hash, trim, level), beds, line RMS, loudness target, mixer digest (including its fades) |
| Master / proxy | film | picture + mix + mux settings / master + proxy profile |
| Check result | none | artifact hash, check version, thresholds |

### Invalidation set per edit

"Reused" means the key is unchanged, so the cached artifact is used. The table is the
expected result of the keys; tests in story [380](https://work.haynesnetwork.com/work_packages/380) assert it.

| Edit | Pre-build assets | Board *k* picture | Other boards' pictures | Film picture, mix, master, proxy |
|---|---|---|---|---|
| Line text, line added or removed | new voice version; TTS only for changed takes | every S2V clip whose drive track changes: the edited line's speaker, plus every speaker with a later line when a take's duration changes; all S2V clips if frames change; segment | reused | rebuilt |
| Line speaker | takes of that line | S2V clips of old and new speaker, plus every speaker with a later line when the new take's duration differs; all if frames change; segment | reused | rebuilt |
| Lead or gap | new voice version, no TTS | S2V clips of every speaker with a line after the edited point (a lead edit moves all); all S2V clips if frames change; segment | reused | rebuilt |
| Tail | none | only if frames change: S2V clips and segment | reused | rebuilt if frames change, else reused (no key changes) |
| Hold (silent board) | none | segment; whole-frame I2V clips reused while the requested clip lengths are unchanged | reused | rebuilt |
| Reorder boards | none | reused | reused | rebuilt (film offsets move) |
| Add or remove a board | that board's | that board's | reused | rebuilt |
| Method (layer or motion) | none | clips and segment | reused | rebuilt |
| Seed | none | that clip; segment | reused | rebuilt |
| Cast still version | photo inputs marked changed where used | clips from that still; segments of every board using it | same rule on those boards | rebuilt |
| Board photo version | none | whole-frame: I2V clip and segment; layered: reused (see Q-03) | reused | rebuilt |
| Layout preset values | none | segments of boards using it | same | rebuilt |
| Move or camera cue | none | segment | reused | rebuilt |
| Sound cue, bed, level, loudness target | none | reused | reused | mix, master, proxy only |
| Note or title | none | reused | reused | reused (the snapshot differs; artifacts do not) |
| Story motion style | none | every segment with bounce | every segment with bounce | rebuilt |
| A cast slot's voice | every take of that speaker | per board as "line text" | same | rebuilt |
| Toolchain or profile digest | as used | every artifact that tool made | same | rebuilt |
| Media kind frame size or fps | none | everything | everything | rebuilt |

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
| `whole_frame` | **Unavailable.** See below. | **Buildable.** Evidence: the 15-clip whole-frame film ([findings.md](../../titles/the-winter-menu/video-e0/findings.md)); D22: not rejected. Known drift in groups and three-quarter poses; chaining compounds it. Adapter: [427](https://work.haynesnetwork.com/work_packages/427), which owns the chain or stretch policy for boards over 121 frames. |

How each buildable cell uses its inputs:

- **Layered + S2V:** every on-screen speaker gets one S2V layer from her drive track
  (TIME-9); every other cast member on the board gets an I2V doll layer (a library
  `motion` asset); the set is a set loop. Seeds `s2v:<slot>`.
- **Layered + I2V:** every cast member gets an I2V doll layer; talk bounce comes from the
  board voice envelope (Legacy `edit.motion`).
- **Whole-frame + I2V:** the start image is the board's current photo version
  (`photo.absent` without one). Seed `i2v:frame`.

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
| `asset.capability_mismatch` | invalid | a layered cast entry whose version lacks `rgba_cutout` or `keyed_layer` | review M6 |

"Invalid" fails on write and needs the board changed. "Unavailable" is a valid design
the studio cannot build yet.

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
  fades in over 0.5 s; lines fade 5 ms at each edge.
- An anchor is `{at_ms}` from board start, or `{after_line_id, offset_ms}`; the line must
  be on the same board (`cue.anchor_line_missing`), and the resolved start must lie inside
  the board (`cue.out_of_range`, TIME-10). A `move` names a slot placed on the board
  (`cue.slot_not_on_board`). Legacy line indexes become line IDs
  on import. Moves add up in order, as in Legacy `edit.motion`.
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
`noncommercial` or `unknown`), `attribution_required`, `checked_at`, `checked_by`, `note`.
A licence moves from `unknown` to a checked value by an appended record; content and
provenance never change. Unknown licences never block Build. What they block at release
is Held **Q-01**. Proposal 0003 lists Stable Audio, Kokoro and Qwen terms as unchecked.
The S2V model files from haynes-ops PR 4625 are Apache-2.0; the lightning LoRA's terms
(PR 4634) are not recorded in this repository.

### Runs

`provenance` on every run ([example](examples/valid/run-succeeded.json)):

- `toolchain`: studio commit, image digests, Python version, ffmpeg version and build,
  adapter versions.
- `engines[]`: `key`, `role`, `name`, `files[]` (each `name`, `sha256`, `licence`),
  `licence` (the most restrictive of its files), `profile`, `hardware`.
- `inputs_externally_generated`: asset versions with the D42 marker, for the E9
  disclosure check.
- `usage`: frontier tokens recorded per production (D8, D40); `null` means unknown,
  never zero.
- `public`: `ai_generated: true` always (D43) and `credits[]` of `{engine_key, text}`,
  where each `engine_key` names an engine with role `video`, `voice` or `sound` and the
  text names it and the hardware it ran on (D44: "the local video and
  voice models and the 3090s"). Image, writer and composite engines, and people, never
  appear (`credit.outside_video_sound`); they stay in private provenance (review C3).

Media on NFS is not backed up (D47). Provenance in Postgres must therefore be complete
enough to regenerate: inputs by hash, prompts, seeds, model digests and profiles. A
regenerated artifact is a new version with a new hash (GPU output is not bit-exact);
nothing silently repoints a lost hash.

## 8. Runs, deliveries and the store

### Runs (D30)

- `queue_run` takes the story's `revision` (stale: `conflict.revision`) and an
  `Idempotency-Key`. Preconditions:
  every spoken board has a current voice (`voice.absent`, `voice.stale`); every
  whole-frame board has a current photo (`photo.absent`); no board method is invalid or
  unavailable; no voice or photo job is in flight for an included board
  (`asset.generating`).
- The snapshot is the story and its boards by value plus every resolved asset version,
  pinned by content hash, or by `definition_signature` for definition-only versions
  (`voice`), or by `input_signature` and take hashes for `board_voice` versions. It holds
  no run ID or time, so the same draft always gives the same hash. It is stored as a
  canonical-JSON blob ([run-snapshot.json](examples/valid/run-snapshot.json);
  the file is pretty-printed, its hash is over the canonical form). The run row stores the
  blob's `sha256`. Draft edits never change a queued, running or finished run.
- States: `queued` (with `wait_reason`: `lease_busy`, `gpu_unavailable` when talosw01 is
  down, D41) → `running` → `succeeded`, `failed` or `cancelled`. `held` is a safety stop
  (unknown work on the Wan lease, an ambiguous external job) that resumes only after
  reconciliation, never by blind resubmission (story
  [410](https://work.haynesnetwork.com/work_packages/410)). `imported` marks legacy runs.
  Terminal states are immutable. Every transition records time, actor and reason.
- An estimate comes back on queue, with a range, its basis and `uncertain: true` (D27).
- Check overrides (for example a decal min-ECC below 0.8 that looks right by eye, as in
  E0) go through `record_check_override` and are recorded per artifact with actor and
  reason, never silently; release checks cannot be overridden
  ([findings-layered.md](../../titles/the-winter-menu/video-e0/findings-layered.md)).

### Deliveries

`studio.delivery/v1` ([new](examples/valid/delivery.json),
[legacy r4](examples/valid/delivery-legacy-r4.json)): master (H.264 and AAC in MP4, the
media kind's frame size at 24 fps) and phone proxy (H.264, 720x1280, under 25 000 000 bytes
for a 60 s fixture, per story [381](https://work.haynesnetwork.com/work_packages/381);
P-10), each with `sha256`, `bytes`, `frames`, codecs and `locator`, plus `verification`
(decoded frames equal expected, hashes re-read). Legacy deliveries use adapter
`legacy_wan_ledger`, read-only.

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

### No purge (D17)

Nothing deletes blobs, staging leftovers, runs or versions automatically. A
`store doctor` command may report orphans and staging leftovers; removing them is a
user action. User deletion, when built, tombstones records; approved or published runs,
and every asset version their snapshots reference, cannot be tombstoned. Removing bytes is
out of scope for E1 to E3 (P-11). The Wan PVC (`ai/wan-video`) ledger and
`/workspace/output/productions/` are legacy inputs that product code never writes
(review H5).

## 9. The library and version IDs

- **Asset** (`ast_`): `kind`, `name`, `labels`, `attributes` (for example
  `character_slot`, `expression`), `scope` (`production_id`, or null for the global
  library). The library is scoped by labels (D16); labels are mutable metadata on the
  asset, outside version content (P-21).
- **Asset version** (`asv_`): `asset_id`, `number` (1, 2, ... per asset), `content`
  (`sha256`, `bytes`, `media_type`, size, `locator`, or null for definition-only kinds),
  `provenance`, `licence`, `capabilities`, `state`. Content, provenance and capabilities
  never change (D15).
- **Kinds:** `cast`, `costume`, `set`, `prop`, `sound`, `motion` (set loops and doll
  clips), `voice` (a stock TTS voice; no bytes), `character_card` (reserved for E2),
  plus board-scoped `photo` and `board_voice`.
- **Capabilities:** `rgba_cutout`, `keyed_layer`, `mask`, `opaque_photo`, `opaque_plate`,
  `motion_clip`, `set_loop`, `tts_voice`, `sound_effect`, `sound_bed`, `board_voice`. An
  opaque photo is not a render-ready layer (review M6).
- **States:** `candidate` (generated, hidden from pickers), `promoted` (explicit and
  idempotent), `board` (board-scoped photo or voice). Promoting a board photo creates a
  library version with `origin: derived` that points at the board version. Rejected
  candidates stay, hidden (D17).
- **Pinning:** boards and snapshots name asset version IDs, never "latest"; only pickers
  resolve "latest".
- **Import:** the same bytes with the same `source_key` return the existing version;
  changed bytes make the next `number`.
- **Filters:** kind, labels, production, board. The board filter is the set of versions
  that board references (D32, D34).

## 10. Pre-build voice policy (D33)

- **VOICE-1** Voices are stock TTS voices only, Kokoro-82M v1.0 stock IDs today (P-22;
  `voice.not_stock`). AGENTS.md forbids a real person's voice, and story 405 excludes
  cloning; stock-only is this contract's way to guarantee both. Each cast slot names
  a `voice` asset version; narrator lines use the story's narrator voice. Speakers are
  cast slots, or `narrator` on a board whose style is narrator
  (`voice.speaker_not_in_cast`).
- **VOICE-2** A board voice version holds one take per line (with `signature`, `sha256`,
  `samples`, `duration_ms`, `offset_ms`) and the assembled track. It is made while
  editing, before any Build, and can be played and regenerated.
- **VOICE-3** Take signature: `sha256` of canonical `{engine, model digest, voice_id,
  text (NFC), speed}`; legacy imports had no recorded digest and use the model name.
  Version signature: takes plus lead and gaps. Only takes whose signature changed go back
  to TTS; a lead or gap edit only re-assembles.
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
  format may change them later.
- **VOICE-8** The transcript check (ASR with the story's tolerances) is a technical check
  recorded on the run. It is not a gate (D29).

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
- Preconditions: run `succeeded` (whether an `imported` legacy run qualifies is Held
  **Q-04**), delivery verified, release checks recorded with the
  approval (AI label on the platform setting and the description line, D43; rights;
  licences per Q-01; D44 credits).
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
| `runs:queue` | queue and cancel runs, record check overrides (Held **Q-02**: until Tom answers, no agent key holds this scope and these operations are for people only) |
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
| `record_check_override` (with a reason; never a release check) | `POST /runs/{id}/checks/{check}/overrides` | `studio_override_check` | runs:queue | 410, [450](https://work.haynesnetwork.com/work_packages/450) |
| `get_delivery` | `GET /runs/{id}/delivery` | `studio_get_delivery` | read | 381, 409 |
| `approve_go_live` | `POST /runs/{id}/go-live-approvals` | | go_live:approve | 412 |
| `withdraw_go_live` | `POST /go-live-approvals/{id}/withdraw` | | go_live:approve | 412 |
| `record_publication` | `POST /runs/{id}/publications` | | human | [449](https://work.haynesnetwork.com/work_packages/449) |
| `claim_work`, `heartbeat_work`, `complete_work`, `fail_work` | `POST /internal/v1/work/...` | | worker | 410 |
| `login`, `callback`, `logout` | `/auth/...` | | none | 409, [432](https://work.haynesnetwork.com/work_packages/432) |
| `healthz`, `readyz` | `GET /healthz`, `/readyz` | | none | [434](https://work.haynesnetwork.com/work_packages/434) |

The legacy import is a CLI command (`studio legacy import <manifest>`), not an endpoint
in v1.

## 13. Stack pin

Each choice is a proposal (P-18) that the coordinator ratified at review. Nothing was
installed or built to make it.

| Layer | Pin | Reason | Rejected |
|---|---|---|---|
| Python | CPython **3.12** in images; `requires-python = ">=3.11,<3.13"`; CI tests 3.11 and 3.12 | studio-render already runs 3.12 with pinned requirements ([services.md](../reference/services.md)); session pods have 3.11.2, and tests must run there without installing an interpreter. No 3.12-only syntax. | 3.13 (no runtime has it); 3.11 only (the worker runs 3.12) |
| Package | distribution `haynes-studio`, import package **`haynes_studio`** under `src/`, CLI command `studio` | `poc/studio.py` is a module named `studio` that the PoC scripts import from their own folder; a package of the same name would shadow or be shadowed | package named `studio` |
| Build and lock | `pyproject.toml` with the **hatchling** backend; **uv** with a committed `uv.lock`, `uv sync --locked` | uv is in every session pod (0.13); one cross-platform lock; hatchling builds with plain pip in image builds too | Poetry (not installed, separate lock); pip-tools (per-platform files) |
| Runtime libraries | numpy, Pillow, PyAV, opencv-python-headless (decal, Apache-2.0), **imageio-ffmpeg** for the ffmpeg binary. A story that ports PoC code adds what that code already uses (scipy for keying, wyoming for the TTS and ASR adapters) to the lock | what `poc/` uses; session pods have no system ffmpeg | system ffmpeg |
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
  `-threads 2`, render `--workers 1`, no xdist, Playwright `workers: 1`, Vitest
  `--maxWorkers=2`; one suite at a time in a session pod. Timing tests use fake clocks,
  not sleeps.
- **Fixtures:** committed fixtures are text only: the public manifests and evidence JSON,
  and these examples. Synthetic media is generated at test time under pytest's `tmp_path`,
  outside the checkout, small (10 s or less, 360x640 unless a test needs delivery size; a
  60 s proxy fixture is allowed for 381). Service fakes (TTS, ASR, image, Wan, store)
  return deterministic synthetic bytes; frozen responses are JSON with hashes. No private
  media, real voices or tokens in CI; `check_no_media.py` stays.
- **Output:** no environment dumps, no tokens; failures print codes and paths.
- **Contract examples:** every file in `examples/valid/` must validate against the schema
  of its type, and every file in `examples/invalid/` must fail with its `rule` code and
  `expect` status, once the story that owns that type has landed its schema and validator
  (378: the legacy manifest; 404: production, story, board, timing and methods; later
  stories for assets, runs, deliveries and approvals, as their tracker items say). Until
  then story 424's harness reports the example as pending by type and never skips one
  silently. Today `check_syntax.py` parses JSON only under
  `titles/` and `poc/graphs/`; story 424 extends it to `docs/contracts/examples/`.
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
| `format.length_exceeded` | warning | 3 | [story-timing-summary](examples/valid/story-timing-summary.json) (valid) |
| `method.unknown` | invalid | 5 | [method-unknown-layer](examples/invalid/method-unknown-layer.json) |
| `method.s2v_needs_line` | invalid | 5 | [method-s2v-needs-line](examples/invalid/method-s2v-needs-line.json) |
| `method.s2v_needs_onscreen_speaker` | invalid | 5 | [method-s2v-needs-onscreen-speaker](examples/invalid/method-s2v-needs-onscreen-speaker.json) |
| `method.layered_needs_cast` | invalid | 5 | [method-layered-needs-cast](examples/invalid/method-layered-needs-cast.json) |
| `method.unavailable` | unavailable (at `queue_run`) | 5 | [method-whole-frame-s2v-unavailable](examples/invalid/method-whole-frame-s2v-unavailable.json) |
| `asset.capability_mismatch` | invalid | 5, 9 | |
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
| `voice.speaker_not_in_cast` | invalid | 10 | [voice-speaker-not-in-cast](examples/invalid/voice-speaker-not-in-cast.json) |
| `voice.not_stock` | invalid | 10 | [voice-not-stock](examples/invalid/voice-not-stock.json) |
| `approval.approver_not_permitted` | forbidden | 11 | [approval-not-human](examples/invalid/approval-not-human.json) |
| `approval.not_exact_run` | invalid | 11 | [approval-not-exact](examples/invalid/approval-not-exact.json) |
| `conflict.revision`, `idempotency.mismatch` | conflict, invalid | 12 | |
| `legacy.duration_with_lines` | invalid | 1 | [legacy-duration-with-lines](examples/invalid/legacy-duration-with-lines.json) |

## 16. Held owner questions

None blocks this document, story 378 or story 404. Each names the fields it affects.

**Q-01 What do unknown or non-commercial licences block at release?** Affects
`licence.commercial_use` and the release checks of stories 412 and
[449](https://work.haynesnetwork.com/work_packages/449).
(a) Release preparation blocks when any engine or asset in the video and sound chain is
`unknown` or `noncommercial`. (b) Block `unknown`; warn on `noncommercial`. (c) Record
only. **Recommendation: (a).** Build is never blocked either way (D29); the channel's
monetization is undecided, and a wrong publication is costly to undo. Tom can relax it
per licence once terms are checked. Under (a) today, the S2V engine stays blocked until
the lightning LoRA's terms are recorded, and Kokoro, Stable Audio and TI2V until theirs
are.

**Q-02 May agent keys queue builds?** Affects the `runs:queue` scope and
`studio_queue_run` (stories 429, 430,
[454](https://work.haynesnetwork.com/work_packages/454)). The layered S2V Winter Menu
took about 37 min plus 92 min of GPU wall time
([findings-s2v.md](../../titles/the-winter-menu/video-e0/findings-s2v.md)). (a) People only in v1. (b) A per-key `runs:queue` scope, off by
default, granted by Tom per production. (c) Any key with `draft:write`.
**Recommendation: (b).** It keeps D40's frontier loop and E5's shepherd possible without
giving every drafting key GPU spend. The same answer covers `studio_cancel_run` and
`studio_override_check`, which the operations table puts under the same scope. Until Tom
answers, (a) applies: nothing is granted to a key by default.

**Q-03 For a layered board, what is the reference photo?** Affects `board.photo`, the
invalidation row "Board photo version", and stories [417](https://work.haynesnetwork.com/work_packages/417), [418](https://work.haynesnetwork.com/work_packages/418) and 426. Layered builds use
cast stills, the set and the layout (E0-proven); a prompt-generated photo cannot be split
into those layers without matting (story [451](https://work.haynesnetwork.com/work_packages/451),
unbuilt). (a) The photo is a preview for layered boards; the UI labels it so and shows
the cast stills the build uses. (b) The photo is the source, matted into layers (waits
for 451). (c) For layered boards the "photo" is a deterministic composite of the build's
own layers (as `poc/keyframes.py` made E0 keyframes); prompt photos only for whole-frame.
**Recommendation: (a) now, with (c) as a cheap follow-up**, so what Tom judges on the
storyboard (D26) matches what is built.

**Q-04 Can an imported legacy run go live?** Affects the go-live preconditions
([section 11](#11-go-live-approval-identity-boundary-only)) and story 412. Candidates
are the r4 cut, which D1 signed off before go-live was defined (D29), and the E0 layered
S2V delivery Tom praised (D24). Their provenance is partly free text. (a) Only canonical
`succeeded` runs; rebuild through E1 first. (b) Imported runs with a verified master hash,
once the importer has turned their provenance into structured engines with licences;
the same release checks apply, and D1 is not itself a go-live approval. (c) The r4 cut
only. **Recommendation: (b).** It lets a finished, already-reviewed cut be the first
release without a rebuild, while keeping the D43 label, D44 credits and Q-01 checks.

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
| P-10 | Phone proxy 720x1280 H.264 under 25 000 000 bytes | delivery-size proxy |
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
