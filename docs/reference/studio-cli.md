# `studio` command reference

The `studio` command and the `haynes_studio` package (story
[378](https://work.haynesnetwork.com/work_packages/378), epic
[372](https://work.haynesnetwork.com/work_packages/372)). Built against
[contract](../contracts/studio-contracts-v1.md) sections 1 to 3 and 13. It reads the
PoC's legacy files and never writes them; `legacy import --out` creates new files only.
It calls no service. The canonical model behind `legacy import` is in
[studio-model.md](studio-model.md) (story
[404](https://work.haynesnetwork.com/work_packages/404)).

## Install and run

```sh
UV_PYTHON_DOWNLOADS=never uv sync --locked --python 3.11   # session pods: system Python 3.11
uv run studio --help
uv run studio --version                                    # studio 0.1.0.dev0
```

`python -m haynes_studio` is the same command. Tests: [testing.md](../process/testing.md).

## Commands

| Command | Does |
|---|---|
| `studio legacy validate <manifest> [--json]` | Validates a title manifest as `legacy.manifest/v1` and summarizes it: revision, shots (spoken and silent), lines, sound cues, beds. |
| `studio legacy timeline <manifest> --speech <speech.json> [--compare <timeline.json>] [--json]` | Computes frames per shot, film start frames, and the placement of every line, sound cue and bed in mix samples (rules TIME-1 to TIME-4, TIME-7, TIME-10). With `--compare`, checks a recorded `timeline.json` under rule TIME-12. |
| `studio legacy import <manifest> --speech <speech.json> --operator-iss <iss> --operator-sub <sub> [--map <legacy-import.json>] [--production <prd_id>] [--out <dir>] [--json]` | Maps the manifest to one canonical story (`studio.story/v1` with its boards, lines, cues, notes and layout references, and `derived` from the takes) and an import map (`studio.legacy-import/v1`). IDs come from `--map` when given, so a second import returns the same IDs; otherwise they are minted. The operator is the person running it (an OIDC issuer and subject, never an email). Prints a summary, or `{story, legacy_import}` with `--json`; `--out` writes `story.json` and `legacy-import.json` and refuses to overwrite either. |

Exit status: `0` valid, the timelines match, or the import succeeded; `1` a rule failed,
or the timelines differ; `2` a usage error, an unreadable file, or an `--out` file that
already exists. Each problem prints on stderr as one
line: `<file>: rule <code> at <path>: <message>`, where `<path>` is a JSON Pointer into
that file and `(root)` is the whole document. Results print on stdout; `--json` prints
integers only (ms, frames, samples) plus display text.

```sh
uv run studio legacy validate titles/the-winter-menu/manifest-r4.json
uv run studio legacy timeline titles/the-winter-menu/manifest-r4.json \
  --speech titles/the-winter-menu/evidence-r4/speech.json \
  --compare titles/the-winter-menu/evidence-r4/timeline.json
uv run studio legacy import titles/the-winter-menu/manifest-r4.json \
  --speech titles/the-winter-menu/evidence-r4/speech.json \
  --map docs/contracts/examples/valid/legacy-import-map.json \
  --operator-iss https://authentik.example.invalid/application/o/haynes-studio/ \
  --operator-sub example-subject-tom --out /tmp/winter-menu-import
```

Run `legacy import` from the repository root: the story records the manifest path
relative to the working directory. With the contract's map, r4 reuses its 24 IDs
(production, story, nine boards, 13 lines) and mints the 45 the contract map does not
record (cues, notes, the bed and asset versions); the map it writes records all 69, so
importing again with it mints none. A map made for another draft revision, production
or manifest file fails with `legacy.import_map_mismatch`.

## Schema and version map

| Document | Schema name | Detected by | Normative form | Read by |
|---|---|---|---|---|
| Title manifest (`titles/<slug>/manifest*.json`) | `legacy.manifest/v1` | an object with `shots`, `frame` and `job` and no `schema` field (contract section 2) | [`legacy.manifest.v1.schema.json`](../../src/haynes_studio/schemas/legacy.manifest.v1.schema.json), draft 2020-12, shipped as package data, plus the code rules below | `haynes_studio.legacy.manifest` |
| `speech.json` (evidence) | none; read only beside its manifest | | checks in `haynes_studio.legacy.speech` | `load_speech`, `pair` |
| `timeline.json` (evidence) | none; compared, never written | | checks in `haynes_studio.legacy.timeline` | `load_recorded`, `compare` |

Package `haynes-studio` 0.1.0.dev0 (`studio --version`). One schema version covers all
four Winter Menu revisions; the shape grew between them:

| Revision | File | `revision` field | First appears |
|---|---|---|---|
| r1 | `manifest.json` | absent, read as 1 | the base: `frame`, `set`, `cast`, `layouts`, `shots` with one `line`, `tail` or `duration`, shot `sfx` with `at`, the `sfx` table, `master`, `asr_tolerances`, `provenance` |
| r2 | `manifest-r2.json` | 2 | `revision_note`, `motion`, `beds`, `set.fire`, shot `moves` and `note` |
| r3 | `manifest-r3.json` | 3 | `lines[]`, `after_line` anchors with `offset` on sounds and moves, `camera`, `foreground`, layout slot `crop` |
| r4 | `manifest-r4.json` | 4 | nothing new; r3's shape |

## The model

`haynes_studio.legacy.load(path)` returns a frozen `LegacyManifest`; nothing writes or
rewrites a legacy file. One typed model holds every revision:

- `shot.lines` is always a tuple: one `line` and `lines[]` both become `Line(k, doll,
  text, gap_ms, gap_defaulted)`; `shot.lead_ms` is the first line's `start`, and
  `shot.lines_field` says which field held them.
- Two defaults only, both named by the contract: a later line without `gap` gets 300 ms
  (`gap_defaulted: true`, `edit.resolve_lines`), and no `revision` is revision 1
  (`revision_field_present: false`). Every other absent field is `None`, or an empty
  tuple for a list or table (`moves`, `sfx`, `cast`, `beds`); for example `foreground`,
  `camera.over` and move `dur` stay `None` where the legacy renderer assumed a value.
  An absent `job_dir` is accepted (the PoC required it); it is never imported.
- Times are integer milliseconds, converted exactly from the decimal seconds as written
  (`timebase.ms_from_seconds`); a value that is not a whole millisecond is refused, never
  rounded. A JSON number is read through a float, so text with more than 15 significant
  digits is already rounded when parsed. Sound `gain_db` is `level_rms_dbfs`: a target
  RMS level, not a gain. A JSON integer written as `4.0` loads as `4`.
- Render presets (`layouts`), `set`, `motion`, `master`, tolerances and provenance are
  kept verbatim as read-only JSON.
- `sha256` is the hash of the file's bytes; it equals `manifest_sha256` in the
  contract's [import map](../contracts/examples/valid/legacy-import-map.json).

`haynes_studio.timebase` holds the integer arithmetic (24 fps, 48 000 Hz, 2000 samples per
frame, 48 per ms) as pure functions with no media library. Story
[404](https://work.haynesnetwork.com/work_packages/404) builds the canonical model and
the legacy import on these two modules.

## Rules

| Code | Source | Fires when |
|---|---|---|
| `schema.unsupported` | contract | the document is not a legacy manifest (no `shots`, `frame` and `job`, or it has `schema`) |
| `schema.unknown_field` | contract | a field the schema does not name, one violation per field |
| `legacy.duration_with_lines` | contract | a shot has `duration` and `line` or `lines` |
| `time.first_line_gap` | contract | the first line has `gap` (the legacy editor ignored it) |
| `time.tail_too_short` | contract | `tail` under 0.25 s (the legacy editor's assertion) |
| `time.negative` | contract | a negative `start`, `gap`, `at`, `offset`, `dur` or trim point |
| `time.not_integer_ms` | contract | a time in seconds that is not a whole millisecond, in a manifest or a take's `duration_s` |
| `cue.out_of_range` | contract | a sound's resolved start is outside its shot (TIME-10), found by `timeline` |
| `legacy.invalid` | proposal | any other schema failure: a missing or mistyped field, `fps` other than 24, `line` and `lines` together, a later line with `start`, a spoken shot without `tail` or a silent one with it, a sound or move without exactly one anchor (`at`, or `after_line` with `offset`), a reversed trim, a non-finite number or a time of 10^15 s or more; also a file that is not strict JSON (duplicate keys, NaN, a number too large for a float, nesting too deep), and a malformed `speech.json` or `timeline.json` |
| `legacy.reference` | proposal | what the timeline depends on: a repeated shot `id`, a sound not in the `sfx` table, an `after_line` beyond the shot's lines |
| `legacy.speech_mismatch` | proposal | a line has no take in `speech.json`, a take has no line, or a take's doll or text differs; a take without `k` on a shot with several lines |
| `legacy.timeline_mismatch` | proposal | `--compare` found a value outside its allowance, a missing or repeated record, or an unknown audio `kind`; the path points into `timeline.json` |

Not checked by `validate` or `timeline`: render and voice references (layout preset
names, cast slots, still paths). `legacy import` checks them against the canonical rules
when it maps them ([studio-model.md](studio-model.md)).

## Timeline comparison

| Value | Recorded as | Allowance |
|---|---|---|
| frames per shot and in total | integers | exact |
| shot `start_s`, `end_s`, `total_s` | seconds, 4 decimals | exact at that precision (within 0.05 ms of `frames / 24`) |
| line, sound and bed `start_s`, `end_s` | seconds, 3 decimals | 1 ms (48 samples), rule TIME-12 |

The legacy editor rounded shot starts to 0.1 ms before placing samples and measured line
ends from the resampled audio; the canonical end is the start plus the recorded
`duration_s`. Recorded sounds carry no shot id and are matched in shot order. A sound
that runs past the last cut ends at film end (TIME-10); the legacy editor cut it 100 ms
later, so its recorded end is checked against that legacy cut (`end (legacy cut)`). No
Winter Menu sound reaches the end. Results on the public fixtures:

| Revision | Shots | Frames (computed = recorded) | Lines | Sound cues | Beds | Checks | Mismatches | Largest audio difference |
|---|---|---|---|---|---|---|---|---|
| r1 | 6 | 662 | 5 | 1 | 0 | 43 | 0 | 0.333 ms |
| r2 | 8 | 823 | 7 | 2 | 1 | 60 | 0 | 0.333 ms |
| r3 | 9 | 1094 | 13 | 4 | 1 | 82 | 0 | 0.667 ms |
| r4 | 9 | 1087 | 13 | 4 | 1 | 82 | 0 | 0.667 ms |

Shot frames, r1: 153, 94, 146, 84, 72, 113. r2: 153, 94, 146, 84, 83, 63, 92, 108. r3:
153, 94, 146, 84, 83, 122, 46, 258, 108. r4: the contract's worked example, 153, 94, 146,
84, 83, 122, 46, 251, 108, with shot 8's six lines and its gavel at sample 1 822 000.
