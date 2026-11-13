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
has a `command(...)` method that returns the `Command` without running it, for inspection
and tests. It takes no lock and makes no check: `ImageClient.render` is the only
supported way to submit an image prompt.

Importing any module of the package starts no process, opens no socket, parses no
arguments and reads no environment
([test](../../tests/adapters/test_import_guard.py); `haynes_studio.__main__` is the
`python -m` entry point and is excluded).

## Clients

| Client (module) | Call | Route | stdin | Timeout | Answer |
|---|---|---|---|---|---|
| `KokoroClient` (`kokoro`) | `synthesize(SpeechRequest(voice, text))` | `kubectl exec -i -n ai deploy/kokoro -c app -- python -c <kokoro_tts.py>` | `{"voice", "text"}` JSON | 55 s (snippet: 45 s, 30 s per event, 2 000 000 audio bytes) | `SpeechTake`: WAV bytes, SHA-256, channels, width, rate, frames, `legacy_duration_s` |
| `WhisperClient` (`whisper`) | `transcribe(TranscriptRequest(wav))` | `... deploy/whisper -c app -- python -c <whisper_asr.py>` | the WAV | 55 s (snippet: 45 s, 30 s per event) | `Transcript(text)`; `heard_matches(heard, text)` is the PoC's `norm` comparison |
| `ImageClient` (`comfyui`) | `render(TextToImage(...) or ImageEdit(...))`; an edit's upload name is `studio-<the PNG's full SHA-256>.png` | `kubectl exec -i -n ai comfyui-0 -c app -- python3 -c <comfyui_prompt.py>` | `{"graph", "client_id", "upload"?}` JSON | 3300 s (snippet: 30 min queue wait, 20 min render) | `ImageResult`: PNG, SHA-256, `prompt_id`, ComfyUI file and subfolder, timings, `graph_sha256` |
| `ImageClient` | `queue()` | `... -- python3 -c <comfyui_queue.py>` | none | 45 s | `QueueState(running, pending)`; submits nothing |
| `ImageClient` | `in_flight()`, `clear_in_flight()` | none (process state) | none | none | `InFlight(prompt_id, code)` or `None`; see below |
| `LedgerReader` (`wan_ledger`) | `get(ledger_id)` | `kubectl exec -i -n ai deploy/wan-video -c api -- python3 -c <wan_ledger_read.py> <id>` | none | 30 s | `LedgerRecord`, checked like `poc/deliver.py` `check_ledger`, plus every asset path under `/workspace/output/productions/` with no `..` segment |
| `LedgerReader` | `list()`, `find(sha256)` | `... -- python3 -c <wan_ledger_list.py>` | none | 60 s | `LedgerListing` of `edited_production` summaries; ledger files that are unparseable, symlinked, not regular files or resolve outside `/workspace/jobs`, and malformed entries, are listed in `unreadable` by file name, never fatal |
| `LedgerReader` | `fetch_asset(ledger_id, sha256)` | `... -- python3 -c <wan_ledger_fetch.py> <id> <sha256>` | none | 180 s, 64 MiB | `AssetBytes`; ledger and asset opened with `O_NOFOLLOW`, asset a regular file with one link, hash checked in the pod and again here |

ComfyUI is shared with Home Assistant and Open WebUI. The prompt snippet waits until
the queue is empty before submitting and never cancels anyone's work, and `render`
refuses a second concurrent call in the same process (`adapter.busy`). Across
processes this is best effort, as in the PoC: checking for an idle queue and submitting
are two steps, so two clients that check at the same moment can both submit.

**A prompt in flight after a failure.** The snippet prints `PROMPT_ID <id>` to stderr
as soon as ComfyUI accepts the prompt. When a render fails, the `ImageError` carries
`prompt_id` if that line was printed: read `/history/<prompt_id>`, do not resubmit.
After a timeout the line is found in the runner's whole redacted stderr
(`redacted_stderr`), however much stderr follows it, not only in the 300-character
`detail`. The process also remembers that a prompt may still be running, as `ImageClient.in_flight()`
(shared by every `ImageClient` in the process, like the render lock). That happens after
a timeout, after a non-zero exit (unless the snippet printed no `PROMPT_ID` and said it
was not submitting because the queue stayed busy), and after an unexpected runner
error. It does not happen when the command could not start, or when the snippet exited
0. While it is set, `render` first calls `queue()`. If ComfyUI reports nothing running
and nothing pending, `render` forgets it and submits. Otherwise `render` fails with
`adapter.busy`, naming the prompt ID when known and saying not to resubmit. If the
queue read fails, nothing is submitted and the state stays. A caller that knows the
prompt finished calls `ImageClient.clear_in_flight()`. Nothing in the package
interrupts, cancels or deletes work on ComfyUI.

The guard is in the client, not the pod. `comfyui_prompt.py` stays the PoC's snippet
byte for byte, and a lock inside the pod would not bind the household's other ComfyUI
clients anyway.

Known PoC behaviour, for the photo client story
([407](https://work.haynesnetwork.com/work_packages/407)) to change: an edit's source
image is uploaded (`/upload/image`, `overwrite=true`) before the snippet's queue wait,
so it reaches ComfyUI even when the snippet then gives up on a busy queue. The upload
is inside the PoC's snippet, so it stays. With the full SHA-256 in the name, an upload
can only overwrite an identical file.

The ledger reader is read-only by construction (contract section 8: product code never
writes the Wan volume): it has no write, publish, link, rename or delete method, and a
test holds its three snippets to an allowlist of read calls and imports, so any new
call fails until someone reviews it. `os.open` is allowed only with `O_RDONLY` and
`O_NOFOLLOW` (and `O_NONBLOCK`). `wan_ledger.ADAPTER` is `legacy_wan_ledger`, the
adapter name the contract gives legacy deliveries.

The two new ledger snippets follow no symlink at the file they read. A ledger file must
resolve under `/workspace/jobs` and be a regular file. It is opened with `O_NOFOLLOW`
and read from that descriptor. `list` reports any other file as unreadable, by file
name only, and `fetch_asset` refuses it. After the path checks, `fetch_asset` opens the
asset with `O_NOFOLLOW` (and `O_NONBLOCK`, so a FIFO cannot hang it). On that
descriptor it requires a regular file with exactly one link and at most 64 MiB, then
reads from the same descriptor and checks the SHA-256. So a symlink or hard link
swapped in after the path checks is refused, not read. `poc/deliver.py` leaves each
delivered asset with one link (it links a temp file into place, then removes the temp
name). One limit remains: a directory above the file swapped for a symlink between the
check and the open is not detected. That takes write access to the Wan volume, and the
bytes must still match the ledger's SHA-256. Tests run both snippets against a temporary
tree, with their `/workspace` roots rewritten.

## Errors

Every failure is an `AdapterError` with a `code`, the call's `label` and a short
message: `adapter.request_invalid` (names the field, before anything runs),
`adapter.pin_mismatch`, `adapter.command_failed` (non-zero exit), `adapter.not_found`
(an HTTP 404 inside the pod), `adapter.timeout`, `adapter.response_invalid`,
`adapter.busy`. The package never puts the request payload, the snippet, the full
command line or an environment value into an error, and the real runner drops the raw
`subprocess` exception (it is not kept as the error's cause or context). The only
service text in a message is `detail`: the last 300 characters of stderr after
redaction. The error also keeps `redacted_stderr`, the same redacted text uncut, for a
caller to search (the ComfyUI client finds `PROMPT_ID` there); it is never part of the
message. Redaction runs on the whole text before the cut, so a cut cannot expose part
of a value. It replaces with `<redacted>`:

- a PEM block, from its `-----BEGIN` line through its `-----END` line, or to the end of
  the text when the END line is missing;
- URL userinfo up to 1024 characters, including a password with spaces
  (`https://user:correct horse@host/...`); a plain `host:8080/path` is left alone;
- AWS access key IDs (`AKIA` or `ASIA` and 16 upper-case letters or digits), anywhere;
- `Bearer`, `Basic` and `token` credentials;
- the value of any key containing `token`, `password`, `secret`, `api_key`,
  `authorization`, `cookie` or `credential` (in `=`, `:`, JSON or Python-repr form): a
  quoted value through its closing quote, spaces included, and an unquoted value to the
  end of the line.

Every pattern stays linear on long input: each repeat is bounded or scans forward once
to its delimiter, and none nests an unbounded repeat (a test runs each on 64 KiB of
adversarial text; the earlier key pattern took 39 s on 4 KiB). The ported ComfyUI snippet prints ComfyUI's error
status on failure, and that status can quote a node's inputs, so `detail` and
`redacted_stderr` may hold part of an image prompt. Prompts are not secrets, but treat
both as service output. Changing the snippet would break byte parity with the PoC.

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
| `wan_ledger_list.py` | new: reads `/workspace/jobs/*.json` (the Wan API has no list route); a ledger must resolve there and be a regular file, opened with `O_NOFOLLOW` | `e068145dfcb8a1b13e525d613e335c8c478ebf04f090e6ede6e1f5d8c248f424` |
| `wan_ledger_fetch.py` | new: one ledger asset's bytes; ledger checked as in `list`, asset path checked, then on its `O_NOFOLLOW` descriptor a regular file with one link and at most 64 MiB, hash checked | `8aaa1c0f555bb907127863968db7087cf08d47aa94be760a2bf1464e4d9c4300` |
| `qwen_image_2_1_t2i_API.json` | `poc/graphs/qwen_image_2_1_t2i_API.json`, byte for byte | `f18a6e29a1f225467874d6c4d9fe16861982ad9ff6e274ca3d170245c43d226d` |
| `qwen_image_2_1_edit_API.json` | haynes-ops `kubernetes/main/apps/ai/stable-diffusion/comfyui/resources/api-workflows/qwen_image_2_1_edit_API.json` at `7c7b2cf6cceecc782cb149a958635852ae162966` (the commit `prompts.json` records; git blob `f520dcd4937c`, last changed in `31b449445dc1`, unchanged at haynes-ops `main` on 2026-11-13), copied once | `946f46812559426297191419e8e4ca614ac948698f8a5ae9d09cda6b0e2fdcb6` |

## Compatibility matrix

[`tests/adapters/test_compat.py`](../../tests/adapters/test_compat.py) reads the PoC
source with `ast` (never importing it) and the committed Winter Menu evidence.

| Call | Same as the PoC, shown by test | Recorded inputs | Differences |
|---|---|---|---|
| Kokoro `synthesize` | argument vector, 55 s timeout, the `input=` expression, snippet text | all 38 r1 to r4 takes: each request's stdin is the PoC's JSON; a fake WAV of the recorded byte size parses to the recorded `duration_s` | none |
| Whisper `transcribe` | argument vector, 55 s timeout, snippet text | each take's recorded `heard` parses back and gives the recorded `heard_matches`; each revision's film transcript parses | the PoC passes the open file as stdin, the package its bytes (same content) |
| ComfyUI text to image | argument vector, 3300 s timeout, payload statements, graph field edits, template bytes, snippet text | **all 14 recorded t2i renders rebuild to the exact `graph_sha256` in `prompts.json`** | the command is the PoC's; after a render that may have left a prompt in flight, the next `render` reads the queue first and refuses while it is busy (P-425-06) |
| ComfyUI edit | graph field edits, upload payload, template from the recorded haynes-ops commit | the three recorded edit graphs cannot be rebuilt: the PoC named each upload with 12 random hex digits | the upload name is `studio-<the PNG's full SHA-256>.png`, derived from the bytes (proposal P-425-03); the in-flight check as for text to image |
| ComfyUI `queue` | new | none | new call (P-425-02) |
| Wan ledger `get` | argument vector with the ledger ID, 30 s timeout, snippet text, required fields of `check_ledger` | the four committed `production.json` files parse as served answers, every asset path passing the new rule | the PoC inherited the caller's stdin; the package sends empty stdin. The package also refuses an asset path outside `/workspace/output/productions/` or with a `..` segment, which `check_ledger` did not check |
| Wan ledger `list`, `find`, `fetch_asset` | new | `find` matches the set still across all four ledgers; the `list` snippet, run on a temporary tree holding the four ledgers, answers as `FakeWanLedger` does | new calls (P-425-04) |

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
- **P-425-03** Edit uploads take a content-derived name, `studio-<the PNG's full
  SHA-256>.png` (64 hex digits), so an edit graph and its hash can be rebuilt. The
  request derives it from its own bytes and takes no name from the caller: ComfyUI's
  upload overwrites by name (as in the PoC), so a name can only ever replace identical
  bytes.
- **P-425-04** The ledger reader adds `list`, `find` and `fetch_asset`. The Wan API has
  no list route, so `list` reads the ledger files directly, following no symlink;
  `fetch_asset` serves only a regular, singly linked file that a ledger lists, under
  `/workspace/output/productions/`, at most 64 MiB, opened without following a
  symlink, with its hash checked in the pod and again by the client. It is the route for
  recovering delivered inputs in story 428.
- **P-425-05** Failure text: stderr is kept as a 300-character, redacted tail in the
  message, and whole but redacted in `redacted_stderr` for searching; the package never
  adds payloads, snippets or full command lines to an error.
- **P-425-06** `ImageClient.render` allows one call at a time per process
  (`adapter.busy`) on top of the snippet's queue wait, and none while a failed render
  may have left a prompt in flight, until ComfyUI's queue is empty or the caller clears
  it.
