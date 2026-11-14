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
been used. The service phase's live clip sources (story
[851](https://work.haynesnetwork.com/work_packages/851)) are story
[842](https://work.haynesnetwork.com/work_packages/842)'s Wan clip client, tested with its
fake pod only ([below](#live-clip-sources-story-851)). Story
[428](https://work.haynesnetwork.com/work_packages/428) makes the first live build
([below](#what-story-428-runs)). Every choice beyond the contract is a **proposal**.

## Modules

| Module | What |
|---|---|
| `build.pipeline` | `build_story`: one run from the draft to a verified delivery; `BuildInputs`, `build_toolchain`, `media_format` |
| `build.prebuild` | `prepare` (the pre-build check), `make_snapshot`, `snapshot_bytes` |
| `build.run` | run states and transitions (`new_run`, `advance`), `RunRecords` (the run's record on the store), `local_run_ids` |
| `build.validate` | `validate_run`, `validate_run_snapshot` (registered with the contract harness) |
| `build.sources` | `ClipSources`, the offline sources that refuse, the local pass's recording sources, and the hook `live_clip_sources` |
| `build.live` | the live clip sources on the Wan client (`WanClips`, `WanS2VSource`, `WanChainSource`), the store's one journal (`journal_path`), the dry run's clip list (`planned_clips`) and its E0 estimate (`estimate`, `dry_run_report`) |
| `build.transcript` | `Transcriber`, `WhisperTranscriber`, `TranscriptChecks` (the master's transcript check, cached) |
| `build.provenance` | engines, licences and public credits from the [licence register](model-licences.md) |
| `build.voice` | `make_story_voices`: every spoken board's voice before a build |
| `build.workers` | segments rendered in up to N processes |
| `build.errors` | `BuildError`, `RunHeld`, `RunUnrecorded`, `failure_of` and the codes below |

Schemas: `studio.run.v1.schema.json` and `studio.run-snapshot.v1.schema.json` in
`src/haynes_studio/schemas/`. The contract's `run` and `run-snapshot` examples validate
and are no longer pending.

## Commands

Every command takes the local store's root (`--store`), and the build commands take the
draft (`--story`, a `studio.story/v1` file with its boards embedded), the library
(`--library`, a JSON array of `studio.asset-version/v1` documents) and the operator
(`--operator-iss`, `--operator-sub`, as `studio legacy import`). Exit status: `0` done,
`1` a rule failed or the run failed, `2` a usage error. Problems print on stderr, one per
line: a failed or held run as `<story file>: rule <code> [at board <brd_id>] (stage
<stage>): <message>` (a held run's message starts `held`); a pre-build problem of a story
that makes no run as `<story file>: rule <code> at <board or story> field <pointer>:
<message>`; a failure the run's record could not take as `<story file>: rule
build.run_unrecorded: <message>` (below).

| Command | Does |
|---|---|
| `studio voice --store ROOT --story S --library L --operator-iss ISS --operator-sub SUB --out DIR [--register R] [--json]` | Makes every spoken board's current voice (below) and writes `story.json` and `library.json` into `DIR`; an existing file is never overwritten. Prints each board's action: `current`, `existing`, `made` or `failed` with the job's code. |
| `studio build --store ROOT --story S --library L --operator-iss ISS --operator-sub SUB [--phase service [--dry-run] \| --offline] [--wan-story URL] [--workers N] [--toolchain T] [--register R] [--studio-commit SHA] [--json]` | Builds the draft as one new run and prints its summary (or the run document with `--json`). Exit 1 for a `failed` or `held` run. |
| `studio run show RUN_ID --store ROOT --production PRD [--history] [--json]` | Prints a run's newest record, or every recorded version with `--history`. |

- `--register` defaults to `docs/reference/model-licences.json` (run from the checkout).
- `--toolchain` is a JSON object of the profiles a build uses: `s2v_profile`,
  `i2v_profile`, `i2v_clip_frames`, `s2v_prompt`, `s2v_negative_prompt`, `i2v_prompt`,
  `procedural_seed` (proposal). Without it the toolchain's defaults apply (E0's
  576x1024 profiles).
- `--studio-commit` is recorded as `git:<SHA>` in the snapshot and the provenance.
- `--wan-story` (story 851): the full `https://work.haynesnetwork.com/work_packages/<id>`
  URL the Wan ledger records each clip job under. Every phase but `--offline` needs it
  (a usage error, exit 2, and no run otherwise).
- `--dry-run` (story 851, only with `--phase service`): the pre-build check, the local
  pass, the check of every clip request and the mix, then the run ends `cancelled` and
  the command lists the clip jobs the phase would request, in order, with their E0 GPU
  time (`--json`: `{"run": ..., "dry_run": {"clips": [...], "total": {...}}}`). No client
  is made, no journal is read, no service is asked.
- The command line is the only place a live client is made: the Kokoro client for
  `studio voice`, the Whisper client for `studio build`, and the runner of the Wan clip
  client (`Clients.wan_runner`, the real `kubectl exec` runner), which
  `haynes_studio.build.live_clip_sources(store_root, story=, runner=)` is given for the
  service phase and a full build. `main(..., clients=Clients(...))` takes fakes in tests
  (`Clients` without a `wan_runner` refuses to make one). Importing the package starts
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

| Phase | Flag | Services | Makes | The run ends |
|---|---|---|---|---|
| all | none | `live_clip_sources(...)` and the Whisper client | everything, then the delivery | `succeeded`, `failed`, or `held` (a refusal of the Wan client) |
| service | `--phase service` | `live_clip_sources(...)` and the Whisper client | what needs a service: drive tracks (the clip requests' input) and clips, speech-to-video and whole-frame; and the transcript check of a master the cache already holds. Also the mix and its own checks, before any clip is asked for (**proposal**, the confirming review's finding a: the mix needs no clip, so it is the cheapest proof that the story's sound can be built before GPU time is spent). Everything else is looked up in the cache, never made. The run lists the mix checks and any transcript check | `cancelled`, reason `service phase complete` (**proposal**: a run is never `succeeded` without a delivery); `failed` with `build.check_failed` (stage `checks`, exit 1) when a transcript check it made or read from the cache did not pass; `held` (exit 1) on any refusal of the Wan client |
| offline | `--offline` | none: `OfflineS2VSource` and `OfflineClipSource` refuse every call, and no recognizer is used | keyed frames, segments, the film, the sound, the sound checks and the delivery, from the cache | `succeeded`, or `failed` |

- **The live clip sources** (story 851) are story 842's Wan clip client on the store's
  one journal, `<store root>/wan-journal.jsonl`; any refusal of the client ends the run
  `held` and nothing further is submitted ([below](#live-clip-sources-story-851)).
- **Offline needs no client.** An offline build of a story whose clips and transcript
  check are cached succeeds with no client at all. One that lacks a clip stops the run
  with `build.offline_missing`, naming the clip's key, its board and the stage, before
  any service is asked. The transcript check is a service call (Whisper), so the offline
  phase reads it from the cache only: a new master stops the run at stage
  `check_result` with `build.offline_missing`, after the picture, mix and master are
  made and cached. The next `--phase service` run checks that cached master, and the
  next offline run delivers. A full build (no flag) does all of it in one run.

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
   too), and `toolchain_request.studio`. A library timed clip is chosen during the plan
   (it is found by the drive track the plan computes), so it is recorded in the board's
   `clips[]` with its version ID, not in the snapshot (observation O-406-4). No run ID, no time: the same draft gives the
   same canonical bytes. A story whose references do not resolve cannot be pinned, and
   **no run is made** (the command prints the problems and exits 1).
3. **The run** is recorded `queued` with its snapshot, then `running`. A blocking
   pre-build problem fails it now, with the problem's code and board, before any clip.
4. **The local pass** (`pipeline._local_pass`, **proposal**): before any clip is asked
   of the phase's sources, the whole story is planned once with clip sources that only
   record the request they would send (`sources.RecordingS2VSource`,
   `RecordingClipSource`). Every drive track is made (a local stage); every speaker's
   library timed clip is resolved, so a damaged, ambiguous or unplayable one stops here;
   every seed the plan needs is checked (`s2v:<slot>`, `i2v:frame`); each clip is a
   checked cache hit, or a request whose inputs (drive track, start image, photo) the
   adapter read and re-hashed; every other artifact is looked up in the cache, and
   nothing else is made. Any error fails the run here with its own code, board and
   stage (`plan` for a refusal the plan makes itself, such as a missing seed;
   `s2v_clip` for a library timed clip), its message ending "(found before any clip was
   requested)", and no clip source has been asked. Only a clean pass goes on. The
   drive tracks it made are recorded as made by this run.

   **Then the mix** (`pipeline._early_mix`), in the full build and the service phase
   (the phases that may ask a clip source; the offline phase never asks one and makes
   the mix where the plan reaches it): the mix key names the voice tracks, the sound
   cues, the beds and the story's levels and never a clip, so the local pass's plan
   holds the real key. The sound builder makes the mix (a cached artifact: a later
   phase finds it) and runs the four checks on the mix (`mix.length`, `mix.loudness`,
   `mix.true_peak`, `mix.clipping`; the master's wait for the master). A refusal
   (`mix.input_invalid`, such as a `true_peak_dbtp` the limiter cannot reach;
   `cue.out_of_range`; a sound blob that is missing or not its hash; a trim past the
   sound's end) fails the run at stage `mix`, and a failed mix check fails it with
   `build.check_failed` at stage `checks`, each with the same "(found before any clip
   was requested)" ending and no clip source asked.
5. **The plan** (story 380's `plan_story`) with one content chain:

   | Kind | Made by |
   |---|---|
   | takes, board voice track, pinned doll and set loops, library timed clips | nothing: the plan names them by hash |
   | `s2v_drive_track`, `s2v_clip`, `keyed_frames` | `LayeredStages` (story 426) |
   | `whole_frame_clip` | `WholeFrameClips` (story 427) |
   | `segment` | the `PictureBuilder` of the key's compositor: `LayeredRenderer` or `WholeFrameRenderer` |
   | `film_picture` | `PictureBuilder.film_picture` (stream-copy splice) |
   | `mix`, `master` | `SoundBuilder` (story 841) |
   | `check_result` (`master.transcript`) | `TranscriptChecks`, through the cache |
   | `proxy` | the delivery (step 7) |

   The toolchain is `build_toolchain(base)`: `compositor` maps each method layer to its
   renderer's digest (`{"layered": layered.COMPOSITOR, "whole_frame":
   wholeframe.COMPOSITOR}`; `cache/plan.py` now keys each board's segment with the
   compositor of its own method), `checks` is the transcript check, and
   `sound_toolchain` names the mixer and mux. The chain records each answer: its key,
   its hash, whether this run made it and how long it took.
6. **Checks.** `film_sound(story, plan, sound)` gives the placement record and the
   seven sound checks (the four on the mix found in the cache, made after the local
   pass); the transcript check compares the master's audio (16 kHz mono)
   with the script, word by word, each heard word replaced by the story's
   `checks.asr_tolerances` (the PoC's `poc/edit.py transcript`). Any failed check stops
   the run with `build.check_failed` naming them, and **nothing is delivered**. A decal
   track below its floor never gets this far: the layered renderer refuses the segment
   (`layered.decal_weak`, stage `segment`) and keeps the check result.
7. **Delivery.** `deliver(master, ..., expected_frames=plan.frames, media_kind=)` checks
   the master, makes and checks the phone proxy, and publishes the delivery (story 381).
   `deliver` makes the proxy itself, so the plan's `proxy` key is recorded with the
   delivery's proxy and is not a separate cache entry (**proposal**).
8. **Verified success.** `read_delivery` re-hashes the master, the proxy and the
   document; it must hold the plan's master and decode to the plan's frames. Only then
   is the run `succeeded`. The success record is validated before `deliver` is called,
   so a record that could not be written never leaves a delivery behind a failed run;
   if a run still fails after its delivery was published, its failure names that
   delivery (`delivery_id` and the message). Once `deliver` has returned, its stage
   exists, so the delivery it returned is named whatever the read-back then says (a
   read that fails, or raises on a blob that does not re-hash). A delivery stage that
   `deliver` left while raising is named from the stage's own document, read without
   the re-hash that failed.

Any error stops the run as `failed` with its code, the board it was on and the stage.
Every stage already completed stays in the store, and the next run reuses it.

**A failure that cannot be recorded** (**proposal**). If writing the failed run raises
(a store error, or `run.transition` because another writer moved the run), the build
raises `build.run_unrecorded` (`errors.RunUnrecorded`) instead of returning: its
message names the run, says its stored state may still read `running`, names the
delivery the run published (or that it published none), and gives the failure and the
write's error. `studio build` prints it as a rule line and exits 1; nothing reports
the run as done. `studio run show RUN_ID` shows what the store holds.

### Workers

`--workers N` (default 1) renders boards in up to N processes. After the local pass, the
plan runs once to make every clip and keyed frame and to collect the segments the cache
lacks; those are rendered by N `spawn`ed processes, each opening the same store with its
own cache for the same run and its own renderer (two threads each: the encoder's sliced
threads, OpenCV's two); then the plan runs again and every segment is a hit. The stage
commit is create-only, so two writers of one segment both succeed with the same record;
no lock or delete is added. A worker sends back its renderer's report and checks, or the
error's code, and the parent fails the run naming the board. Workers need the local
store. Tests: two workers give the same decoded frames as one.

## Live clip sources (story 851)

`live_clip_sources(store_root, *, story, runner=None, dry_run=False)` (the hook, in
`build.sources`; the code is `build.live`) fills the service phase's `ClipSources` with
story 842's `WanClipClient` ([legacy-adapters.md](legacy-adapters.md#wan-clip-clients-story-842)).
Glue only: every guard is the client's. Nothing here retries, waits, loops, catches a
refusal to go on, or calls `clear_in_flight()` or `clear_halt()` (those are a person's).
Making the sources contacts nothing and reads nothing; the one client is made on the
first clip request, so a phase whose clips are all cached never reads the journal.

- **One journal per store.** `journal_path(root)` is `<store root>/wan-journal.jsonl`
  (P-842-08), the only path ever given to the client, for every run of the store; it
  cannot be passed in (`client_options={"journal": ...}` is a `TypeError`). Keep the
  store on a local file system (`flock`). Nothing here deletes, moves, empties or
  replaces it or its `.lock` file.
- **One request, one call, in plan order.** The adapters ask for clips in plan order,
  each missing clip once (a hit is never asked). A speech-to-video request becomes one
  `SpeechToVideo` and one `render`; a whole-frame chain one `ImageToVideo` and one
  `render` per clip not already kept (below), in order, clip *k* starting on clip
  *k - 1*'s last frame (`wholeframe.source.last_frame_png`). The two sources share the
  one client.
- **A chain clip collected is kept at once** (`build.live.KeptClips`, proposal). The
  adapter commits a chain whole (story 427), so the chain source keeps each clip itself
  as soon as `render` or `recover` hands it back: a cached artifact of kind
  `wan_chain_clip` (the MP4; outputs `wan_chain_clip` and `inputs`, as every cache
  entry), after its provenance stage `wan_chain_clip_record-<key hex>` (one `record`,
  `studio.wan-chain-clip/v1`: the key, the source, the clip's hash and size, the whole
  Wan record). Committed create-only under the run on the run's own cache
  (`ClipSources.bind`, given before any clip), never deleted, found from any later run.
  The key (`kept_key`) is only what the clip request is: the start image's hash (the
  photo for clip 0, else clip *k - 1*'s last frame), the prompt, the client's negative
  prompt, the seed, the size, the length, the key's profile and the source name
  `studio.build.wan-i2v/1`; not the chain, the clip's place in it or `--wan-story`.
  Before asking the client for any chain clip the source looks that key up; a kept clip
  is re-hashed and used with its Wan record, with no `render` and no `recover`. A
  damaged one fails the run with the store's code (`store.hash_mismatch`, ...) or
  `cache.entry_invalid`, and nothing is rendered in its place. So a chain stopped at
  clip *k* (a refusal that settles the journal, a crash) gives the next phase clips 0
  to *k - 1* from the store, and only clip *k* and later are asked for.
- **Checked before any clip.** After the local pass, before the mix, every recorded
  request is turned into its Wan request(s), sending nothing (`ClipSources.check`). A
  request the client would refuse (`adapter.request_invalid`: a side not a multiple of
  32, more than 3 chunks, an empty prompt or negative prompt, ...) or a key whose
  profile the client does not make (`build.live_unsupported`) fails the run at that
  board with "(found before any clip was requested)".
- **A job the journal holds is settled first.** After a lost answer, fetch or clip
  check, the client keeps the job `in_flight` or `uncollected`. Before any `render`, if
  the client holds such a job and the graph it rebuilds for the current request under
  that job ID hashes to the journal's `graph_sha256` (the same request), the clip is
  collected with `recover(request, job_id)`, read-only, never rendered again; `recover`
  itself refuses unless the ledger reads `succeeded` and matches. Any other request
  stops the phase `held` with `build.wan_unsettled`, asking the client nothing.
- **Any refusal ends the phase `held`.** Every exception `render`, `recover` or the
  client's construction raises becomes `errors.RunHeld`: the run is recorded `held`
  (table below) and the sources refuse every later call with the same stop, without
  asking the client. A `held` run is a safety stop (section 8): it resumes only after a
  person reconciles it, never by resubmitting.
- **Foreign work during this request's own job** (`adapter.competing_work` with the
  clip): the clip passed every check and the client kept it (guard 27). A speech clip, or
  a chain's last clip, is handed to the adapter and cached, and the build stops `held`
  right after (`ClipSources.stopped`); the next run finds it cached and is stopped by
  the journal's halt before any submission (a chain's last clip is also kept, above). A
  chain clip before the last is not handed back (the adapter takes a chain whole), so
  it is not kept either: the stop is raised at once, and the record names it
  (`clip_kept.handed_to_adapter: false`; see the known limits).
- **One build per process.** The client keeps the job that blocks and the halt per
  process, for every client (story 842), and the build reads that state to choose
  between `recover` and a stop; the command line runs one build per process. A long-lived
  process that builds two stores would share it (tests reset it between builds).
- **The journal is not stray.** `LocalStore.doctor()` lists `wan-journal.jsonl` and its
  `.lock` among a store's unexpected paths (the store does not know them): never remove
  them to tidy a store.

### Request mapping

| Adapter request | Wan request field | From |
|---|---|---|
| `S2VRequest` (story 426) | `SpeechToVideo.image_png`, `drive_wav`, `board_frames`, `prompt`, `negative`, `seed`, `width`/`height` | `start_image`, `drive_track`, `board_frames`, `prompt`, `negative_prompt`, `seed`, `profile.size`; `story` is `--wan-story`. The client's `length` must equal the request's `frames` (both TIME-9). |
| `ClipRequest` (story 427), clip *k* | `ImageToVideo.image_png`, `prompt`, `seed`, `length`, `width`/`height` | the photo (*k* = 0) or clip *k - 1*'s last frame; `prompt`; `clips[k].seed`; `clips[k].frames`; `profile.size`. The chain names no negative prompt: the client's own (E0's) is used and recorded. |
| profile | | speech-to-video: `model` `wan2.2-s2v-14b-fp8`, `lora` `lightx2v-4step`, `steps` 4, `cfg` 1, `chunk` 77, `source_fps` 16, plus `size` and `delivery`; image-to-video: `model` `wan2.2-ti2v-5b`, `source_fps` 24, plus `size`, `adapter`, `delivery`. Any other value or key is `build.live_unsupported`. |

### Clip record mapping

| Adapter provenance (`S2VClip`, `SourceClip`) | From `WanClip` |
|---|---|
| `data` | `data` (the MP4 the client fetched and checked) |
| `seed`, `frames_requested` | `record.seed`, `record.frames_requested` (the adapter checks both against its request) |
| `start_image_sha256` | `record.inputs.image.sha256` |
| `drive_track_sha256` (speech-to-video) | `record.inputs.audio.sha256` |
| `engine`, `engine_job_id`, `files_sha256` | `record.engine`, `record.job_id`, `record.model_files_sha256` |
| `index` (whole-frame) | the chain's `clips[k].index` |
| `extra` | `{"wan": record}`: the whole record, every field (graph and template hashes, preset, story, prompt, negative, size, fps, frames requested and delivered, timings, temperatures, telemetry tail, `recovered`); a chain clip also has `kept`: `{key, run_id}`, the key it is kept under and the run whose stage holds it |

The adapter then measures the clip itself (hash, frames, size) and records the source
name (`studio.build.wan-s2v/1`, `studio.build.wan-i2v/1`). The run's board stage takes
its clip entry from that record (engine, job ID, model files, seed, lengths).

### Held states

Each row ends the run `held` at the request's board and stage (`s2v_clip` or
`whole_frame_clip`), exit 1. `error.problems[0]` is `{rule, status: "held", job_id,
check, journal, in_flight, halt, collected_before_stop[, clip_kept]}`: the code, the Wan
job (null when no job reached the run step; the journal still names it, settled
`no_submission`), what a person must check, the journal's path, the job the client still
holds and its state, the halt, and the clips of a chain in hand before the stop (each
`{index, job_id, sha256, kept, reused}`: the key it is kept under, and whether this run
found it kept). Tests are in `tests/build_story/test_live_sources.py`.

| Client refusal or state | Code | What the build does | Test |
|---|---|---|---|
| API holding (`accepting_jobs` false) | `adapter.busy` | held; nothing ran | `test_every_refusal_..._further[api_holding]` |
| API busy (an `active_job`) | `adapter.busy` | held; nothing ran | `[api_busy]` |
| unknown engine work queued | `adapter.busy` | held; nothing ran | `[unknown_work_queued]` |
| GPUs not cool after the client's own 1800 s wait | `adapter.busy` | held; nothing ran | `[gpus_never_cool]` |
| the admission readback holds | `adapter.busy` | held; the run step submitted nothing | `[admission_readback_holds]` |
| the compute lease is busy | `adapter.busy` | held; the job failed without a prompt | `[compute_lease_busy]` |
| GPUs busy at `generate()` | `adapter.job_failed` | held | `[gpus_busy_at_generate]` |
| the job failed | `adapter.job_failed` | held | `[job_failed]` |
| the answer lost (timeout) | `adapter.timeout` | held; the job stays in flight | `[answer_lost]` |
| the clip cut in transfer (or failing its checks) | `adapter.response_invalid` | held; the job stays uncollected | `[clip_cut_in_transfer]` |
| the pod cannot be reached | `adapter.command_failed` | held | `test_a_runner_that_cannot_reach_the_pod_stops_the_phase_held` |
| a journal it cannot read | `adapter.journal_failed` | held at the client's construction; no command; the file is not touched | `test_an_unreadable_journal_stops_the_phase_held_before_any_command` |
| the journal held by another holder | `adapter.busy` | held; no command | `test_a_journal_another_holder_has_stops_the_phase_held_before_any_command` |
| foreign work during the job | `adapter.competing_work` | the checked clip is cached (a speech clip or a chain's last), then held; the next run is held by the halt with nothing submitted; on a chain's earlier clip, held at once, the clip named and not kept | `test_competing_work_keeps_the_checked_clip_then_holds_and_the_halt_holds_the_next_run`, `test_foreign_work_on_a_chains_earlier_clip_holds_and_submits_nothing_more` |
| a refusal at a chain's later clip (one that settles the journal: the API holding, a busy lease, `no_submission`) | its code | held; the clips before it are kept and named (`collected_before_stop`); the next phase, a new run with no reconciliation, uses them with no client call and asks only for the refused clip and later: one Wan job per clip in all | `test_a_refusal_inside_a_chain_holds_naming_the_clips_collected_before_it`, `test_a_chain_refused_at_clip_1_keeps_clip_0_and_the_next_phase_submits_only_clip_1`, `test_a_chain_of_three_stopped_at_clip_2_reuses_clips_0_and_1` |
| the process dies after a chain clip was collected, before the next is journalled | (no record: the run stays `running`) | the next process (a new client and sources on the same store and journal) uses the kept clips and asks only for the rest | `test_a_crash_after_a_chains_first_clip_keeps_it_for_the_next_process` |
| a kept chain clip that is not its bytes (or its record, or another key's) | `store.hash_mismatch` (the store's code), `cache.entry_invalid` | **failed** at the chain's board, stage `whole_frame_clip`; the client is not asked for that clip or any later one, and nothing is rendered in its place | `test_a_kept_clip_that_is_not_its_bytes_is_refused_and_nothing_is_rendered_in_its_place` |
| an earlier job in flight whose ledger reads succeeded, same request | (none) | `recover`, then the next clip | `test_a_lost_answer_is_recovered_by_the_next_phase_never_rendered_again` |
| an earlier job uncollected, same request | (none) | `recover`, then the next clip | `test_a_lost_fetch_is_recovered_by_the_next_phase_never_rendered_again` |
| a lost answer on a chain's later clip | (none) | the next phase uses the kept clips before it, then `recover`s that clip | `test_a_lost_answer_on_a_chains_later_clip_is_recovered_on_the_kept_clips_before_it` |
| an earlier job still running / with no ledger / failed | `adapter.busy` / `adapter.not_found` / `adapter.job_failed` | `recover` refuses: held, no render | `test_a_lost_job_that_has_not_succeeded_stops_the_next_phase_held_without_a_render` |
| an earlier job made for another request | `build.wan_unsettled` | held; neither `recover` nor `render` | `test_a_journal_job_made_for_another_request_stops_the_phase_held` |
| any other exception of the client | its code, else `build.internal` | held | (the same path) |

Each parametrized refusal test also checks that the client was called once, that the
next clip was never asked for, and that a later request to the stopped sources raises
the same stop without a call. A chain of two clips is rendered in order, clip 1 on clip
0's last frame (`test_a_chain_renders_each_clip_once_in_order_each_on_the_last_frame_before`).
A one-clip chain and a speech clip stay one job each; the chain's clip is kept and the
board stage lists it, made, then reused by the next run
(`test_a_single_clip_chain_and_a_speech_clip_are_one_job_each_and_the_chain_clip_is_kept`).

A held run stays held for the same request until its cause is gone: a job the journal
still holds is asked of `recover` again by every later run, and `recover` refuses until
its ledger reads `succeeded`. A failed job whose prompt the engine accepted is therefore
settled only by a person (`clear_in_flight()` once its ledger reads failed and the queue
holds nothing of it); the client's own settle on an empty queue (story 842's row 7)
happens inside `render`, which the build does not call while a job is held.

### The dry run

`studio build ... --phase service --dry-run --wan-story URL` lists, in the order the
phase would request them, the clip jobs the plan lacks: kind, board, slot (speech) or
chain index (whole-frame), requested length, size, chunks and seed, each with its GPU
time from the E0 records (`titles/the-winter-menu/video-e0/clip-records*.jsonl` of the
checkout the code runs from; none found reads "no E0 records were read"): the range of `render_s` and the longest `wall_s` (with its cool-down
wait) of the E0 jobs of the same kind and size, speech-to-video by chunk count,
image-to-video of at least its length (E0 ran 121 frames only), marked an upper or lower
bound when E0's lengths were longer or shorter (proposal). The one 20-step speech job is
another profile and is left out. A shape E0 never ran has no estimate, and the total is
then unknown. The fixture's output (its clips are 288x512, a size E0 never ran):

```text
dry run: 2 clip job(s) would be requested, in this order (nothing was asked of a service):
  s2v board 1 brd_01JB4060000000000000000001 slot a: 13 frames at 288x512, 1 chunk(s), seed 11; no E0 estimate
  i2v board 3 brd_01JB4060000000000000000003 clip 0: 121 frames at 288x512, seed 31; no E0 estimate
  total: 2 Wan job(s); unknown: a job has no E0 job of its shape
```

The same two clips at E0's 576x1024 read `GPU 142.5-203.1 s, at most 328.9 s with
cool-down (4 E0 jobs)` and `GPU 116.5-152.1 s, at most 294.1 s with cool-down (24 E0
jobs)`, `total: 2 Wan job(s), GPU 259-355.2 s, at most 623 s with cool-down`.

### Known limits

- **A stopped chain no longer loses its earlier clips.** The chain itself is still
  committed whole (story 427), but clips 0 to *k - 1* collected before a stop or crash
  at clip *k* are kept as they arrive and reused by the next phase, which asks only for
  clip *k* and later; a lost answer on clip *k* is `recover`ed there on the kept clips'
  last frame. What remains: (a) foreign work on a chain's earlier clip: the client hands
  that clip back only on its stop, so it is named (`clip_kept`) and not kept, and once a
  person has cleared the halt the next phase renders it again; (b) a store that refuses
  a kept clip's commit fails the run, and the next phase asks for that clip again; (c)
  the dry run lists every clip of a chain the cache lacks, kept ones included (an upper
  bound: the phase asks fewer). With the default 121-frame clips a chain is one clip for
  a board of up to 5 s.
- **No negative prompt is invented.** The toolchain's default `s2v_negative_prompt` is
  empty, which the Wan graph refuses (`adapter.request_invalid`, before any clip): story
  428 sets it in `--toolchain` (E0's is the client's `NEGATIVE`).

## The run

`studio.run/v1` holds the contract's fields and these proposals: `phase`,
`transitions` (every status change with `from`, `to`, `at`, `by`, `reason`), and
`error` (`code`, `message`, `board_id`, `board_number`, `stage`, and the pre-build
problems).

- **States** (section 8): `queued` then `running`, then `succeeded`, `failed` or
  `cancelled`; `held` is a safety stop that resumes only after reconciliation (story
  410). A terminal run never changes (`run.transition`), and a run ID is never reused.
  A build records `held` (from `running`) when a live clip source stops it (story 851):
  `finished_at` stays null, `error` holds the code, message and the held problem above.
  Nothing in the build moves a held run on; a later build is a new run.
- **On the store** (proposal; the product's is a Postgres row, story 434): each
  version of a run document is a completed stage of the run, `run-0001` (with the
  snapshot blob as its second output), `run-0002` and so on. A stage name is
  create-only, so two writers moving one run from the same version race to one name and
  the loser gets `store.collision` (a compare-and-set). Before each write the stored
  versions are counted again: a run another writer moved since this one read it, or
  whose stored status is terminal, is `run.transition`. Readers take the highest
  completed version (`RunRecords.latest`). Which runs a production has is read from the
  local adapter's `records/` folder (`local_run_ids`, newest first); every build
  searches those runs for cached artifacts. The run `number` is one more than the
  production's runs (proposal).
- **A finished run is unchanged** by later edits to the draft: its snapshot blob holds
  the story as it was, and its record is never written again.

### The record of a build

| Field | Holds |
|---|---|
| `stages[]` | one per board in film order: `board_id`, `board_number`, `method`, `frames`, `film_start_frame`, `clips[]` (role, slot, hash, key, `made`, and from the clip's own record its frames, fps, requested length, seed, engine, engine job, model files and trim; a library clip's version ID; a whole-frame chain's `clips[]`, each with `kept: {key, made}` when a live source kept it), `segment_sha256`, `segment_key`, `compositor`, `artifacts[]` (every planned artifact of the board: name, kind, key, hash, `made`, `seconds`; and each kept chain clip, `wan_chain_clip/<index>` of kind `wan_chain_clip`, `made` when this run collected it, else reused from the run that did), `report` (the renderer's report of a segment rendered in this run), `checks[]` (the renderer's decal checks), `render_s` |
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
  with hashes and licences, its licence (the most restrictive of the register's entry
  and its files: `noncommercial`, then `unknown`, then `conditional`, then `allowed`;
  `conditional` where the register says so, P-23), its profile, its hardware (what the
  engine reported, else the register's `where`), and what it made (`used_by`). A
  generator the register does not name is an `unregistered-...` engine with an `unknown`
  licence and the reason; nothing is guessed. Licences block nothing (D49).
- `inputs_externally_generated`: every input version with the D42 marker.
- `usage`: `{frontier_tokens: null, basis: "not metered"}`.
- `public`: `ai_generated: true` and one credit per video, voice or sound engine,
  `"<Video|Voices|Sound>: <engine name>"`, with `" on <hardware>"` only when the engine
  itself reported its hardware (proposal). The register's `where` names cluster
  deployments and nodes, so it stays in the private `engines[].hardware` and never
  reaches a credit. Image, check and writer engines stay private
  (`credit.outside_video_sound`).

## Supported method matrix as built

| Layer \ motion | `s2v` | `i2v` |
|---|---|---|
| `layered` | **Built**: drive tracks, speech-to-video clips (or a library timed clip made from the board's own drive track with its seed), keyed frames, idle dolls from pinned loops, the set loop, `LayeredRenderer` | **Built**: idle dolls from pinned loops with talk bounce from the board voice, the set loop, `LayeredRenderer` |
| `whole_frame` | **Refused** before any clip: `method.unavailable` (section 5) | **Built**: the clip chain from the board's current photo, `WholeFrameRenderer` |

## Failure table

No row ends in success. Only a failure after `deliver` returned (a read-back row at
stage `delivery`, or `build.run_unrecorded` after one) leaves a published delivery, and
the failure names it. Tests are in `tests/build_story/`
(not `tests/build/`: pytest's default `norecursedirs` skips every folder named `build`, so
tests there would never run in `uv run pytest` or CI).

| Code | Stage | When | Test |
|---|---|---|---|
| (usage, exit 2) | (no run) | `studio build` or `--phase service` without a valid `--wan-story`; `--dry-run` without `--phase service` | `tests/cli/test_cli_build.py::test_the_service_phase_and_a_full_build_need_a_wan_story_and_make_no_run`, `test_live_sources.py::test_the_cli_needs_a_wan_story_and_a_dry_run_only_of_the_service_phase` |
| `asset.unresolved`, `ref.unknown`, `store.*` | (no run) | a reference the library or the store cannot give; nothing can be pinned | `test_failures.py::test_a_story_whose_assets_do_not_resolve_makes_no_run` |
| `voice.absent` | `prebuild` | a spoken board without a current voice | `test_failures.py::test_a_missing_voice_fails_the_run` |
| `voice.stale` | `prebuild` | a board voice that is not the board's lines, or signed with another engine (VOICE-9) | `test_a_stale_voice_fails_the_run`, `test_a_voice_signed_with_another_engine_is_stale` |
| `method.unavailable` | `prebuild` | whole-frame speech-to-video | `test_a_refused_method_fails_the_run_before_any_clip` |
| `wholeframe.*`, `layered.*` | `prebuild` | an adapter's own check refuses the board (a camera cue on a whole-frame board, a layout that does not place a slot, ...) | `test_an_adapter_refusal_fails_the_run_before_any_clip` |
| `motion.clip_absent` and the resolver's other codes | `prebuild` | a cast still without a loop, an ambiguous or corrupt pin | `test_a_cast_still_without_a_loop_fails_the_run` |
| `photo.absent` | `prebuild` | a whole-frame board without a current photo | the pre-build check's own tests (story 379, 427) |
| `build.voice_track_missing` | `voice` | a current board voice that records no assembled track (a legacy import's), which the picture's envelope and the mix read | `test_failures.py::test_a_board_voice_without_a_track_fails_the_run` |
| `cache.key_input_invalid` (a missing seed, ...), `motion.*` and `store.*` (a library timed clip that is damaged, ambiguous or cannot be played), `layered.*`, `wholeframe.*` (a clip request's inputs) | `plan`, `s2v_clip`, `s2v_drive_track`, `whole_frame_clip`, ... | the local pass finds it anywhere in the story, before any clip of any board is asked for; no clip source is asked, and the message ends "(found before any clip was requested)" | `test_local_pass.py::test_a_damaged_timed_clip_of_a_later_speaker_stops_the_run_before_any_clip`, `test_a_later_boards_missing_seed_stops_the_run_before_an_earlier_boards_clip` |
| `mix.input_invalid`, `cue.out_of_range`, `store.*`, `time.conservation`; `build.check_failed` (a mix check) | `mix`; `checks` | the mix, made after the local pass in a full build or the service phase, is refused (a `true_peak_dbtp` of -30 the schema accepts and the limiter cannot reach, a cue outside its board, a sound blob) or fails one of its own checks (a `master_lufs` the limited speech cannot reach); no clip source is asked, and the message ends "(found before any clip was requested)" | `test_local_pass.py::test_a_mix_the_limiter_refuses_stops_the_service_phase_before_any_clip`, `test_a_mix_the_limiter_refuses_stops_a_full_build_before_any_clip` (1 and 2 workers), `test_a_mix_that_fails_its_own_checks_stops_before_any_clip` |
| `adapter.request_invalid`, `build.live_unsupported` | `s2v_clip`, `whole_frame_clip` | a live source's check of a request the local pass recorded: the Wan client would refuse it, or does not make its profile; before the mix and any clip, "(found before any clip was requested)" | `test_live_sources.py::test_a_request_the_client_would_refuse_fails_the_run_before_any_clip`, `test_a_profile_the_client_does_not_make_fails_the_run_before_any_clip` |
| `adapter.*`, `build.wan_unsettled`, `build.internal` (status **held**) | `s2v_clip`, `whole_frame_clip` | any refusal of the Wan client ([held states](#held-states)) | `test_live_sources.py` |
| `store.hash_mismatch`, `store.blob_missing`, `cache.entry_invalid` | `whole_frame_clip` | a kept chain clip (story 851) that is not as recorded; nothing is asked of the client | `test_live_sources.py::test_a_kept_clip_that_is_not_its_bytes_is_refused_and_nothing_is_rendered_in_its_place` |
| `layered.clip_invalid`, `wholeframe.clip_invalid`, `time.source_short` | `s2v_clip`, `whole_frame_clip`, `segment` | a clip source's answer that is not what was asked, or a clip too short | `test_a_failed_clip_fails_the_run_on_its_board` |
| `build.offline_missing` | `s2v_clip`, `whole_frame_clip`, `check_result` | the offline phase needs a clip, or a transcript check of a new master, that no run made | `test_phases.py::test_the_offline_phase_refuses_a_service_call_naming_the_missing_artifact`, `test_the_service_phase_fills_the_cache_and_the_offline_phase_never_asks_the_recognizer` |
| `layered.decal_weak`, render and splice codes (`render.*`, `splice.incompatible`, `time.conservation`) | `segment`, `film_picture` | a decal track below its floor, a renderer, encoder or splice refusal | the adapters' and cache's own tests |
| `build.check_failed` | `checks` | a sound check or the transcript check did not pass; in the service phase, the transcript check it made or read of a cached master did not pass (`studio build --phase service` exits 1) | `test_a_failed_check_fails_the_run_and_delivers_nothing`, `test_phases.py::test_a_failed_transcript_in_the_service_phase_fails_the_run`, `tests/cli/test_cli_build.py::test_a_failed_transcript_in_the_service_phase_exits_1` |
| `delivery.*` | `delivery` | the master or the proxy fails a delivery check | `test_a_failed_delivery_fails_the_run` |
| `build.delivery_unverified`, `store.*`, `delivery.record_invalid` | `delivery` | the delivery does not read back with the plan's master, decodes another frame count, or its read-back raises; the run names the delivery `deliver` published (`delivery_id`, message) | `test_a_delivery_that_does_not_read_back_fails_the_run`, `test_a_delivery_whose_read_back_raises_is_named_on_the_failed_run`, `test_a_delivery_stage_left_by_a_failed_deliver_is_named_from_its_own_record` |
| `build.run_unrecorded` | (raised; the stored run may still read `running`) | writing the failed run raised a store or transition error; the message names the run, the delivery and the failure, and `studio build` exits 1 | `test_a_failure_the_store_cannot_record_names_the_run_and_its_delivery`, `test_a_transition_error_writing_a_failure_raises_naming_the_run`, `tests/cli/test_cli_build.py::test_a_failure_the_store_cannot_record_exits_1_naming_the_run` |
| `build.internal` | where it was | an exception that carries no code | (a bug: the message names its type) |

| Code | Status | Source |
|---|---|---|
| `build.offline_missing` | failed | proposal |
| `build.check_failed` | failed | proposal |
| `build.delivery_unverified` | failed | proposal |
| `build.voice_track_missing` | failed | proposal |
| `build.run_unrecorded` | failed (not recorded on the run) | proposal |
| `run.transition`, `run.unknown` | conflict, invalid | proposals |
| `build.internal` | failed (held when a live source raised it) | proposal |
| `build.wan_unsettled` | held | proposal (story 851) |
| `build.live_unsupported` | failed | proposal (story 851) |
| `build.dry_run_asked` | failed (a dry run's source was asked: a bug) | proposal (story 851) |
| `adapter.*` from a live source's call | held | story 842's codes |

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
   whole pre-build check and the local pass have passed: any `voice.*`, `photo.absent`,
   `method.*`, `motion.*` or adapter problem, a missing `s2v:<slot>` or `i2v:frame`
   seed, or a library timed clip (an E0 clip) that is damaged or cannot be played shows
   here first, before any service is asked. A run that stops in the local pass says
   "(found before any clip was requested)".
6. **The service phase** (story 851's live sources), with the coordinator watching:
   first `uv run studio build ... --phase service --dry-run --wan-story
   https://work.haynesnetwork.com/work_packages/428`, which lists every clip job, in
   order, with its length, seed and E0 GPU time, and asks nothing; put that list in
   front of the coordinator. The toolchain file must set `s2v_negative_prompt` (the
   default is empty, which the Wan graph refuses before any clip; E0's is the client's
   `NEGATIVE`). Then work through the [checklist](#before-the-first-live-job) and run
   the same command without `--dry-run`. The local pass, the check of every request
   and the mix run first, so no Wan job is submitted for a story they refuse anywhere.
   Otherwise the run ends `cancelled` with "service phase complete"; the mix and every
   clip are now cached. A refusal ends it `held` (exit 1, `rule adapter.<code> ...
   held ...`): stop and follow the held record's `check` before anything else. Watch the
   Wan compute lease; never bypass it.
7. **The offline phase.** `nice -n 10 uv run studio build ... --offline --workers N`
   (N up to 22 on `ai/studio-render`, 1 in a session pod). It renders the picture, the
   mix and the master, then stops at the transcript check with `build.offline_missing`
   (stage `check_result`): the master is new, and the recognizer is a service.
8. **The transcript.** `uv run studio build ... --phase service` again, from where the
   Whisper client works (`kubectl exec`): it checks the cached master and makes nothing
   else. A transcript that does not pass ends the run `failed` with `build.check_failed`
   (stage `checks`, naming `master.transcript`) and exits 1; the result is cached, so a
   later service or offline run reads the same failure until the script, its
   `checks.asr_tolerances` or the master changes. Nothing is delivered from that master.
   **(428 decides)** whether the render worker can reach the store this needs.
9. **Delivery.** `uv run studio build ... --offline` once more: every artifact is a hit;
   the run delivers and ends `succeeded`. `studio run show <run_id> --store ROOT
   --production <prd> --json` prints the record. A run that fails after the delivery was
   published names it (`delivery_id`); a `rule build.run_unrecorded` line means the
   failure could not be written, and names the run and the delivery: read the stored
   run with `studio run show` before anything else. (Where one host has both the services
   and the CPU, steps 6 to 9 are one full build: `studio build` with no flag.)
10. **A second build** of the same draft with `--offline`: every artifact is a hit and
    no source or recognizer is asked; only the new run's delivery is made.
11. **Record** the run's timings (each artifact's `seconds`, `render_s`), sizes and IO,
   and compare with the E0 delivery. Tom watches the delivery for the demo; a source PR
   and a delivered run are not his acceptance.

### Before the first live job

Story 842's own checklist ([legacy-adapters.md](legacy-adapters.md#before-the-first-live-job-story-428)),
as the build runs it. Read-only checks with the coordinator watching, then one job:

0. The store root is on a local file system, and every run of it uses the one journal,
   `<store root>/wan-journal.jsonl` (the build gives the client no other). If a run is
   held with `adapter.busy` naming the journal, find the process holding it; never point
   a run at another store root or file. Never delete, move, empty or replace the journal
   or its `.lock` file while a build runs; a journal missing beside its lock file, or
   empty, is a stop until a person has checked the Wan service. Keep the store writable
   by the build only.
1. `git -C ~/repos/haynes-ops fetch`; `kubernetes/main/apps/ai/wan-video/app/workflow.json`
   still hashes to `88fe79ad...136b`, and `api.py` still has `acquire_compute`,
   `gpu_sample`, `engine`, `save` and `generate(job, prompt, lease=None)` with the
   checks in story 842's rows 18 and 19; `save` still writes the whole job and
   `GET /videos/<id>` still returns it (`recover` needs `graph_sha256` back); `/health`'s
   `active_job` is still set only by `POST /videos`; `EXPECTED` is still the two IDs in
   `pinned.WAN_GPU_UUIDS`. A change there is a stop.
2. `kubectl -n ai get deploy wan-video` is ready with containers `api`, `app`, `foley`,
   and `/config/video/api.py` in the `api` container is the haynes-ops file.
3. One `WanClipClient.probe()` (outside the build): `accepting_jobs` true, no active job,
   both queue lists empty, exactly the two approved GPUs, temperatures and utilization
   sensible.
4. Free space on PVC `ai/wan-video` for the inputs and clips.
5. The journal holds no job and no halt: `FileJournal(<store root>/wan-journal.jsonl)
   .read_state()` shows `job` and `halt` `None` (or the file does not exist yet).
6. The dry run's list is what the coordinator expects. The first live service phase
   asks for one `ImageToVideo` at 576x1024 and 121 frames: build a draft whose only
   missing clip is that one (the dry run shows exactly one `i2v` job). Watch the GPUs
   during the job. Check the clip record in the cache (the whole-frame clip set's
   `extra.wan`: 121 frames delivered, 576x1024, `fps` 24 as measured,
   `cool_before_upload`, `engine_read_retries`, no `unexpected_work_seen`), read
   `/videos/<job_id>` (`succeeded`, the same `bytes` and `graph_sha256`), and confirm the
   journal ends with that job's `settle collected` line.
7. Only then one `SpeechToVideo`, on a board of at most one chunk (the dry run shows one
   `s2v` job, `1 chunk(s)`).

If a run is held, read its record (`studio run show RUN_ID --store ROOT --production
PRD --json`, `error.problems[0]`), then the journal, then `/videos/<job_id>` for the job
it names and the engine queue. A finished job whose answer was lost is collected by the
next service phase of the same draft (and `--wan-story`) with `recover`, never rendered
again; a failed job whose prompt was accepted is a person's to settle
(`clear_in_flight()` once its ledger reads failed and the engine queue holds nothing of
it); anything else is a person's too: never resubmit to recover, never call
`clear_in_flight()` or `clear_halt()` without checking, and never start a new journal to
get past a blocked one. A chain held part way keeps the clips it collected
(`collected_before_stop` names each with its `kept` key): the next service phase asks
only for the rest, and its board stage lists each chain clip as made or reused.

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
- A service-phase run ends `cancelled` at the phase boundary, or `failed` with
  `build.check_failed` when a check it made or read did not pass.
- The mix and its own checks are made after the local pass and before any clip is
  asked for, in the full build and the service phase; the service phase therefore
  makes the mix too, and its run lists the mix checks.
- The local pass before any clip request, with recording clip sources, and the stage
  `plan` for a refusal the plan makes itself.
- A failure that cannot be written raises `build.run_unrecorded` and is never returned.
- The run record on the local store as versioned stages, the run list from `records/`,
  and the run number.
- The pre-build check runs before the run is queued, and a story whose references do
  not resolve makes no run; any other refusal (`queue_run`'s included) fails a recorded
  run, so the refusal is on record (the acceptance's "a missing voice ends the run as
  failed").
- The proxy key is answered by the delivery's proxy.
- The transcript check's version `1`, its 16 kHz mono input and the PoC's word-level
  comparison; its result document.
- The engine matching rules, the unregistered engine, the credit text (no hardware
  unless the engine reported it), the order of restriction for an engine's licence.
- The transcript check runs in the service phase (it is a service call), on a master the
  cache holds; the offline phase reads it from the cache only.
- The codes above; `--toolchain`, `--studio-commit`, the library file as a JSON array.
- Story 851: the live sources' glue (`build.live`): the journal at
  `<store root>/wan-journal.jsonl`; the client made on the first clip request; a held
  run for every refusal, recorded from `running` with the held problem; `recover` for a
  journal job whose graph matches the current request, `build.wan_unsettled` otherwise;
  a kept clip (foreign work during its own job) cached, then held; the check of every
  request before the mix; the profile match (`build.live_unsupported`); `--wan-story`,
  `--dry-run`, the dry run as a recorded run ended `cancelled`, the E0 estimate rule;
  the source names `studio.build.wan-s2v/1` and `studio.build.wan-i2v/1`; the whole Wan
  record kept as the clip's `extra.wan`; each chain clip kept as it is collected (kind
  `wan_chain_clip`, its key `kept_key`, the stage `wan_chain_clip_record-<key hex>` and
  schema `studio.wan-chain-clip/v1`, `extra.kept`, `ClipSources.bind`) and listed on the
  board stage.
