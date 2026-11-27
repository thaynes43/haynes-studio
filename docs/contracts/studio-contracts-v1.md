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
one-off drivers were then held in PR 70), and its six small fixes, story
[860](https://work.haynesnetwork.com/work_packages/860) (PR 71). The film was delivered
privately. Tom's verdict was pending at that amendment. The choices beyond this
text are P-46 to P-49.
The contract owner decided Q-428-2 and Q-428-3, O-860-1, the reading of the command
line's operator (O-428-1) and a practice on GPU heat, each a proposal Tom may overrule.
Tom decided nothing in this batch. The heat practice rests on a relayed message that
could not be verified, so confirming it is open for him (Q-428-6), with Q-428-4, Q-428-5
and the differences he weighs with his verdict ([section 16](#16-held-owner-questions)).

**Fifth amendment, 2026-11-18**, story
[889](https://work.haynesnetwork.com/work_packages/889): the merged follow-ups of the
first live build are folded in. Stories
[861](https://work.haynesnetwork.com/work_packages/861) (PR 73),
[863](https://work.haynesnetwork.com/work_packages/863) (PR 75) and
[864](https://work.haynesnetwork.com/work_packages/864) (PR 77) are source and tested;
the private-view command's first live use is **not done**. Stories
[865](https://work.haynesnetwork.com/work_packages/865) (haynes-ops PR 4931),
[881](https://work.haynesnetwork.com/work_packages/881) (haynes-ops PR 4928) and
[862](https://work.haynesnetwork.com/work_packages/862) (haynes-ops PR 4932, studio PR
74) are installed. At that amendment no offline phase had run on the worker.
PR 70 kept five drivers as records and dropped the private-view driver. Story
[888](https://work.haynesnetwork.com/work_packages/888) (PR 76) added diagnostics;
the frame mismatch's cause stays open. PR 78 raised the source CI limit to 20 minutes.
P-50 already records the contract owner's operator decision; P-51 and P-52 record the
owner's cache-key and private-view decisions, each a proposal Tom may overrule.
No new decision by Tom is recorded here. His open questions and verdict stay open;
the private link's default file and the store's custody join them in section 16.

**Sixth amendment, 2026-11-24**, story
[954](https://work.haynesnetwork.com/work_packages/954). At base `fa52968`, the first
two execution waves supply E1 archive evidence, board photos, delivery conversion,
asset candidates, technical checks, the Studio API, browser shell and Editor, MCP,
and image packaging. Studio PRs 82–93 and 95 and haynes-ops PRs 5020, 5021 and 5023
are folded in. Studio PR 94 was open at pickup. Its run-queue implementation stays
outside this amendment. The local-model profile is a proposal with a pilot choice.
[Section 16](#16-held-owner-questions) records the owner questions and provisional
rulings, and [section 13](#installed-and-published-state) records the dated install
and publication evidence. The API, web and MCP source has tests. Installed Studio
sign-in and authenticated phone playback still await story 434 and the story 944
proof. Tom's November 21 verdict applies to the exact quieter-gavel cut. E1 acceptance
and the verdict on One More Meeting remain open.

**Seventh amendment, 2026-11-25**, story
[960](https://work.haynesnetwork.com/work_packages/960), at base `be640a6`.
It folds in the queue, drafting, go-live, media operations, archive import,
recovery, recipes, escalation, review UI and feedback, plus the three CPU media
backend profiles. It covers Studio PR 94 and PRs 97–114 and 116, and haynes-ops
PRs 5024–5028, 5043, 5048, 5049 and 5053. The matting service PR 115 and local-model
activation PR 5050 were open at pickup.
[Section 19](#19-coordinator-rulings-provisional) adds the provisional rulings.
[Section 13](#installed-and-published-state) records the installed app at
`f30445f`, the automated playback proof for both imports and the dormant local-model
installation. Human phone playback, the isolated restore drill and Tom's
acceptance remain open.

**Eighth amendment, 2026-11-26**, story
[972](https://work.haynesnetwork.com/work_packages/972), at base `fd8e4a3`.
It folds in staging and subtitle source, the asset library, private release
packages, lane grants, the CPU media backends and their adapters, the drafting
benchmark, and the API, browser and operator references. It covers Studio
PRs 119–139, 141–146, 148 and 149, plus PRs 115 and 118, which landed
after the seventh amendment's pickup and before its merge. Studio PRs
140 and 147 remain open as references for story 968.
[Section 19](#19-coordinator-rulings-provisional) records CR-36 to CR-66 as the
saga coordinator's provisional rulings for Tom's review.
[Section 13](#installed-and-published-state) records the fourth pin, the matte
policy and activation hold, and the separate backend evidence.

**Ninth amendment, 2026-11-27**, story
[985](https://work.haynesnetwork.com/work_packages/985), at base `0239c602`.
It folds in the merged pause, lane read and Editor Format amendments from
[Studio PR 152](https://github.com/thaynes43/haynes-studio/pull/152) and
[PR 153](https://github.com/thaynes43/haynes-studio/pull/153).
[Section 19](#19-coordinator-rulings-provisional) records CR-67 to CR-71 as
the saga coordinator's provisional rulings for Tom's review.
[Section 13](#installed-and-published-state) records the fifth pin, current
holds and the permanent park of Studio PR 151.

**Story 971 contract amendment, source.** The occlusion queue adds a person-only
admission, an independently authorized FIFO worker lane and a verified mask
version that an OP968 foreground role can pin. CR-67 target hints are optional
set inputs and use source-pixel bounds. The frozen request and profile govern
reclaims, diagnostics and publication. The [occlusion job and activation
contract](../reference/segmentation-adapter.md#occlusion-jobs) records the
source scope and deployment dependencies. Serving activation and Tom's
acceptance are tracked separately. [Story 971](https://work.haynesnetwork.com/work_packages/971)

Every rule carries its source:

| Label | Meaning |
|---|---|
| **D*n*** | Tom's decision in [proposal 0003](../proposals/0003-studio-plan.md). Later rulings beat older prose. |
| **Evidence** | An E0 measurement, with its file under [`titles/the-winter-menu/video-e0/`](../../titles/the-winter-menu/video-e0/). |
| **Legacy** | What the PoC code or a Winter Menu manifest does today (file named). |
| **Proposal P-*nn*** | This contract's choice, with the alternative it rejects. Not Tom's decision. The coordinator ratified each at review as the working choice; Tom may overrule any. |
| **Q-*nn*** | An owner choice only Tom can make. The question, its options, Tom's answer and the D-number that records it are in [section 16](#16-held-owner-questions). |
| **Coordinator's reading** | How the contract owner applies a ruling of Tom's where his words leave the detail open. Not Tom's words; he may correct it. |
| **CR-*nn*** | A provisional ruling by the saga coordinator for Tom's review. [Section 19](#19-coordinator-rulings-provisional) records the source and standing. |

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
| Publication (drop) | A recorded manual release after go-live. | D43 |
| Candidate | A successful Studio run presented for one target in its frozen format recipe. Each run and target pair has at most one candidate. | story 448 |
| Feedback | A person's append-only note on a candidate. It can name stable board IDs and the prior note it corrects. | story 448 |
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

Every schema document carries `"schema": "studio.<type>/v<major>"`. Types in v1: `production`,
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

The list above is the example harness baseline. Merged features add
`studio.agent-draft/v1` (411), `studio.format-recipe/v1` (447) and
`studio.escalation/v1` (445), `studio.release-package/v1` and
`studio.publication/v1` (449). Their own references and feature suites
cover them. The drafting receipt and proposed worker backend request and
result documents are described in sections 7 and 8.

### Identifiers (P-01)

`<prefix>_<ULID>`: a type prefix, an underscore and a 26-character ULID in upper-case
Crockford base32 (first character `0` to `7`; no `I`, `L`, `O` or `U`).

```
^(prd|sty|brd|lin|cue|nte|ast|asv|job|run|dlv|apr|key|fmv|pub|fbk|cnd|arc|arv)_[0-7][0-9A-HJKMNP-TV-Z]{25}$
```

| Prefix | Entity | Prefix | Entity |
|---|---|---|---|
| `prd` | production | `job` | asynchronous job (voice, photo, asset candidate, matte) |
| `sty` | story | `run` | run |
| `brd` | board | `dlv` | delivery |
| `lin` | line | `apr` | go-live approval |
| `cue` | cue | `key` | agent key |
| `nte` | note | `fmv` | immutable format version |
| `ast` | asset | `pub` | publication (E9) |
| `asv` | asset version | `fbk` | feedback note |
| `cnd` | candidate | | |
| `arc` | staging archive record | `arv` | staging archive version |

- IDs are made by the server or the CLI, never typed by people, and never reused.
  Errors: `id.malformed`, `id.type_mismatch`.
- Display codes are not IDs: board `S01-B03` (mockup), run `Run 02` (per-story `number`
  from 1), asset version `v3` (per-asset `number` from 1).
- A principal is one of `{kind: human, iss, sub}` (from a verified OIDC token, never an
  email or display name), `{kind: agent, key_id}`, `{kind: worker, worker_id}` or
  `{kind: cli, command, operator}`, where `operator` is a human or agent-session
  principal (P-50). v1 adds
  `{kind: agent_session, session, harness, model}` for work an agent did in its own
  dev-env session without a studio key, such as checking a licence (P-24). It records
  who did the work and grants nothing. The principal schema accepts it wherever a
  principal goes since story 849: its three fields are non-empty strings and it has no
  other (P-40). The licence register's entries still name their checking session
  `{kind: worker, worker_id: "dev-env agent session <name>"}`, as recorded at the check
  (story 809).
- **The command line's operator when an agent session runs it (O-428-1; the contract
  owner's decision, a proposal Tom may overrule, P-48).** The command line took only a
  human operator when story 428's agent session recorded itself as `{kind: human, iss:
  "https://agent-session.invalid/dev-env", sub: "agent-session:<session>"}`. That
  reading stands for the E1 records already written: the stand-in issuer, which no
  sign-in can issue, marks each of them as an agent session's work. Such a record is
  never presented as a person's act. **O-428-1 is closed** by story
  [864](https://work.haynesnetwork.com/work_packages/864), which adds an `agent_session`
  operator below (P-50), source and tested without a live run.
- **Amendment P-50, story [864](https://work.haynesnetwork.com/work_packages/864) (the
  contract owner's decision of 2026-11-18, a proposal Tom may overrule).** A CLI `operator` may be exactly
  a `human` or an `agent_session`, never another CLI, a worker or a studio key. Choose
  `--operator-iss ISS --operator-sub SUB` or the complete
  `--operator-session SESSION --operator-harness HARNESS --operator-model MODEL` set.
  Both, neither, and incomplete sets are usage errors. These are self-reported
  statements, with no authentication or access grant. This replaces the former
  human-only CLI restriction for new records; P-48's historical records stay unchanged.
  New builds use that actor in `queued_by` and every transition's `by`; imports,
  voice jobs and assets keep the same actor fields they already write. Private
  viewing also records the CLI actor in its ledger's `provenance.created_by`, inside
  the new local `production.json`; the original run and delivery remain untouched.
  `promote_asset_version`, `WanClipClient.clear_in_flight` and
  `WanClipClient.clear_halt` require a human principal (direct or one CLI wrapper)
  before any lookup or state change. The two clears now require keyword `by`.
  Check overrides, go-live approval/withdrawal, publication, selections, production
  creation, media enabling and library candidate generation have no operation or
  CLI implementation yet. Their people-only contract stays in force; agent-session
  attribution does not authorize them. Legacy import's minted production ID is
  an import parameter/reference, not the `create_production` operation.
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
| `format_version_id` | `fmv_` or null | new pins reference a saved version whose frame size matches the media kind. Null means no format length warning |
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
| `id`, `story_id`, `number`, `revision` | IDs, integers | `number` is an immutable per-story creation sequence. The Editor display label is the 1-based position in `board_order` |
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
| `drafted_by`, `created_by` | principals | the API sets the draft's author and records the creator at local board creation. The creator is immutable and trusted import strips it from editable boards, preserving frozen snapshot bytes |
| `draft_application` | server-managed stamp | stable board key, exact draft SHA-256, model, session, server time, current stamp revision and original applied board revision. `drafted_by` names the stamping key |
| `origin` | `{source_key, legacy_revision, legacy_shot, manifest}` or null | |
| `derived` | `timing_state` (`timed`, `untimed`), `content_ms`, `frames`, `film_start_frame`, `voice_state` (`not_needed`, `absent`, `generating`, `current`, `stale`), `photo_state` (`absent`, `generating`, `current`, `stale`) | read-only; absent and stale assets are explicit, never inferred from nulls |

The API records a person's creation, patch, reorder or tombstone in `person_edit`
and `person_edit_revision`, inside the stamp when present and directly on an
unstamped board. Each acknowledged agent write appends `key_id`, `acknowledged_at`
and the replaced `board_revision` to `person_edit_acknowledgments`. Later edits and
re-drafts preserve edit and acknowledgment history. See [agent drafting](../reference/agent-drafting.md).

Archive apply can set the server-owned `draft_application.archive_version_id`.
The stamp includes the exact version, board key and draft hash, with the
person-edit marker for a person's apply or model and session for an agent.
Direct board requests cannot set the archive version. [Story 443](https://work.haynesnetwork.com/work_packages/443).

A job (`studio.job/v1`, story [405](https://work.haynesnetwork.com/work_packages/405)) is
`{id, kind (voice, photo, asset_candidate, matte), target_id, input_signature, status (queued,
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

The `asset_candidate` job (story [408](https://work.haynesnetwork.com/work_packages/408))
targets a reserved `ast_` ID. Freeze the normalized name, asset kind (cast, costume,
set or prop), production ID or null for global scope, labels, requester, prompt, seed
and request size. Its `input_signature` signs those inputs and the model in
`studio.asset-candidate-inputs/v1`. Success points to the recorded `asv_` ID. The
worker verifies the frozen signature and checks for an existing result before
submitting. The operation and fencing boundary are in section 12.

The `matte` job targets the source `asv_` ID. The job read adds
`matte: {source_version_id, source_sha256, production_id, kind, format_version_id, format_sha256, slot, target_height_px}`.
Here `kind` is the derived asset kind and `production_id` is null for shared
library input. The signature covers the immutable source descriptor and exact
recipe normalization. [Story 965](https://work.haynesnetwork.com/work_packages/965).

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

**Delivery conversion (TIME-8, TIME-11, story
[453](https://work.haynesnetwork.com/work_packages/453)).** The
`studio.delivery-conversion/v1` profile uses the board clock. Board frame `n`
selects source frame `trim_start + floor(n × source_fps / 24)` (at 16 fps,
`trim_start + floor(2n / 3)`). Extra source frames are trimmed and a short source
is refused. At 24 fps the 48 kHz mix clock holds 2,000 samples per frame or 48 per
millisecond. A canonical 24 kHz S2V drive track holds 1,000 samples per board frame.
TIME-7 line placement holds across conversion. See
[Delivery conversion](../reference/delivery-conversion.md).

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
there are illustrative). [Story 447](https://work.haynesnetwork.com/work_packages/447)
reports this on story summaries, timing and run estimates after the known frames
exceed the pinned recipe maximum. The warning carries `build_allowed: true`
and `decision: D45`.

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

**Artifact inputs and the scheme (P-51; the contract owner's decision, 2026-11-18).**
Adding an input to one artifact changes that artifact's keys, without bumping
`studio.cache-key/v1` or invalidating unrelated artifacts. The scheme names the shared
normalization and hashing, not each artifact's input list.

| Artifact | Clock | Key inputs |
|---|---|---|
| Voice take | none | TTS model digest, voice ID, NFC text, speed, sample rate |
| Board voice track | board | take hashes, lead, gaps, mix rate, assembler version (no tail) |
| S2V drive track | board | speaker, **that speaker's takes on the board, each as its hash and start in ms (board clock)**, board frames, fps, rate (the takes' own, 24 000 for Kokoro: story 426), assembler version (P-25) |
| S2V clip | source | drive track, start still (the speaker's cast still's loop's start image: story 426), prompt, negative prompt, seed, profile (model files, LoRA, steps, cfg, size, chunk, source fps), adapter version. A library timed clip made from the same drive track with the board's seed takes its place (Q-426-2) |
| Doll clip or set loop (library `motion`) | source | the image the engine animated (the record's `source.image_sha256`; for E0 the doll on green, not the cutout), prompt, seed, profile (which names the adapter). Made by an asset job, never by a build (Q-457-1); the build reads the key from the pinned record (`keys.clip`). It has no negative prompt; the record's identity carries it (P-37) |
| Whole-frame I2V clip(s) | source | photo, prompt, negative prompt (story [861](https://work.haynesnetwork.com/work_packages/861)), seed, profile (which names the adapter, `studio.i2v/1`), requested clip lengths (set by the frames needed and the chain policy of TIME-8, story [427](https://work.haynesnetwork.com/work_packages/427)). A chain is one artifact |
| Keyed and decal frames | source | clip, key thresholds, protect boxes, still (the clip's start image, as Legacy `DollClip.cache_dir` hashed it), decal box, decal version, keyer as `<record's keyer>@<build>` (the numpy, OpenCV, Pillow, scipy, PyAV and libavcodec versions). The keying inputs are the pinned loop record's; the decal floor is not an input (P-39) |
| Board picture segment | board | method, layout preset values, cast stills, clip and keyed hashes, phases, how each layer plays (loop or timed, trim, source fps, decal floor), set plate and set loop with its phase, a whole-frame board's clip, motion style (every layered board), voice envelope when any line is spoken, who speaks when (each line's speaker and span), move and camera cues resolved to ms, frames, frame size, fps, foreground edge, procedural stream, compositor digest, `delivery_profile_sha256`, encoder settings and build (P-26). A spoken whole-frame board's segment carries the voice envelope and who speaks when too, though its renderer draws nothing from them |
| Film picture | film | ordered segment hashes, each with its frame count, splicer |
| Mix | film | ordered voice tracks with `F[k]` and line spans, sound cues resolved to samples (sound hash, trim, level), beds, line RMS, loudness and true-peak targets, frames, rate, mixer digest (every number of the mixer, its fades included, and the filter build: story 841). It has no board boundaries and no take sample counts |
| Master / proxy | film | picture + mix + mux settings (container, video copy, codec, bit rate, layout, rate, faststart, movie timescale, threads, encoder build: story 841) / master + proxy profile; both name the encoder build |
| Check result | none | artifact hash, check version, thresholds; a transcript check also the story's tolerances and the script's hash; a sound check's thresholds carry the story's targets and `frames x 2000`, its version the filter build (story 841) |

`delivery_profile_sha256` is the 64-digit digest of the canonical versioned conversion
profile (section 7). Older segment keys omit it. New plans re-key board segments and
reuse the upstream source, keying and mix keys. Resolved content hashes still key the
film picture, master, proxy and checks, so byte-identical inputs keep those keys. The
shared key scheme is `studio.cache-key/v1` (P-51).

**Negative prompts (story 861, P-51).** `s2v_negative_prompt` defaults to the Wan
client's `NEGATIVE` (E0's text). The new `i2v_negative_prompt` toolchain setting
defaults to the same text, and the whole-frame key, request and clip-set record all
name it. Changing either prompt changes its clips and their picture dependents,
leaving voices, drive tracks, library motion and mix keys unchanged. Old whole-frame
keys change once to include the missing input; speech keys made with an empty default
change too (none had a live clip). All 14 recorded speech keys of story 428 recompute
unchanged: that run set E0's text explicitly. **O-851-2 is closed.** Source and tested
with the fake pod; no live call or GPU job in story 861.

**P-25 (H-1, the contract owner, 2026-11-13).** A drive track is keyed on its own
speaker's takes at their starts, as `cache.keys.s2v_drive_track_key` does: a line edit
then rebuilds the edited speaker and, when a take's length changes, every speaker with a
later line, as the invalidation table says. Rejected: the whole board voice track as the
input, which rebuilds every speaker's S2V clip on any line edit.

**P-26 (H-2, stories 380 and [955](https://work.haynesnetwork.com/work_packages/955)).**
A board picture segment is constant-frame-rate H.264 in MP4 with one video stream:
libx264 `fast`, CRF 18, `yuv420p`, no B-frames, an initial IDR and a maximum
48-frame GOP. RGB conversion and encoding each use one thread. x264 uses one
encode and one lookahead thread, with sliced threads and asynchronous lookahead
disabled and preset lookahead and MB-tree active. Assembly is `AVX2` on
x86-64-v3 CPUs and `0` elsewhere. The segment key names the codec, format,
preset, CRF, GOP, B-frames, container, thread count and mode, assembly path
and encoder build (PyAV and libavcodec versions). The film stream-copies
segments in frame-offset order and checks compatibility and frame conservation.

**Reproducibility (stories 888 and 955).** The layered CI recurrence had the same
recorded inputs and different segment bytes, with a maximum RGB delta of 45.
Fixed frames reproduced changing x264 packets with sliced threads and separately
with serial encoding and automatic assembly dispatch on the AVX-512 worker.
The exact native operation in B4 remains unknown. Repeated encodes and fresh-store
comparisons check bytes and decoded pixels exactly within the pinned build and
profile. Every board segment re-keys. Downstream keys follow their input hashes
and existing blobs and records remain addressable.
[Encoding evidence](../reference/cache-and-splice.md#encoding-and-the-splice).

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

**Encoder rebuilds (story 966, [CR-52](#ruling-52)).** PyAV 18.1.1 replaces
the withdrawn 18.1.0. On the paired synthetic fixture the mix was
byte-identical and the pictures decoded to identical frames, while
embedded encoder strings changed the picture and master hashes.
Use the original lock (for the third pin, `80975a9`) or its image digest
for exact 18.1.0 rebuilds. The new build recomputes older encoded
segments. [Recovery and regeneration](../reference/studio-recovery.md#share-contents-and-regeneration).

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

**Photo currency (story 407).** `generator.params.input_signature` is `sha256:`
plus the SHA-256 of the canonical JSON document with `schema: studio.board-photo-inputs/v1`,
`board_id`, `layer`, `size: [width, height]` at delivery dimensions, `prompt`
(NFC or null), ordered `sources` as `{version_id, sha256}`, and `composite_signature`.
Layered uses a null prompt, the set then cast stills in draw order, and the story
426 composite signature. Whole-frame uses the selected reference versions in order
and a null composite signature. A selected photo is current when its stored signature
matches the current plan. An unsigned selection is stale.

Record a completed version even if the draft changed, its selected photo differs,
the board was removed, or the job lost its terminal compare-and-set. Select the
result only after these checks pass in the same fenced write. Story 430 integrates
active jobs and photo currency into the board and preflight facts. Whole-frame
I2V Build refuses a stale or unsigned photo with `422 photo.stale`.

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

### Delivery scaling and decal checks

**Delivery scaling (story 453).** The conversion profile applies Pillow Lanczos
to whole-frame clips and layered set loops at the same aspect. Equal sizes pass
through. Another aspect yields `wholeframe.unsupported` or `layered.unsupported`,
respectively. Still set plates use centred Lanczos cover fit. Either renderer
refuses an unknown profile at `/delivery_profile_sha256`.

**Recipe methods (story 447).** A board with a placed speaker is `speaking`.
Cast with no placed speaker is `reaction`. No cast is `ambient`. A new board
without an explicit method uses the first pinned recipe method for that shot type
when available. Existing boards retain their method. A globally buildable method
outside the recipe can save as a draft and gives `method.unavailable` at preflight.

**Matte stills (stories 451 and 965).** BiRefNet Lite produces an aligned
`rgba_cutout` and `mask` candidate. A person promotes it for layer use.
Optional recipe `cast.matte_slots` maps slots `a`–`z` to an integer
`target_height_px` from 1 through 2048. A layered reference photo verifies
the exact format and slot, measures the alpha-128 half-open bounding box and
area, and positions the normalized silhouette at the target height using the
layout slot's horizontal center and bottom. The receipt records the threshold
and target-to-box-height ratio. A conflicting crop, changed measurement or
target that exceeds the frame fails. The timed motion loop requirement and
clip chroma keying, APNG, decal checks and clocks still apply.
Temporal refinement needs a new keyed cache input and paired clip evidence.

**Segmentation and visibility (stories 460, 452, 968, 975 and 971).** Grounding
DINO Tiny and SAM 2.1 Hiera Tiny observe one explicit target. Under
[CR-67](#ruling-67), the merged [foreground role contract](../reference/foreground-roles.md)
freezes role masks at new admissions and retains foreground edge and feather
for legacy composition. The merged [film visibility check](../reference/film-visibility.md)
uses rendered film frames and the existing run-check framework. CR-54's person
review and hard refusal, CR-57's bounds and CR-58's rendering oracle govern
that check. The [occlusion job](../reference/segmentation-adapter.md#occlusion-jobs)
consumes CR-67 target hints and publishes a verified mask version. Segmentation
serving activation is separate. [Story 971, comment 10369](https://work.haynesnetwork.com/work_packages/971/activity#comment-10369)

**Upscaling comparison (story 461).** Pillow Lanczos remains the delivery
profile. FSRCNN ×2 followed by Lanczos runs as a one-shot comparison under
[CR-35](#ruling-35) and [CR-55](#ruling-55). One stored proxy frame and its
paired master frame can be verified against their delivery and opened
read-only under [CR-49](#ruling-49). The scores measure reconstruction of
that encode.
Tom owns the visual verdict. A future selectable
learned profile would pin its backend manifest in `studio.delivery-conversion/v1`
and apply FSRCNN ×2 then Lanczos to opaque exact-aspect clips and centered plate
crops that need up to 2×. Plate crops use the largest exact-aspect integer box
with left/top rounded down. Keep the clock, source generation, keyed sprites, proxy
sizing, equal-size and downscale behavior and legacy Lanczos identity. Unavailable
or unsupported learned upscaling refuses the build. A planned Lanczos fallback
has its own digest.
[Matting](../reference/matting-backend-profile.md) ·
[Segmentation](../reference/segmentation-backend-profile.md) ·
[Upscaling](../reference/upscaling-backend-profile.md).

**Decal drift (story [450](https://work.haynesnetwork.com/work_packages/450)).**
`decal.drift` v1 uses `layered.decal_gate` on the shown source indices with the
default floor 0.8 and frame 0 as the visual template. See the
[jacket-relative bounds, region evidence and motion limits](../reference/wardrobe-decal-checks.md#decal-drift).
Invalid ECC evidence goes to review. Invalid visual-region evidence retains any
valid weak or lost ECC finding and its escalation. Weak and lost tracks carry
`clip_id`, `check`, the one-based `attempt` and `max_rerolls: 2`. Guidance is
`reroll` for attempts 1 and 2 and `stop_with_evidence` from attempt 3. Story
[454](https://work.haynesnetwork.com/work_packages/454) owns the calling loop.

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

**Board photo provenance (story 407).** Each completed operation appends a version
with its own provenance, even when bytes match an earlier version. All three origins
record ordered source IDs and hashes in `generator.params.source_assets`. Uploads
record the declared generation sources there. ComfyUI records the actual prompt,
seed, configured model, filled workflow digest, engine job ID, timings and engine
output SHA-256. A layered composite records `origin: derived`, generator role
`composite` and the story 426 input document in `generator.params.composite`.

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

### Staging archive provenance

Under [CR-39](#ruling-39), an archive record belongs to one production, has a
kind (`brief`, `script`, `storyboard`) and a title of 1–80 characters. Each
immutable version stores its sequence number, parent, exact UTF-8 bytes (up
to 256 KiB), length, SHA-256, writing principal and time, an optional
`fmv_` pin and provenance. Storyboard text validates as a
`studio.agent-draft/v1` for that production.

Original provenance uses `{origin: original}`. Adapted writes send
`{origin: adapted, source_locator: {label, sha256}}` with an opaque source ID
and scene number matching `^[A-Za-z][A-Za-z0-9]*-[0-9]+$`, at most 40 ASCII
characters. The archive stores and returns `{label, hmac_sha256}` in place of
the raw digest. It HMACs the decoded digest under a production-specific
key derived from the existing OIDC client secret with a dedicated archive
context. Rotation affects new records. Prior versions keep their digests.
Logs carry IDs, kind, bytes and digest and omit archive text and MCP payloads.
[Staging archive](../reference/staging-archive.md).

**Adapted scene receipts (story 444).** The subtitle reader keeps cues in
memory. An optional private receipt carries source ID, opaque title and
episode IDs, range and unit, passage SHA-256, principal and UTC read time.
Selector IDs use a per-source HMAC over the canonical JSON inputs. The
passage hash covers the canonical UTF-8 JSON array of
`[start_ms,end_ms,text]` triples in returned order. The adapter creates no
persistent receipt or log. Archive staging uses the guarded locator above.

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

**Drafting benchmark (story 455, D46).** The [benchmark](../reference/drafting-benchmark.md)
freezes five original briefs, starting stories, a recipe, asset metadata and
assertions under one content-derived SHA-256. The scorer consumes a
`studio.agent-draft/v1` file and separate write evidence keyed to the draft
hash. It checks the scoped writes and canonical UTF-8 bytes of protected
boards. Missing evidence fails a check. Tom's labels apply to exact draft hashes.

**Delivery profile (story 453).** `toolchain.delivery_profile` records the conversion
version, timing, scaling, upscaler name, version and tool (the Pillow version),
model SHA-256 (null for Lanczos) and the segment key's profile digest. Hash the
canonical profile without its own digest or the `measured` block.
`measured.tool_sha256` records the native Pillow core loaded by the process for
provenance only. That lets the Python 3.11 planner and the Python 3.12 worker agree
on the key under one lock. Generation model files stay in clip provenance.

**Local-model evidence (story 442, expected at rollout).** Record the selected
profile ID, weight and projector SHA-256s, backend image digest, card UUID, token
limits and licence entries with any technical check or production plan that uses
the model. Publish the validated profile and evidence in the
[local-model reference](../reference/local-model-profile.md). D46 keeps frontier
writing as the default until Tom's switch verdict.

NFS media has no backup (D47). Recorded input hashes, prompts, seeds, engine profiles
and model digests support rebuilding where the inputs survive. A reconstruction
must match the recorded SHA-256 to recover an original blob. Different bytes get
a new hash and a new asset version or delivery. Uploaded and hand-made originals
need a surviving exact copy. See [Studio recovery](../reference/studio-recovery.md).
The Winter Menu's fire bed, which the PoC never
copied to the Wan volume, is made again by the in-cluster sound model as a new `sound`
version; its old hash stays as recorded (D54).

**Agent application and backend provenance.** A `studio.agent-draft/v1` binds
to one production and story. The applicator hashes the exact UTF-8 draft bytes
and records model, session, input and output tokens, and cost in its private
`studio.agent-draft-receipt/v1`. Null means unknown. The proposed
`production_draft_applications` ledger is append-only and keyed by production
and attempt, with the story, draft hash and usage JSON. Its proposed HTTP and
MCP writes require `draft:write`. Run usage stays in run provenance.
[Drafting reference](../reference/agent-drafting.md).

Proposed still and frame backend receipts record the pinned profile and verified
artifact hashes. The profile references specify graph, weight and runtime
digests, effective parameters, shape, geometry and scale where applicable.

## 8. Runs, deliveries and the store

### Runs (D30)

- `queue_run` takes the story's `revision` (stale: `conflict.revision`) and an
  `Idempotency-Key`. Preconditions:
  every spoken board has a current voice (`voice.absent`, `voice.stale`); every
  whole-frame I2V board has a current photo (`photo.absent`, `photo.stale`),
  every method is buildable, and no included board has a voice or photo job
  in flight (`asset.generating`).
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
  the CLI leaves held runs in place. A later build is a new run. A service-phase
  run ends `cancelled` with reason "service phase complete", because a run is never
  `succeeded` without a delivery (Q-406-1, the contract owner); one whose transcript
  check failed ends `failed`. The durable product queue below can requeue a
  run after a proved pre-admission refusal.
- An estimate comes back on queue, with a range, its basis and `uncertain: true` (D27).
- Check overrides (for example a decal min-ECC below 0.8 that looks right by eye, as in
  E0) go through `record_check_override` and are recorded per artifact with actor and
  reason, never silently; release checks cannot be overridden
  ([findings-layered.md](../../titles/the-winter-menu/video-e0/findings-layered.md)).
  The decal gate is the check `layered.decal_gate` (section 5); the layered renderer
  keeps its results in `renderer.checks` and does not commit them as stages, so story 406
  records them, and each renderer's `reports`, with the run; a reused segment's results
  are listed too (story 860). The product API appends an immutable override for a
  failed decal artifact, with a person, reason and timestamp. The check measurement
  and terminal run outcome stay intact. The CLI has no override.

**Technical checks (story 450).** `wardrobe.attributes` and `decal.drift` emit
`studio.check-result/v1` evidence with `check`, `version`, primary SHA-256 in
`artifact`, role-to-hash `artifact_refs`, `result` (`pass`, `fail` or `uncertain`),
`passed` (true only for pass), `confidence` (`high` or `low`), `thresholds`,
`measured`, `issues` and `escalation` (null on pass). An incomplete result is
`uncertain` unless the remaining evidence establishes failure. A run check keeps the
full evidence as `actual` and maps `uncertain` to blocking `fail`. Only a person
can override a named artifact check through `record_check_override`. Story 450
supplies the check library. The product API can record decal overrides. The automatic re-roll loop belongs
to story 454.

**Durable queue (stories 410, 956, 430 and 976).** Enqueue reserves the
`Idempotency-Key` by story and authenticated actor. The same accepted revision
replays the same run ID (200), even after edits. Another revision with the same
key gives `422 idempotency.mismatch`. The API freezes the draft, resolved
asset versions and eligible motion alternatives. The worker verifies the
snapshot and re-hashes inputs before requesting a clip. Estimates carry uncertain
method and chunk ranges and ahead-of-run wait. A paused head or missing worker
can make the wait unknown.

One FIFO head owns the run lane. The lane and active head use
`FOR UPDATE SKIP LOCKED` and recheck the head's active state under lock.
The database clock governs claim expiry. A stale fence cannot send, heartbeat,
publish or finish. Takeover reads unresolved Wan IDs before dispatch. A
durable sent marker keeps the exact PUT. Under [ruling 19](#ruling-19), an
absent-ID read permits one identical replay per claim. A recorded retryable
pre-admission refusal or explicit restart failure permits a new attempt and
ID. `worker_busy` without a job record keeps the original ID. Readiness gates
every PUT, with admission backoff at 60, 120 and at most 240 seconds. Recognized
machine admission codes take precedence, using exact legacy queue texts only
when the code is absent. Unknown or pre-admission failure codes keep the run held.
The installed queue predates machine-code handling and waits on the foreign
ComfyUI queue and Rack GPU busy or warm texts. The separate command-line
clip client classifies only the lease text as busy. Other refusals end as
`adapter.job_failed`.

Under [CR-68](#ruling-68), pause stops claiming queued work, preserves FIFO
order and leaves live claim fences in force. A live claim may finish,
including a media job's first publish or a run's transcript request after a
clip. An engine request authorized before pause may start after the pause
response. Leases last 90 seconds from grant or the last renewal on the
database clock.

Under [CR-69](#ruling-69), the signed-in `GET /v1/queue/lanes` reports an
additive, read-only `live_claim` for each of `run`, `voice`, `image` and
`matte` in both switch states. A lane is quiet at the time of the read
when `paused` is true and `live_claim` is false. The session and
CSRF-protected `PUT /v1/queue/lanes/{lane}` keeps its existing response
shape with `lane`, `paused`, `changed_at` and `changed_by`.

`STUDIO_PAUSED_RECONCILE` defaults off. With it set to `1`, a paused run
poll can return a reconciliation-only claim to a worker that sends
`X-Studio-Paused-Reconcile: 1`. The FIFO head must be running or held,
have an unresolved `sent` Wan attempt, and have an expired or released
lease with no retry delay remaining. The replacement receives a fresh
fence and `reconcile_only: true`. It reads the recorded Wan ID and settles
known outcomes without a Wan submission or replay. An absent ID stays held
for another read. A verified result or restart failure is recorded and the
head is released for normal claiming after resume. Definite job failure or
cancellation can finish the run while paused. Other paused run polls return
204.

With the switch on, new Wan reservations check pause. The sent marker and
the final fenced pre-PUT `wan_submitting` heartbeat take the lane row lock
before the run lock. When pause wins dispatch authorization, the API returns
`409 work.lane_paused`. A PUT that passes its final check may start after
the pause response. Resume restores regular FIFO claims.

A definite client rejection or verified Wan result mismatch fails the attempt
and run, with evidence. A different frozen build revision fails with
`work.revision_mismatch`. A new snapshot can reuse verified matching clips.
Cancellation clears cooldown, drains known active jobs and settles known
terminal work. For a sent ID that returns `404 job_not_found`, hold with
`wan.cancel_waiting_for_absence` until a second clean absence at least 110
seconds later (90-second lease plus 20-second PUT timeout, measured by the
database). Cancel before the current claim's first PUT can settle immediately.
Wan deduplicates a late PUT that already passed the last fence check.
Cancellation sends no replay. Fenced publication closes cancellation. The
worker stages its result and the API publishes the verified canonical delivery
and private playback index. A definite completion refusal fails and releases
the head. A transport or database failure permits recovery from staging by a
replacement claim. [Queue reference](../reference/run-queue.md).

**Frozen recipe and feedback (stories 447 and 448).** A pinned snapshot stores
`format_version: {id, sha256, recipe}`, with the story's ID and canonical
recipe digest. The snapshot hash covers the complete object. Workers verify
the recipe and consume it by value. Unpinned snapshots omit the object. An
unresolved old pin needs replacement or clearing before enqueue. A draft
with an active feedback iteration records `answers: {candidate_id, run_id,
note_ids}` under the story lock. Here `run_id` names the answered run.
List and detail reads preserve this lineage after the draft moves on.
The exact-run approval remains tied to its own run and master.

**Snapshot read (stories 958 and 448).** `GET /v1/runs/{id}/snapshot` serves
verified canonical bytes as `application/json`, `Cache-Control: private, no-store`
and a strong quoted SHA-256 ETag. It uses the run read's production scope.
A matching `If-None-Match` uses weak comparison and returns 304 only after
verification. Unknown or out-of-scope runs return `404 not_found`. A run with
no stored snapshot by design returns `404 run.snapshot_missing`. A lost
pinned blob, locator or hash mismatch, and oversized blob return 503 with
`run.snapshot_lost`, `run.snapshot_changed` and `run.snapshot_too_large`
respectively. The limit is 16 MiB. Enqueue returns 422 with
`run.snapshot_too_large`, `bytes` and `max_bytes` for a new oversized
snapshot. Snapshots have their own run route and no
generic media index entry. [Ruling 31](#ruling-31).

**Archive import (story 957).** The schema owner on revision
`0003_studio_run_queue` or later runs
`studio-api-admin import-production ARCHIVE --receipt FILE --name NAME --media-type {short,video} [--recovered]`.
An independent flat inventory binds each opened file to its size and SHA-256
and checks the run and delivery before writes. The command reads the archive
without following links, publishes verified master, proxy and available snapshot
create-only outside the queue lock, then rechecks identity and commits draft,
pins, terminal run and delivery index. A new import requires unused production
and catalog IDs. It never adopts an existing production or a shared version.
An exact replay verifies existing blobs without writing. It survives a
production display-name edit but requires the original archive basename and
receipt digest. The recovered five-file layout keeps the original snapshot
hash and locator, stores JSON null in `runs.snapshot`, leaves the frozen library
empty, and creates no reconstructed boards. Recovery evidence describes
container metadata, not decoded frames.
[Import reference](../reference/studio-import.md).

**Escalation (story 445).** Fenced worker reports append technical evaluations.
Two failed ordinals with the same run, check, board, input key and artifact hash
make one `studio.escalation/v1` proposal. Its ID is the SHA-256 of canonical JSON
over the schema name and those five identifiers. The package freezes one
production, story, run, snapshot hash and optional board, plus scoped evidence,
permitted operations, expiry, reserved key, usage cap and callback. Duplicate,
overridden, busy or pre-admission reports add no new failure. A later override
fences authorization, request and responder writes. Package bytes and lifecycle
events are append-only. The worker supplies the ordinals and evidence, which are
still unchecked against stored run records. The fixture transport and cap in
[ruling 30](#ruling-30) do not establish a live responder flow.
[Escalation reference](../reference/escalation.md).

**Recovery (story 435).** Point-in-time restore can lose a job ID while Wan
still has that job. Keep the worker paused until the owner reconciles the queue,
engine and store. Deduplication requires the retained job ID and original
request. Restored approvals bind their original run and master. Reconcile
withdrawals after the recovery target before relying on a restored approval.
A replacement run needs its own approval. [Recovery](../reference/studio-recovery.md).

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
  up to N processes, with one thread per segment encoder and at most two for other
  media operations. Two workers give the same frames as one.
- **Where a live build runs (Q-406-2, the contract owner).** Until the NFS store adapter of
  story [434](https://work.haynesnetwork.com/work_packages/434), a live build runs its
  service phases from a session pod (which reaches Kokoro, Whisper and the Wan API) and
  its offline phase on `ai/studio-render`, with the store copied between them. The
  worker could not run the package on 2026-11-14: it ran Python 3.13 with media
  libraries outside the lock, and the keyer's and encoder's builds are key inputs. So
  story 428 ran its offline phase in the session pod at two threads under its work
  order instead. **O-428-7 is closed as installed** by story
  [862](https://work.haynesnetwork.com/work_packages/862), haynes-ops PR 4932 and studio
  PR 74: read inside the worker on 2026-11-18, Python 3.12.16 and all twelve runtime
  packages exported from `uv.lock` at `f431c240`, environment `py312-51d95b693bf4`.
  Renovate holds the image at 3.12.x and does not update the generated list.
  [Versions and procedure](../reference/services.md#studio-render-cpu-work).
  Story 942 later ran the offline phase there with a hash-checked cache transfer.
  A paired offline run comparing the worker's keys and outputs with a session pod's
  remains open. Tom's acceptance is separate.
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
  until a person calls `clear_halt(by=human)` (`adapter.competing_work`; the checked
  clip is kept on the error);
- a job that did not succeed is `adapter.job_failed`; the clip is fetched read-only (a
  redirect refused), its hash and size checked against the pod's and the ledger's, and it
  must decode to exactly its frames and rate: an image-to-video clip its requested length
  at 24 fps, a speech-to-video clip TIME-9's fixed over-delivery at 16 fps, both at the
  requested size (`adapter.response_invalid` otherwise);
- no snippet deletes, moves, interrupts or overwrites anything. The installed
  `generate()` removes or interrupts its own prompt when its own job fails; that is the
  API's behaviour for a well-formed queue answer.

**The API as installed on 2026-11-18** (stories
[865](https://work.haynesnetwork.com/work_packages/865) and
[881](https://work.haynesnetwork.com/work_packages/881), haynes-ops PRs 4931 and 4928):
every engine `/queue` read uses `engine_queue()`. It requires an object with both
`queue_running` and `queue_pending`, each a list of lists of at least two items, a
text prompt ID at index 1, and object client data at index 3 when present. A malformed
or unreadable answer is unknown work: startup recovery and failed-job cleanup set
`UNSAFE` without guessing an interrupt or deletion; pre-submit fails the job without
submitting; both interrupt waits refuse a malformed answer as proof of emptiness.
Malformed JSON at startup fails closed at once; transport errors keep their retry
window. The file route now answers one byte range with 206 and `Content-Range`,
advertises `Accept-Ranges: bytes` on 200 and 206, and answers an unsatisfiable range
with 416. Unsupported ranges and a range with `If-Range` are ignored (whole file,
200); a disconnected player gets no second response written into its stream.
The deployed `api.py` hash read that day is `8f576f6c…ea13`
([full hash and evidence](../reference/services.md#wan-api-storage-and-delivery)).
**Tested:** 27 unit tests, a local browser playing/seeking the real master, then live
health and byte-range read-backs. **Not exercised live:** a malformed queue answer or
a GPU job on the new code; the Traefik path and Tom's player are not verified.
Tom's viewing verdict remains open.

**The journal.** The client requires one: an append-only JSON-lines file, opened with a
`created` line and never rewritten, truncated or deleted, held for a whole `render` or
`recover` by a lock on its `.lock` sibling and on the journal file itself. A job is
journalled before the first probe and blocks every later call, in any process on that
journal, until it is settled: its ledger reads `failed` (and, if its prompt was
accepted, a probe shows the engine queue empty), its clip is fetched and checked, a
refusal certainly submitted nothing, or a person calls `clear_in_flight(by=human)`
after checking the service. A lost answer is never resubmitted. A journal that is missing beside its lock
file, empty, headerless or replaced during a call is `adapter.journal_failed`, and nothing
more is probed, uploaded or submitted. **What it protects against:** forgetting, after a
crash, a timeout, a lost answer, a restarted build, a second process, or a second name for
the same file. **What it does not:** tampering. Whoever can write in the run directory can
already clear it by other means, and overwriting it with another valid journal is
the same act, which the client does not detect. What holds without the
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

### Wan product jobs (story 458)

Product transport version `1.0.0` runs on the cluster Wan Service. Before a live
use, record `GET /v1/profiles` and `GET /v1/ready` to verify the installed version,
profile and readiness. Stage PNG and PCM WAV by digest. Submit
`PUT /v1/jobs/{type}/{job_id}` for `i2v`, `s2v` or `foley` with a new lowercase
32-character hex UUID per attempt. An equivalent retry at the same ID returns the
existing job. Changed input at that ID conflicts. After a lost response, GET by ID
before repeating only the same PUT if the ID is absent. Poll for the recorded prompt
UUID and terminal result. A success gives a file URL, media type, byte count and
SHA-256. Verify the downloaded bytes against that count and digest.

Admission and cleanup use the shared lease and unknown-work checks. Early release
for an unacknowledged submission requires 120 seconds of clean absence polls and
readable idle GPU samples, with no latched hold. The conservative watchdog covers
acknowledged or observed prompts and uncertain evidence. See the
[Wan product job API](../reference/wan-product-api.md) for the bounds, error envelope
and restart limits. Section 13 records installation. Story 842 remains the E1
client record.

### The first live build (story 428)

Story [428](https://work.haynesnetwork.com/work_packages/428) built The Winter Menu on
2026-11-14 with the studio's own code, privately, from the command line, on the two
3090s ([run log](../../titles/the-winter-menu/e1-build/run-log.md)). An agent session
ran it for the coordinator, each GPU step after a written go. **State: delivered
privately. Tom's verdict on the exact quieter-gavel cut is below. E1 acceptance
remains open.**

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
  `d009d61541774a429fcabfeedadd8b51` (home network only). **This link plays the first
  run's master**, not its proxy or the gavel edit below (story 428, comment 8823).
  PR 70 merged five other drivers as records on 2026-11-18 and dropped this driver
  after its review; it is not on `main`. The replacement `studio private-view`
  (story [863](https://work.haynesnetwork.com/work_packages/863), PR 75) is source and
  tested, with first live use still not done ([below](#private-viewing-as-built-story-863)).
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

### Private build and archive evidence (story 942)

Tom approved the exact quieter-gavel Winter Menu cut for private viewing on
2026-11-21 (epic [372](https://work.haynesnetwork.com/work_packages/372), comment
9487). Story [941](https://work.haynesnetwork.com/work_packages/941) recovered that
cut byte for byte. Story [942](https://work.haynesnetwork.com/work_packages/942)
proved a new bounded build, [One More Meeting](../../titles/one-more-meeting/run-log.md),
through a session service phase and two offline passes on `ai/studio-render`. One
staged Wan S2V clip produced a 196-frame vertical master and proxy at 24 fps. One
ASR request matched the normalized script exactly. The
[archive receipt](../../titles/one-more-meeting/run-evidence.json) records 15 files
across both create-only copies on the canonical private Studio share. A separate
read-back matched all sizes and hashes (story 942, comment 9516).

The legacy LAN playback route lacked authentication when checked. The new proxy
has no playback publication. Story [944](https://work.haynesnetwork.com/work_packages/944)
takes signed-out denial and signed-in phone playback and seek on the installed
range-capable Studio API, with Authentik and the app deployment of stories 432 and
434. It uses the verified delivery's proxy hash at
`GET /v1/media/{sha256}` under the authorization and range rules in section 12.
Tom's creative verdict on One More Meeting and acceptance of E1 remain open.

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

**Private release packages (stories 449 and 963).** A
`studio.release-package/v1` pins the run and snapshot hash, frozen recipe, target, delivery,
master hash and size. The insert-only database row retains the exact
canonical document bytes, length and SHA-256. Reads verify those fields
and run and target binding. A create-only copy at that digest supports
private download and repair. Keep prior package versions.
[Release packages](../reference/release-package.md).

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

For the LAN app the API mounts the share's dedicated `api-store-v1` directory
at `/studio` read-write as UID:GID `1000:1000`. Startup probes publication,
fsync, hard links, same-content retry and read-back on a temporary `.probe/`
path. The queue worker mounts the canonical store read-only. Both mount
`build-stage-v1` at `/build-stage` read-write for per-run staging. The API
publishes canonical snapshots and deliveries. The archive import Job is
the separate schema-owner path, with archive mounts read-only. The NAS
and its archives remain outside D47 coverage and replica protection.
[Deployment](https://github.com/thaynes43/haynes-ops/blob/main/docs/reference/studio-deployment.md).

**Private backend artifacts (stories 451, 452, 459–461 and 965).** The profile
references define validation and publish fences. A `studio.matte-request/v1`
freezes the job ID, authorized opaque PNG or JPEG source, profile ID,
profile hash and parameters. The canonical request signature is
`sha256:<hex>`. The Unix HTTP envelope carries a separate fresh 32-hex
`attempt_id`. The `studio.matte-result/v1` receipt repeats the pinned
request identity and records the signature, artifacts, shape and provenance.
Publish the source-size RGBA8 cutout, L8 mask and canonical receipt before
the fenced derived candidate write. A verified result remains a candidate
until a person promotes it.

`studio.segmentation-request/v1` pins a source still, target and profile with
an optional point, box or text hint. `studio.segmentation-result/v1` reports
source-pixel boxes, raw scores, provenance and `ready`, `needs_hint` or `failed`.
A ready result requires the validated mask and result JSON to be published by
hash under the caller's fence. The mask is a source-sized, single-channel
8-bit PNG with values 0 and 255. A non-ready observation stays diagnostic.
CR-64 ships the explicit-target adapter. Story 968 owns the proposed
foreground semantics and story 971 owns the job that would call it.

`studio.upscale-frame-request/v1` signs one frozen RGB8 PNG source record,
target dimensions, profile ID and manifest hash. It permits at most 4 MiB,
921,600 pixels and a 1280 px long side, with an exact target aspect and a
1080 × 1920 or 1920 × 1080 target. A local Unix socket uses verified private
scratch files. A local attempt owns a fresh 32-hex directory with
`input.png` and create-only `result/output.png`. A deadline kills and reaps
the child before retry. `studio.upscale-frame-result/v1` binds the request
digest, source and target to an RGB8 target PNG (at most 8 MiB) and the
admitted manifest and its digest. Consumer groups and delivery publication
remain proposed. [Matting fields](../reference/matting-backend-profile.md#artifact-contract-for-story-451) ·
[Segmentation fields](../reference/segmentation-backend-profile.md#artifact-contract-for-story-452) ·
[Upscaling profile](../reference/upscaling-backend-profile.md).

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
out of scope for E1 to E3 (P-11). On the Wan PVC (`ai/wan-video`), existing delivery
ledgers (`edited_production`) and files under `/workspace/output/productions/` are
never changed (review H5). P-52 permits new private-view files and a new ledger as
described below; it changes no legacy reader's authority. Engine jobs run through the
Wan API's own `generate()` create their own
ledgers and outputs, and the clip client creates its inputs once under
`/workspace/input/studio-e0/` (story 842). The private import only reads the volume
(story 846).

### Private viewing (as built, story 863)

`studio private-view` ([reference](../reference/studio-private-view.md)), PR 75,
puts a verified delivery on private viewing, never a public platform. **P-52 (the
contract owner's decision of 2026-11-18, a proposal Tom may overrule):** the link
plays the phone proxy by default, the master by `--master`. Both hashes and the choice
are recorded. Source and tested against a temporary root through a fake exec route;
**first live use is not done**, so Installed and Tom's acceptance are not claimed.

- `read_delivery` re-hashes the master and proxy; `RunRecords.latest()` supplies its
  named, validated `run` output, which must be `succeeded` and match the delivery.
  The four copied files are the master, proxy, run record and delivery document.
- Free space is checked first. An exclusive create reserves the new production
  folder; descriptor traversal follows no symlink and later steps check folder and
  parent identities. A new folder must be empty and owned by the effective uid.
  Existing folders, files or ledgers are refused, even with identical bytes. A new
  attempt needs a new job and local output folder; `--check-only` writes nothing.
- Each file is synced, hash-checked and linked create-only from its held descriptor.
  Final files are reopened and hashed in place before the ledger is linked; both
  validators check the ledger, and its paths, sizes and hashes must name this job's
  verified files. The ledger is linked create-only under `/workspace/jobs/`.
- Read-back checks `LedgerReader.get`, the selected file's bytes through the API and
  `LedgerReader.list`. A failure after a link attempt withdraws only this attempt's
  own ledger by a same-volume, no-replace rename after checking its identity. A
  replacement moved in the last race is checked after the rename and restored
  create-only; a failed restoration is reported with its retained path. No deletion
  or overwrite; the command records what it left behind in `production.json` where
  writable. A hard process kill cannot run withdrawal; later writers are not locked
  out after exit. Recovery is separate.
- Accepted as proposals by the contract owner: `private_view.invalid`,
  `private_view.remote_failed`, `private_view.readback_failed`,
  `private_view.withdraw_failed`. Existing store and delivery codes remain.
- Attribution is P-50: the ledger's `provenance.created_by` names the CLI actor and
  is included in local `production.json`; the source run and delivery are unchanged.

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

**Board-owned photos (story 407).** A `studio.asset-version/v1` uses kind `photo`,
state `board`, capability `opaque_photo` and production/story/board scope. The
board-owned asset uses `board-photo:<board_id>`. See
[Board reference photos](../reference/studio-photo.md) for provenance and version
writes. Promotion to a reusable production photo remains the library operation
above.

**Generated candidates (story 408).** One image job creates version 1 of one
asset under `asset-candidate:<job_id>` with `origin: generated`. It stores a
metadata-free RGB PNG create-only in the production or global library blob scope.
The generator records the model, prompt, seed, filled workflow SHA-256, engine job
ID, wait and render times, input signature and original PNG SHA-256. The canonical
digest covers the stored PNG. Cast, costume and prop get `opaque_photo`, and set gets
`opaque_plate`. These still capabilities assert opacity. Decline or regeneration
keeps the prior version privately in `candidate`, outside normal pickers.
Explicit human promotion exposes effective state `promoted` and returns the same
version on retry. In the product API, the promotion has its own record. See [Asset candidates](../reference/asset-candidates.md).

**Costume evidence (story 450).** `wardrobe.attributes` v1 checks a keyed RGBA still
with a hashed declaration of named costume attributes. An injected observer may
supply evidence for other attributes. Missing, ambiguous or low-confidence
observations go to review. See the
[sleeve profile and thresholds](../reference/wardrobe-decal-checks.md#wardrobe-attributes).

**Media operations (story 430).** Candidate promotion appends an immutable
decision. Readers derive the effective promoted state from it and retain version
IDs, pins and stored asset-version documents. The runtime role has no update
grant on asset versions. Archive pins recorded without media stay private and
outside the media index, and block rebuild, selection, promotion and use as
job or upload inputs with `asset.recorded_without_media`. Story 958 permits
a replacement upload when the selected photo is recorded-only. Its sources
still need media. [Media jobs](../reference/media-jobs.md).

**Matte candidates (stories 451 and 965).** The candidate keeps the source's
library scope. Cast, costume and prop keep their kinds. An eligible opaque
library photo yields cast. The RGBA8 cutout is the content and the aligned
L8 mask matches its alpha. Derived provenance records generator role
`composite`, engine `studio-matting`, profile ID, image and graph pins,
source version, input signature, canonical receipt and blob descriptors,
and `studio.cast-matte-size/v1` normalization with the exact recipe and slot.
The worker publishes three verified blobs create-only before fenced
completion. Identical source, profile and normalization reuse one
version. A replay repairs missing blobs from the original receipt request
and refuses changed bytes. Success leaves `result_is_current: false`.
Promotion preserves the candidate version and provenance.
[Matting and cast size matching](../reference/matting-adapter.md).

**Assets filters (story 456).** Board scope lists exact pins via
`GET /v1/assets?production=&board=&cursor=`. Story scope unions board
results and resolves direct story pins against the production catalog.
Production and library scope use the catalog. Group by asset ID and sort
version numbers newest first. Ordinary results and pickers exclude
candidate versions. **Not now** hides a candidate in that tab and writes
nothing. **Review again** restores the preview (CR-14 and CR-44).

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
  The working defaults are the cast voices in the quieter-gavel cut, with per-board
  voice changes before Build ([ruling 04](#ruling-04)). Per-line speed and delivery
  are requirements of the next engine ([ruling 05](#ruling-05)).
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
  pre-build check. A build with a configured current engine refuses a mismatched
  voice as stale.
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

<a name="11-go-live-approval-identity-boundary-only"></a>
## 11. Go-live approval identity

Go-live is the only formal approval (D29). It binds one Studio-built,
succeeded run to its exact verified master, independent of later draft edits.
[Story 412](https://work.haynesnetwork.com/work_packages/412) implements
`POST /v1/runs/{id}/go-live-approvals` with `{master_sha256, platform_setting}`.
A 201 returns the immutable `studio.go-live-approval/v1` record: approval,
run and delivery IDs, snapshot and master hashes, verified approver,
display name, `auth_time`, `approved_at` and `release_checks`. Imported
runs keep their historical terminal status and a `legacy.archive_import`
marker. Its basename, layout kind, receipt hash and database time record
the import. Both layouts give `422 approval.legacy_run` (D52).

The approver is an Authentik user whose verified issuer is
`STUDIO_OIDC_ISSUER` and whose subject is in the separate
`STUDIO_GO_LIVE_APPROVER_SUBJECTS` JSON array (default `[]`). The route
authenticates the approver before reading the body and checks freshness on
the database clock. The window defaults to 900 seconds. Story 430 caps
`STUDIO_GO_LIVE_FRESHNESS_SECONDS` at 3600 (minimum 1). A missing or stale
authentication time gives `403 approval.sign_in_again`. Group sign-in alone,
agent keys and worker tokens cannot approve.

Delivery checks bind the record to the server's verified delivery and hash.
Licence checks record the packaged register rows for all engines and model
files and refuse missing evidence. An `unknown` term is visible and eligible
under D49. AI-label evidence records the required platform setting and the
description line and credits only video, voice and sound (D43/D44).
`external_inputs` carries D42 disclosure evidence privately. API and workers
use the same register packaged in the wheel. `STUDIO_MODEL_REGISTER` can
select a local override.

One approval can be active per run. `POST /v1/go-live-approvals/{id}/withdraw`
appends the verified withdrawal and returns 201. Derived state and withdrawal
come from the appended record. Any eligible approver may withdraw, and an
eligible run may be approved again ([ruling 24](#ruling-24)). Approval and
manual publication are separate writes.

`GET /v1/runs/{id}/go-live-approvals` (stories 958 and 448) reads one database
snapshot with the run's production scope and a signed-in person's session.
It returns the delivered hash or null, newest-first approvals with derived
withdrawal, any available release-check preview and an approve and withdraw
decision. Each decision is `{allowed: true}` or `{allowed: false, code}`.
A refused decision is a 200 for an in-scope reader. The preview uses the
verified master and the synthetic-content setting enabled. It can be partial
or null. Reads create no records and leave sign-in freshness alone. Writes
recheck current eligibility. All signed-in in-scope readers see display names
and decision times. Only allowlisted approvers get issuer, subject and sign-in
times ([ruling 32](#ruling-32)). Non-approver fields use an explicit allowlist.

**Package eligibility and manual publication (stories 449 and 963).**
Preparation and approval share current delivery, provenance, description
and disclosure checks. The description starts with `This video was AI-generated.`
and credits the recorded video, voice and sound generators and any hardware
recorded as public.
Match stated engine and file rows, including registered SHA-256 pins, and
record terms with their source (D49). Check the frozen target's maximum
against delivery frames and fps and enforce its aspect. An unset maximum
refuses preparation. D52 excludes legacy runs.

Each approval rechecks eligibility and the stored package record. Refused
current evidence leaves the package `held` with `evidence_status: stale`.
When current evidence passes but differs, approval records it and returns
`package_evidence_older: true`. A releasable package needs an active
approval for the exact run, snapshot, delivery and master.

`studio.publication/v1` records a manual drop's package digest, approval,
actor, server time and literal location. A supplied `published_at` must
be at or after approval and within five minutes ahead of the database clock.
Approve, withdraw, prepare and record serialize on the run row. PostgreSQL
binds each drop to its package's run and target and permits one drop per
run and target across package versions. Story publication status is derived
from recorded drops. Withdrawal preserves those drops.
[Release packages](../reference/release-package.md).

[Go-live reference](../reference/go-live.md) ·
[Original boundary example](examples/valid/go-live-approval.json).

## 12. API, UI and MCP boundaries

### Boundaries (D41)

- **studio-api** writes product records (Postgres `studio` database) and canonical
  store blobs. A separately authorized schema-owner Job imports archived productions.
  The LAN deployment runs two replicas each of API, web and MCP in `ai`, with required
  hostname anti-affinity and one available pod per disruption budget. Internal probes
  and worker routes have no ingress. [Deployment evidence](#installed-and-published-state).
- **Web UI** is a static SPA. All data goes through studio-api. The hosting serves
  UI routes from `index.html` and forwards `/v1/` and `/auth/` on the same HTTPS
  origin. The deployed origin is LAN-only `https://studio.haynesops.com`.
  The shared sign-in limit is 120 requests per minute, burst 30, per ingress
  replica. The UI has no database or store access.
- **MCP** runs as a separate process. `studio-mcp` v1 serves stateless Streamable
  HTTP at `/mcp`. Each request verifies the caller's bearer with `GET /v1/me` and
  forwards the unchanged Authorization header to its fixed Studio API origin.
  The API resolves scopes and makes draft mutations. The listener exposes port 8001 in
  the deployment, calls the internal API on 8000 and configures Host
  and Origin explicitly. Upstream TLS supports a private CA via `STUDIO_API_CA_FILE`. The client ignores ambient proxy and trust settings and disables redirects. Plain
  HTTP is limited to loopback and Kubernetes Service DNS. The deployment uses a
  fully qualified Service name. NetworkPolicy permits selected in-cluster agent
  and Studio pods on the MCP port. The same policy applies to `/mcp/upload`.
  Any caller still needs its own egress permission and a scoped key. MCP returns
  compact metadata. Approval, publication, shell, raw-graph and media-byte reads
  have no MCP tool. Tombstoning is the draft edit `studio_remove_board`.
  [Ruling 21](#ruling-21).
- **Workers** claim, heartbeat, publish and settle through `/internal/v1/work/*`
  with a worker bearer authenticated before query or body parsing (P-14).
  Work writes carry the run or job ID and current fence. The worker has no direct
  database access. Story 430 requires the `worker_` prefix on the bearer.
  Story 962 binds each worker ID to one lane. Work needs a live token and a
  lane grant. Empty claims default to `run`. Missing grants, wrong-lane
  claims and wrong-lane continuations give 403 `work.lane_forbidden` before
  payload model validation or queue access. In shared heartbeat, publish,
  complete and fail routes a JSON object with `job_id` and without `run_id`
  selects media work. A lookup confined to the granted media lane returns
  404 for an ID outside it. In-lane payload errors give 422. A continuation
  still needs the stored worker ID, fence and unexpired deadline.
- Protected operations authenticate every request, including media and writes before
  reading metadata bodies. Agents supply a hashed bearer key with production-specific
  grants. Workers use service tokens. Browser auth uses the session below.

### Browser authentication and private media

- Authentik OIDC uses the authorization-code flow with S256 PKCE from a confidential
  studio-api client. Login attempts are one-use, tied to a temporary Secure cookie
  and stored in Postgres. The callback verifies issuer, RS256 signature, audience,
  nonce, time and a valid subject. Default ID-token leeway is 60 seconds (0–300).
  Per-process discovery and JWKS caches default to 300 seconds (1–3,600). An unknown
  key prompts one refresh per lookup. An in-flight fetch or a cached failure returns
  `503 service_unavailable` immediately. Failure cooldown defaults to 10 seconds
  (1–60). Failed fetches cannot make an expired key valid. Story
  [434](https://work.haynesnetwork.com/work_packages/434) owns ingress rate limits.
- `STUDIO_OIDC_ALLOWED_SUBJECTS` and `STUDIO_OIDC_ALLOWED_GROUPS` are JSON arrays of
  non-empty strings, default `[]`. At least one must have entries at startup.
  A verified ID token passes with a listed subject or an exact case-sensitive
  match in its string-array `groups` claim. Otherwise it gets HTTP 403
  `auth.subject_forbidden`. Subject sessions keep the issuer and subject checks.
  Group-only sessions bind the stored cookie digest to the configured group policy,
  and group claims are discarded. Authentik membership is checked at sign-in.
  Removal from the group leaves an existing session valid to expiry (8 hours by
  default, 24 at most). Logout, deleting that subject's session rows or changing
  the group policy can end access sooner. Authentik may allow child-group members
  whom the API then refuses because the token lists direct memberships.
- The API creates an absolute Postgres session and returns the HttpOnly, Secure,
  SameSite=Lax `__Host-studio-session` cookie (P-15). The browser keeps no bearer token.
  Read CSRF from `GET /v1/me` and send `X-Studio-CSRF` on unsafe requests, including
  `POST /auth/logout`. Record the verified ID token's `auth_time` if present and
  callback time otherwise. The provider timestamp uses the configured clock leeway
  and is capped at callback time. Older sessions with no evidence need a fresh
  sign-in to approve (section 11). `GET /auth/login` validates an optional
  same-origin path and query (`return_to`, at most 2048 characters) on its one-use
  attempt. Success returns there or `/`. Failure redirects to
  `/?auth_error=<code>`. `fresh=true` sends OIDC `prompt=login`.
- The installed Authentik application and confidential provider are `haynes-studio`.
  They use the per-provider issuer
  `https://authentik.haynesnetwork.com/application/o/haynes-studio/`, stable user UUID
  subjects, one strict callback `https://studio.haynesops.com/auth/callback`, and
  managed `openid profile` scopes with mapped claims in the ID token. Authentik binds
  the app to `authentik Admins`. Story 434 configures that exact API group on the
  LAN origin. The `99-studio-oidc.yaml` blueprint reads the generated Secret from an
  optional worker mount. ESO projects `STUDIO_OIDC_CLIENT_SECRET` from `network` into
  Secret `ai/studio-oidc-client`. Story 434 depends on Flux Kustomization
  `ai/studio-oidc` and verifies the current successful import before enabling sign-in.
  The installed provider and projection are recorded in section 13. A regenerated
  secret requires reapplying the blueprint.
- `GET` and `HEAD /v1/media/{sha256}` serve one bounded, open-ended or suffix range
  from the canonical no-follow store. Return exact `Content-Range` on 206 and
  `bytes */<size>` on 416 when a valid range starts at or beyond EOF. A malformed
  range (including end before start), multiple ranges or a nonmatching `If-Range`
  gets the full representation. The strong ETag is the hash. HEAD sends headers
  only. Authorize before opening any file. A production-owned non-candidate version
  or delivery grants access in scope. Shared-library media needs a pin in a current
  draft of an allowed production. Unknown and inaccessible hashes return the same
  404. Responses are private and never cached. Candidate previews need the authorized
  result and media path of story 430.
- `GET /healthz` is independent of the store and database. `GET /readyz` checks the
  database and answers from the last completed store probe. A successful result
  must be fresh (30 seconds by default, bounded 5–300). Start one background check
  per process when no result exists or its age is over half the window, and keep
  late completions. A hung store ages out of readiness. Both probes have empty bodies.

### Conventions

- Entity and selection revisions return quoted integer ETags. Writes to existing
  revisions use that ETag in `If-Match`. Creating a production or story mints an ID
  without `If-Match`. The first enable of a media kind requires the production
  revision and increments it. Board creation and reorder use the story revision.
  Board patch and tombstone use the board revision and advance the story revision
  in the same transaction. Refresh the story before the next story-level write.
  `409 conflict.revision` carries `current_revision` and the current ETag.
- Lists return `{items, next_cursor}`. The story summary carries the ordered board
  IDs. Individual boards are read separately. PATCH replaces each supplied top-level
  field. Omit IDs on new line, note and cue entries and keep returned IDs on edits.
  Metadata bodies are strict UTF-8 JSON up to 2 MiB. Query names and values must be
  UTF-8 without NUL. Selections are keyed by verified `(iss, sub)`, start at revision
  0 and return `{revision, values}`. PUT takes `{values}` and replaces the selection.
- `POST` that creates a job or run takes `Idempotency-Key`; the same key with a different
  body gets `422 idempotency.mismatch`. See Operations for the candidate job result fence.
- JSON errors carry `error.code`, `status`, `http_status`, `path`, `message` and
  `request_id`, with operation-specific details. `invalid` (422), `unavailable` (422
  for a method that cannot be built), `conflict` (409), `forbidden` (403),
  `unauthenticated` (401), `not_found` (404) and `too_large` (413) remain. Dependency
  outages use `service_unavailable` (503), and unexpected failures use `internal`
  (500). The server-generated ID matches `X-Request-ID` and the JSON access log,
  whose path excludes the query string. The
  [original example](examples/valid/error-method-unavailable.json) predates the
  HTTP request ID.
- MCP caps tool JSON arguments at 64 KiB and compact structured results at 128 KiB.
  The outer HTTP body and upstream JSON caps are 256 KiB and 8 MiB. Tool errors use
  `isError`. A valid API error envelope up to 64 KiB passes through with status and
  details such as `board_id` and `current_revision`. Invalid arguments report JSON
  Pointers and rule codes within the result cap.
- D42 uses the authenticated agent key, model, actual prompt, session, harness,
  ordered `source_asset_version_ids` (which may be empty) and a no-paid-API declaration
  (`paid_api: false` in the photo operation). Story 409's OpenAPI declaration
  describes the model, prompt, source IDs, session and harness. Story 430 ties the
  declaration and verified key to the raw upload with `If-Match` and
  `X-Studio-Photo-Provenance`. The 201 includes the version, selection flag and
  resulting board revision when selected.
  Resolve and scope-check source versions. Accept one PNG, JPEG or WebP still up to
  20 MiB and 4096 px per side. Inspect header dimensions before decode, apply EXIF
  orientation, flatten on white and store an RGB PNG without original metadata.
  Compare an optional lowercase claimed SHA-256 to the original bytes. Record the
  raw hash and MIME type in `generator.params.upload_sha256` and `upload_media_type`. The API metadata stores the server-computed raw digest as `received_sha256` when
  registering it with the library version. The stored PNG supplies
  `content.sha256`. The returned external block marks `externally_generated` and
  `server_computed_sha256` true. No URL fetch (P-16).

**Protected board writes (stories 411 and 958).** Under the story lock the
API permits a plain agent patch, reorder that moves the board, or tombstone
only when that same key created and still drafts the board and no person
edited it. Imported, older, person-edited and other-key boards require
acknowledgment and otherwise give `409 draft.protected`. A person follows
ordinary revision checks. An agent acknowledges only a board a person named
by ID, using `acknowledge_person_edit: {board_revision, read_token}` (a map by
board ID for reorder). The HTTP `X-Studio-Board-Read-Token` header or MCP
`read_token` binds the acknowledgment to the authenticated key, board and
revision. A reorder that moves a protected board advances its revision and
records the replacement. Agent-only create declares board key, draft hash,
model and session. A re-draft adds the prior hash and story revision and
checks the stable key under lock. The applicator preserves confirmed writes
on partial failure, marks a lost response uncertain and records named
acknowledgments in its private receipt. It rejects an unbuildable method or
incompatible cue kind or count before mutation. A local line key in a cue
resolves to a new line ID accepted in the same write.
[Drafting reference](../reference/agent-drafting.md).

**Media jobs and D42 (story 430, with story 958).** Voice generation takes
`{}`. Photo generation takes optional `seed` (default 0). Person-only
candidate creation takes kind, name, prompt, optional production, labels and
seed. Generation returns 202, compact status and a Location, or 200 for an
identical replay. A changed body under the same principal, operation, target
and idempotency key gives `422 idempotency.mismatch`. The job read returns
`studio.job/v1`. Its photo block freezes production, story, layer, prompt,
ordered source IDs and hashes, previous selection, input signature, seed
and model. Its candidate block freezes library or production scope, kind,
name, labels, normalized prompt, seed, model and requested size. Failed and
stale jobs keep their input pins. Candidate results have `result_is_current: false`.

Only people may read candidate results, promote or use job and version previews,
including history. Those private `GET` and `HEAD` reads support ranges and hash
ETags and return 404 for unavailable or inaccessible bytes. Ordinary hash lookup
requires current draft references for board-scoped and shared-library bytes
and excludes candidates. The image worker checks the household queue before
marking dispatch. An expired dispatched job fails with `work.dispatch_unconfirmed`.
Media claims use `lane: voice` or `lane: image`. An empty body keeps the run
lane. Heartbeat, publish, complete and fail use the job ID and claim fence.
A paused lane accepts submissions and stops claiming queued work. A live
media claim can complete, including its first `/publish` and engine
request. A paused media poll returns 204. Matte can settle an expired
dispatched FIFO head as `work.dispatch_unconfirmed` while paused. Voice and
image do the same when `STUDIO_PAUSED_RECONCILE=1`. An expired dispatch
is retired because the worker cannot confirm whether the non-idempotent
engine received it. The matte-only `settle_only` path can still settle
expiry without taking a claim. Read `paused` and `live_claim` using the
lane read in [section 8](#8-runs-deliveries-and-the-store). The session and
CSRF-protected pause change appends a person and database timestamp.

Selection uses the immutable `media_jobs.requester` principal, outside its
runtime UPDATE grant. A missing or malformed requester fails closed. A person's
eligible selection records a person edit, even for a reused voice version,
and preserves existing edit history. An owning agent's eligible result
advances its draft stamp. Agent media on a protected board stays unselected.
A replacement upload on a recorded-only selection is permitted. Its sources
still need media. [Rulings 27](#ruling-27) and [28](#ruling-28).

D42 upload requires authentication and scope before body read and before taking
the process's single upload slot. The MCP precheck requires `assets:upload`
on a production. The API verifies it against the target board's production.
Ordinary MCP keeps its 256 KiB request cap. `/mcp/upload` offers the upload tool
with the same Host, Origin and bearer checks. Busy uploads answer
`503 photo.upload_busy` and `Retry-After`. The body deadline is 90 seconds
(`STUDIO_UPLOAD_BODY_SECONDS`, 15–300) with a 15-second chunk idle timeout.
On expiry `408 photo.upload_timeout` discards partial bytes and frees the slot.
[Media job reference](../reference/media-jobs.md).

### Web UI

The shell remembers same-origin UI paths with canonical IDs and scope in
`values.web_shell` under `productions`, `board` and `assets`. Selection writes keep
unrelated values, use the returned ETag and refetch and retry once on
`409 conflict.revision`. Breadcrumbs drop deeper context. Backstage theme is a
device preference with a Dark fallback. A 401 clears the shell's in-memory
session and offers sign-in at the current URL. The API records the validated
return path. The shell also keeps its validated tab-storage recovery path.

`/editor` opens the Storyboard editor and Asset Library choices. The Storyboard
route carries production ID, media kind and story ID. Production and story pickers
read cursor pages within their scope. Enabled media kinds are destinations. Missing
kinds have an add action. A successful story creation opens its board route. Before
a create, the Editor compares trimmed, NFC-normalized, lowercased names using fresh
list pages. PostgreSQL enforces atomic uniqueness with trimmed NFC and Unicode
lowercase keys, globally for production names and within production and media kind
for titles. Upgrade reports and preserves existing collisions. The name keys depend
on the database's ICU version. Conflicts give `409 production.name_duplicate` or
`story.title_duplicate` with `existing_entity_id`.
On a stale enable, the Editor reloads the production and waits for user action
before a new attempt. See [stories 413](https://work.haynesnetwork.com/work_packages/413)
and [415](https://work.haynesnetwork.com/work_packages/415).

**Productions and review (stories 414, 958 and 448).** Story routes under
`/productions/<production_id>/<kind>/<story_id>` have optional board and run
descendants. Selection state keys publication and approval filters by the canonical
media-list path, with the selection ETag and one rebase. Filters combine before
pagination. Story results include `latest_finished_run`, `approved` and
`published`. Run reads include `active_approval_id`. Native video uses the
authenticated media route for proxy or master. The review panel uses the
go-live read installed by the second pin. If sign-in is stale,
return through fresh login to the same run and submit only on a new user action.
Productions shows candidate targets, frozen board labels, feedback corrections,
iteration conflicts and links between answering and answered runs.

**Storyboard (stories 416 and 417).** Stage, filmstrip and breadcrumb derive
labels from `board_order` and use stable board IDs for selection, URLs, writes
and media. A removed selection falls back to the nearest surviving board in
the last order, next on ties or first if unknown, replaces the URL and shows a
notice. Render timing from the timing read at the current story revision,
using its frame counts and FPS. Show a lower-bound total and pending film
range when timing is incomplete. Add and reorder use the story ETag.
Tombstone uses the board ETag. A conflict refreshes the draft and waits for a person.
Stage looks up the exact selected version by board and production. Play an
assembled voice track through the authenticated media route. The duration
bar uses `voice.speech_end_ms`. A legacy selection with no assembled track
has no player.

The inspector patches changed lines, timing, voice, method, notes and cues
with the read board ETag. Keep existing child IDs and omit new ones. After a
conflict, show saved and unsaved values before another deliberate save.
Filter the layer/motion pair by the capability matrix and current recipe shot
type, disable S2V without lines, and surface API refusal codes. Keep the note
composer available when collapsed. Executable cues retain typed fields.
Voice generation uses one key per press with the same key on ambiguous retry.
Status uses board jobs and lane reads. A current result agrees with the job,
selected version, server-derived board facts and local voice inputs. Native
track and line players use the person-only version preview with ranges.

**Story format (story 977).** The storyboard has an expandable **Format**
section for the current draft. A signed-in person reads the format catalog,
immutable version details and scoped stock voice versions. The picker matches
the recipe's frame dimensions to the enabled media type and flags targets
that lack a platform maximum before Save. Save sends only the changed
`format_version_id`, `cast` and `narrator_voice_version_id` fields to
`PATCH /v1/stories/{id}` with the current story revision in `If-Match`.
A `409 conflict.revision` or a verified successful PATCH establishes a
minimum revision for the story and timing read-back. On conflict the editor
uses the reported current revision, falling back to the sent revision plus
one. A successful PATCH must name the same story and report the sent
revision plus one in its body. If the response has an ETag, it must match
that revision, with either a strong or weak tag.

An uncertain write or stale read-back holds Build and Save and offers
**Reload draft** even while Format is collapsed. An unresolved conflict
stays visible when Format is closed and holds Build until the person keeps
their edited fields or chooses the latest saved version. Kept edits need
another Save before Build uses them. When a finished run's loaded snapshot
has no targets, its message links to the originating draft's Format section
and preserves that destination through sign-in. A subsequent enqueue
freezes the saved recipe and targets.

**Runs page (stories 419 and 958).** Build sends the displayed draft revision
and a key for that press. Ambiguous retries keep the key and original revision.
A revision conflict offers a reload. Length warnings remain advisory. List
reads work independently of the draft and selected board. Visible active
runs refresh every five seconds, backing read failures off to one minute.
Cancel uses the run ETag and shows pending until terminal. A person can
record the reason for a failed, unoverridden decal artifact on a succeeded
or failed run. Comparison verifies frozen snapshot digests and pairs stable
board IDs. It shows additions, removals, relative moves and script, method,
photo and voice changes. An unavailable snapshot leaves either proxy playable.
Productions keeps go-live with the finished run.

**Reference photo composer (story 418).** A board's `/photo` route opens
the inspector composer alongside the desktop stage or below the phone
filmstrip. Save ordered still pins and prompt with the board's
`If-Match` revision. Whole-frame generation uses a per-press seed and
`Idempotency-Key`. Ambiguous retries retain both. A layered board shows
its D51 composite inputs and uses seed 0 for recomposition. Read the
board jobs and image lane for progress. Job currency and
`derived.photo_state` apply to saved inputs, with an unsaved edit shown
separately. Preview the selection on the scoped media hash route and
newest-first history on the version route. Recorded-only inputs show
provenance and cannot be selected. A reference selected in Assets
returns via Router state `{photoAssetVersionId}`. Validate its current
scope, promoted state, still kind and available media before adding
the immutable version once and consuming the return state.
[Photo composer](../reference/photo-composer.md).

**Assets (stories 456, 438 and 965).** `/editor/assets` and its `/generate`
child accept origin `production`, `media`, `story` and `board` parameters.
`scope=story|production|library` widens the filter. `target` overrides the
origin board within that story. `q` and `kind` filter text and kind.
`job` reopens a known candidate job. Shell selections keep scope, target
and kind. Search and job stay in the URL. The search input updates locally
on each keystroke and replaces the URL query. History and reload restore
it. Generate polls the shared image lane while visible, including when
the job is missing. A confirmed missing job stops its own polling and the
next filter change drops its ID. **Use on board** returns the selected
version through `photoAssetReturn`. **Cut out** uses the exact format and
slot and follows the API job state. Ambiguous cutout replies keep the same
body and key for that source, format and slot while the page is open. Reload
can lose the key before a job URL is known.

Use the [Studio user journey](../process/studio-user-journey.md) for the
newcomer flow and the [operator runbook](../process/studio-operator-runbook.md)
for health, lane holds and private recovery. The fifth pin's served web
bundle contains the Format control, so a person can pin a new story in the
Editor to reach feedback and private package preparation. The browser
contract mock covers that journey. A signed-in walkthrough on the installed
app and Tom's verdict on wording and placement remain open.
[Story 977, comment 10404](https://work.haynesnetwork.com/work_packages/977/activity#comment-10404) ·
[Story 978, comment 10409](https://work.haynesnetwork.com/work_packages/978/activity#comment-10409).

### Scopes (P-17)

| Scope | Allows |
|---|---|
| `read` | reads within the key's productions |
| `draft:write` | stories, boards, lines, cues, notes |
| `assets:generate` | voice and photo jobs. Candidate generation is person-only |
| `assets:upload` | D42 board photo uploads |
| `runs:queue` | queue and cancel runs; for a signed-in person, also record check overrides. An agent key may hold it to queue and cancel (D50, Q-02 answered 2026-11-13; coordinator's reading: the per-key scope is the mechanism and is no longer people-only). Tom's ruling is about using the GPUs, so it does not reach check overrides: a judgement by eye stays with people, and no agent key may record one until Tom says otherwise. A key holds the scope only when issued with it, for its productions. A build takes the Wan compute lease, one job at a time, with its unknown-work checks, through the Wan clip client and its journal (section 8, story 842); a lease or queue across agents is dev-env work in haynes-engineering |
| `formats:write` | explicit agent grant on any production for studio-wide recipe writes over HTTP. Excluded from default grant sets |
| `archive:read` | list one production's staging records and history and read pinned versions |
| `archive:write` | create and append staging records in the granted production |
| `go_live:approve` | humans on the allowlist only; never on a key |

A key lists its productions; anything else is `forbidden` (story
[429](https://work.haynesnetwork.com/work_packages/429)).

Provision keys with the migration identity or a dedicated key-admin role. Grant
SELECT on credential tables and `productions.id`, INSERT on credential columns,
and UPDATE on key expiry, revocation and grant activity as listed in the
[API reference](../reference/studio-api.md#database-privileges). Migration
`0002_active_agent_grants` adds grant activity. The CLI checks permissions and
refuses the API runtime role. Deploy with `studio-api-admin register --key-file PATH`
for a cluster-minted 48–128 character ASCII alphanumeric token. Identical grants
and expiry return the existing key ID without change. `--replace-grants` updates
active grants and expiry and cannot revive a revoked key. Registering a revoked
key gives `409 key_admin.key_revoked`. `create --out PATH` writes a 43-character
base64url secret to a new 0600 file after the database commits. Without a path it requires an
interactive terminal before connecting. Use an interactive exec for that mode,
since pod output can be logged even with a TTY. Only digests go into the DB. List
and revoke use key IDs. Actions emit secret-free audit events.

Register an unbound worker ID with
`studio-api-admin worker-token register --worker-id ID --lane LANE --token-file PATH`
using the migration identity. Revision `0011_worker_lane_grants` seeds
`studio-worker` → `run`, `studio-voice-worker` → `voice` and
`studio-image-worker` → `image`. Existing tokens for those IDs work
with the seeded bindings. For a bound ID, omit `--lane` to keep its
binding. Another lane gives `key_admin.worker_lane_conflict`. The file has
48–121 ASCII alphanumeric characters and may end in a newline. The worker
prepends `worker_`. PostgreSQL stores its bearer SHA-256 and worker ID.
Identical registration returns the ID. `--replace` revokes and inserts
atomically while preserving the binding. A dedicated token admin can
register or rotate bound IDs and list with lane-grant SELECT. Revocation
keeps the existing token-admin grants. The runtime role cannot register
tokens. [Worker token administration](../reference/studio-api.md#worker-token-administration).

**Formats (story 447).** A lowercase catalog slug has a stable name. Each
append creates a consecutive immutable `fmv_` version with the SHA-256 of
canonical `studio.format-recipe/v1`. It defines frame size at 24 fps, length
range, ordered shot methods, cast and costume, voice/audio, checks, go-live
and targets. Target accounts are local metadata, with null IDs for placeholders
and optional max duration, AI-label rule and aspect. A story pin uses
`draft:write` and the story revision. People or keys with an explicit
`formats:write` grant author via HTTP. People and keys with active `read`
on any production read the studio-wide catalog. Catalog reads reveal no
production associations, and workers receive the pin only in their claim.
Writes cap canonical UTF-8 JSON at 64 KiB and enforce field limits and closed,
typed check parameters. The credential check guards against pasting and has
misses and false positives. If a credential is stored, rotate it and record
a manual schema-owner removal. The app exposes no version update or deletion.
[Formats reference](../reference/formats.md).

### Operations

Paths are under `/v1`. MCP tool names replace the old `patch_shot` and
`get_title_summary` (review H6).

The [generated Studio API and MCP reference](../reference/api-reference.md)
pins the offline OpenAPI export and MCP registry by digest and lists exact
inputs, scopes, schemas, parity gaps and worker-only exclusions.

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
| `list_board_jobs` | `GET /boards/{id}/jobs` | | read | 430 |
| `get_job_result` | `GET /jobs/{id}/result` | | person | 430 |
| Job and version preview | `GET`, `HEAD /jobs/{id}/media/{sha256}`, `/asset-versions/{id}/media/{sha256}` | | person | 430 |
| `search_assets` | `GET /assets?kind=&label=&production=&board=` | `studio_search_assets` | read | [382](https://work.haynesnetwork.com/work_packages/382), 409 |
| `get_asset` | `GET /assets/{id}` | `studio_get_asset` | read | 382, 409 |
| `generate_asset_candidate` | `POST /asset-jobs` | | person | [408](https://work.haynesnetwork.com/work_packages/408), 430 |
| `request_matte` | `POST /asset-jobs/matte` | | person | 965 |
| `promote_asset_version` | `POST /asset-versions/{id}/promote` | | human | 408 |
| `get_media` | `GET /media/{sha256}` | | read | 409 |
| `estimate_run` | `GET /stories/{id}/estimate` | `studio_estimate_run` | read | 410, 430 |
| `queue_run` | `POST /stories/{id}/runs` | `studio_queue_run` | runs:queue | 410, 430 |
| `list_runs` | `GET /stories/{id}/runs` | `studio_list_runs` | read | 410, 430, [419](https://work.haynesnetwork.com/work_packages/419) |
| `get_run` (status, progress, stages, checks) | `GET /runs/{id}` | `studio_get_run` | read | 410, 430 |
| `cancel_run` | `POST /runs/{id}/cancel` | `studio_cancel_run` | runs:queue | 410 |
| `get_run_snapshot` | `GET /runs/{id}/snapshot` | | read | 958, 448 |
| `record_check_override` (with a reason for a failed decal artifact) | `POST /runs/{id}/checks/{check}/overrides` | | person | 410, [450](https://work.haynesnetwork.com/work_packages/450) |
| `get_delivery` | `GET /runs/{id}/delivery` | `studio_get_delivery` | read | 381, 409 |
| `get_queue_lanes`, `set_queue_lane` | `GET /queue/lanes`, `PUT /queue/lanes/{lane}` | | person | 430 |
| `get_go_live_approvals` | `GET /runs/{id}/go-live-approvals` | | signed-in production reader | 958, 448 |
| `approve_go_live` | `POST /runs/{id}/go-live-approvals` | | go_live:approve | 412 |
| `withdraw_go_live` | `POST /go-live-approvals/{id}/withdraw` | | go_live:approve | 412 |
| `create_format`, `add_format_version` | `POST /formats`, `POST /formats/{id}/versions` | | person or formats:write | 447 |
| `list_formats` | `GET /formats` | `studio_list_formats` | person or read | 447 |
| `list_format_versions` | `GET /formats/{id}/versions` | `studio_list_format_versions` | person or read | 447 |
| `get_format_version` | `GET /format-versions/{id}` | `studio_get_format_version` | person or read | 447 |
| `present_candidate` | `POST /runs/{id}/candidates` | | runs:queue | 448 |
| `list_candidates` | `GET /stories/{id}/candidates` | `studio_list_candidates` | read | 448, 449 |
| `add_candidate_feedback`, `start_feedback_iteration` | `POST /candidates/{id}/feedback`, `POST /candidates/{id}/iterations` | | person | 448 |
| `clear_feedback_iteration` | `DELETE /stories/{id}/feedback-iteration` | | person and draft:write | 449 |
| `create_archive_record` | `POST /productions/{id}/archive-records` | `studio_create_archive_record` | archive:write | 443 |
| `add_archive_version` | `POST /archive-records/{id}/versions` | `studio_add_archive_version` | archive:write | 443 |
| `list_archive_records` | `GET /productions/{id}/archive-records` | `studio_list_archive_records` | archive:read | 443 |
| `get_archive_record` | `GET /archive-records/{id}` | `studio_get_archive_record` | archive:read | 443 |
| `get_archive_version` | `GET /archive-versions/{id}` | `studio_get_archive_version` | archive:read | 443 |
| `apply_archive_storyboard` | `POST /archive-versions/{id}/apply` | `studio_apply_archive_storyboard` | archive:read and draft:write | 443 |
| `list_escalation_packages`, `get_escalation_package` | `GET /productions/{id}/escalations[/{package_id}]` | | production read | 445 |
| `get_escalation_check` | `GET /runs/{run_id}/escalation-checks/{record_sha256}` | | production read | 445 |
| `authorize_escalation`, `decline_escalation`, `cancel_escalation` | `POST /productions/{id}/escalations/{package_id}/{authorize,decline,cancel}` | | person and CSRF | 445 |
| `report_escalation` | `POST /productions/{id}/escalations/{package_id}/callback` | | exact named responder key and Idempotency-Key | 445 |
| `list_release_packages`, `download_release_package` | `GET /runs/{id}/release-packages`, `GET /runs/{id}/release-packages/{digest}/download` | | read | 449 |
| `prepare_release_package` | `POST /runs/{id}/release-packages` | | runs:queue | 449 |
| `record_publication` | `POST /runs/{id}/publications` | | go_live:approve (signed-in, configured approver with fresh authentication) | [449](https://work.haynesnetwork.com/work_packages/449) |
| `claim_work`, `heartbeat_work`, `complete_work`, `fail_work` | `POST /internal/v1/work/...` | | worker | 410 |
| `login`, `callback`, `logout` | `/auth/...` | | none | 409, [432](https://work.haynesnetwork.com/work_packages/432) |
| `healthz`, `readyz` | `GET /healthz`, `/readyz` | | none | [434](https://work.haynesnetwork.com/work_packages/434) |

Story [429](https://work.haynesnetwork.com/work_packages/429) serves the 15 core
MCP operations backed by story 409. The [tool reference](../reference/studio-mcp.md#tools-and-revisions)
names the implemented rows. Lists and ordered board and timing pages accept
`cursor` and `limit` (10 by default, 20 maximum). Ordered cursors bind to the story
revision and last board ID. The story summary includes a page of board IDs and
story and board reads can select editable fields. Board creation, patch and
tombstone advance the story revision. Patch and tombstone return the board
revision. Asset pins reuse the existing draft-write fields and API checks.
Story 430 adds the media and run tools and story 447 adds the catalog reads
shown above. CI regenerates the checked-in browser client and checks the diff.

`present_candidate` takes `{target_id}` from the frozen recipe and returns
201 or 200 with the original record on repeat. Candidate lists are cursor
paged, optionally filtered by run ID, with the current iteration and story
revision ETag. A feedback write appends `{text, board_ids?, replaces_id?}`
with 201. Board IDs name frozen boards and a correction points to a note on
the same candidate. Starting an iteration with `{note_ids}` and a current
story `If-Match` returns 201, the new iteration, revision and ETag. A stale
write gives `409 conflict.revision`. Under [CR-36](#ruling-36), a person can
clear the current iteration with the story ETag and production `draft:write`.
An out-of-scope story returns 404. The write advances the revision and
appends attribution. The database prevents references across stories and
frozen runs keep their `answers`. `studio_list_candidates` can filter by
candidate ID and up to ten note IDs. These operations exclude worker tokens.
[Feedback reference](../reference/feedback.md).

**Staging archive (stories 443 and 963).** A create writes the record and
version 1 together. Append names the newest `revises_version_id`. A stale
append stores nothing and returns 409 `archive.stale_version` with
`error.existing_entity_id` (CR-40). Create and append require
`Idempotency-Key` (`idempotency_key` in MCP), give 201 for creation and
200 for an exact replay, and refuse reuse with different input with 422
`idempotency.mismatch`. PostgreSQL requires exactly one parentless root
at commit and a same-record parent with the immediately prior number.
Lists carry metadata. Exact version reads and apply verify the stored
UTF-8 SHA-256 and refuse a mismatch with 500 `archive.text_hash_mismatch`.
Unknown and out-of-scope records and versions give 404 on reads.
The MCP envelope cap is 256 KiB with a 2 MiB write exception for create
and append. People can call the six HTTP operations with CSRF on writes.
Agent scopes follow CR-42. Worker tokens are refused.

Apply uses the same-production story named in the pinned draft, a story
revision (`If-Match` or MCP `revision`) and existing set pins. One
transaction applies eligible boards through normal drafting mutations
and returns per-board outcomes. Archive replacement preserves
person-edited boards for every caller. It also preserves unstamped boards
protected by the drafting rules. An eligible board without an archive
stamp uses the story revision as the caller's acknowledgment of the
current story (CR-47). An already applied exact version can be skipped.
An archive-stamped board accepts only a descendant from the same record.
Otherwise the per-board receipt carries `archive.version_not_descendant`
and `stamped_version_id` (CR-41 and CR-45).
[Staging archive](../reference/staging-archive.md).

**Subtitle source (story 444).** The read-only Python `SubtitleSource`
lists titles, lists episodes and reads one scene. The Linux adapter
takes one explicit root, with title directories and SubRip or WebVTT
episodes directly beneath them. Cue positions are one-based and
half-open. Millisecond ranges return wholly contained cues. Output is
chronological with file-order ties. Bounds are 512 entries per directory,
1 MiB and 10,000 cues per episode, 4,096 input characters per cue, and
120 seconds, 80 cues and 8,192 parsed characters per scene.
Descriptor-relative opens reject escapes, symlinks, nested mounts,
non-regular and multiply linked episode files. Denial gives
`subtitle.access_denied` without a path. The runner needs a read-only
or `noatime` mount or ownership of the entries opened for read so access
times are preserved.

The staging helper accepts a summary of the conflict and timed,
paraphrased beats. It compares the summary, archive text and title
with the in-memory passage, including normalized strings and storyboard
keys and cue joins in time or file order. More than four consecutive
source words by default gives `subtitle.verbatim`. The setting allows
one through eight. The helper verifies the SHA-256 of the serialized
HTTP body or MCP arguments before transport. D14 and D29 still govern
creative review and go-live.

**Release operations (story 449).** Package list and download share the
run's production read scope. The response includes frozen targets and
one preferred item per prepared target. Prefer current evidence and fall
back to the newest package version. Agent views omit `approval_id` and
`recorded_by_display_name`. Prepare takes
`{target_id}` and gives 201 for new bytes or 200 for the same package.
Add `package_sha256` to repair a known copy, returning 200. A scope miss,
including a delivery-only import, gives 404. Publication takes
`{package_sha256, location, published_at?}`, CSRF and an
`Idempotency-Key`. Creation returns 201 and requires the active exact
approval. An exact actor, run, key and body replay returns 200.
Changed input for the same key gives 422 `idempotency.mismatch`.
[Release packages](../reference/release-package.md).

**Candidate media and matte lane (stories 456 and 965).** Use
`GET /jobs/{id}` and `GET /queue/lanes` for progress and
`GET /jobs/{id}/result` and job media for a successful candidate.
Photo and board voice use authenticated version media. Other
promoted catalog media uses the hash route. A global generated version
can preview through its source job. Recorded-only versions lack previews.
Promotion is a bodyless person-only write without a revision header.
It returns the same candidate version with effective promoted state.
Promoting a board photo creates an idempotent production-level copy.
Candidate enumeration and decline have no API operations.

`POST /asset-jobs/matte` takes
`{source_version_id, format_version_id, slot}` with CSRF and
`Idempotency-Key`. Return 202 for admission, 200 for exact replay
and 422 `idempotency.mismatch` for changed input. Under
[CR-50](#ruling-50), people request work and read shared-library status,
preview results, or promote. Production matte status is also available
through `get_job` or `studio_get_job` with production read. Image
candidate status is people-only. Ineligible input or slot gives
422 `adapter.request_invalid`. Dispatched failures retain their
adapter or matting code. A result that fails API verification records
`work.result_rejected`.

The matte lane runs one claim at a time. The worker verifies exact sidecar
readiness and waits for outstanding scratch attempts before claiming.
A pause allows submissions and lets an existing claim finish.
`POST /internal/v1/work/release-matte`
requires the matte grant and current `{job_id, fence}`. After dispatch
reservation it also needs `reason` of `connect` for failed connection,
`busy` for confirmed lock refusal or `readiness` for confirmed
pre-inference loading. Valid releases return 204. The counter stops
at three. Further busy replies requeue and a further connection or
readiness outage records `matting.sidecar_unavailable`. Expiry after
dispatch records `work.dispatch_unconfirmed`, including on a paused
lane. A matte worker can settle expiry without claiming using
`POST /internal/v1/work/claim` with `{"lane":"matte","settle_only":true}`.
[Matte job reference](../reference/studio-api.md#matte-requests-and-reads).

**Database recovery (story 437).** Transient disconnect gives 503
`database.failed`. After a rolled-back claim, the next claim can acquire
the same FIFO row with the next durable fence. A committed enqueue with
a lost reply replays with the same key and draft revision.

**Local segmentation (stories 460, 452 and 971).** `POST /v1/segment` on
`/segmentation/segment.sock` takes a closed `{attempt_id, request}`
body up to 4 KiB. An attempt uses a fresh 32-character lowercase hex
scratch directory with one `input`. A ready response writes `mask.png`
and canonical `result.json` create-only and returns `{result, result_sha256}`.
`needs_hint` has null usable geometry. Startup and request execution each
have a 60 s budget. The service reaps a timed-out worker before replacement.
Readiness returns the v1 pairing selector, serving manifest hash and CPU
device (CR-53). The explicit-target client uses pinned readiness and
bounded waits, stages one still under a held scratch descriptor, verifies
the response, mask and receipt (including the grounded depth prior), and
publishes immutable artifacts before fenced completion. Durable cache
hits verify the exact private identity, score floor and artifacts again.
Story 971 wires the adapter into one person-approved target per occlusion job.
The API checks the stored still, receipt and mask under the active claim and
commits the mask version together with job completion. Verified refusals
record diagnostic receipts. See the [source queue and activation contract](../reference/segmentation-adapter.md#occlusion-jobs).

**Responder boundary (story 445).** Reserve a key ID in the package, with
`read`, `draft:write` and `runs:queue` on its limited production resources.
A run-wide request has read only. Studio confines the key to listed resources
and operations, verifies its expiry and closes writes on callback,
cancellation or deadline. A person must name the board in authorization
before a responder may acknowledge a person's edit. Authorization defaults
to `person` (also for unrecognized settings). Automatic mode authorizes
under one database lock when both UTC-day limits have room. Defaults are
one per production and two total. It records issuer and counts. Over-cap
proposals wait for a person. Manual decisions require a person in either
mode. Authorization creates no outbound request. The fake transport records
one external ID for `requested`. A callback appends one `done`, `failed` or
`escalate` result with summary, usage (or explicit unknown) and changed IDs.
Identical callback retries replay until expiry. Real transport and automatic
mode remain held pending stored-evidence checks and story 446's drill.
[Escalation reference](../reference/escalation.md).

**Local inference (stories 441 and 442).** The additive Wan routes
`GET /v1/local-model/profile` and `PUT` and `GET /v1/local-model/requests/{request_id}`
discover one optional configured profile and record typed load, inference or
unload before dispatch. The ID is 32 lowercase hex characters. An equivalent
PUT replays. A changed valid body conflicts. Poll the original ID after a
lost reply. Inference accepts bounded text and either one staged PNG digest
or one to four ordered staged PNG digests. Each frame is at most 1080×1920
or 1920×1080 and 8 MiB. Check the full context and output cap before image
encoding. Server-defined `text`, `frame_check_v1`, `plan_v1` and
`plan_tool_v1` modes bind the request fingerprint. Structured results are
validated before return, and callers validate before acting.

Load, inference, unload, child reaping and handover stay inside the existing
Wan lease. Preserve foreign work and refuse malformed or unreadable queues.
A live child with no residency journal latches a hold. The absence of both
permits normal idle engine cache. An unavailable sidecar refuses
an operation needing residency evidence. Before fresh load, evict idle
ComfyUI cache and record the memory baseline under the lease. After reaping,
fresh idle memory at or below the profile ceiling and within 4 MiB of
baseline verifies release. A failure with verified release preserves the
original error. Unverified release records `residency_unverified` and
holds the lane. The pilot unloads before every Wan and Foley dispatch.
Over-bound replies give `output_limit`. Valid capped text may be marked
`truncated` without partial UTF-8. An incomplete or mode-invalid structured
reply gives `invalid_result` with a reason. Optional `admission_code` is
additive to existing failure replies. Without a mounted profile, local
routes return `503 local_model_not_installed`.
[Wan product API](../reference/wan-product-api.md#local-model-requests).

The legacy import is a CLI command (`studio legacy import <manifest>`), not an endpoint
in v1. E1's private command-line build of The Winter Menu ran on the 3090s
(story 428, D55); the API and its deployment stay in E3. The commands it uses are built:
`studio voice`, `studio build` (`--phase service`, `--offline`, `--dry-run`,
`--workers N`, `--wan-story`) and `studio run show` (story 406, section 8), and
`python -m haynes_studio.importer` (story 846, section 9).

## 13. Stack pin

Each choice is a proposal (P-18) that the coordinator ratified at review. The original
pin installed nothing; story 862 has since installed the worker at the lock (section 8).

| Layer | Pin | Reason | Rejected |
|---|---|---|---|
| Python | CPython **3.12** in images; `requires-python = ">=3.11,<3.13"`; CI tests 3.11 and 3.12 | studio-render already runs 3.12 with pinned requirements ([services.md](../reference/services.md)); session pods have 3.11.2, and tests must run there without installing an interpreter. No 3.12-only syntax. | 3.13 (no runtime has it); 3.11 only (the worker runs 3.12) |
| Package | distribution `haynes-studio`, import package **`haynes_studio`** under `src/`, CLI command `studio` | `poc/studio.py` is a module named `studio` that the PoC scripts import from their own folder; a package of the same name would shadow or be shadowed | package named `studio` |
| Build and lock | `pyproject.toml` with the **hatchling** backend; **uv** with a committed `uv.lock`, `uv sync --locked` | uv is in every session pod (0.13); one cross-platform lock; hatchling builds with plain pip in image builds too | Poetry (not installed, separate lock); pip-tools (per-platform files) |
| Runtime libraries | numpy, Pillow, PyAV, scipy (keying, BSD-3-Clause), opencv-python-headless (decal, Apache-2.0), **imageio-ffmpeg** for the ffmpeg binary, all in the lock (scipy 1.16 and OpenCV 4.14 since 2026-11-13, PR 56, used by story 426's keying and decal). A story that ports PoC code adds what that code already uses (wyoming for the TTS and ASR adapters) to the lock | what `poc/` uses; session pods have no system ffmpeg | system ffmpeg |
| Encoder | PyAV **18.1.1** in the Studio image lock and the offline render requirements export ([CR-52](#ruling-52)) | Replaces withdrawn 18.1.0. The earlier pin remains relevant to exact old bytes. | serving on the withdrawn wheel |
| Tests | **pytest**, serial; markers in [section 14](#14-test-contract) | standard; serial keeps the 2-thread rule | pytest-xdist by default |
| JSON Schema | draft 2020-12 files; the `jsonschema` library checks them against the examples | language-neutral, shared with the web app and MCP | Python models as the only schema |
| API | **FastAPI** + Pydantic v2 + Uvicorn | OpenAPI with auth and errors (story 409's acceptance); typed request models; streaming responses for media | Django (stateful sessions, ORM-first); Flask (no OpenAPI or validation) |
| MCP | the official `mcp` Python SDK, streamable HTTP, as its own process | thin client over studio-api (story 429) | MCP inside the API process |
| Database | PostgreSQL 16 (`database/postgres16`, D39) through **psycopg 3** and **SQLAlchemy 2.0 Core**; **Alembic** migrations | explicit SQL for claims and fencing (`FOR UPDATE SKIP LOCKED`); a migration graph; downgrades tested on an empty database, production rolls forward | the ORM's identity map; SQLModel (couples API and table models); SQLite in tests (different locking gives false confidence) |
| Web | **TypeScript**, **React**, **Vite**, **pnpm**; static build served by an unprivileged nginx image; **Vitest** and **Playwright** | stateless static tier (D41); Node and pnpm are in session pods; component model for the v6 surfaces | Next.js (a server tier with its own auth); plain JavaScript like the mockup |
| Images | GitHub Actions builds Linux amd64 from digest-pinned bases and the commit timestamp. `ghcr.io/thaynes43/haynes-studio` contains the locked CPython 3.12 package for API, migration, CLI, MCP and queue worker, UID:GID 10001:10001, port 8000. `ghcr.io/thaynes43/haynes-studio-web` serves Vite on port 8080 as 101:101. Both use read-only roots with writable `/tmp`. Deploy through haynes-ops by registry digest looked up using the full commit SHA. | [Studio images](../reference/studio-images.md), story [433](https://work.haynesnetwork.com/work_packages/433) | |

**API commands (story 409).** `studio-api openapi` emits OpenAPI 3.1 from the canonical
schemas with no database or secret. `studio-api serve` starts the app.
`studio-api-migrate upgrade head` is the only migration CLI action. It uses the
separate migration DSN and configured schema. The DB fixture tests reversal on an
empty disposable schema. `studio-worker` invokes `python -m haynes_studio.queue.worker`.
Story 430 adds the worker's main-thread progress file and age check for liveness.

**Database provision (story 431).** CNPG `database/postgres16` retains the `studio`
database owned by `postgres` and the `studio` schema owned by `studio_migrator`.
Runtime role `studio_app` gets CONNECT, schema USAGE and explicit table and
column grants matching the deployed migrations, with no DDL or credential-table
writes. The [merged API grants](../reference/studio-api.md#database-privileges)
supersede the initial haynes-ops table-grant recipe. Two distinct ESO Password
generators use CreatedOnce and project the DSNs into `ai`. Inject
`studio-runtime-db/STUDIO_DATABASE_URL` into the API and
`studio-migrator-db/STUDIO_MIGRATION_DATABASE_URL` into the one-shot migration Job
and authorized schema-owner import and credential administration Jobs only.
Set `STUDIO_DATABASE_SCHEMA=studio` on these database consumers. Web, MCP
and workers use the API. The archive proof Job has scoped key files and no
database credentials. The existing postgres16 physical base backups and archived
WAL cover metadata under D47. The guarded Gatus check requests LAN
`/v1/me` anonymously every minute and expects 401. Startup and readiness use
internal pod probes. Studio mounts raw NFS and has no app PVC for VolSync.
Story [436](https://work.haynesnetwork.com/work_packages/436) owns the read-only
catalog/store audit and isolated restore.

**Migration and rollout.** Promote both published amd64 images from one full
Studio commit. The API, MCP, worker and operator Jobs use the Python digest.
The API and worker share `STUDIO_BUILD_REVISION=git:<commit>`. Worker provenance
records the image digest. Flux gates each revision on its digest-named migration
Job with `STUDIO_RUNTIME_ROLE=studio_app`. Revision 0001 and queue revision
0003 transactionally apply their runtime grants. The queue worker waits for
the digest-matched registration Job, app readiness and the offline render
limit. The cluster creates a 64-character alphanumeric worker secret
with CreatedOnce and an orphaned Secret. Flux retention and idempotent
registration with `--replace` protect worker rotation. The registration Job
uses the migration identity. Neither Job nor worker mounts a service account
token. The worker reaches only the required internal services and routes.
CR-22 splits D18's low-priority talosw01 allocation into 20 vCPUs for
`studio-render` and 4 for the serial `studio-worker`.
[CR-37](#ruling-37) governs media worker placement. Place the 1-vCPU voice
and image workers off talosw01 unless they need a dependency available
only there. Name that dependency, reduce offline render by the same
amount, and account for the render pod rolling.
The media-worker listener on TCP 8002 exposes exact authenticated
worker routes and keeps the queue and browser boundaries separate.
[Deployment reference](https://github.com/thaynes43/haynes-ops/blob/main/docs/reference/studio-deployment.md).

Merged source uses revisions `0001_studio_metadata`, `0002_active_agent_grants`,
`0003_studio_run_queue`, `0004_go_live_approvals`,
`0005_job_operations`, `0006_format_recipes`, `0007_escalation_packages`,
`0008_candidate_feedback`, `0009_release_packages`,
`0010_staging_archive`, `0011_worker_lane_grants`,
`0012_release_constraints` and `0013_matte_jobs` in order.
API readiness checks the schema and grant reads.
Runtime grants use select and insert for approvals, withdrawals, promotions,
format versions, escalation records, candidates, notes and iterations, with
specific draft columns writable for current pins and the active iteration.
Archive, package and publication records also use SELECT and INSERT.
`0011` seeds lane bindings and gives the runtime SELECT on worker lane grants.
`0012` checks `octet_length(document_bytes) = bytes`, backfills
`publications.target_id` from its package, refuses duplicate run/target
history transactionally and matches the drop's run and target to the package.
`0013` creates the matte FIFO and its release counter and permits matte
worker grants and lane pauses. It prelocks in predecessor readiness and
claim order, with 500 ms per lock acquisition and `NOWAIT` on later
prelocks. Include the grant wait, DDL and commit in queued-read latency.
The Job can retry the same atomic upgrade within its retry budget.
An operator starts a later retry through a reviewed PR.
The executable grants and dedicated credential administration grants are
listed in the [API reference](../reference/studio-api.md#database-privileges).

**Fourth-pin rollout (stories 967 and 970).** Under [CR-63](#ruling-63),
fresh preflight gates a reviewed GitOps merge. Flux reconciles the new
revision. The runbook waits and audits. Migration retry and workload
rollback each use a separate reviewed PR. This supersedes the
receipt-timing design in CR-62. Read the installed network policies
before merge and after reconciliation. Those reads are the authoritative
isolation check. [CR-65](#ruling-65) keeps the pin to the app, existing
lane workers, `0013_matte_jobs` and the encoder update.

The separate matte worker and sidecar share one network namespace.
Under [CR-59](#ruling-59), restrict that pod's egress to DNS and
the API worker listener, authenticate every listener route, mount
the worker token only in the worker and give the sidecar no
service-account token. [CR-66](#ruling-66) governs the isolation stage.
Before any matte worker pod exists, install and read back the policy-only
Flux stage. Protect the policy from Flux pruning and from garbage
collection if the stage is deleted, and verify that the policy selects
no existing pod. Then require an inside-pod denied-connection check
before the launcher requests its grant and repeat the check while running.
The separate activation also owns the credential, registration,
listener and ingress change, and any render split.

**Paused reconciliation cutover (stories 976 and 978).** The fifth pin
ships the code with `STUDIO_PAUSED_RECONCILE` unset on both API replicas.
[Story 978, comment 10409](https://work.haynesnetwork.com/work_packages/978/activity#comment-10409).
Before enabling it, verify the new build on every API replica reachable
through either listener and on the run worker. Stop the workers or drain
their traffic, including in-flight requests. In a separate GitOps change,
set the switch to `1` on every API replica. Verify that workers can reach
only enabled endpoints, including during replica termination, before
starting workers or restoring their traffic. Read back the build and
switch on each replica, worker readiness and progress, and the signed-in
lane state. A disabled endpoint can return 200 to the final
`wan_submitting` heartbeat and allow replay of a missing Wan ID while
the lane is paused. Before rolling back to a build without the dispatch
check, disable the switch on every serving API replica and drain the
enabled endpoints. The rollout and rollback use the
[operator runbook](../process/studio-operator-runbook.md#activate-paused-reconciliation).
[Story 976, comments 10397](https://work.haynesnetwork.com/work_packages/976/activity#comment-10397) and [10400](https://work.haynesnetwork.com/work_packages/976/activity#comment-10400).

**Local runtime (story 442).** Provisioning and activation are separate.
The temporary Job-scoped download policy precedes a one-shot CPU weights
Job. It uses a verified platform image, pinned revision, exact sizes and
hashes, hostname-only redirect evidence and create-only publication with
8 GiB and 1,024 inode reserves. Retry uses a new Job name, a 1 GiB memory
limit and cache flushing/dropping every 64 MiB, with blockwise read-back.
The staged procedure verifies both files before any later activation and
retires temporary policy and Job inventories while retaining the verified
weights. Measured release drift and sidecar readiness gate future leased
smoke. See the [local profile](../reference/local-model-profile.md) and
[hosting runbook](https://github.com/thaynes43/haynes-ops/blob/main/docs/reference/local-model-hosting.md).

**Media CPU pins.** The `haynes-studio-matting` image uses the pinned
CPython 3.12 base with UID/GID 10001, a read-only root and weights, and
`/matting` scratch. BiRefNet Lite FP32 uses ONNX Runtime 1.32.0 CPU with
two intra-op threads, one inter-op thread, sequential execution and one
request in flight. Startup has 120 s and dispatch has 30 s. The service
reaps a stuck subprocess before replacement.
CR-38 sets memory from measured runtime settings. CR-43 disables the CPU
arena and sets 8 GiB requested and 10 GiB limit for the serving sidecar and
smoke. The offline render limit stays 32 GiB. The socket service drains
at most 64 KiB under its 3 s socket timeout on a header-level refusal before
returning `400 adapter.request_invalid`.
Segmentation pins Grounding DINO Tiny and SAM 2.1 Hiera Tiny together with
the tokenizer and CPU runtime. Its Linux amd64 CPython 3.12 image uses
CPU Torch 2.14.1+cpu, TorchVision 0.29.1+cpu, Transformers 5.24.1,
safetensors 0.8.0 and Pillow 13.0.0. The OCI resource label binds the
measurement and serving resource contracts to the image. The measuring
stage uses a 16 GiB minimum. CR-51 selects memory-mapped weights with
4 GiB requested and a 5 GiB serving limit. CR-53 keeps the v1 pairing
selector and binds the v2 serving contract through its manifest hash.
The staged pod allows 150 s for shutdown, including request completion or
reaping and clean exit.
The FSRCNN comparison image is separate from Studio's core OpenCV
wheel. It pins CPython 3.12 Linux amd64, OpenCV DNN contrib headless
4.14.0.94, Pillow 13.0.0 and NumPy 2.4.6. Its manifest binds the image,
build, graph and wheel digests, CPU features, native and adapter hashes,
and resources. CR-55 keeps the staged backend comparison-only.
Each profile records exact pins and effective parameters in its reference.
A runtime or parameter change needs a new profile identity.

### Installed and published state

Tracker evidence through 2026-11-27. Installed, published,
usable and accepted have separate evidence.

| Component | Recorded evidence | Open proof |
|---|---|---|
| Wan product job API v1 | Flux installed haynes-ops `1a5d2e08`. Seven deployed files matched. In-pod `/v1/ready` and `/v1/profiles` returned 200 for `i2v`, `s2v` and `foley`; legacy ranged playback passed and the ingress excluded `/v1`. [Story 458, comment 9749](https://work.haynesnetwork.com/work_packages/458/activity#comment-9749). | Live product job and post-S2V admission through the queue. |
| CNPG and Authentik | DB/roles at haynes-ops `f6c17236`; three instances reloaded without restart and Portal rules stayed intact. Authentik application and group binding at `e7e604d3`; projection Ready and public health 200. [Story 431, comment 9742](https://work.haynesnetwork.com/work_packages/431/activity#comment-9742); [story 432, comment 9794](https://work.haynesnetwork.com/work_packages/432/activity#comment-9794). | LAN user's sign-in, non-member denial and logout. |
| Studio images and LAN deployment | First images built, scanned, smoked and published from `fb69580` with anonymous registry reads ([story 433, comment 9788](https://work.haynesnetwork.com/work_packages/433/activity#comment-9788)). Initial installed app at haynes-ops `18935d3b`, Studio `fa52968`, Alembic `0002_active_agent_grants`. Six pods Ready, separate TLS DB roles and HBA refusals, shared store read-back, anonymous API 401, verified sign-in redirect and internal paths absent from ingress. [Story 434, comment 9819](https://work.haynesnetwork.com/work_packages/434/activity#comment-9819). | A person completes sign-in and uses the installed pages. |
| Queue worker | Haynes-ops `23c6d69c` installed Studio `c75086b`, Alembic `0003_studio_run_queue` and one worker Ready on talosw01. Token minted and registered in cluster. Worker route refused anonymous calls and accepted the worker identity before validation. Idle claims returned 204. Stage read-back worked across worker and both API pods. The offline worker rolled to 20 vCPUs. [Story 956, comment 9872](https://work.haynesnetwork.com/work_packages/956/activity#comment-9872). | A new queued run claims, pauses on Wan refusal and completes. Failure/recovery proof belongs to [story 437](https://work.haynesnetwork.com/work_packages/437). |
| First archive import pin | Haynes-ops `c20a53a4` installed Studio `f30445f` (Python digest `1aa9b473…`, web `88305cda…`), Alembic `0004_go_live_approvals`, seven Ready pods. One More Meeting imported with its canonical snapshot and recorded-only asset pins. The Winter Menu imported in the recovered layout. The source archives stayed intact. [Story 957, comment 9914](https://work.haynesnetwork.com/work_packages/957/activity#comment-9914). | Signed-in phone playback and seek. |
| Automated private playback | Each production's proof key read its own run and delivery and verified the exact master and proxy. Proxy HEAD returned 200, and whole, first, past-midpoint and suffix ranges returned 206 with exact ranges. One More Meeting proxy: 1,789,344 bytes, SHA-256 `63dbb1e26287360ed6c4a0422dbdbfa250ad981c74e9719133d4dfe72d809d1b`. Other production's key 404, anonymous 401, scoped key writes 403. Both proof keys were revoked within two minutes. [Story 957, comment 9914](https://work.haynesnetwork.com/work_packages/957/activity#comment-9914); [story 944, comment 9915](https://work.haynesnetwork.com/work_packages/944/activity#comment-9915). | Human playback and creative verdict. |
| Database backup and health | Daily physical base backup and continuous WAL cover metadata with a 30-day window. First completed base containing Studio and both imports: `postgres-20261125000000`, Kubernetes creation time 2026-11-25 05:00Z, Barman ID `20261125T000000`. CNPG had three Ready instances and continuous archiving. Gatus passed with expected anonymous 401. [Story 435, comments 9887](https://work.haynesnetwork.com/work_packages/435/activity#comment-9887) and [9948](https://work.haynesnetwork.com/work_packages/435/activity#comment-9948). | Isolated restore. NAS media has no backup (D47). |
| Dormant local-model runtime | Flux applied haynes-ops `79fa01b5`. Wan pod recreated once, four changed files matched, Wan/Foley readiness stayed 200; local discovery gave `503 local_model_not_installed`. Published `ghcr.io/thaynes43/studio-local-model@sha256:e2e9b5e9b71aee89d0b8077ae47be113587b61054957b10f694cb4ab92b93f03`. [Story 442, comment 9924](https://work.haynesnetwork.com/work_packages/442/activity#comment-9924). | Sidecar/profile activation, calibration and leased inference/handover proof. |
| Wan local weights and activation | Download policy installed at haynes-ops `942f1785`. The first Job (`e7d237a6`) was OOMKilled, exit 137, under 256 MiB and published nothing. Retry `wan-local-model-provision-r2` (`e1c703b7`) published both verified files (7,499,546,400 bytes). The first activation was reverted after Wan was off its Service for about 32 minutes. The fixed dormant build rolled out and the diagnostic identified the device-variable rewrite. [Story 442, comments 9959](https://work.haynesnetwork.com/work_packages/442/activity#comment-9959), [9973](https://work.haynesnetwork.com/work_packages/442/activity#comment-9973), [10006](https://work.haynesnetwork.com/work_packages/442/activity#comment-10006) and [10007](https://work.haynesnetwork.com/work_packages/442/activity#comment-10007). | Story 442 is marked **Needs approval** after the restart-only ask lapsed unanswered. [Story 442, comments 10413](https://work.haynesnetwork.com/work_packages/442/activity#comment-10413) and [10573](https://work.haynesnetwork.com/work_packages/442/activity#comment-10573). [Haynes-ops PR 5064](https://github.com/thaynes43/haynes-ops/pull/5064) remains open and unmerged. [Story 442, comment 10413](https://work.haynesnetwork.com/work_packages/442/activity#comment-10413). |
| Second app pin | Haynes-ops `04bb6c82` installed Studio `393fe1d` and schema `0007_escalation_packages`. It brought default protection for unstamped drafts, media and job operations, recipes, Runs comparison, person-mode escalation, go-live and snapshot reads, and board inspector. [Story 959, comment 9977](https://work.haynesnetwork.com/work_packages/959/activity#comment-9977). | First signed-in use and real jobs. [Story 959, comment 9977](https://work.haynesnetwork.com/work_packages/959/activity#comment-9977). |
| Voice and image lanes | The two consumers were installed off talosw01 at 1 vCPU each. The image policy initially selected a label Cilium ignored. The corrected policy was installed and engine reachability passed. [Story 961, comments 9993](https://work.haynesnetwork.com/work_packages/961/activity#comment-9993), [9997](https://work.haynesnetwork.com/work_packages/961/activity#comment-9997) and [10002](https://work.haynesnetwork.com/work_packages/961/activity#comment-10002). | A real take and photo need a signed-in person. [Saga 362, comment 10012](https://work.haynesnetwork.com/work_packages/362/activity#comment-10012). |
| Third app pin | Haynes-ops `ccf83a52` installed Studio `80975a9` with `0012_release_constraints`. It added feedback and iteration, the photo composer, private release packages, Assets, staging archive, lane grants and shutdown drain. The installed worker identities passed cross-lane denials. Both archived films read back intact. [Story 964, comment 10061](https://work.haynesnetwork.com/work_packages/964/activity#comment-10061) · [Saga 362, comment 10064](https://work.haynesnetwork.com/work_packages/362/activity#comment-10064). | Real feedback and release package. [Saga 362, comment 10064](https://work.haynesnetwork.com/work_packages/362/activity#comment-10064). |
| Fourth app pin | Haynes-ops `59dc8678` installed Studio `470a90af73a2201e6542b5d867853dce6facad04` and Alembic `0013_matte_jobs` on 2026-11-25. Two API, two web and two MCP pods, the run, voice and image workers, and the offline render pod rolled with zero restarts. Offline render stayed at 20 vCPUs and the run worker kept its 4-vCPU share. PyAV 18.1.1 was read back in six encoder locations: both API pods, run, voice and image workers, and offline render. Postflight and the independent verify each logged 75 PASS and 0 FAIL, with 35 expected HTTP listener refusals. The pre/post comparison found identical archived runs, deliveries, indexes and store evidence. Gatus had no failure in 21 results across the rollout. [Story 967, comments 10322](https://work.haynesnetwork.com/work_packages/967/activity#comment-10322), [10327](https://work.haynesnetwork.com/work_packages/967/activity#comment-10327) and [10329](https://work.haynesnetwork.com/work_packages/967/activity#comment-10329) · [Story 956, comment 9872](https://work.haynesnetwork.com/work_packages/956/activity#comment-9872). | Migration retry, workload rollback and Tom's acceptance. [Story 967, comment 10329](https://work.haynesnetwork.com/work_packages/967/activity#comment-10329). |
| Fifth app pin | Haynes-ops `6597e708` installed Studio `eeeb2a40105ae1e64325063b0aa93c890fdefa43` on the six app and worker Deployments on 2026-11-26. [Story 978, comment 10409](https://work.haynesnetwork.com/work_packages/978/activity#comment-10409). Alembic stayed at `0013_matte_jobs`, PyAV 18.1.1 was read back at all six encoder locations, and the offline render pod stayed in place. [Story 978, comment 10409](https://work.haynesnetwork.com/work_packages/978/activity#comment-10409). Postflight logged 79 PASS and 0 FAIL and matched both archived runs, their deliveries and indexes, and the store to the baseline. [Story 978, comment 10409](https://work.haynesnetwork.com/work_packages/978/activity#comment-10409). | Migration retry, workload rollback and Tom's acceptance. [Story 978](https://work.haynesnetwork.com/work_packages/978). |
| Editor Format control | The editor can pin a format version, narrator voice and cast on a draft (story 977). [Story 977, comment 10404](https://work.haynesnetwork.com/work_packages/977/activity#comment-10404). The served web bundle contains the control. [Story 978, comment 10409](https://work.haynesnetwork.com/work_packages/978/activity#comment-10409). | Signed-in Editor walkthrough and Tom's verdict on wording and placement. [Story 978, comment 10409](https://work.haynesnetwork.com/work_packages/978/activity#comment-10409) · [Story 977, comment 10404](https://work.haynesnetwork.com/work_packages/977/activity#comment-10404). |
| Paused-lane reconcile | The story 976 code is in the fifth build with `STUDIO_PAUSED_RECONCILE` unset on both API replicas. [Story 976](https://work.haynesnetwork.com/work_packages/976) · [Story 978, comment 10409](https://work.haynesnetwork.com/work_packages/978/activity#comment-10409). | Activation remains pending and requires its own worker cutover. [Story 978, comment 10409](https://work.haynesnetwork.com/work_packages/978/activity#comment-10409). |
| Matting backend and matte lane | The pinned matting allocation passed the real-weight one-shot smoke with all 13 verdicts. The app accepts a cutout with 202 and the job waits for a consumer. [Story 459, comment 10004](https://work.haynesnetwork.com/work_packages/459/activity#comment-10004) · [Story 967, comment 10322](https://work.haynesnetwork.com/work_packages/967/activity#comment-10322). | The sidecar and matte worker await activation. The private cast trial needs a content-addressed photo from an authorized upload or reviewed import, then Tom's visual verdict. [Story 451, comment 10049](https://work.haynesnetwork.com/work_packages/451/activity#comment-10049) · [Story 970, comment 10338](https://work.haynesnetwork.com/work_packages/970/activity#comment-10338). |
| Matte worker isolation | The protected policy-only stage is installed at haynes-ops `ed212ad0`. Read-back verified both protections and zero matching pods, including terminating pods. All stages recovered Ready after reconciliation and no pod rolled. [Story 970, comments 10332](https://work.haynesnetwork.com/work_packages/970/activity#comment-10332) and [10333](https://work.haynesnetwork.com/work_packages/970/activity#comment-10333). | Story 970 is marked **Needs approval** pending Tom's decision on the credential, lane grant and API ingress peer, with the isolation proof still uncleared. [Story 970, comment 10574](https://work.haynesnetwork.com/work_packages/970/activity#comment-10574). [Haynes-ops PR 5096](https://github.com/thaynes43/haynes-ops/pull/5096) remains held, open and unmerged because all three designs for the isolation proof inside the pod can give a false pass. [Story 970, comment 10382](https://work.haynesnetwork.com/work_packages/970/activity#comment-10382). |
| Segmentation | The pinned image and real weights are installed as verified allocation `-06`. The one-shot serving smoke passed at 2.74 GiB peak under 5 GiB. Serving remains inactive. [Story 460, comment 10228](https://work.haynesnetwork.com/work_packages/460/activity#comment-10228). | Continuous serving and the private quality trial. [Story 460, comment 10228](https://work.haynesnetwork.com/work_packages/460/activity#comment-10228). |
| Upscaling comparison | The provisioned FSRCNN graph passed its measuring smoke and produced one private proxy-frame comparison. Lanczos was closer to the master on all three reference metrics for that frame. Delivery uses Lanczos. The learned scaler has no serving stage. [Story 461, comment 10229](https://work.haynesnetwork.com/work_packages/461/activity#comment-10229) · [Saga 362, comment 10231](https://work.haynesnetwork.com/work_packages/362/activity#comment-10231). | Tom's visual verdict on the pair. [Story 461, comment 10229](https://work.haynesnetwork.com/work_packages/461/activity#comment-10229). |

**Included in the fifth pin.** The segmentation client adapter from `fd8e4a36`
is in the build with no calling job, route or worker.
[Story 452, comment 10313](https://work.haynesnetwork.com/work_packages/452/activity#comment-10313) · [Story 978, comment 10408](https://work.haynesnetwork.com/work_packages/978/activity#comment-10408).
The fifth pin's source also includes PR 149's escalation fixture clock fix.
[Story 978](https://work.haynesnetwork.com/work_packages/978).

**Foreground role masks.** Haynes-studio PR 151 (story 968) is parked for
good, open and unmerged at `5b87773`. [Story 968, comment 10582](https://work.haynesnetwork.com/work_packages/968/activity#comment-10582).
PRs 140 and 147 stay open as earlier references. [Story 968, comment 10582](https://work.haynesnetwork.com/work_packages/968/activity#comment-10582).

**Recovery evidence.** During the third-pin one-API-pod replacement,
300 of 300 internal ingress samples returned the expected 401. Both
imported proxies read back unchanged. The baseline had no saved selection
or queued snapshot.
[Story 437, comments 10077](https://work.haynesnetwork.com/work_packages/437/activity#comment-10077) and [10078](https://work.haynesnetwork.com/work_packages/437/activity#comment-10078).
The isolated restore drill (story 436) is **Needs answer** on Tom's choice
of archive credential. [Story 436, comment 10572](https://work.haynesnetwork.com/work_packages/436/activity#comment-10572).
The available archive credential would expose a production role password
to the recovery pod. [Story 436, comment 10072](https://work.haynesnetwork.com/work_packages/436/activity#comment-10072).
The separate single-instance cluster, Studio-only query, no archive
writes and verified same-drill cleanup remain the CR-48 boundary.
[Saga 362, comment 10064](https://work.haynesnetwork.com/work_packages/362/activity#comment-10064).

**Held.** Story [446](https://work.haynesnetwork.com/work_packages/446) awaits the
dev-env coordinator's sanctioned responder interface and the stored-evidence
fixes. [Story 446, comment 9927](https://work.haynesnetwork.com/work_packages/446/activity#comment-9927).
The installed go-live approver list is empty. D52 excludes both imported films.
[Story 964, comment 10061](https://work.haynesnetwork.com/work_packages/964/activity#comment-10061).
Human sign-in, phone playback and acceptance are open.
[Saga 362, comment 10325](https://work.haynesnetwork.com/work_packages/362/activity#comment-10325).

**Open risks.** D47 leaves hand-made and uploaded originals and the two exact
archives dependent on surviving NAS copies. Some bytes cannot be regenerated.
The escalation trigger trusts worker-supplied evidence until checked against
stored records. The recipe credential check only guards against pasting.
Matting and segmentation private still quality remain open. Upscaling has
one proxy-frame comparison with visual review pending. NFS does not report free inodes.
The coordinator accepted a budget of 32 new entries for matting without an inode
reading and accepted the small segmentation file-count budget on the same basis.
[Story 435, comment 9887](https://work.haynesnetwork.com/work_packages/435/activity#comment-9887);
[story 445, comment 9926](https://work.haynesnetwork.com/work_packages/445/activity#comment-9926);
[story 447, comment 9919](https://work.haynesnetwork.com/work_packages/447/activity#comment-9919);
[story 459, comment 9934](https://work.haynesnetwork.com/work_packages/459/activity#comment-9934);
[story 460, comments 9946](https://work.haynesnetwork.com/work_packages/460/activity#comment-9946) and [9947](https://work.haynesnetwork.com/work_packages/460/activity#comment-9947);
[story 451, comment 10049](https://work.haynesnetwork.com/work_packages/451/activity#comment-10049) ·
[story 460, comment 10228](https://work.haynesnetwork.com/work_packages/460/activity#comment-10228) ·
[story 461, comment 10229](https://work.haynesnetwork.com/work_packages/461/activity#comment-10229).

First published [registry digests](../reference/studio-images.md#first-publication)
from [story 433, comment 9788](https://work.haynesnetwork.com/work_packages/433/activity#comment-9788):

- `ghcr.io/thaynes43/haynes-studio@sha256:284d97311e46f13a14da50bca20dbd786d522aa4c6e3e2d73f0fe2e687805f4a`
- `ghcr.io/thaynes43/haynes-studio-web@sha256:8ea1576f1efa6502cb4633a018cdd6dd631869d05fa5895dae7df58ef36aebfc`

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
  `--maxWorkers=2`; one suite at a time in a session pod. Cached board segments use
  the single-threaded encoding and RGB conversion in P-26. Timing tests use fake clocks,
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
  required checks; the Claude review stays advisory. Since PR 78 (2026-11-18), each
  `source` job has a 20-minute limit to catch a hang; `db` stays at 10 minutes and
  `browser` at 15. This changes no thread limit and does not make the suite faster.
  Both source jobs run `uv run --locked python scripts/checks/api_reference.py --check`.
  This checks offline HTTP and MCP inventories and synthetic schema examples
  against the committed reference and bundle. Run the command without
  `--check` to regenerate them when operations, tools or schemas change.
- **Browser (stories 413 and 415):** `pnpm typecheck`, `pnpm test` (at most two
  Vitest workers) and `pnpm test:e2e` (one Playwright worker). Playwright builds
  the SPA and checks the API and completed login against a contract mock at
  400 × 860 and 1280 × 900. Merged cases cover create, reload, revision conflicts,
  storyboard selection and timing, inspector edits, disposable ranged playback,
  exact-run review/refusals, Build and frozen-snapshot comparison (including
  404 and both proxies), candidate feedback and iteration, Assets filter
  and target restore, candidate refusal, retry, preview and promotion, and
  matte states. The photo composer cases exercise durable job transitions
  and revision conflicts with synthetic images. Story 977's mock flow
  creates a draft with a buildable board, follows the Format link from an
  unpinned run, saves format, cast and narrator settings, and sees frozen
  targets with **Present run** and **Prepare package** on the next finished
  run. Cases cover keyboard operation, pending controls, visible focus,
  API refusals and no overflow at both viewports. They also cover stale
  read-back, a collapsed conflict holding Build, recovery from a successful
  reply with a mismatched revision, and return through sign-in. The
  [behaviour matrix](../reference/web-behaviour-matrix.md)
  records story 438's mock cases. The opt-in installed playback spec needs
  a person-supplied HTTPS origin and Playwright storage state, skips in CI,
  and tests cookie-authenticated ranges and playback for the exact imports.
  Interactive sign-in and physical phone playback require human evidence.
  The standalone v6 mockup has its own smoke.
- **DB (stories 409 and 429):** disposable PostgreSQL 16 covers the documented
  least-privilege API role and separate provisioner. The SDK test exercises
  Streamable HTTP against the real API, all 15 tools, expiry and revocation,
  concurrent clients with different production grants, forbidden operations
  and revision conflicts.
- **Queue, operations and approval DB tests (stories 410, 956, 412, 430, 447,
  445, 958 and 448):** runtime-role PostgreSQL exercises queue concurrency,
  fencing, recovery, private playback, worker credential rotation, immutable
  promotion, upload and media scopes, append-only privileges, recipe claims,
  responder confinement, snapshot scope and conditional reads, exact review
  and write decisions, concurrent withdrawal visibility, frozen board
  references and revision-safe feedback lineage. Voice, image and Wan services
  use synthetic fakes. A source test compares documented runtime grants with
  executable grants. Archive tests cover read-only imports, queued work during
  copy, fail-closed collisions, recovery evidence and idempotent replay.
- **API and queue recovery (story 437):** real API replicas and workers
  share a disposable PostgreSQL 16 and store with fake external services.
  Tests cover FIFO exclusion and disjoint lanes, expiry and reclaim with
  the same or different worker ID, pool recovery after rollback, one
  durable engine submission, one-use OIDC state, nonce, provider code
  reuse, session expiry and approval freshness, scope and ranged media.
  The talosw01 simulation leaves the run queued with `gpu_unavailable`
  while edits, delivery reads and voice and image work stay available.
  Wrong-lane operations leave queue bytes and counts intact. The
  escalation fixture samples PostgreSQL time for responder-key expiry
  boundaries and advances its fake lifecycle clock for expiry and budget tests.
- **Paused reconciliation (story 976):** disposable PostgreSQL and fake
  engines cover pause before reclaim, pause racing reclaim, dispatch
  authorization ordered with pause, live media dispatch and live ASR, and
  an authorized Wan PUT starting after pause returns. The tests load the
  pinned serving worker and API handlers from Git and pair each with the
  new counterpart in both switch states. Coverage includes missing and
  verified Wan IDs, ineligible FIFO heads, live fencing, media expiry
  settlement, FIFO on resume and matte `settle_only`. Guard regressions
  cover the default-off claim and reservation paths, rejection of
  `X-Studio-Paused-Reconcile: 0` for paused claims, and cancellation
  priority at the final submitting heartbeat.
- **Archive and release DB tests (stories 443, 449 and 963):** check
  API/MCP parity, read-only pinned archive reads, exact UTF-8 bytes,
  provenance, stale append and replay, per-board protection, apply
  rollback, ancestry, size and envelope limits, and metadata-only logs.
  Runtime writes that skip parent sequence numbers or commit a record
  without a root fail. Populated legacy drop backfill, duplicate history
  refusal, exact package length and linkage constraints, and locks in
  both publication/withdrawal orders run against disposable PostgreSQL.
- **Subtitle source (story 444):** runtime-generated fixtures cover
  bounded parsing and discovery, path and file refusals, safe fallback,
  changes while reading, unchanged metadata, cue-free receipts and
  logs, archive compatibility, immutable request bodies and copied
  dialogue in both summary and outgoing archive text. A real read is
  Expected and needs Tom's designated source, scope and runner.
- **Matte job and migration (stories 965 and 967):** disposable PostgreSQL 16
  and a real Unix service with a fake graph check readiness, bounded releases,
  fencing, bidirectional lane grants, pause and expiry settlement, scoped
  HTTP and MCP reads, create-only repair and promotion. Migration tests
  exercise predecessor lock order, contention and atomic rollback.
- **Drafting benchmark (story 455):** generated evidence and hand-authored
  passing fixtures cover each case, with independent failures for schema,
  recipe methods, timing, references, brief assertions, write scope and
  preservation. Scoring and summaries run offline and refuse a tampered
  corpus. Summary requires all five results from one corpus and reports
  safety and structure independently of Tom's five exact-hash labels.
  Frontier stays default until Tom's D46 switch verdict.
- **GitOps release checks (stories 434, 956 and 957):** validate digest and
  revision parity across the app and its Jobs and Flux health gates. On rollout,
  record registry, readiness, role TLS/HBA, internal-route denial and NFS
  read-back separately. The installed playback proof uses short-lived
  production-read keys over verified ingress, records sizes, hashes, ranges
  and denial evidence, then revokes the keys. Personal phone playback
  requires its own evidence.
- **Wan admission (stories 441 and 442):** the haynes-ops CPU-only suite
  `python3 -m unittest discover -s scripts/wan-video -v` exercises lease
  transfer, queue refusal, durable recovery, child deadlines, memory checks and
  typed results with fake engines. The weights read-back checks both pins.
  Live hosting and handover require a bounded leased smoke.
- **Media backend smokes (stories 459–461):** image CI uses synthetic graphs
  to exercise the runtimes, including the segmentation socket and offline
  loader with the pinned model classes and processors. Real-weight one-shot
  jobs check pins and bounds. Matting measures phase and post-request RSS,
  preservation of green eyes and deterministic aligned outputs. Segmentation
  first compares mapped and buffered byte parity. Its serving smoke records
  three passes of six calls after cold load, each phase and pass-end sample,
  readiness and create-only replay. Pass 1 warms the weights. The maxima
  for worker RSS and cgroup residency in pass 3 may each grow at most 64 MiB
  over pass 2. Pass-end memory is diagnostic. The run budget is 840 s
  within the 900 s Job deadline.
  Upscaling measures allocator parity and deterministic replay, timing,
  phased memory, deadline recovery, edge spread, ringing, texture, glyphs,
  faces and flicker. CR-56 uses Lanczos-relative overshoot and motion
  verdicts and retains the absolute figures for both. The private
  comparison reports the two output hashes and objective diagnostics.
  Private still trials in stories 451 and 452 and Tom's verdict on the
  story 461 comparison stay separate from smoke outcomes.
- **Segmentation adapter (story 452):** the real Unix handler with a fake
  graph and synthetic stills covers readiness, grounded mask verification,
  scratch path safety, missing or mismatched staged receipts, cache pins and
  publication. Board, asset-version and snapshot schemas are pinned
  byte-for-byte against the unchanged source baseline.
- **Images (story 433):** PR and main jobs scan and smoke both images, with
  Python package and OpenAPI checks, a disposable PostgreSQL 16 migration and
  nginx SPA fallback, cache headers and reserved-path 404s. The main-only
  publisher pushes the tested archives and records digests alongside the revision.

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
| `photo.too_large` | too_large | 5, 12 | |
| `photo.image_invalid`, `photo.hash_mismatch`, `photo.method_invalid` | invalid | 5, 12 | |
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
| `run.snapshot_missing` | invalid | 8 (snapshot GET uses 404) | [run-snapshot-missing](examples/invalid/run-snapshot-missing.json) |
| `voice.absent`, `voice.stale`, `photo.absent`, `asset.generating` | invalid at queue | 8, 10 | |
| `store.locator_invalid` | invalid | 8 | [store-locator-invalid](examples/invalid/store-locator-invalid.json) |
| `store.collision` | failed stage | 8 | |
| `store.hash_mismatch`, `store.blob_missing` | failed stage | 8 | |
| `store.record_invalid`, `store.media_type_unsupported` | invalid | 8 | |
| `delivery.master_invalid`, `delivery.record_invalid`, `delivery.legacy_mismatch` | invalid | 8 | |
| `delivery.proxy_invalid`, `delivery.master_changed`, `delivery.not_verified` | failed stage | 8 | |
| `private_view.invalid` | invalid | 8 | |
| `private_view.remote_failed`, `private_view.readback_failed`, `private_view.withdraw_failed` | failed private-view attempt | 8 | |
| `cache.key_input_invalid` | invalid | 4 | |
| `cache.entry_invalid`, `render.frame_count`, `render.frame_invalid`, `splice.incompatible` | failed stage | 4 | |
| `voice.speaker_not_in_cast` | invalid | 10 | [voice-speaker-not-in-cast](examples/invalid/voice-speaker-not-in-cast.json) |
| `voice.not_stock` | invalid | 10 | [voice-not-stock](examples/invalid/voice-not-stock.json), [job-voice-not-stock](examples/invalid/job-voice-not-stock.json) |
| `voice.not_needed`, `voice.request_invalid`, `voice.format_mismatch`, `voice.engine_mismatch` | invalid | 10 | |
| `job.transition` | conflict | 2 | |
| `approval.approver_not_permitted` | forbidden | 11 | [approval-not-human](examples/invalid/approval-not-human.json) |
| `approval.not_exact_run` | invalid | 11 | [approval-not-exact](examples/invalid/approval-not-exact.json) |
| `conflict.revision` | conflict (HTTP 409) | 12 | |
| `idempotency.mismatch` | invalid for idempotency-key reuse, conflict for candidate job ID/result mismatch | 12 | |
| `auth.subject_forbidden` | forbidden (HTTP 403) | 12 | |
| `service_unavailable` | dependency outage (HTTP 503) | 12 | |
| `internal` | unexpected failure (HTTP 500) | 12 | |
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
| `decal.offset_high`, `decal.ink_excess`, `decal.track_lost` | failed check | 5, 8 | |
| `decal.track_weak`, `decal.track_unmeasured`, `decal.visual_unmeasured`, `decal.visual_invalid`, `decal.evidence_invalid` | incomplete check evidence | 5, 8 | |
| `wardrobe.attribute_mismatch` | failed check | 8, 9 | |
| `wardrobe.attribute_unmeasured`, `wardrobe.costume_unmeasured`, `wardrobe.evidence_invalid` | incomplete check evidence | 8, 9 | |
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
| `draft.protected` | conflict (409) | 12 | |
| `photo.stale`, `asset.recorded_without_media` | invalid (422) | 4, 8, 9, 12 | |
| `photo.upload_busy`, `photo.upload_timeout` | unavailable (503), body timeout (408) respectively | 12 | |
| `work.dispatch_unconfirmed` | failed job | 12 | |
| `work.lane_paused` | conflict (409, internal Wan dispatch authorization) | 8, 12 | |
| `work.revision_mismatch` | failed run | 8 | |
| `wan.cancel_waiting_for_absence`, `wan.pre_admission_failed`, `wan.admission_unknown` | held run | 8 | |
| `run.snapshot_lost`, `run.snapshot_changed`, `run.snapshot_too_large` (snapshot read) | service unavailable (503) | 8 | |
| `run.snapshot_too_large` (new enqueue) | invalid (422) with size evidence | 8 | |
| `approval.approver_not_configured`, `approval.subject_not_permitted`, `approval.group_not_permitted`, `approval.worker_not_permitted`, `approval.sign_in_again` | forbidden (403) | 11 | |
| `approval.legacy_run`, `approval.run_unfinished`, `approval.delivery_unverified`, `approval.delivery_mismatch`, `approval.provenance_missing`, `approval.licence_missing`, `approval.ai_label_missing` | invalid (422) | 11 | |
| `approval.already_active`, `approval.already_withdrawn` | conflict (409) | 11 | |
| `approval.licence_register_unavailable` | service unavailable (503) | 11 | |
| `auth.return_to_invalid` | invalid (422) | 12 | |
| `production.name_duplicate`, `story.title_duplicate`, `key_admin.key_revoked`, `format.id_duplicate` | conflict (409) | 12 | |
| `format.frame_mismatch`, `format.target_invalid`, `format.length_invalid`, `format.credential`, `format.recipe_too_large` | invalid (422) | 12 | |
| `candidate.legacy_run`, `candidate.run_unfinished`, `candidate.target_required`, `candidate.format_missing`, `candidate.target_unknown` | invalid (422) | 12 | |
| `feedback.text_required`, `feedback.board_unknown`, `feedback.note_unknown`, `feedback.duplicate_reference` | invalid (422) | 12 | |
| `feedback.already_corrected` | conflict (409) | 12 | |
| `feedback.person_required` | forbidden (403) | 12 | |
| `work.lane_forbidden` | forbidden (403) | 12 | |
| `database.failed` | service unavailable (503) on transient disconnect | 12 | |
| `key_admin.worker_lane_conflict` | worker token administration refusal | 12 | |
| `archive.invalid_text`, `archive.credentials`, `archive.production_mismatch`, `archive.not_storyboard`, `archive.story_mismatch` | invalid (422) | 7, 12 | |
| `archive.too_large` | too large (413) | 7, 12 | |
| `archive.stale_version` | conflict (409) | 12 | |
| `archive.text_hash_mismatch` | internal (500) | 12 | |
| `archive.version_not_descendant` | per-board apply refusal | 12 | |
| `subtitle.access_denied`, `subtitle.verbatim` | local source and staging refusals | 12 | |
| `release.format_missing`, `release.target_unknown`, `release.maximum_unset`, `release.over_length`, `release.aspect_mismatch`, `release.location_invalid`, `release.publication_before_approval`, `release.publication_in_future` | invalid (422) | 11, 12 | |
| `release.approval_required`, `release.already_published` | conflict (409) | 11, 12 | |
| `release.store_unavailable`, `release.package_changed`, `release.package_record_changed` | service unavailable (503) | 8, 11, 12 | |
| `adapter.request_invalid` (matte admission) | invalid (422) | 12 | |
| `adapter.request_invalid` (matting socket) | bad request (400) | 13 | |
| `adapter.pin_mismatch`, `adapter.busy` (matting socket) | conflict (409) | 13 | |
| `adapter.command_failed`, `adapter.response_invalid`, `adapter.not_found`, `adapter.timeout` (matting socket) | 500, 502, 503 and 504 respectively | 13 | |
| `matting.shape_invalid`, `matting.slot_mismatch`, `matting.target_exceeds_frame`, `ref.unpromoted` | candidate or placement refusal | 5, 8, 9 | |
| `matting.sidecar_unavailable`, `work.result_rejected` (matte) | failed job | 12 | |

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
| Q-840-01 The voice per cast slot, from story 840's Kokoro reels: (a) one candidate per slot, (b) keep the r4 voices, (c) wait for the next model trial | Open for review. Working choice in [ruling 04](#ruling-04). The audition reels stay available. | Tom, open |
| Q-840-02 Per-line speed and delivery: (a) keep the service's one speed, 1.0, (b) a studio Kokoro with per-request speed (haynes-ops), (c) per-request speed and a delivery instruction as requirements of the next voice engine | Open for review. Working choice in [ruling 05](#ruling-05). | Tom, open |
| Q-406-1 The terminal state of a service-phase run: (a) `cancelled` with reason "service phase complete", (b) a new state for a completed phase, (c) a phase that is not a run | (a), until E3's job queue gives phases their own records (section 8) | the contract owner |
| Q-406-2 Where the live build runs: (a) all in a session pod at two threads, (b) the service phases in a session pod and the offline phase on `ai/studio-render`, the store copied between them, (c) let studio-render reach the services (haynes-ops) | (b), until the NFS store adapter of story 434 (section 8) | the contract owner |
| Q-846-01 A row the private import does not read on purpose: (a) `absent` with a reason, keeping three statuses, (b) a fourth status `not_read` | (a) (section 9) | the contract owner |
| Q-846-02 Read the E0 drive tracks too (11 more reads a layered build does not need)? | Yes: no other record of them exists outside the volume (section 9) | the contract owner |
| Q-846-03 The r1 ComfyUI renders, which a CronJob may remove around 2026-12-03 | Not imported: they matter only to regenerate a cutout, and the layered build does not need them (section 9) | the contract owner |
| Q-428-2 The off-frame limit on keyed frames: (a) keep the 240 px limit the port applies to still cutouts, (b) no limit for keyed frames, as E0's film had | (a) for E1; the demo's draft moved r4's `closeup` slot `x` from 0.56 to 0.55 (board 7 was 9 px over); revisited with the layout editor (section 5) | the contract owner |
| Q-428-3 A weak lettering track on a clip the build made: (a) a re-roll by a draft seed edit, (b) a lower floor | (a): a new clip and key, the weak clip stays in the store; no agent lowers a floor, and a person's override stays `record_check_override` (stories 410, 450) (section 5) | the contract owner |
| Q-428-4 The speech-clip prompt: the build sends one prompt for every doll, where E0 described each doll in her own. (a) Keep one prompt if the demo's dolls look right, (b) a per-cast description that the build puts into each speech prompt (a model and key change) | Open for review. Working choice in [ruling 01](#ruling-01). | Tom, open |
| Q-428-5 After a weak lettering track: (a) the build re-rolls by itself up to twice per clip, then stops; (b) it always stops for a person | Open for review. Working choice in [ruling 02](#ruling-02). Each re-roll is one GPU job of 3 to 15 min. | Tom, open |
| Q-428-6 Confirm the relayed word on GPU heat. An unverified message (story 428, comment 8409) says 89 C is acceptable. P-49 records it as the reason cited at the time. | Open for review. The relay remains unverified. The working practice in [ruling 03](#ruling-03) stands on the existing guards. | Tom, open |
| Private verdict and E1 acceptance (D56) | Tom approved the exact quieter-gavel Winter Menu cut on 2026-11-21 ([epic 372](https://work.haynesnetwork.com/work_packages/372), comment 9487). The record covers that cut. E1 acceptance and the creative verdict on One More Meeting are open. | Tom |
| Q-841-01 A sound cut at the film's end: (a) hard cut at the last sample, (b) fade the last 50 ms before the cut (a new mixer version) | Open for review. Working choice in [ruling 06](#ruling-06). | Tom, open |
| The private link's default file: phone proxy or master | Open for review. [Ruling 07](#ruling-07) keeps P-52. The first story 428 link still plays the master. | Tom, open |
| Keep story 428's private store before its worker volume may be archived from about 2026-11-21? | Open (story 428, comment 8952). Keeping it needs a platform action by Tom, or the dev-env coordinator on his word; no such action is planned | Tom, open |

Tom was told on 2026-11-14 that the r1 ComfyUI renders lapse around 2026-12-03;
he has not asked for them to be kept.

**Store custody (story 428, comment 8952, 2026-11-18, historical).** The store is outside git on
the suspended worker `haynes-studio-1114-013021`'s volume. Rescue keeps git work only. Archival would lose keyed frames, segments, mixes, the then-unserved gavel
edit and the Wan journal. The first delivery's four files and the 14 speech clips
with their Wan ledgers remain on the Wan volume, and public records and hashes stay
in git. The missing parts can be made again by CPU work after a fresh import, without
a GPU job. The store was not reachable by the coordinator. Story 941 later recovered the exact quieter-gavel
delivery and story 942 archived both films on the Studio share. Those archives do
not establish custody of the original scratch store or first live use of
`studio private-view`.

**Follow-up states as of 2026-11-18 (fifth amendment).** Source, tested, installed and accepted are separate.

- **Source and tested, no live run:** story 861's negative prompts and keys
  (O-851-2 closed, PR 73); story 864's agent-session operators and people-only guards
  (O-428-1 closed, P-50, PR 77). Their other-family reviews ran before merge.
- **Source and tested, first live use not done:** story 863's `studio private-view`
  (PR 75), with the other-family review and its fix round complete. It replaces the
  driver dropped from PR 70, not present on `main`; five other drivers merged as
  records. First use needs story 428's store made reachable or the next build's
  verified delivery. Tom's acceptance is separate.
- **Installed:** the render worker at the lock (story 862, O-428-7 closed as installed,
  haynes-ops PR 4932 and studio PR 74); the Wan API's queue-answer validation (story
  865, haynes-ops PR 4931) and byte ranges (story 881, haynes-ops PR 4928). **Not done:**
  an offline phase on the worker with keys/hashes compared; a malformed queue answer
  or GPU job on the new API exercised live; verification through Traefik and Tom's
  player. Installed does not claim his acceptance.
- **Cause still open:** the intermittent frame mismatch (story 888, PR 76). The merged
  diagnostics keep the comparison exact; a recurrence supplies frame/input evidence.
- **CI:** source jobs now have 20 minutes (PR 78); speeding up or splitting the suite
  is not done.
- **Still a known limit:** a refused board's partial stage has no place in the run
  record (story 860); it gets a story only if a build needs that time.

**Questions from the first two waves.** Working choices are linked below. They
stay open for Tom's review, including those whose implementation already landed.

| Question | Working record | By |
|---|---|---|
| Authenticated private phone playback proof (story 944) | [Ruling 08](#ruling-08). Installed automated proof is recorded in section 13. Human sign-in, seeking and phone playback remain open. | Tom, open |
| Q-409-01 Who may sign in? | [Ruling 09](#ruling-09) was replaced by [ruling 16](#ruling-16) | Tom, open |
| Which namespace hosts the app? | [Ruling 10](#ruling-10) | Tom, open |
| How is the database role provisioned? | [Ruling 11](#ruling-11) | Tom, open |
| Where do deployment secrets come from? | [Ruling 12](#ruling-12) | Tom, open |
| Which error statuses distinguish method refusal, outages and unexpected failures? | [Ruling 13](#ruling-13) | Tom, open |
| Q-408-01 Does declining a preview need its own persistent disposition? | [Ruling 14](#ruling-14) | Tom, open |
| Q-413-01 What restores a deep route after login with tab storage blocked? | [Ruling 15](#ruling-15). Story 412 ships the validated return path. Live user sign-in proof remains open. | Tom, open |
| What LAN address serves Studio? | [Ruling 17](#ruling-17) | Tom, open |
| Q-415-01 Must production names and story titles be unique at the API? | [Ruling 18](#ruling-18). Story 412 ships atomic enforcement. | Tom, open |
| Q-410-01 What follows an ambiguous queue PUT when Wan has no job at that ID? | [Ruling 19](#ruling-19). The queue fix is merged and installed. Live completion remains open. | Tom, open |
| Q-442-01 Which local profile proceeds? Q-442-03 When may it remain resident for one-card S2V? | [Ruling 20](#ruling-20) selects the pilot and keeps unload before any Wan dispatch pending placement proof | Tom, open |
| Q-442-02 When should structured output and multi-frame input be available? | Story 441 ships both modes of input and structured output in dormant admission code. Story 442 owns live proof. | Tom, open |
| Q-433-01 Does first image publication need a visibility change? | Answered by anonymous registry reads of both packages (section 13). | Observation, 2026-11-24 |

**Questions from the seventh amendment.** The working choices in section 19
remain open for Tom's review. Q-434-01 uses [ruling 21](#ruling-21).
Q-419-01 uses the run-scoped snapshot in [ruling 31](#ruling-31).
The choices of CPU matting, segmentation and comparison scaler are in
[rulings 33–35](#ruling-33), with install and quality checks still open.

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
| P-17 | Scopes `read`, `draft:write`, `assets:generate`, `assets:upload`, `runs:queue` per production, plus explicit `formats:write` authoring (ruling 25) | one all-powerful key |
| P-18 | The stack in section 13 | as listed there |
| P-19 | Test suites, markers and commands in section 14 | per-story ad hoc suites |
| P-20 | `video` media kind 1920x1080 at 24 fps | 25 or 30 fps |
| P-21 | Labels are mutable asset metadata, outside version content | labels inside immutable versions |
| P-22 | Stock TTS voices only | any voice without a real-person check |
| P-23 | `commercial_use` value `conditional`, with the conditions in `note`; a research- or evaluation-only term is `noncommercial` with a note that it is narrower (the contract owner, after story 809) | `unknown` for a known conditional term (it hides what the register knows); a value of its own for research-only terms |
| P-24 | Principal `{kind: agent_session, session, harness, model}` for work an agent did in its own session without a studio key; it grants nothing (the contract owner, after story 809) | `{kind: worker, worker_id}` naming the session (a worker is a studio process with a service token, P-14); `{kind: agent}` without a key (an agent principal is a studio key) |
| P-25 | S2V drive track keyed on its speaker's takes and their starts (H-1, the contract owner) | the whole board voice track, which rebuilds every speaker on any line edit |
| P-26 | Reproducible segment encode: serial x264, AVX2 on x86-64-v3 or scalar elsewhere, no B-frames, 48-frame maximum GOP, profile and build in the key, stream-copy splice | frame threads, sliced threads, uncapped assembly |
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
| P-46 | The first live build's working choices (story 428): E0's seeds in the draft, as no server assigns seeds yet; one speech prompt for every doll (Q-428-4 open for Tom); the 240 px off-frame limit kept for keyed frames, with board 7's `closeup` slot moved to `x` 0.55 (Q-428-2, the contract owner); a weak lettering track answered by a re-roll by seed edit, the weak clip kept (Q-428-3, the contract owner); the offline phase in the session pod before story 862 put the worker at the lock | no limit for keyed frames, as E0's film had; an agent lowering a decal floor; installing into the cluster to use the render worker during story 428 |
| P-47 | Six small fixes as built (story 860): a stopped run (`failed`, `cancelled`, `held`) keeps the board stages it completed; a reused layered segment lists its decal gate results, reported and never a second gate, and a run check may name its `slot`; `store doctor` reports the journal's two root files under `journal`; one register file entry per engine for a file two engines load; the import's summary reads voices as the library does, while its stored story and map keep their own derived values (O-860-1, the contract owner) | `stages: []` on a stopped run (its work in no record); running the gate again on a reused segment; an `engines` list on a register file entry (changes the register's shape and its readers); rewriting what `studio legacy import --out` stores |
| P-48 | The command line's operator when an agent session runs it (O-428-1, the contract owner): the E1 records written as `{kind: human}` under the stand-in issuer `https://agent-session.invalid/dev-env` are kept as they are: that issuer marks them, and they are never presented as a person's act; new records use P-50 (story 864, O-428-1 closed) | rewriting the records already written; letting an agent session sign in as a person |
| P-49 | GPU heat (the contract owner's practice): no temperature stop line of the coordinator's own in GPU work orders; each job's peak recorded; the API's lease, the client's cool-idle start check and the unknown-work checks as the guards. Its recorded reason is a relayed, unverified message (story 428, comment 8409), not Tom's ruling; Q-428-6 asks him to confirm it | a fixed stop line such as story 428's 88 C (taken from E0's 84 to 88 C range, not a platform limit) |
| P-50 (the contract owner, 2026-11-18; story [864](https://work.haynesnetwork.com/work_packages/864)) | CLI operator `human` or `agent_session`; exclusive complete flag sets; existing actor fields preserved; private-view ledger `provenance.created_by`; people-only promotion and Wan clears require a human | a stand-in human issuer for new agent work; treating attribution as authentication or permission |
| P-51 (the contract owner, 2026-11-18; story [861](https://work.haynesnetwork.com/work_packages/861)) | Speech negative prompt defaults to the client's `NEGATIVE`; `i2v_negative_prompt` in the whole-frame key, request and clip-set record; adding an artifact input changes that artifact's keys without bumping `studio.cache-key/v1`; story 428's speech keys stay unchanged (O-851-2 closed) | an empty speech default the client refuses; a whole-frame key missing the negative prompt; a shared scheme bump that invalidates unrelated keys |
| P-52 (the contract owner, 2026-11-18; story [863](https://work.haynesnetwork.com/work_packages/863)) | `studio private-view` may create new files and a new ledger on the Wan volume, proxy by default, master by `--master`; exclusive folder reservation, no-follow identity checks, final hashes before the link, read-backs and withdrawal of only this attempt's own ledger; create-only local record; the four `private_view.*` codes of section 8 | reusing the retired one-off driver; master as the default link file; overwriting a production or deleting a ledger; leaving a known failed read-back served without attempting withdrawal |
| P-53 (story 407) | Board photo signature per current plan, provenance and immutable version per operation, with a fenced pointer update (sections 4, 7, 9 and 12) | a stale or unsigned photo treated as current, or changing the draft for a late result |
| P-54 (story 453) | Versioned delivery conversion changes segment keys only. The hashed profile names the Pillow version and the measured native core digest stays in provenance (sections 3–5 and 7) | hashing the interpreter-specific native core into the board segment key |
| P-55 (stories 409, 429 and 432) | HTTP revision and error conventions, scoped single-range media, group or subject sign-in, and a stateless MCP over the API (section 12) | browser tokens, direct MCP database access, or sign-in membership granting go-live authority |
| P-56 (story 450) | Versioned wardrobe and decal evidence. Uncertain blocks. Story 454 owns the calling loop for the bounded re-roll guidance (sections 5, 8 and 9) | treating missing evidence as a pass or weakening the gate for one clip |

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
| What `held` covers | section 8: unknown work on the lease, an ambiguous external job | CLI holds on all Wan clip client refusals. The product queue requeues verified retryable pre-admission refusals with backoff | stories 851 and 410 (section 8) |
| A legacy board voice | story 405's planner: current (its signatures match); story 406's build: unusable (no track) | stale for a build until `studio voice` assembles it | the contract owner's decision, built by story 857 |
| Wan ledgers and outputs | section 8 before stories 842 and 863: the Wan PVC is never written | engine jobs create their own ledgers and outputs; `studio private-view` may create a new production and ledger, never overwrite an existing one | the API's own `generate()` (story 842); P-52, the contract owner's exception for private viewing |
| Off-frame limit for keyed frames | `poc/edit.py`'s 240 px assert for still cutouts; E0's layered film checked none for keyed frames | 240 px for keyed frames too | Q-428-2 (the contract owner), until the layout editor |
| A legacy import's derived values | the import's own facts (every legacy voice current); the library's facts for a build (stale without a track) | stored documents keep the import's values; the summary and the library's facts speak for a build | O-860-1 (the contract owner) |
| An artifact gains a key input | a shared `studio.cache-key/v1` bump would invalidate all stored motion identities | change only that artifact's keys; keep the scheme | P-51, the contract owner's decision; story 861 adds the whole-frame negative prompt |
| CLI operator | old command line: human only, including agent sessions under a stand-in issuer | human or `agent_session` for new records; old records unchanged | P-50, the contract owner's decision; attribution grants no access and people-only guards remain |
| Private link's file | story 428's one-off driver linked the master, leaving its phone proxy without a link | the command defaults to proxy, with `--master` for the master | P-52 and [ruling 07](#ruling-07). First live use of that command remains open |
| Render worker | 2026-11-14 observation: Python 3.13 and media outside the lock; D18 and Q-406-2 put offline work there | Python 3.12.16 and the twelve locked runtime packages installed on 2026-11-18 | story 862, O-428-7 closed as installed. Story 942 later ran the offline phase, and a paired key/hash comparison remains open |
| Delivery profile digest | story 453's initial text hashed the native Pillow core, which differs across Python wheels | hash the Pillow version and measure the core in provenance only | [PR 84 coordinator review](https://github.com/thaynes43/haynes-studio/pull/84#issuecomment-7143158345). This keeps one segment key across the planner and worker. |
| Browser sign-in | story 409 started with a subject allowlist | verified exact group claim or a listed subject. Go-live has its own issuer/subject policy | [ruling 16](#ruling-16) replaces [ruling 09](#ruling-09) |
| After sign-in | the sign-in handoff assigned an API return path to story 432 | API records a validated path on the one-use attempt and uses a safe failure redirect | [ruling 15](#ruling-15), implemented in story 412. Live user sign-in proof remains open |
| Image package names | PR 91 originally proposed `studio` and `studio-web` | `haynes-studio` and `haynes-studio-web` | coordinator review renamed them before first publication, verified in story 433 comment 9788 |
| Local model operation | the initial story 441 proposal has one staged image and plain text | multi-frame and structured modes are merged and installed dormant. The selected pilot needs a live proof | story 442, [ruling 20](#ruling-20). D46 still governs a writer switch |
| Snapshot comparison | story 419 proposed indexing snapshots in generic media | run-scoped, authorized and verified snapshot bytes with distinct loss evidence | [ruling 31](#ruling-31), stories 958 and 448 |
| Approval history identity | first review read returned issuer, subject and sign-in time to every signed-in in-scope reader | display name and decision times for those readers; full identity and sign-in time for approvers | [ruling 32](#ruling-32), story 448 |
| Older and imported board protection | initial drafting protected person edits and other-key drafts | default protection unless the same key created and still drafts the board with no person edit | [ruling 28](#ruling-28), story 958 |

## 19. Coordinator rulings (provisional)

These are the coordinator's rulings, made under Tom's instruction of 2026-11-24
that work must not wait on his approvals ([saga 362](https://work.haynesnetwork.com/work_packages/362),
comment 9653). Tom has not seen or confirmed any of them.

| Number | Date | Question | Option taken | Why | Recorded in | What it changed | Standing |
|---|---|---|---|---|---|---|---|
| <a name="ruling-01"></a>CR-01 | 2026-11-24 | Q-428-4, one speech prompt or per-cast descriptions? | (a) Keep one prompt. | The quieter-gavel cut built with it received Tom's private verdict (comment 9487). Per-cast text would change keys. | [Epic 372](https://work.haynesnetwork.com/work_packages/372), comment 9659 | Keeps story 428's prompt default. | Provisional |
| <a name="ruling-02"></a>CR-02 | 2026-11-24 | Q-428-5, what follows a weak lettering track? | (a) Re-roll automatically at most twice per clip, then stop with evidence. | The recommended bound fits D9's unattended factory. | [Epic 372](https://work.haynesnetwork.com/work_packages/372), comment 9659 | Story 450 emits bounded guidance. Story 454 owns the loop. | Provisional |
| <a name="ruling-03"></a>CR-03 | 2026-11-24 | Q-428-6, should the coordinator set a separate GPU temperature stop? | Keep the Wan cool-idle start gate, lease and unknown-work checks, and record each job's peak. No separate coordinator temperature line. | P-49's working practice is independent of the unverified relay. | [Epic 372](https://work.haynesnetwork.com/work_packages/372), comment 9659 | Continues the existing GPU work-order practice. | Provisional |
| <a name="ruling-04"></a>CR-04 | 2026-11-24 | Q-840-01, which cast voices are defaults? | Keep the voices of the quieter-gavel cut, with the story 840 reels available and pre-build switching per board. | Tom chooses voices by ear. | [Epic 372](https://work.haynesnetwork.com/work_packages/372), comment 9659 | Keeps defaults while preserving D33 iteration. | Provisional |
| <a name="ruling-05"></a>CR-05 | 2026-11-24 | Q-840-02, where do per-line speed and delivery belong? | (c) Require both of the next voice engine. Keep Kokoro at one speed. | The worker's recommendation avoids an immediate service change. | [Epic 372](https://work.haynesnetwork.com/work_packages/372), comment 9659 | Sets the next engine's requirements. | Provisional |
| <a name="ruling-06"></a>CR-06 | 2026-11-24 | Q-841-01, hard cut or a 50 ms fade at film end? | (a) Hard cut at the last sample. | That's the built behaviour and neither film cuts a sound there. | [Epic 372](https://work.haynesnetwork.com/work_packages/372), comment 9659 | Keeps the mixer boundary in P-38. | Provisional |
| <a name="ruling-07"></a>CR-07 | 2026-11-24 | What file should a private link choose by default? | Phone proxy by default, master by `--master` (P-52). | The command already defaults to the phone rendition prepared for both films. | [Epic 372](https://work.haynesnetwork.com/work_packages/372), comment 9659 | Keeps the default without changing historical links or claiming live command use. | Provisional |
| <a name="ruling-08"></a>CR-08 | 2026-11-24 | Where should story 944 prove the authenticated viewer? | Fold the proof into E3. Use story 409's range-capable media endpoint with Authentik and stories 432 and 434. | An isolated loopback path would differ from what ships. | [Epic 372](https://work.haynesnetwork.com/work_packages/372), comment 9659 | Automated proof verifies scoped ranges and denial. Human sign-in, play and seek remain open. | Provisional |
| <a name="ruling-09"></a>CR-09 | 2026-11-24 | Q-409-01, who may sign in? | Explicit verified subject allowlist in Studio and the Authentik `authentik Admins` application binding. | Conservative for the single human user in D5 and consistent with the subject-based go-live boundary. | [Epic 374](https://work.haynesnetwork.com/work_packages/374), comment 9700 | Initial sign-in plan for deployment. | Provisional, superseded by [ruling 16](#ruling-16) |
| <a name="ruling-10"></a>CR-10 | 2026-11-24 | Where do API, web and MCP run? | Namespace `ai`, with Wan and studio-render. | Uses the existing Studio service namespace. | [Epic 374](https://work.haynesnetwork.com/work_packages/374), comment 9700 | Sets placement for the DB projections and the story 434 app. | Provisional |
| <a name="ruling-11"></a>CR-11 | 2026-11-24 | How should Studio get database roles? | CNPG Database and managed runtime and schema-owner roles on `database/postgres16`, following the portal pattern. | Least privilege for story 431 without passing a superuser password to the app. | [Epic 374](https://work.haynesnetwork.com/work_packages/374), comment 9700 | Sets the installed two-role design and migration boundary. | Provisional |
| <a name="ruling-12"></a>CR-12 | 2026-11-24 | Where should deployment secrets come from? | In-cluster External Secrets Password generator with CreatedOnce. | No dependency on an agent creating a 1Password item or seeing a value. | [Epic 374](https://work.haynesnetwork.com/work_packages/374), comment 9700 | Sets DB/SSO generation and projection and the MCP file registration path. | Provisional |
| <a name="ruling-13"></a>CR-13 | 2026-11-24 | How does a client distinguish method refusal, outage and unexpected failure? | Keep `unavailable` at 422 and add `service_unavailable` 503 and `internal` 500. Carry `request_id` in every JSON error. | Clients can distinguish dependency failure from a method capability refusal. | [Epic 374](https://work.haynesnetwork.com/work_packages/374), comment 9765; [PR 86](https://github.com/thaynes43/haynes-studio/pull/86#issuecomment-7143412295) | Story 409 implements the statuses and correlation ID. | Provisional |
| <a name="ruling-14"></a>CR-14 | 2026-11-24 | Q-408-01, persist a separate rejection when a person declines a preview? | (a) Keep `candidate`. Later explicit promotion remains possible. | The current state and picker exclusion already preserve a declined preview privately. | [Story 408](https://work.haynesnetwork.com/work_packages/408), comment 9709; [PR 87](https://github.com/thaynes43/haynes-studio/pull/87#issuecomment-7143441262) | Keeps the built candidate and promotion states. | Provisional |
| <a name="ruling-15"></a>CR-15 | 2026-11-24 | Q-413-01, how should deep routes survive login without tab storage? | Record a validated same-origin return path on the one-time OIDC attempt and send a safe failure redirect. | API-side state works when browser tab storage is blocked. | [Story 413](https://work.haynesnetwork.com/work_packages/413), comment 9751; [PR 88](https://github.com/thaynes43/haynes-studio/pull/88#issuecomment-7144510993) | Story 412 implements the return path and safe failure redirect. | Provisional |
| <a name="ruling-16"></a>CR-16 | 2026-11-24 | Who may sign in after revisiting Q-409-01? | Bind Authentik to `authentik Admins`. The API accepts a verified exact group claim or an allowed subject. Go-live keeps its own subject allowlist that Tom fills in. | Follows Tom's 2026-10-26 preference for group-based portal access and needs no personal ID in configuration. | [Epic 374](https://work.haynesnetwork.com/work_packages/374), comment 9765 | Replaces [ruling 09](#ruling-09). Story 432 added the API group path and installed Authentik. | Provisional |
| <a name="ruling-17"></a>CR-17 | 2026-11-24 | What is Studio's address? | LAN-only `https://studio.haynesops.com`. | Follows D3/D41 and the private video host convention. | [Epic 374](https://work.haynesnetwork.com/work_packages/374), comment 9765 | Pins the origin and exact OIDC callback. Story 434 supplies ingress. | Provisional |
| <a name="ruling-18"></a>CR-18 | 2026-11-24 | Q-415-01, where is name and title uniqueness enforced? | Enforce atomically in the API with trimmed, NFC, case-insensitive comparison. Scope story titles to production and media type. Report existing duplicates and keep their names. New conflicts return a structured duplicate error. | Client checks cannot close a race between callers. | [Epic 374](https://work.haynesnetwork.com/work_packages/374), comment 9765; [PR 90](https://github.com/thaynes43/haynes-studio/pull/90#issuecomment-7145233048) | Story 412 implements API enforcement. Editor prechecks remain advisory. | Provisional |
| <a name="ruling-19"></a>CR-19 | 2026-11-24 | Q-410-01, what follows an ambiguous queue PUT? | Read the ID. If Wan does not know it, retry the same PUT with the same ID and body. | Product idempotency permits at most one submission and lets the queue recover when the first request never arrived. | [PR 94](https://github.com/thaynes43/haynes-studio/pull/94#issuecomment-7146496362), coordinator comment | Implemented in story 410 and installed with the queue. | Provisional |
| <a name="ruling-20"></a>CR-20 | 2026-11-24 | Q-442-01 and Q-442-03, which pilot and when may it stay resident? | Qwen3.5-9B Q5_K_M first, Ministral 3 8B Instruct 2512 Q5_K_M fallback, pinned llama.cpp sidecar in the Wan pod on one card. Unload before any Wan dispatch until fixed S2V placement on the other card is proved. | Both fit the observed 26 GiB free on disk and leave card headroom for a bounded admission and handover proof. | [Story 442](https://work.haynesnetwork.com/work_packages/442), comment 9798; [PR 95](https://github.com/thaynes43/haynes-studio/pull/95#issuecomment-7146586727) | Chooses the pilot before hosting. The larger Qwen3.8-27B candidate goes to the E10 benchmark (455 and 463) and needs a volume change if selected. | Provisional, activation and live proof pending |
| <a name="ruling-21"></a>CR-21 | 2026-11-24 | Q-434-01, may callers reach Studio MCP from outside the cluster? | Keep MCP cluster-only without ingress. NetworkPolicy selects in-cluster dev-agent and Studio pods. The upload shares the MCP port and boundary. Decide a TLS path with the first caller that needs one. | The LAN app does not require an external MCP caller. | [haynes-ops PR 5025](https://github.com/thaynes43/haynes-ops/pull/5025#issuecomment-7147158253); [Studio PR 102](https://github.com/thaynes43/haynes-studio/pull/102#issuecomment-7151034951) | Sets deployment reachability and keeps `/mcp/upload` within it. Dev-env egress is separate. | Provisional |
| <a name="ruling-22"></a>CR-22 | 2026-11-25 | How is D18's talosw01 CPU allocation split with the queue worker? | 20 vCPUs for offline `studio-render` and 4 for serial `studio-worker`, both low priority. | Keeps the combined limit at D18's 24 vCPUs. | [haynes-ops PR 5026](https://github.com/thaynes43/haynes-ops/pull/5026); [story 956](https://work.haynesnetwork.com/work_packages/956), comment 9872 | Gates worker startup on the reduced offline render cap. | Provisional, installed |
| <a name="ruling-23"></a>CR-23 | 2026-11-25 | May an agent edit a board a person changed? | Every agent patch, reorder that moves it or removal over HTTP or MCP needs an explicit acknowledgment of the board revision read, bound to key, board and revision. Otherwise return `409 draft.protected`. Record acknowledged writes. People retain normal revision checks. | Prevents an ordinary agent write from silently replacing a person's work. | [Studio PR 98](https://github.com/thaynes43/haynes-studio/pull/98#issuecomment-7148411647); [story 411](https://work.haynesnetwork.com/work_packages/411), comment 9883 | Gives one protection path to all draft writes, including blank person-created boards and a reorder across them. | Provisional |
| <a name="ruling-24"></a>CR-24 | 2026-11-25 | Who withdraws, and can a withdrawn run be approved again? | Any eligible approver may withdraw any approval. The run may be approved again. | Retains the reviewed append-only behavior and one active approval per run. | [Studio PR 101](https://github.com/thaynes43/haynes-studio/pull/101#issuecomment-7149000131); [story 412](https://work.haynesnetwork.com/work_packages/412), comment 9857 | A withdrawal appends a record. Reapproval creates its own exact-run record. | Provisional |
| <a name="ruling-25"></a>CR-25 | 2026-11-25 | Who may write formats? | A signed-in person or an agent key with an explicit `formats:write` grant. No default grant set includes it. | Recipe authorship needs explicit authority separate from read and draft work. | [Studio PR 105](https://github.com/thaynes43/haynes-studio/pull/105); [story 447](https://work.haynesnetwork.com/work_packages/447), comment 9919 | HTTP create and version append require the separate scope for agents. | Provisional |
| <a name="ruling-26"></a>CR-26 | 2026-11-25 | May a key overwrite a board another key drafted? | A key with write access may do so with the acknowledgment in [ruling 23](#ruling-23). Record the taking key, time and replaced revision. | Reuses one explicit audit path for writing over work belonging to another principal. | [Studio PR 98](https://github.com/thaynes43/haynes-studio/pull/98#issuecomment-7149951410) | Acknowledgment allows a recorded takeover. | Provisional |
| <a name="ruling-27"></a>CR-27 | 2026-11-25 | Whose authority selects a media job's result? | Use the authenticated requester. Keep an agent result unselected on a person-edited board. A person's eligible result selects as a person edit. | Completion must respect the same draft protection as a direct write, including edits made during the job. | [Studio PR 102](https://github.com/thaynes43/haynes-studio/pull/102#issuecomment-7149951812); [story 430](https://work.haynesnetwork.com/work_packages/430), comment 9911 | Worker completion uses immutable requester provenance. It preserves unselected versions and person edit history. | Provisional |
| <a name="ruling-28"></a>CR-28 | 2026-11-25 | Are older and imported boards with no stamp protected? | Yes. A plain agent write is allowed only when the server records that same key both created and still drafts the board and no person edited it. | Missing provenance must default to protection. The creator is server-owned. | [Studio PR 98](https://github.com/thaynes43/haynes-studio/pull/98#issuecomment-7149951410); [Studio PR 110](https://github.com/thaynes43/haynes-studio/pull/110#issuecomment-7153030071); [story 958](https://work.haynesnetwork.com/work_packages/958), comment 9937 | Adds the creator check to HTTP and MCP board writes. Deploy it before issuing a live agent key. | Provisional, source only at pickup |
| <a name="ruling-29"></a>CR-29 | 2026-11-25 | Who reads formats? | People and agent keys with active `read` on any production can read the studio-wide catalog. Worker tokens are refused. | Catalog recipes reveal no production associations. A worker already receives its own frozen recipe. | [Studio PR 105](https://github.com/thaynes43/haynes-studio/pull/105#issuecomment-7150060762); [story 447](https://work.haynesnetwork.com/work_packages/447), comment 9919 | Adds shared HTTP and MCP reads and excludes workers at the catalog boundary. | Provisional |
| <a name="ruling-30"></a>CR-30 | 2026-11-25 | Who authorizes a responder escalation? | `person` is default. In `automatic`, authorize inside one per production and two total per UTC day. Over-cap packages wait for a person. Enable automatic only after the drill passes and the recorded preconditions are met. | D12 calls for responder escalation without depending on Tom. The cap bounds launches while the interface and evidence checks mature. | [Studio PR 109](https://github.com/thaynes43/haynes-studio/pull/109); [story 445](https://work.haynesnetwork.com/work_packages/445), comment 9926 | Adds an authorization setting and transactional counts. Story 446 remains held. | Provisional |
| <a name="ruling-31"></a>CR-31 | 2026-11-25 | Q-419-01, where do readers get a frozen snapshot? | `GET /v1/runs/{id}/snapshot` with the run read's scope. | The run record binds authorization, locator and hash for the snapshot being compared. | [Studio PR 110](https://github.com/thaynes43/haynes-studio/pull/110); [story 958](https://work.haynesnetwork.com/work_packages/958), comment 9937 | The Runs comparison uses this route. Snapshots stay outside the generic media index. | Provisional |
| <a name="ruling-32"></a>CR-32 | 2026-11-25 | Who can see who approved? | Every signed-in in-scope reader gets display name and decision times. Only allowlisted approvers get issuer, subject and sign-in time. | The review page needs the name and times. OIDC identifiers and authentication evidence are for approvers. | [Studio PR 110](https://github.com/thaynes43/haynes-studio/pull/110#issuecomment-7153030071); [Studio PR 116](https://github.com/thaynes43/haynes-studio/pull/116) | Redacts the approval/withdrawal review read under story 448. | Provisional |
| <a name="ruling-33"></a>CR-33 | 2026-11-25 | Which CPU matting profile? | `birefnet-lite-ort-cpu-v1`, BiRefNet Lite FP32 on ONNX Runtime 1.32.0, two CPU threads, one in flight. BRIA RMBG 1.4 only on a new ruling after a failed smoke. Clips keep existing chroma keying. | Stills can run in seconds on the low-priority render allocation without occupying Wan. The smoke targets green-eye holes. | [Story 459](https://work.haynesnetwork.com/work_packages/459), comment 9934; [profile](../reference/matting-backend-profile.md) | Selects the still pilot and leaves clip refinement to separate paired evidence. | Provisional, profile only |
| <a name="ruling-34"></a>CR-34 | 2026-11-25 | Which segmentation and detection profile? | `grounding-dino-tiny-sam2.1-tiny-cpu-v1`, FP32 CPU, two threads and one request in flight. Grounding DINO Tiny plus SAM 2.1 Hiera Tiny only. Faces use the same grounding and hint path as props. A person-supplied point or box goes straight to SAM. OWLv2 fallback only on a new ruling if grounding fails. Failed masks go to person-drawn geometry. | Keeps Wan available, with measured source-pixel geometry and a path for uncertain targets. | [Story 460](https://work.haynesnetwork.com/work_packages/460), comment 9946 as corrected by 9947; [profile](../reference/segmentation-backend-profile.md) | Selects a combined detector and segmenter with no separate face detector. Story 452 owns private quality proof. | Provisional, profile only |
| <a name="ruling-35"></a>CR-35 | 2026-11-25 | Which delivery scaler should be used? | Keep Pillow Lanczos. Compare only with `fsrcnn-x2-opencv-cpu-v1`, FSRCNN ×2 on two CPU threads followed by Lanczos. Make it selectable only after install smoke and one private comparison show useful gain. | Published scores are mixed and doll faces, hair and lettering are unmeasured. CPU comparison leaves the Wan lease free. | [Story 461](https://work.haynesnetwork.com/work_packages/461), comment 9952; [profile](../reference/upscaling-backend-profile.md) | Preserves default scaling and assigns separate install and private comparison evidence. | Provisional, comparison only |
| <a name="ruling-36"></a>CR-36 | 2026-11-25 | Can a person clear a draft's feedback iteration? | A person can clear the current iteration with the story's revision. Record the draft write and preserve the lineage of frozen runs. | A person can start again without changing what an older run answered. | [Story 449, comment 9987](https://work.haynesnetwork.com/work_packages/449/activity#comment-9987), with the coordinator's text in its work order | Section 12 and Studio PR 120. | Provisional, in force |
| <a name="ruling-37"></a>CR-37 | 2026-11-25 | Where do voice and image workers run? | Place the 1-vCPU voice and image workers off talosw01 unless they need a dependency available only there. Name that dependency, reduce offline render by the same amount, and account for the render pod rolling. Keep talosw01 at 24 Studio vCPUs. | Both are clients of remote engines. The image lane's local composite is one still. | [Story 961, comments 9968](https://work.haynesnetwork.com/work_packages/961/activity#comment-9968) and [9993](https://work.haynesnetwork.com/work_packages/961/activity#comment-9993), with the full placement rule in its work order | Sections 12–13 and haynes-ops PR 5057. | Provisional, in force |
| <a name="ruling-38"></a>CR-38 | 2026-11-25 | What follows the matting smoke's memory failure? | Keep BiRefNet Lite. Measure runtime arena and memory-pattern settings, then set the profile, smoke threshold and sidecar limit from the measured peak with headroom. Return for a ruling if the peak stays at or above 16 GiB. | The first smoke to report passed the chosen image cases, including green eyes. Memory was the failing bound. | [Story 459, comment 9969](https://work.haynesnetwork.com/work_packages/459/activity#comment-9969) | Sections 13–14 and Studio PR 119. | Provisional, measurement rule in force. Interim 14/16 GiB figures superseded the same day by [CR-43](#ruling-43). |
| <a name="ruling-39"></a>CR-39 | 2026-11-25 | What is a staging archive record? | One production, a kind (brief, script or storyboard) and a title. Keep immutable UTF-8 versions up to 256 KiB with hash, revised version, writing principal, optional format pin and original or adapted provenance. Adapted provenance holds a private source locator. | Preserve exact creative inputs and keep source passages out of provenance. | [Story 443, comment 9980](https://work.haynesnetwork.com/work_packages/443/activity#comment-9980) | Sections 2 and 7 and Studio PR 123. | Provisional, in force |
| <a name="ruling-40"></a>CR-40 | 2026-11-25 | What happens when a version has already been revised? | An append names the newest version as its parent. Refuse a stale append and store nothing. | Keep one revision chain. | [Story 443, comment 9980](https://work.haynesnetwork.com/work_packages/443/activity#comment-9980) | Section 12 and Studio PRs 123 and 131. | Provisional, in force |
| <a name="ruling-41"></a>CR-41 | 2026-11-25 | How does an archived storyboard reach a story? | Apply a pinned version through the existing drafting path. Leave person-edited and unstamped protected boards alone and report them. Keep Build's existing approval boundary. | Preserve draft protections and D12/D29. | [Story 443, comment 9980](https://work.haynesnetwork.com/work_packages/443/activity#comment-9980) | Sections 2 and 12 and Studio PR 123, with the ancestry and revision refinements in CR-45 and CR-47. | Provisional, in force |
| <a name="ruling-42"></a>CR-42 | 2026-11-25 | Who can use the staging archive? | Separate production-scoped `archive:read` and `archive:write`. Apply needs `archive:read` and `draft:write` on that production. The shepherd reads by exact version ID with a read-only key. | Confine staging and drafting writes and let the shepherd reuse pinned inputs. | [Story 443, comment 9980](https://work.haynesnetwork.com/work_packages/443/activity#comment-9980) | Section 12 and Studio PR 123. | Provisional, in force |
| <a name="ruling-43"></a>CR-43 | 2026-11-25 | What is the measured matting memory contract? | Disable the CPU arena. Request 8 GiB and limit to 10 GiB for the sidecar and smoke. Keep the offline render memory limit at 32 GiB. | The measured peak fell 42% with byte-identical output. | [Story 459, comment 9985](https://work.haynesnetwork.com/work_packages/459/activity#comment-9985) | Sections 13–14 and Studio PR 124. | Provisional, in force |
| <a name="ruling-44"></a>CR-44 | 2026-11-25 | What does dismissing a candidate do? | Label the action **Not now** and say it hides the candidate in this tab and records nothing. Keep the candidate under CR-14. | The API has no decline operation. | [Story 456, comment 10017](https://work.haynesnetwork.com/work_packages/456/activity#comment-10017) | Sections 9 and 12 and Studio PR 121. | Provisional, in force |
| <a name="ruling-45"></a>CR-45 | 2026-11-25 | Which version can replace an archive-stamped board? | Only a descendant in the same record can replace it. An eligible same-version apply is skipped. An older or unrelated version reports the stamped version on that board. | A stale storyboard must leave a newer applied board intact. | [Story 443, comment 10037](https://work.haynesnetwork.com/work_packages/443/activity#comment-10037) · [Coordinator relay](https://github.com/thaynes43/haynes-studio/pull/123#issuecomment-7157208825) | Section 12 and Studio PRs 123 and 131. | Provisional, in force |
| <a name="ruling-46"></a>CR-46 | 2026-11-25 | What supplies the private matting trial? | Read one existing cast photo of an imported production where it lies. Keep output in the private jobs area and leave the quality verdict pending until Tom looks. | A bounded trial lets Tom judge a real still. | [Story 451, comment 10015](https://work.haynesnetwork.com/work_packages/451/activity#comment-10015), corrected by [10049](https://work.haynesnetwork.com/work_packages/451/activity#comment-10049) · [Saga 362, comment 10064](https://work.haynesnetwork.com/work_packages/362/activity#comment-10064) | Section 13 records the content-addressed input gate and open trial. | Provisional, input assumption superseded the same day by the content-addressed gate in story 451. Tom's verdict remains pending. |
| <a name="ruling-47"></a>CR-47 | 2026-11-25 | What authorizes apply over a board with no archive stamp? | Where the ordinary drafting rules allow the write, the story revision precondition is the caller's statement that it saw the current story. | An eligible board without an archive stamp has no archive ancestry to compare. | [Story 443, comment 10037](https://work.haynesnetwork.com/work_packages/443/activity#comment-10037) · [Saga 362, comment 10064](https://work.haynesnetwork.com/work_packages/362/activity#comment-10064) | Section 12 and Studio PR 123. | Provisional, in force |
| <a name="ruling-48"></a>CR-48 | 2026-11-25 | What is the restore drill's isolation boundary? | Use a separate single-instance recovery cluster and PVC, restore to a recorded point and connect only to the Studio database. Restrict access to the drill Job. Share only what is needed to read the backup. Write no backups or WAL archive. Cap the target at 2 CPUs and 4 GiB. Start it deliberately through GitOps. Stop if recovery exceeds 30 minutes and verify deletion of the cluster and PVC within the same 60-minute drill. | A physical backup contains every tenant and production backup history must be protected. | [Saga 362, comment 10064](https://work.haynesnetwork.com/work_packages/362/activity#comment-10064) · [Story 436, comment 10072](https://work.haynesnetwork.com/work_packages/436/activity#comment-10072) · story 436 work order | Section 13 records the credential hold. | Provisional, in force. Execution held on Tom's archive credential decision. |
| <a name="ruling-49"></a>CR-49 | 2026-11-25 | Can the scaler comparison use an archived film? | Read one frame of a stored proxy by content hash and frame selector, with its paired master's frame as reference when supplied. Read from the store and write the comparison privately. Report that this measures reversal of a particular downscale and encode. Tom judges the pair by eye. | The store had videos and no stills. | [Saga 362, comment 10064](https://work.haynesnetwork.com/work_packages/362/activity#comment-10064) · [Story 461, comments 10067](https://work.haynesnetwork.com/work_packages/461/activity#comment-10067) and [10229](https://work.haynesnetwork.com/work_packages/461/activity#comment-10229) · story 461 part 3 work order | Sections 5 and 14 and Studio PR 136. | Provisional, in force |
| <a name="ruling-50"></a>CR-50 | 2026-11-25 | Who requests mattes and where do they run? | People request candidates on their own `matte` lane. Agents can only read production-scoped job state. | Keep cutout selection and promotion with people and fence the CPU consumer separately. | [Saga 362, comment 10089](https://work.haynesnetwork.com/work_packages/362/activity#comment-10089) · [Story 965, comment 10106](https://work.haynesnetwork.com/work_packages/965/activity#comment-10106) | Sections 9 and 12 and Studio PR 139. | Provisional, in force |
| <a name="ruling-51"></a>CR-51 | 2026-11-25 | What is the measured segmentation serving limit? | Use memory-mapped weights, request 4 GiB and limit to 5 GiB. Keep the offline render memory limit at 32 GiB. | Mapped and buffered loads yielded identical bytes in measurement. | [Saga 362, comment 10089](https://work.haynesnetwork.com/work_packages/362/activity#comment-10089) · [Story 460, comment 10090](https://work.haynesnetwork.com/work_packages/460/activity#comment-10090) | Sections 13–14 and Studio PR 138. | Provisional, in force. Serving activation remains open. |
| <a name="ruling-52"></a>CR-52 | 2026-11-25 | What follows withdrawal of PyAV 18.1.0? | Install PyAV 18.1.1 at the fourth pin, in the locked images and offline render requirements. Exact rebuilds of 18.1.0 outputs require the original lock or image digest. | On the measured fixture the mix bytes and decoded picture were identical. Embedded encoder strings changed the picture and master hashes. | [Story 966, comment 10095](https://work.haynesnetwork.com/work_packages/966/activity#comment-10095) · [Saga 362, comment 10089](https://work.haynesnetwork.com/work_packages/362/activity#comment-10089) | Sections 4 and 13 and Studio PR 137. | Provisional, in force |
| <a name="ruling-53"></a>CR-53 | 2026-11-25 | How is the segmentation serving version identified? | Keep the v1 model-pair selector in requests and readiness while models and thresholds stay unchanged. Version the serving contract in the manifest, report its exact hash in readiness, and pin that hash in result provenance. | The client verifies the full readiness tuple and still uses the v1 selector. | [Story 460, comment 10112](https://work.haynesnetwork.com/work_packages/460/activity#comment-10112) | Sections 12–13 and Studio PR 138. | Provisional, in force |
| <a name="ruling-54"></a>CR-54 | 2026-11-25 | What does the proposed visibility gate refuse or send to review? | Send `uncertain` with the measurement to person review for a possible override. Block `hidden` without override. Refuse sets declaring foreground roles until the renderer draws those masks. Keep legacy boards intact. | Measurement must reflect the scene that will be drawn. | [Story 452, comment 10116](https://work.haynesnetwork.com/work_packages/452/activity#comment-10116) | Section 5 records the deferred visibility gate. | Provisional. [CR-64](#ruling-64) parked story 452's evaluator. [CR-67](#ruling-67) carries the verdicts to the proposed post-render check in story 975. |
| <a name="ruling-55"></a>CR-55 | 2026-11-25 | Should an upscaling service be staged? | Keep FSRCNN comparison-only and stage no serving overlay until Tom chooses it from the comparison. Delivery stays Lanczos. | The trial needs only its bounded Jobs and no change to the render allocation. | [Story 461, comment 10159](https://work.haynesnetwork.com/work_packages/461/activity#comment-10159) | Sections 5 and 13 and haynes-ops PR 5083. | Provisional, in force |
| <a name="ruling-56"></a>CR-56 | 2026-11-25 | How do the synthetic overshoot and motion checks pass? | Judge against the Lanczos baseline using the existing relative margins. Keep both absolute measurements as diagnostics and drop the two absolute caps as pass conditions. This gates the private comparison only. | The delivery baseline itself failed both absolute caps. | [Story 461, comment 10180](https://work.haynesnetwork.com/work_packages/461/activity#comment-10180) | Section 14 and Studio PR 144. | Provisional, in force |
| <a name="ruling-57"></a>CR-57 | 2026-11-25 | How should unknown occluders affect a verdict? | Compute bounds. Use `hidden` when the upper bound is at or below the floor, `visible` when the lower bound is at or above it, and `uncertain` otherwise. Exclude layers at or below the subject. Bind every supplied input in the evidence digest before validation. | Occluders can only hide, and a review must name the inputs actually measured. | [Story 452, comment 10182](https://work.haynesnetwork.com/work_packages/452/activity#comment-10182) | Section 5 records the deferred evaluator. | Provisional. [CR-64](#ruling-64) parked story 452's evaluator. [CR-67](#ruling-67) carries the bounds to story 975. |
| <a name="ruling-58"></a>CR-58 | 2026-11-25 | What scene and test oracle should the visibility check use? | Measure the scene `compose_photo` draws. An omitted component makes its affected target `unsupported`, with no override. Generated cases compare the evaluator's count against the rendered frame and require its bounds to contain the rendered count for every completion of unknowns. | A check for a richer scene can certify a frame the renderer never produces. | [Story 452, comment 10227](https://work.haynesnetwork.com/work_packages/452/activity#comment-10227) | Section 5 records the proposed post-render check. | Provisional. [CR-64](#ruling-64) parked story 452's evaluator. [CR-67](#ruling-67) carries the renderer-oracle requirement to story 975, using the rendered film frames. |
| <a name="ruling-59"></a>CR-59 | 2026-11-25 | What isolation is required for the shared matte pod? | The worker and sidecar share a network namespace. Restrict pod egress to DNS and the worker API listener, mount the worker token only in the worker, give the sidecar no service-account token, and require worker authentication on every listener route. | Network policy applies to the pod. | [Story 967, comment 10254](https://work.haynesnetwork.com/work_packages/967/activity#comment-10254) | Section 13. CR-65 moved activation to story 970 and CR-66 stages the isolation first. | Provisional, in force for activation under story 970 |
| <a name="ruling-60"></a>CR-60 | 2026-11-25 | What was the first proposed split for story 452? | Ship the adapter with verified observations and the optional mask and layout fields. Refuse builds using the new fields without override. Move the evaluator and its approval machinery to the renderer story and preserve legacy bytes. | Review showed the separate evaluator drifting from the actual renderer. | [Story 452, comment 10259](https://work.haynesnetwork.com/work_packages/452/activity#comment-10259) | Section 5 records why PRs 140 and 147 remain reference material. | Provisional, narrowed the same day by [CR-61](#ruling-61) and superseded by [CR-64](#ruling-64). |
| <a name="ruling-61"></a>CR-61 | 2026-11-25 | Could a writer store the proposed opt-in before the evaluator exists? | Keep the optional schema fields but refuse every write setting board `layout.check_poses` or set `occlusion` with `occlusion.check_unavailable`. Keep the pre-build refusal and remove preservation and ownership machinery for the opt-in. | A stored declaration would have no functioning consumer. | [Story 452, comment 10271](https://work.haynesnetwork.com/work_packages/452/activity#comment-10271) | Section 5 records the parked write-refusal design. | Provisional, superseded the same day by [CR-64](#ruling-64). |
| <a name="ruling-62"></a>CR-62 | 2026-11-25 | When was a rollout admission receipt meant to expire? | Gate the merge by time. After merge require the receipt for that revision and the expected live sequence. Keep read-only audit available. | An elapsed clock window could strand a rollout that Flux was still applying. | [Story 967, comment 10281](https://work.haynesnetwork.com/work_packages/967/activity#comment-10281) | Section 13 records the final rollout rule. | Provisional, superseded the same day by [CR-63](#ruling-63). |
| <a name="ruling-63"></a>CR-63 | 2026-11-25 | What may mutate the cluster during this rollout? | Merge the reviewed GitOps PR. After merge the runbook waits and audits while Flux reconciles. Rollback and migration retry each require a new reviewed PR. Read the installed network policies before merge and after reconciliation. Those reads are the authoritative isolation check. | Flux reconciles the stages without manual mutations after merge. | [Story 967, comment 10285](https://work.haynesnetwork.com/work_packages/967/activity#comment-10285) · [Saga 362, comment 10325](https://work.haynesnetwork.com/work_packages/362/activity#comment-10325) | Section 13 and haynes-ops PR 5093. | Provisional, in force |
| <a name="ruling-64"></a>CR-64 | 2026-11-25 | What does story 452 actually deliver? | Merge the explicit-target client and verified create-only mask publication. Keep the proposed fields out of stored schemas until story 968 lands them with the renderer change and visibility check. Park PRs 140 and 147 as references. | Schema exclusion preserves the existing declaration boundary across every writer. | [Story 452, comments 10288](https://work.haynesnetwork.com/work_packages/452/activity#comment-10288) and [10313](https://work.haynesnetwork.com/work_packages/452/activity#comment-10313) | Sections 5, 8 and 12–14 and Studio PR 148. Story 971 owns the separately tracked job. | Provisional, in force for story 452's delivered scope. [CR-67](#ruling-67) moves the proposed visibility check out of story 968. |
| <a name="ruling-65"></a>CR-65 | 2026-11-25 | What belongs in the fourth pin? | Pin Studio `470a90af`, including the app, existing workers, schema `0013_matte_jobs` and PyAV 18.1.1 in both runtime paths. Move the matte worker, sidecar, credential, grant, registration, isolation and 17-CPU render split to story 970. | A plain pin separates the migration and encoder change from worker activation. | [Story 967, comment 10309](https://work.haynesnetwork.com/work_packages/967/activity#comment-10309) · [Saga 362, comment 10325](https://work.haynesnetwork.com/work_packages/362/activity#comment-10325) | Section 13 and haynes-ops PR 5093. | Provisional, in force |
| <a name="ruling-66"></a>CR-66 | 2026-11-25 | In what order may matte isolation and activation land? | Before any matte worker pod exists, install and read back the policy-only Flux stage. Protect the policy from Flux pruning and from garbage collection if the stage is deleted, and verify that the policy selects no existing pod. During activation, prove a blocked connection from inside the new pod before requesting the grant and recheck while running. | A single stage could start the pod before its isolating policy exists. | [Story 970, comment 10324](https://work.haynesnetwork.com/work_packages/970/activity#comment-10324) · [Saga 362, comment 10325](https://work.haynesnetwork.com/work_packages/362/activity#comment-10325) | Section 13 and story 970 part A. Part B is held under haynes-ops PR 5096, which is open and unmerged. Independent review left the inside-pod proof uncleared. [Story 970, comments 10382](https://work.haynesnetwork.com/work_packages/970/activity#comment-10382) and [10574](https://work.haynesnetwork.com/work_packages/970/activity#comment-10574). | Provisional, in force. Activation awaits Tom. |
| <a name="ruling-67"></a>CR-67 | 2026-11-26 | What remains in story 968 after the visibility review? | Limit story 968 to the proposed declaration and renderer. A set version may declare foreground role masks as pinned library asset versions. Both renderers must draw them in front of the cast or refuse the build, including when `layout.foreground` is false. Share validation with the run writers and archive import and enforce the declaration at the model. Move visibility to story 975 as a post-render check on the film's own frames in the existing run-check framework, carrying forward CR-54, CR-57 and CR-58. Move segmentation target hints to story 971, the job that uses them. | Keyed frames only exist after keying, so a pre-build check on reference stills cannot gate visibility in the film. | [Story 968, comment 10368](https://work.haynesnetwork.com/work_packages/968/activity#comment-10368) | Section 5 records the scope split. The proposed renderer and declaration stayed on [Studio PR 151](https://github.com/thaynes43/haynes-studio/pull/151). | Provisional. PR 151 is parked for good, open and unmerged. The mask proposal never landed on `main`. [Story 968, comment 10582](https://work.haynesnetwork.com/work_packages/968/activity#comment-10582). |
| <a name="ruling-68"></a>CR-68 | 2026-11-26 | What does pausing a lane stop? | Pause blocks claims on queued work. A live claim retains its fence and may finish, including a media job's first publish or a run's transcript request. An already authorized engine request may start after the pause response. A lane is quiet at the time of the read when paused with no live claim. Give a paused reconciliation claim only to a worker that declares support, behind a default-off switch. | Pause preserves work already held by a worker. The capability and switch protect mixed-version deployments. | [Story 976, comment 10393](https://work.haynesnetwork.com/work_packages/976/activity#comment-10393) | Sections 8 and 12–15, and merged [Studio PR 152](https://github.com/thaynes43/haynes-studio/pull/152). | Provisional, in force. PR 152 is installed in the fifth pin with `STUDIO_PAUSED_RECONCILE` off. [Story 976, comment 10400](https://work.haynesnetwork.com/work_packages/976/activity#comment-10400) · [Story 978, comment 10409](https://work.haynesnetwork.com/work_packages/978/activity#comment-10409). |
| <a name="ruling-69"></a>CR-69 | 2026-11-26 | Does the lane read expose a live claim with the switch off? | Report additive, read-only `live_claim` for every lane on the signed-in lane read in both switch states. This is the only intended change to the prior response behavior with the switch off. Pause and resume write responses keep their shape. Activate separately after verifying the new build everywhere and draining workers. Enable every API replica, start workers on enabled endpoints and read back. | Operators can observe a quiet lane before activation. A disabled endpoint can permit a missing Wan ID to be replayed. | [Story 976, comment 10397](https://work.haynesnetwork.com/work_packages/976/activity#comment-10397) | Sections 8 and 12–14, and merged [Studio PR 152](https://github.com/thaynes43/haynes-studio/pull/152). | Provisional, in force. The read field ships in the fifth pin with `STUDIO_PAUSED_RECONCILE` off. [Story 976, comment 10400](https://work.haynesnetwork.com/work_packages/976/activity#comment-10400) · [Story 978, comment 10409](https://work.haynesnetwork.com/work_packages/978/activity#comment-10409). |
| <a name="ruling-70"></a>CR-70 | 2026-11-27 | What should story 968 do with set loops and replayed jobs? | (1) The proposed admission rule resolved a loop's source set from its pinned still. If that set declared masks, the build was to be refused with a specific code even if the board did not select the still. The work order also required refusal when the source could not be resolved. (2) A job renders the versions it froze at admission. An expired photo claim replayed after the draft moves from an unmasked to a masked set would still render the frozen unmasked version and save a non-current result. | Part 1 sought to prevent masks being lost when using a loop. Part 2 preserves frozen-input behavior when a draft moves on. | [Saga 362, comment 10575](https://work.haynesnetwork.com/work_packages/362/activity#comment-10575) and story 968 work order `wo-968-fix3`. | Recorded here as the proposed loop rule and the frozen-input clarification for [Studio PR 151](https://github.com/thaynes43/haynes-studio/pull/151). | Provisional. Part 1 is superseded by [CR-71](#ruling-71). Part 2 stands. PR 151 is parked for good, open and unmerged. No story 968 change landed on `main`. [Story 968, comment 10582](https://work.haynesnetwork.com/work_packages/968/activity#comment-10582). |
| <a name="ruling-71"></a>CR-71 | 2026-11-27 | What binds a proposed role-mask declaration to a set or motion loop? | Bind the declaration to the set version that carries it. A board or job selecting a declaring set version must draw its masks or be refused. A motion loop is its own asset version and carries no declaration. Refuse a board using a loop only if it also selects a declaring set version or the loop's own recorded provenance names one. Infer nothing from bytes. Every other loop keeps its `main` behavior and snapshot bytes. A copy registered with different provenance is a different asset with the author's recorded provenance. The build would not detect that its bytes once came from a declaring set. Copy and conflicting catalog lineage rules are out of scope. | Identical still bytes can belong to several sets. Inferring ownership refused legacy loops and still allowed relabelled copies. | [Story 968, comment 10578](https://work.haynesnetwork.com/work_packages/968/activity#comment-10578) | Replaces the loop half of [CR-70](#ruling-70) in the design recorded on [Studio PR 151](https://github.com/thaynes43/haynes-studio/pull/151). | Provisional. PR 151 is parked for good, open and unmerged. The mask proposal never landed on `main`. [Story 968, comment 10582](https://work.haynesnetwork.com/work_packages/968/activity#comment-10582). |
