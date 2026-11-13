# Building a story from its boards

`haynes_studio.build` and the `studio voice`, `studio build` and `studio run show`
commands (story [406](https://work.haynesnetwork.com/work_packages/406), epic
[372](https://work.haynesnetwork.com/work_packages/372)): one run of a story, from the
draft to a verified delivery with its phone proxy, each board through the adapter of its
method. Built against [contract v1](../contracts/studio-contracts-v1.md) sections 4, 5,
7 and 8, on what is merged and nothing else: the store and pre-build check
([store-and-stages.md](store-and-stages.md)), the cache, plan and splice
([cache-and-splice.md](cache-and-splice.md)), the layered and whole-frame adapters
([layered-adapter.md](layered-adapter.md), [whole-frame-adapter.md](whole-frame-adapter.md)),
the motion resolver ([motion-clips.md](motion-clips.md)), the film's sound
([studio-mix.md](studio-mix.md)), deliveries ([studio-delivery.md](studio-delivery.md)),
board voices ([studio-voice.md](studio-voice.md)), the library
([studio-library.md](studio-library.md)) and the Kokoro and Whisper clients
([legacy-adapters.md](legacy-adapters.md)).

**State: source and tested with fakes only.** No service, GPU or production media has
been used. The service phase's live clip sources are a hook left unfilled until story
[842](https://work.haynesnetwork.com/work_packages/842)'s Wan clients merge. Story
[428](https://work.haynesnetwork.com/work_packages/428) makes the first live build
([below](#what-story-428-runs)). Every choice beyond the contract is a **proposal**.

## Modules

| Module | What |
|---|---|
| `build.pipeline` | `build_story`: one run from the draft to a verified delivery; `BuildInputs`, `build_toolchain`, `media_format` |
| `build.prebuild` | `prepare` (the pre-build check), `make_snapshot`, `snapshot_bytes` |
| `build.run` | run states and transitions (`new_run`, `advance`), `RunRecords` (the run's record on the store), `local_run_ids` |
| `build.validate` | `validate_run`, `validate_run_snapshot` (registered with the contract harness) |
| `build.sources` | `ClipSources`, the offline sources that refuse, and the hook `live_clip_sources` |
| `build.transcript` | `Transcriber`, `WhisperTranscriber`, `TranscriptChecks` (the master's transcript check, cached) |
| `build.provenance` | engines, licences and public credits from the [licence register](model-licences.md) |
| `build.voice` | `make_story_voices`: every spoken board's voice before a build |
| `build.workers` | segments rendered in up to N processes |
| `build.errors` | `BuildError`, `failure_of` and the codes below |

Schemas: `studio.run.v1.schema.json` and `studio.run-snapshot.v1.schema.json` in
`src/haynes_studio/schemas/`. The contract's `run` and `run-snapshot` examples validate
and are no longer pending.

## Commands

Every command takes the local store's root (`--store`), and the build commands take the
draft (`--story`, a `studio.story/v1` file with its boards embedded), the library
(`--library`, a JSON array of `studio.asset-version/v1` documents) and the operator
(`--operator-iss`, `--operator-sub`, as `studio legacy import`). Exit status: `0` done,
`1` a rule failed or the run failed, `2` a usage error. Problems print on stderr as
`<file>: rule <code> [at board <brd_id>] (stage <stage>): <message>`.

| Command | Does |
|---|---|
| `studio voice --store ROOT --story S --library L --operator-iss ISS --operator-sub SUB --out DIR [--register R] [--json]` | Makes every spoken board's current voice (below) and writes `story.json` and `library.json` into `DIR`; an existing file is never overwritten. Prints each board's action: `current`, `existing`, `made` or `failed` with the job's code. |
| `studio build --store ROOT --story S --library L --operator-iss ISS --operator-sub SUB [--phase service \| --offline] [--workers N] [--toolchain T] [--register R] [--studio-commit SHA] [--json]` | Builds the draft as one new run and prints its summary (or the run document with `--json`). |
| `studio run show RUN_ID --store ROOT --production PRD [--history] [--json]` | Prints a run's newest record, or every recorded version with `--history`. |

- `--register` defaults to `docs/reference/model-licences.json` (run from the checkout).
- `--toolchain` is a JSON object of the profiles a build uses: `s2v_profile`,
  `i2v_profile`, `i2v_clip_frames`, `s2v_prompt`, `s2v_negative_prompt`, `i2v_prompt`,
  `procedural_seed` (proposal). Without it the toolchain's defaults apply (E0's
  576x1024 profiles).
- `--studio-commit` is recorded as `git:<SHA>` in the snapshot and the provenance.
- The command line is the only place a live client is made: the Kokoro client for
  `studio voice` and the Whisper client for `studio build`, each with the real runner;
  the service phase's clip sources come from `haynes_studio.build.live_clip_sources`.
  `main(..., clients=Clients(...))` takes fakes in tests. Importing the package starts
  no process.

### `studio voice`

Voices are pre-build assets (section 10): a build never makes one. For each spoken board
it runs story 405's path as the API's worker will: `request_voice` (plan, then a job only
if something must be made), `start`, `run_voice_job` with the speech client, and points
the board at the result when it is current. Takes and tracks are published to the
production's folder of the store; a take a version of the board already holds is read
back and re-hashed, never asked again. New versions take their licence from the
register. A failed job is reported with its code and the next board is still tried.

## Phases

The service phase and the offline phase are one build with different clip sources.

| Phase | Flag | Clip sources | Makes | The run ends |
|---|---|---|---|---|
| all | none | `live_clip_sources()` | everything, then the delivery | `succeeded`, or `failed` |
| service | `--phase service` | `live_clip_sources()` | drive tracks (the clip requests' input) and clips: speech-to-video and whole-frame; nothing else | `cancelled`, reason `service phase complete` (**proposal**: a run is never `succeeded` without a delivery) |
| offline | `--offline` | `OfflineS2VSource`, `OfflineClipSource`: refuse every call | keyed frames, segments, the film, the sound, the checks, the delivery, from the cache | `succeeded`, or `failed` |

- **The hook is not wired yet.** `live_clip_sources()` raises
  `build.clip_sources_unwired` ("the Wan clip clients (story 842) are not on main; build
  from cached clips with `studio build --offline`"). The command line calls it before it
  makes a run, so `studio build` and `studio build --phase service` stop with that
  message, exit 1 and record nothing. A later story fills the hook with story 842's
  clients; nothing else changes.
- **Offline needs no client.** An offline build of a story whose clips are all cached
  succeeds with no clip client at all. One that lacks a clip stops the run with
  `build.offline_missing`, naming the clip's key, its board and the stage, before any
  service is asked.

## What a build does

`build_story(inputs, store=, phase=, sources=, transcriber=, actor=, earlier_runs=,
workers=)`, in order:

1. **The pre-build check** (`prebuild.prepare`), before any run exists:
   - the facts: `voice_facts(library, story, current_engine=Engine().signing_name)`, so
     a board voice signed with another engine is `voice.stale` (VOICE-9, story 849);
   - the library resolves every referenced asset version (story 382), and story 379's
     `preflight` runs: the story's `queue_run` rules (`voice.absent`, `voice.stale`,
     `photo.absent`, `method.unavailable`, `asset.generating`, ...), every reference
     resolved, every blob present and re-hashed. The cast entry's motion pin
     (`motion_asset_version_id`) is now one of its references (this story);
   - each board's adapter check: `wholeframe.check_board(board, frames=, source_fps=,
     clip_frames=)` for whole-frame boards; `layered.check_board(story, board,
     motion=pin_board(...), frame_size=, s2v_size=)` for layered ones, which carries
     the motion resolver's problems (`motion.clip_absent` and the rest).
   Each problem names its board. A refusal both checks report (`method.unavailable`) is
   listed once.
2. **The snapshot** (`studio.run-snapshot/v1`): the story and its boards by value (no
   `derived` blocks), every asset version the build reads pinned by content hash
   (by `definition_signature` for a voice, by `input_signature` and take hashes for a
   board voice), the motion loops the resolver chose (a loop found by search is an input
   too), and `toolchain_request.studio`. No run ID, no time: the same draft gives the
   same canonical bytes. A story whose references do not resolve cannot be pinned, and
   **no run is made** (the command prints the problems and exits 1).
3. **The run** is recorded `queued` with its snapshot, then `running`. A blocking
   pre-build problem fails it now, with the problem's code and board, before any clip.
4. **The plan** (story 380's `plan_story`) with one content chain:

   | Kind | Made by |
   |---|---|
   | takes, board voice track, pinned doll and set loops, library timed clips | nothing: the plan names them by hash |
   | `s2v_drive_track`, `s2v_clip`, `keyed_frames` | `LayeredStages` (story 426) |
   | `whole_frame_clip` | `WholeFrameClips` (story 427) |
   | `segment` | the `PictureBuilder` of the key's compositor: `LayeredRenderer` or `WholeFrameRenderer` |
   | `film_picture` | `PictureBuilder.film_picture` (stream-copy splice) |
   | `mix`, `master` | `SoundBuilder` (story 841) |
   | `check_result` (`master.transcript`) | `TranscriptChecks`, through the cache |
   | `proxy` | the delivery (step 6) |

   The toolchain is `build_toolchain(base)`: `compositor` maps each method layer to its
   renderer's digest (`{"layered": layered.COMPOSITOR, "whole_frame":
   wholeframe.COMPOSITOR}`; `cache/plan.py` now keys each board's segment with the
   compositor of its own method), `checks` is the transcript check, and
   `sound_toolchain` names the mixer and mux. The chain records each answer: its key,
   its hash, whether this run made it and how long it took.
5. **Checks.** `film_sound(story, plan, sound)` gives the placement record and the
   seven sound checks; the transcript check compares the master's audio (16 kHz mono)
   with the script, word by word, each heard word replaced by the story's
   `checks.asr_tolerances` (the PoC's `poc/edit.py transcript`). Any failed check, the
   renderers' decal checks included, stops the run with `build.check_failed` naming
   them, and **nothing is delivered**.
6. **Delivery.** `deliver(master, ..., expected_frames=plan.frames, media_kind=)` checks
   the master, makes and checks the phone proxy, and publishes the delivery (story 381).
   `deliver` makes the proxy itself, so the plan's `proxy` key is recorded with the
   delivery's proxy and is not a separate cache entry (**proposal**).
7. **Verified success.** `read_delivery` re-hashes the master, the proxy and the
   document; it must hold the plan's master. Only then is the run `succeeded`.

Any error stops the run as `failed` with its code, the board it was on and the stage.
Every stage already completed stays in the store, and the next run reuses it.

### Workers

`--workers N` (default 1) renders boards in up to N processes. The plan runs once to
make every clip and keyed frame and to collect the segments the cache lacks; those are
rendered by N `spawn`ed processes, each opening the same store with its own cache for the
same run and its own renderer (two threads each: the encoder's sliced threads, OpenCV's
two); then the plan runs again and every segment is a hit. The stage commit is
create-only, so two writers of one segment both succeed with the same record; no lock or
delete is added. A worker sends back its renderer's report and checks, or the error's
code, and the parent fails the run naming the board. Workers need the local store.
Tests: two workers give the same decoded frames as one.

## The run

`studio.run/v1` holds the contract's fields and these proposals: `phase`,
`transitions` (every status change with `from`, `to`, `at`, `by`, `reason`), and
`error` (`code`, `message`, `board_id`, `board_number`, `stage`, and the pre-build
problems).

- **States** (section 8): `queued` then `running`, then `succeeded`, `failed` or
  `cancelled`; `held` is a safety stop that resumes only after reconciliation (story
  410). A terminal run never changes (`run.transition`), and a run ID is never reused.
- **On the store** (proposal; the product's is a Postgres row, story 434): each
  version of a run document is a completed stage of the run, `run-0001` (with the
  snapshot blob as its second output), `run-0002` and so on. A stage name is
  create-only, so two writers moving one run from the same version race to one name and
  the loser gets `store.collision` (a compare-and-set). Readers take the highest
  completed version (`RunRecords.latest`). Which runs a production has is read from the
  local adapter's `records/` folder (`local_run_ids`, newest first); every build
  searches those runs for cached artifacts. The run `number` is one more than the
  production's runs (proposal).
- **A finished run is unchanged** by later edits to the draft: its snapshot blob holds
  the story as it was, and its record is never written again.

### The record of a build

| Field | Holds |
|---|---|
| `stages[]` | one per board in film order: `board_id`, `board_number`, `method`, `frames`, `film_start_frame`, `clips[]` (role, slot, hash, key, `made`, and from the clip's own record its frames, fps, requested length, seed, engine, engine job, model files and trim; a library clip's version ID), `segment_sha256`, `segment_key`, `compositor`, `artifacts[]` (every planned artifact of the board: name, kind, key, hash, `made`, `seconds`), `report` (the renderer's report of a segment rendered in this run), `checks[]` (the renderer's decal checks), `render_s` |
| `checks[]` | the seven sound checks, `master.transcript` (with what was heard, the tolerances used and the result), and `frame_count` from the verified delivery |
| `outputs` | frames, fps, picture, mix, master and proxy hashes, their keys, and the placement record with the story's IDs |
| `provenance` | below |
| `delivery_id` | the verified delivery |

A reused segment has no report in this run (the run that rendered it has it).

### Provenance (section 7, D44)

- `toolchain`: the studio commit, the image digest (null until story 428 records one),
  Python, the encoder build (PyAV with its bundled FFmpeg), the compositors, encoder,
  adapters, profiles, assemblers, splicer, mixer, mux, keyer build and the pinned Kokoro
  and Whisper snippets' hashes.
- `engines[]`: one per engine whose work the film holds or checks, from the register:
  a clip the build made, by the register engine whose `files` hold the profile's
  `model` (with the files and hardware the clip's record reports); a library version
  (stills, loops, timed clips, sounds, voices), by its generator's role and recorded
  model name; the transcript check, the register's `asr`. Each engine lists its files
  with hashes and licences, its licence (the register's, `conditional` where the
  register says so, P-23), its profile, its hardware, and what it made (`used_by`). A
  generator the register does not name is an `unregistered-...` engine with an `unknown`
  licence and the reason; nothing is guessed. Licences block nothing (D49).
- `inputs_externally_generated`: every input version with the D42 marker.
- `usage`: `{frontier_tokens: null, basis: "not metered"}`.
- `public`: `ai_generated: true` and one credit per video, voice or sound engine,
  `"<Video|Voices|Sound>: <engine name> on <hardware>"` (proposal); image, check and
  writer engines stay private (`credit.outside_video_sound`).

## Supported method matrix as built

| Layer \ motion | `s2v` | `i2v` |
|---|---|---|
| `layered` | **Built**: drive tracks, speech-to-video clips (or a library timed clip made from the board's own drive track with its seed), keyed frames, idle dolls from pinned loops, the set loop, `LayeredRenderer` | **Built**: idle dolls from pinned loops with talk bounce from the board voice, the set loop, `LayeredRenderer` |
| `whole_frame` | **Refused** before any clip: `method.unavailable` (section 5) | **Built**: the clip chain from the board's current photo, `WholeFrameRenderer` |

## Failure table

No row ends in success, and none delivers anything. Tests are in `tests/build/`.

| Code | Stage | When | Test |
|---|---|---|---|
| `build.clip_sources_unwired` | (no run) | `studio build` or `--phase service` while the hook is unfilled | `tests/cli/test_cli_build.py::test_the_unfilled_hook_stops_the_service_phase_and_a_full_build_with_no_run` |
| `asset.unresolved`, `ref.unknown`, `store.*` | (no run) | a reference the library or the store cannot give; nothing can be pinned | `test_failures.py::test_a_story_whose_assets_do_not_resolve_makes_no_run` |
| `voice.absent` | `prebuild` | a spoken board without a current voice | `test_failures.py::test_a_missing_voice_fails_the_run` |
| `voice.stale` | `prebuild` | a board voice that is not the board's lines, or signed with another engine (VOICE-9) | `test_a_stale_voice_fails_the_run`, `test_a_voice_signed_with_another_engine_is_stale` |
| `method.unavailable` | `prebuild` | whole-frame speech-to-video | `test_a_refused_method_fails_the_run_before_any_clip` |
| `wholeframe.*`, `layered.*` | `prebuild` | an adapter's own check refuses the board (a camera cue on a whole-frame board, a layout that does not place a slot, ...) | `test_an_adapter_refusal_fails_the_run_before_any_clip` |
| `motion.clip_absent` and the resolver's other codes | `prebuild` | a cast still without a loop, an ambiguous or corrupt pin | `test_a_cast_still_without_a_loop_fails_the_run` |
| `photo.absent` | `prebuild` | a whole-frame board without a current photo | the pre-build check's own tests (story 379, 427) |
| `build.voice_track_missing` | `voice` | a current board voice that records no assembled track (a legacy import's), which the picture's envelope and the mix read | `test_failures.py::test_a_board_voice_without_a_track_fails_the_run` |
| `layered.clip_invalid`, `wholeframe.clip_invalid`, `time.source_short` | `s2v_clip`, `whole_frame_clip`, `segment` | a clip source's answer that is not what was asked, or a clip too short | `test_a_failed_clip_fails_the_run_on_its_board` |
| `build.offline_missing` | `s2v_clip`, `whole_frame_clip` | the offline phase needs a clip no run made | `test_phases.py::test_the_offline_phase_refuses_a_service_call_naming_the_missing_artifact` |
| `layered.decal_weak`, render and splice codes (`render.*`, `splice.incompatible`, `time.conservation`) | `segment`, `film_picture` | a renderer, encoder or splice refusal | the adapters' and cache's own tests |
| `build.check_failed` | `checks` | a sound check, the transcript check or a decal check did not pass | `test_a_failed_check_fails_the_run_and_delivers_nothing` |
| `delivery.*` | `delivery` | the master or the proxy fails a delivery check | `test_a_failed_delivery_fails_the_run` |
| `build.delivery_unverified` | `delivery` | the delivery does not read back with the plan's master | `test_a_delivery_that_does_not_read_back_fails_the_run` |
| `build.internal` | where it was | an exception that carries no code | (a bug: the message names its type) |

| Code | Status | Source |
|---|---|---|
| `build.clip_sources_unwired` | failed | proposal |
| `build.offline_missing` | failed | proposal |
| `build.check_failed` | failed | proposal |
| `build.delivery_unverified` | failed | proposal |
| `build.voice_track_missing` | failed | proposal |
| `run.transition`, `run.unknown` | conflict, invalid | proposals |
| `build.internal` | failed | proposal |

## What story 428 runs

The first live build: The Winter Menu r4 with live voices, clips and transcript. These
steps use only what this story built; the two places that need story 428's own
decision are marked **(428 decides)**.

1. **Checkout and tools.** In a session pod, at `main`:
   `UV_PYTHON_DOWNLOADS=never uv sync --locked --python 3.11`.
2. **The draft.** Import r4 as a story (`studio legacy import` with the contract's map,
   [studio-cli.md](studio-cli.md)), then make it buildable: write the seeds the server
   would (`s2v:<slot>` for every speaker of a layered speech-to-video board), and, if any
   board is to be whole-frame, its current photo version. Keep the file as the draft.
3. **The library and the store.** Build the Winter Menu library from public files
   (`build_winter_menu_library`, [studio-library.md](studio-library.md)) and import the
   E0 motion records (`build_e0_motion`, [motion-clips.md](motion-clips.md)); publish the
   private bytes through the store and import them under the same source keys (the
   library's "private import"). Write `Library.documents()` as the library file.
   **(428 decides)** where the store root is: the CLI needs one root that both the
   service clients (reached by `kubectl exec` from a session pod) and the CPU work
   (`ai/studio-render`, `/studio`) can reach; see held question Q-406-2 in the PR.
4. **Voices.**
   `uv run studio voice --store ROOT --story draft.json --library library.json
   --operator-iss <iss> --operator-sub <sub> --out voiced/`. Expect `made` for every
   spoken board (or `current` where the legacy takes are current). Kokoro is called once
   per new take signature.
5. **The pre-build check, offline.** `uv run studio build --store ROOT --story
   voiced/story.json --library voiced/library.json --operator-iss ... --operator-sub ...
   --toolchain toolchain.json --studio-commit $(git rev-parse HEAD) --offline`. With no
   clip cached it stops at the first missing clip with `build.offline_missing`, after the
   whole pre-build check has passed: any `voice.*`, `photo.absent`, `method.*`,
   `motion.*` or adapter problem shows here first, before any service is asked.
6. **The service phase** (after the hook is filled with story 842's clients):
   `uv run studio build ... --phase service`. The run ends `cancelled` with
   "service phase complete"; every clip is now cached. Watch the Wan compute lease;
   never bypass it.
7. **The offline phase.** `nice -n 10 uv run studio build ... --offline --workers N`
   (N up to 22 on `ai/studio-render`, 1 in a session pod). Expect `succeeded` with a
   delivery; `studio run show <run_id> --store ROOT --production <prd> --json` prints the
   record. **(428 decides)** where the transcript check runs: the Whisper client is
   reached by `kubectl exec`, which the render worker may not have.
8. **A second build** of the same draft with `--offline`: every artifact is a hit and the
   source and recognizer are asked nothing; only the new run's delivery is made.
9. **Record** the run's timings (each artifact's `seconds`, `render_s`), sizes and IO,
   and compare with the E0 delivery. Tom watches the delivery for the demo; a source PR
   and a delivered run are not his acceptance.

Known blockers with r4 as imported, both observations in the PR: O-406-1, the phone
proxy of a film whose frame count is not a multiple of 3 fails `delivery.proxy_invalid`
(r4 is 1087 frames); O-406-2, a legacy board voice records no track, so a build of the
imported r4 stops at `build.voice_track_missing` until each spoken board is voiced again,
and `studio voice` reports those boards `current` (story 405's planner).

## Proposals beyond the contract

- The run fields `phase`, `transitions` and `error`; the board stage fields beyond the
  contract's example (`artifacts`, `report`, `checks`, `segment_key`, `compositor`,
  `render_s`, `board_number`); `outputs.keys`, `outputs.placement`,
  `outputs.proxy_sha256`; the check entry fields beyond `check` and `result`.
- A writer engine may have a null licence (the contract's example records one; every
  other engine and file has a licence object).
- A service-phase run ends `cancelled` at the phase boundary.
- The run record on the local store as versioned stages, the run list from `records/`,
  and the run number.
- The pre-build check runs before the run is queued, and a story whose references do
  not resolve makes no run; any other refusal (`queue_run`'s included) fails a recorded
  run, so the refusal is on record (the acceptance's "a missing voice ends the run as
  failed").
- The proxy key is answered by the delivery's proxy.
- The transcript check's version `1`, its 16 kHz mono input and the PoC's word-level
  comparison; its result document.
- The engine matching rules, the unregistered engine, the credit text.
- The codes above; `--toolchain`, `--studio-commit`, the library file as a JSON array.
