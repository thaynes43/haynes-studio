# Legacy service adapters

Story [425](https://work.haynesnetwork.com/work_packages/425) (E1.11), epic
[372](https://work.haynesnetwork.com/work_packages/372). The package
`haynes_studio.adapters` ([source](../../src/haynes_studio/adapters/)) holds clients
for the in-cluster services the PoC used, ported from `poc/studio.py`, `poc/speech.py`,
`poc/comfy.py` and `poc/deliver.py`. Routes and service facts are in
[services.md](services.md).

**State: source and tested with fakes only.** No client has been run against a live
service. Wan, Foley and speech-to-video clients are stories
[426](https://work.haynesnetwork.com/work_packages/426) and
[427](https://work.haynesnetwork.com/work_packages/427), with the compute-lease rules.

## How a call works

A service call is data. A client builds a `Command` (argument vector, stdin bytes,
timeout, label) and hands it to the `Runner` it was given; it never starts a process
itself. Tests pass `FakeRunner` from `haynes_studio.adapters.fakes`; an authorized live
story passes `SubprocessRunner`, a thin `subprocess.run` wrapper (no shell, no retries)
that no test and no CI job calls.

```python
from haynes_studio.adapters.fakes import FakeKokoro, FakeRunner
from haynes_studio.adapters.kokoro import KokoroClient, SpeechRequest

take = KokoroClient(FakeRunner(FakeKokoro())).synthesize(SpeechRequest("bf_emma", "Aye."))
```

Swap in `SubprocessRunner()` for the real call; nothing else changes. Every client also
has a `command(...)` method that returns the `Command` without running it.

Importing any module of the package starts no process, opens no socket, parses no
arguments and reads no environment
([test](../../tests/adapters/test_import_guard.py); `haynes_studio.__main__` is the
`python -m` entry point and is excluded).

## Clients

| Client (module) | Call | Route | stdin | Timeout | Answer |
|---|---|---|---|---|---|
| `KokoroClient` (`kokoro`) | `synthesize(SpeechRequest(voice, text))` | `kubectl exec -i -n ai deploy/kokoro -c app -- python -c <kokoro_tts.py>` | `{"voice", "text"}` JSON | 55 s (snippet: 45 s, 30 s per event, 2 000 000 audio bytes) | `SpeechTake`: WAV bytes, SHA-256, channels, width, rate, frames, `legacy_duration_s` |
| `WhisperClient` (`whisper`) | `transcribe(TranscriptRequest(wav))` | `... deploy/whisper -c app -- python -c <whisper_asr.py>` | the WAV | 55 s (snippet: 45 s, 30 s per event) | `Transcript(text)`; `heard_matches(heard, text)` is the PoC's `norm` comparison |
| `ImageClient` (`comfyui`) | `render(TextToImage(...) or ImageEdit(...))`; an edit's upload name comes from its PNG's hash | `kubectl exec -i -n ai comfyui-0 -c app -- python3 -c <comfyui_prompt.py>` | `{"graph", "client_id", "upload"?}` JSON | 3300 s (snippet: 30 min queue wait, 20 min render) | `ImageResult`: PNG, SHA-256, `prompt_id`, ComfyUI file and subfolder, timings, `graph_sha256` |
| `ImageClient` | `queue()` | `... -- python3 -c <comfyui_queue.py>` | none | 45 s | `QueueState(running, pending)`; submits nothing |
| `LedgerReader` (`wan_ledger`) | `get(ledger_id)` | `kubectl exec -i -n ai deploy/wan-video -c api -- python3 -c <wan_ledger_read.py> <id>` | none | 30 s | `LedgerRecord`, checked like `poc/deliver.py` `check_ledger` |
| `LedgerReader` | `list()`, `find(sha256)` | `... -- python3 -c <wan_ledger_list.py>` | none | 60 s | `LedgerListing` of `edited_production` summaries; unparseable ledger files and malformed entries are listed in `unreadable`, never fatal |
| `LedgerReader` | `fetch_asset(ledger_id, sha256)` | `... -- python3 -c <wan_ledger_fetch.py> <id> <sha256>` | none | 180 s, 64 MiB | `AssetBytes`, hash checked in the pod and again here |

ComfyUI is shared with Home Assistant and Open WebUI. The prompt snippet waits until
the queue is empty before submitting and never cancels anyone's work, and `render`
refuses a second concurrent call in the same process (`adapter.busy`). Across
processes this is best effort, as in the PoC: checking for an idle queue and submitting
are two steps, so two clients that check at the same moment can both submit. If a
render fails after ComfyUI accepted the prompt (including a timeout), the `ImageError`
carries `prompt_id`: read `/history/<prompt_id>`, do not resubmit.

The ledger reader is read-only by construction (contract section 8: product code never
writes the Wan volume): it has no write, publish, link, rename or delete method, and a
test holds its three snippets to an allowlist of read calls and imports, so any new
call fails until someone reviews it. `wan_ledger.ADAPTER` is `legacy_wan_ledger`, the
adapter name the contract gives legacy deliveries.

## Errors

Every failure is an `AdapterError` with a `code`, the call's `label` and a short
message: `adapter.request_invalid` (names the field, before anything runs),
`adapter.pin_mismatch`, `adapter.command_failed` (non-zero exit), `adapter.not_found`
(an HTTP 404 inside the pod), `adapter.timeout`, `adapter.response_invalid`,
`adapter.busy`. The package never puts the request payload, the snippet, the full
command line or an environment value into an error, and the real runner drops the raw
`subprocess` exception (it is not kept as the error's cause or context). The only
service text is `detail`: the last 300 characters of stderr, with URL userinfo,
`Bearer` and `Basic` credentials, and the value of any key containing `token`,
`password`, `secret`, `api_key`, `authorization`, `cookie` or `credential` (in `=`,
`:`, JSON or Python-repr form) replaced by `<redacted>`. Redaction runs before the cut,
so a cut cannot expose part of a value. The ported ComfyUI snippet prints ComfyUI's
error status on failure, and that status can quote a node's inputs, so `detail` may
hold part of an image prompt. Prompts are not secrets, but treat `detail` as service
output. Changing the snippet would break byte parity with the PoC.

## Pinned inputs

The graphs and in-pod snippets are package data in
[`pinned-inputs/`](../../src/haynes_studio/adapters/pinned-inputs/) (a hyphenated
folder, so no snippet can be imported). Their hashes are in
[`pinned.py`](../../src/haynes_studio/adapters/pinned.py). A client loads its inputs
when it is constructed and checks them again before every command; a changed file is
refused (`adapter.pin_mismatch`) and never sent. Nothing reads `~/repos/haynes-ops` or
any other checkout at run time.

| File | Source | SHA-256 |
|---|---|---|
| `kokoro_tts.py` | `poc/studio.py` `TTS`, byte for byte (from haynes-ops `scripts/wan-video/butter_speech.py`) | `7fcf8605f9713f66a110516606f8c2493fe851b986842015a746e9ef1f11fadf` |
| `whisper_asr.py` | `poc/studio.py` `ASR`, byte for byte (from haynes-ops `scripts/wan-video/check_butter_dialogue.py`) | `6e2ce027609d4f1e071bccd5ff9d5b16fe8e19f2d303a651bb04687e415d0b57` |
| `comfyui_prompt.py` | `poc/comfy.py` `REMOTE`, byte for byte | `2b5f31d2bbe42d4532fee006423edc6d11d83371fc7acb9536d51146880abcdb` |
| `comfyui_queue.py` | new: `GET /queue`, prints the two counts | `281325a754325867d53559a37057179005f6680695e5d21a6589894f0c267d6f` |
| `wan_ledger_read.py` | `poc/deliver.py` `READ`, byte for byte | `ba9fa7aac19a20a54d52d6081323c008345bc74e243c359e7c35ea7005a96469` |
| `wan_ledger_list.py` | new: reads `/workspace/jobs/*.json` (the Wan API has no list route) | `32d6228e662fc4d793e0d037c5543c2f03eed3a968a0ebc243adb0f1de4f0ede` |
| `wan_ledger_fetch.py` | new: one ledger asset's bytes, path and hash checked | `5682a9ea1f50c7724095008b3e5fdb426371e4302c62baf33df7fda76dcd9584` |
| `qwen_image_2_1_t2i_API.json` | `poc/graphs/qwen_image_2_1_t2i_API.json`, byte for byte | `f18a6e29a1f225467874d6c4d9fe16861982ad9ff6e274ca3d170245c43d226d` |
| `qwen_image_2_1_edit_API.json` | haynes-ops `kubernetes/main/apps/ai/stable-diffusion/comfyui/resources/api-workflows/qwen_image_2_1_edit_API.json` at `7c7b2cf6cceecc782cb149a958635852ae162966` (the commit `prompts.json` records; git blob `f520dcd4937c`, last changed in `31b449445dc1`, unchanged at haynes-ops `main` on 2026-11-13), copied once | `946f46812559426297191419e8e4ca614ac948698f8a5ae9d09cda6b0e2fdcb6` |

## Compatibility matrix

[`tests/adapters/test_compat.py`](../../tests/adapters/test_compat.py) reads the PoC
source with `ast` (never importing it) and the committed Winter Menu evidence.

| Call | Same as the PoC, shown by test | Recorded inputs | Differences |
|---|---|---|---|
| Kokoro `synthesize` | argument vector, 55 s timeout, the `input=` expression, snippet text | all 38 r1 to r4 takes: each request's stdin is the PoC's JSON; a fake WAV of the recorded byte size parses to the recorded `duration_s` | none |
| Whisper `transcribe` | argument vector, 55 s timeout, snippet text | each take's recorded `heard` parses back and gives the recorded `heard_matches`; each revision's film transcript parses | the PoC passes the open file as stdin, the package its bytes (same content) |
| ComfyUI text to image | argument vector, 3300 s timeout, payload statements, graph field edits, template bytes, snippet text | **all 14 recorded t2i renders rebuild to the exact `graph_sha256` in `prompts.json`** | none |
| ComfyUI edit | graph field edits, upload payload, template from the recorded haynes-ops commit | the three recorded edit graphs cannot be rebuilt: the PoC named each upload with 12 random hex digits | the upload name is `studio-<first 12 hex of the PNG's SHA-256>.png`, derived from the bytes (proposal P-425-03) |
| ComfyUI `queue` | new | none | new call (P-425-02) |
| Wan ledger `get` | argument vector with the ledger ID, 30 s timeout, snippet text, required fields of `check_ledger` | the four committed `production.json` files parse as served answers | the PoC inherited the caller's stdin; the package sends empty stdin |
| Wan ledger `list`, `find`, `fetch_asset` | new | `find` matches the set still across all four ledgers | new calls (P-425-04) |

## Fakes

`haynes_studio.adapters.fakes` is importable by any test. `FakeRunner(*services)`
records every command in `calls` and answers it from the service that owns its snippet
(found by the snippet's pinned hash; anything else raises `UnexpectedCommand`).
`FakeKokoro` returns synthetic WAVs (frame counts settable per line) and fills
`spoken`; `FakeWhisper(transcripts)` answers by the WAV's hash; `FakeComfyUI` returns a
synthetic PNG and a prompt ID derived from the graph's hash, and queue counts;
`FakeWanLedger(ledgers, files=...)` serves ledger documents (such as the committed
evidence) and asset bytes. `FailingRunner` returns one fixed exit status and stderr.
`synthetic_wav` and `synthetic_png` make small deterministic media in memory.

## Proposals

Choices beyond the contract, each open to change:

- **P-425-01** Request limits: Kokoro text up to 1000 characters and voice names
  `[a-z]{2}_[a-z0-9]+`; image names and jobs `[a-z0-9][a-z0-9-]*`, sizes multiples of 8
  from 64 to 4096, prompts up to 10 000 characters; transcript input a PCM WAV up to
  64 MiB. The PoC checked none of these.
- **P-425-02** `ImageClient.queue()` reads ComfyUI's queue without submitting, so a
  caller can show "waiting for a household render" first.
- **P-425-03** Edit uploads take a content-derived name, `studio-<first 12 hex of the
  PNG's SHA-256>.png`, so an edit graph and its hash can be rebuilt. The request derives
  it from its own bytes and takes no name from the caller: ComfyUI's upload overwrites
  by name (as in the PoC), so a name can only ever replace identical bytes.
- **P-425-04** The ledger reader adds `list`, `find` and `fetch_asset`. The Wan API has
  no list route, so `list` reads the ledger files directly; `fetch_asset` serves only a
  file that a ledger lists, under `/workspace/output/productions/`, at most 64 MiB,
  with its hash checked in the pod and again by the client. It is the route for
  recovering delivered inputs in story 428.
- **P-425-05** Failure text: stderr is kept as a 300-character, redacted tail; the
  package never adds payloads, snippets or full command lines to an error.
- **P-425-06** `ImageClient.render` allows one call at a time per process
  (`adapter.busy`) on top of the snippet's queue wait.
