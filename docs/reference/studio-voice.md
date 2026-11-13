# Board voice and jobs

`haynes_studio.voice` (story
[405](https://work.haynesnetwork.com/work_packages/405), epic
[372](https://work.haynesnetwork.com/work_packages/372)): the pre-build board voice of
[contract v1](../contracts/studio-contracts-v1.md) section 10 (VOICE-1 to VOICE-6),
timed by TIME-1 to TIME-3, and the `studio.job/v1` type. It builds on the
[asset library](studio-library.md) (story 382), the [canonical model](studio-model.md)
(story 404), `haynes_studio.timebase` and the Kokoro client of the
[legacy adapters](legacy-adapters.md) (story 425).

**State: source and tested with fakes only.** No speech service has been called from
this code. Tests use `FakeKokoro` behind `FakeRunner` and an in-memory store. A live
smoke test needs its own authorized story.

## Signatures

Every signature is `sha256:` plus the hex SHA-256 of canonical JSON (contract section 4).
They are the library's functions, not copies:

| Name | Canonical JSON | Function |
|---|---|---|
| take `signature` | `{engine, voice_id, text (NFC), speed}` | `library.model.take_signature` |
| version `input_signature` | `{takes: [take signature], lead_ms, gaps_ms}` | `library.model.input_signature` |
| version pin (what a snapshot pins) | `{input_signature, takes: [take sha256]}` | `library.model.pin` |

- `engine` is the model weights' digest once one is recorded (`Engine(digest=...)`).
  Until then it is the model name, `Kokoro-82M v1.0`. No digest is recorded today, so
  new takes sign exactly as the legacy takes do. A generated r4 board 8 has the contract
  example's input signature `sha256:cedb5264...`.
- `speed` is always `1.0`. The Kokoro client sends no speed, so the server default
  applies.
- `gaps_ms` holds one gap before each later line (`len(lines) - 1` values).

## What an edit costs

`plan_board_voice(story, board_id, library, engine=Engine())` answers it. The function
is pure and calls nothing:

| `action` | When | Speech calls | New version |
|---|---|---|---|
| `current` | the board's current voice version is this input | 0 | no |
| `existing` | another version of this board is this input (an undo) | 0 | no; the board points at it again |
| `assemble` | every take signature is held by a version of this board (lead or gap edit, a line moved to a speaker whose take exists) | 0 | yes, re-assembled |
| `synthesize` | some take signatures are new (text, speaker voice, a cast voice change) | one per new signature, even if two lines share it (`plan.speech_lines`) | yes |

A version **is** an input when its input signature is the input's and its takes have the
same line IDs, speakers and cast voice versions. This is stricter than the library's
currency in `Library.facts(story)`, which compares lines, speakers, cast voices, lead and
gaps but not the engine. Once a model digest is recorded, a legacy board stays timed and
buildable, yet a request for it re-synthesizes every take.

A take is reused when any version of the board's voice holds its signature, newest
version first (`take_sources`; the worker applies the same function, so the plan shows
what the worker does). A stale result therefore still saves calls on the next request.
A line whose text the speech client would refuse (blank, or over 1000 characters) is
`voice.request_invalid` at request time, so no job is queued that can only fail.

## Making a version

`make_voice(voice, board_id, library, speech=, publish=, fetch=, by=, now=)`:

1. If a version of the board already is the input, it is returned (`created: False`),
   and nothing is called or published.
2. Every reused take is read back with `fetch(locator, sha256)`, checked by hash and
   re-measured from its WAV header. Every other request is checked too. A missing take
   (`asset.bytes_missing`) or a bad request fails here, before any speech call. The
   worker validates the job document first, stock voices included.
3. Each new signature goes once to `speech.synthesize(SpeechRequest(voice_id, text))`
   (the Kokoro client and its injected runner). Each answer is published with
   `publish(bytes, "audio/wav") -> (sha256, locator)`. An answer in another format than
   the board's other takes fails the job before the next call.
4. `duration_ms = ceil(samples * 1000 / rate)` (TIME-1, `timebase.take_duration_ms`).
   Offsets follow TIME-2 (`timebase.line_spans`), and `speech_end_ms` is the last take's
   end. All of these are integers.
5. The track is 16-bit PCM at the takes' own rate (Kokoro: 24 kHz mono), built with
   `wave`. Take *i* starts at sample `offset_ms[i] * rate div 1000`, the gaps are
   silence, and the track ends at `speech_end_ms * rate div 1000`. At 24 kHz that is
   24 samples per ms, exactly. Takes in different formats are refused
   (`voice.format_mismatch`). Nothing is resampled: the mix converts to 48 kHz (VOICE-7).
6. The track is published, and the version is imported through
   `library.import_version`. It is a `board_voice` in state `board`, origin `generated`,
   under source key `board-voice:<board_id>`, so each board's generated versions are
   numbered 1, 2, ... on one asset. Its licence is `unknown`. Takes have `heard` and
   `heard_matches` null (the transcript check is VOICE-8). The library validates it
   (TIME-1, TIME-2, stock voices, the track's locator).

The library's pin for a board voice is its input signature and take hashes only. A new
version can therefore carry another version's pin with other line IDs, speakers or
cast voice versions. Examples: a line deleted and re-added with the same text, or a
cast voice swapped for another `voice` version of the same stock voice. Importing it
on the board's asset would be `idempotency.mismatch`, so it goes to an asset keyed
`board-voice:<board_id>:lines:<16 hex digits of the lines' signature>` (proposal,
until the library's pin covers line identity).

`publish` is bound to the job's production by the caller. It must answer the bytes'
own hash (`store.hash_mismatch`) and place them at
`productions/<production_id>/sha256/<h[0:2]>/<h>.wav` (`store.locator_invalid`). Takes
have no locator field: a take is found by its hash in that folder.

### Worked example: r4 board 8

Lead 1900, gaps 300, 200, 250, 700, 900. The takes are 24 kHz, with sample counts equal
to the recorded `duration_s` × 24 000:

| Line | Speaker | Samples | `duration_ms` | `offset_ms` | End | Track samples |
|---|---|---|---|---|---|---|
| 1 | b | 24 072 | 1003 | 1900 | 2903 | 45 600 to 69 672 |
| 2 | a | 19 464 | 811 | 3203 | 4014 | 76 872 to 96 336 |
| 3 | c | 21 000 | 875 | 4214 | 5089 | 101 136 to 122 136 |
| 4 | d | 12 288 | 512 | 5339 | 5851 | 128 136 to 140 424 |
| 5 | b | 24 576 | 1024 | 6551 | 7575 | 157 224 to 181 800 |
| 6 | b | 27 648 | 1152 | 8475 | 9627 | 203 400 to 231 048 |

`speech_end_ms` is 9627, and the track has 231 048 samples (9627 ms). With tail 800,
`content_ms = 10427` and `frames = (10427 * 24 + 999) div 1000 = 251` (TIME-3), as
recorded. Every r4 board generated this way is timed at the recorded 1087 frames. So is
every board whose takes are up to 11 samples longer: the same 3-decimal `duration_s`,
and 1 ms more per take.

## Jobs (`studio.job/v1`)

Schema `src/haynes_studio/schemas/studio.job.v1.schema.json`, validator `validate_job`
(contexts `read`, `write` and `queue_run` check the same rules), read-only model `Job`.

| Field | Content |
|---|---|
| `id`, `kind`, `target_id` | `job_` ID; `voice`, `photo` or `asset_candidate`; a `brd_` ID for voice and photo jobs |
| `input_signature` | the signature the job started from (VOICE-4) |
| `status` | `queued`, `running`, `succeeded`, `failed` or `cancelled` |
| `result_version_id`, `result_is_current` | set only when `succeeded` |
| `error` | `{code, message}`, only when `failed` (proposal) |
| `created_by`, `created_at`, `updated_at` | principal and times (proposal) |
| `voice` | voice jobs only (proposal): `production_id`, `story_id`, `name`, `engine` (signing name), `model`, `lead_ms`, `gaps_ms`, and `lines` of `{line_id, speaker, text, voice_version_id, voice_id, signature}`. The validator checks that each signature and the `input_signature` follow from it, and that each `voice_id` is a stock voice of `model` (`voice.not_stock`). |

The job runs from its own `voice` block, so the worker never reads the draft as it was
at queue time. State machine (`haynes_studio.voice.jobs`):

```
queued -> running | cancelled
running -> succeeded | failed | cancelled
succeeded, failed, cancelled -> nothing (job.transition, status conflict)
```

**VOICE-4.** `run_voice_job(job, library, draft=..., ...)` starts the job and makes its
version. It then reads `draft()`, the story as it is when the job finishes. The result
is always kept as a version. The job is `succeeded` with `result_is_current: true` only
if the board as drafted now is still the job's input (`is_current`). Otherwise
`result_is_current` is `false`, the board keeps its old current voice, and the result
stays as a stale version that later requests can reuse takes from. A rule or adapter
error fails the job with its code, and no version is made. Blobs that were already
published stay; they are harmless orphans (section 8).

## Timing and Build (VOICE-5, VOICE-6)

`voice_facts(library, story, jobs)` is story 404's `Facts`: the library's measured
takes and currency, plus `generating` for every board with a voice or photo job in
flight. With them, `with_derived` and `timing_summary` time each board from its
current voice. `queue_run` refuses `voice.absent`, `voice.stale` and `asset.generating`
and accepts the rest. Voices are never made inside a run.

## What story 430 needs

| Operation | Call | Notes |
|---|---|---|
| `generate_board_voice` `POST /boards/{id}/voice-jobs` | `request_voice(story, board_id, library, jobs=in_flight, by=, now=)` | Returns `plan`, `job` and `created`. `job` is null for `current` (answer 200 with the version) and `existing` (point the board at `make_current` as a board edit, with a revision bump). An in-flight job for the same input is returned with `created: false`. With `Idempotency-Key`, the same key and body return the same job. Show `plan.speech_lines` and `plan.action` before or after queueing. |
| worker | `run_voice_job(job, library, draft=lambda: current_story, speech=KokoroClient(SubprocessRunner()), publish=store.publish, fetch=store.fetch, by=worker, now=)` | Claim, run, complete through the internal endpoints. If `make_current`, set `board.voice.current_version_id` to `version.id` (`with_current_voice` shows the change) and bump the story's revision. Persist the terminal job and the new version. |
| `get_job` `GET /jobs/{id}` | `job.to_document()` | Valid `studio.job/v1`. |
| `list_board_voice_versions` `GET /boards/{id}/voice-versions` | `board_voice_versions(library, board_id)`, then `library.document(id)` | Newest first, legacy and generated, current and stale. Mark the board's current one. |
| play | `GET /media/{sha256}` with `version.voice.track.sha256` (the board), or a take's `sha256` (one line) | Track and takes are `audio/wav` at the take rate. Offsets for a waveform or captions are each take's `offset_ms` and `duration_ms`. Legacy versions have no track (`track: null`, `track_note`), and their take bytes are private until story 428 imports them. |
| board read | `with_derived(story, facts=voice_facts(...))` | `voice_state` is `generating`, `absent`, `stale` or `current`, and the board is timed from its current voice. |

## Codes

| Code | Where | Source |
|---|---|---|
| `voice.not_stock` | a cast voice that is not a recorded stock voice of the engine's model, a cloned voice (the library's rule), a job line's `voice_id` | contract |
| `voice.speaker_not_in_cast` | story 404's validator, run on the draft first | contract |
| `voice.absent` | a narrator line without the story's narrator voice | contract |
| `asset.kind_mismatch`, `asset.bytes_missing`, `ref.unknown` | a cast voice that is not a `voice`; a reused take the store does not hold (or holds with another hash); an unknown board or voice | story 382 and 404 proposals |
| `store.locator_invalid` | `publish` placed bytes outside the production's hash path | contract |
| `voice.not_needed`, `voice.request_invalid`, `voice.format_mismatch`, `voice.engine_mismatch`, `store.hash_mismatch`, `job.transition` | a silent board; a line the speech client would refuse; a take that is not 16-bit PCM or differs in format; a job signed for another engine; `publish` answered another hash; a move the state machine refuses | proposals |

## Proposals

- The track stays at the takes' own rate, so no resampling is done here. The contract's
  cache table lists a mix rate among the track's inputs. Here the mix rate belongs to
  the mix, and the track key is its version pin plus `ASSEMBLER` (`studio.voice.track/1`).
- The track ends at `speech_end_ms`, because the tail is not voice. A take starts at
  `offset_ms * rate div 1000`.
- Speed is fixed at 1.0.
- A board's generated versions share one asset under `board-voice:<board_id>`, with a
  lines-keyed asset only when the library's pin would collide. A legacy import keeps
  its own asset.
- Takes are reused from any version of the same board, newest first, never across
  boards.
- Generated takes have `heard` and `heard_matches` null, reused ones included, so a
  version's content follows from its input, its take bytes and the engine alone.
- The take signature has no sample rate, although the contract's cache table lists one
  among a take's key inputs. If Kokoro's rate changed, takes of two rates would share
  signatures, and a partly edited board would fail with `voice.format_mismatch`. Nothing
  here remakes a take whose signature is held, so the fix is the rate in the signature
  (an observation for the contract owner and story 382).
- The job fields beyond the contract's: `error` as `{code, message}`, `created_by`,
  `created_at`, `updated_at`, and the `voice` block.
- An in-flight job is never cancelled automatically when the board changes. It
  finishes stale.

Not here: the mix and loudness (VOICE-7), the transcript check (VOICE-8), the store
adapter (story [379](https://work.haynesnetwork.com/work_packages/379)), the API
([430](https://work.haynesnetwork.com/work_packages/430)) and any live call.
