# Legacy service adapters

Story [425](https://work.haynesnetwork.com/work_packages/425) (E1.11), epic
[372](https://work.haynesnetwork.com/work_packages/372). The package
`haynes_studio.adapters` ([source](../../src/haynes_studio/adapters/)) holds clients
for the in-cluster services the PoC used, ported from `poc/studio.py`, `poc/speech.py`,
`poc/comfy.py` and `poc/deliver.py`. Routes and service facts are in
[services.md](services.md).

**State: source and tested with fakes only.** No client has been run against a live
service. The Wan clip clients (image-to-video and speech-to-video, story
[842](https://work.haynesnetwork.com/work_packages/842)) are described in
[their own section](#wan-clip-clients-story-842); stories
[426](https://work.haynesnetwork.com/work_packages/426) and
[427](https://work.haynesnetwork.com/work_packages/427) own the clip-source interfaces
they plug into. Foley has no client.

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
`adapter.busy`, and for the Wan clip clients `adapter.job_failed` (the Wan job ended
other than `succeeded`), `adapter.competing_work` (foreign engine work seen) and
`adapter.journal_failed` (the Wan journal could not be read exactly or written). The package never puts the request payload, the snippet, the full
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
| `wan_probe.py` | `poc/wan.py` `PROBE`, byte for byte: `/health`, `api.gpu_sample()`, the engine's `/queue` | `cd73ebd733c48c1a40222fc7a1a39ad9788db09b2b145837c5db5839c0eb6716` |
| `wan_upload.py` | `poc/wan.py` `UPLOAD`, byte for byte: create-only under `/workspace/input/studio-e0/`, hash checked | `636cb89c132f83ec40426e971df9ba48ddcb466fe16f78a3c896baa7052748a9` |
| `wan_run.py` | `poc/wan.py` `RUN`, byte for byte (from OP342): admission readback, read-only engine retries, the unknown-work observer, then `api.generate()` | `b44fcef47d1b125c0f061fd6f4f6d69357969a34f298549e85d44645b90836ce` |
| `wan_clip_fetch.py` | `poc/wan.py` `fetch`, with the job ID as an argument and a `CLIP_SHA256 <hash> <bytes>` line on stderr; a read redirected to any other URL (`geturl()`) exits non-zero having written nothing to stdout | `3db29f979cb996dfe351f0e5c040f193670a65f292c926a49272110b4f1d5c56` |
| `wan_ti2v_workflow.json` | haynes-ops `kubernetes/main/apps/ai/wan-video/app/workflow.json` at `3a3571c4016a57465b5e995077bb691037224705` (git blob `5f9e9f968176`, its only commit; unchanged at haynes-ops `main` `bab21e14` on 2026-11-13), copied once; the `template_sha256` of all nine E0 layer records | `88fe79ad543a93febd6f72e0dc86eecdb27b70c73e54d4553917f72cb95a136b` |

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

## Wan clip clients (story 842)

Story [842](https://work.haynesnetwork.com/work_packages/842) (E1.18). Module
[`wan.py`](../../src/haynes_studio/adapters/wan.py): `WanClipClient` makes image-to-video
clips (Wan2.2 TI2V-5B) and speech-to-video clips (Wan2.2 S2V-14B, lightning profile) on
the studio's two RTX 3090s, through the sanctioned E0 route of `poc/wan.py` and
`poc/s2v.py`. Inside the Wan API container the pinned `wan_run.py` imports the
installed `api` module and runs its own `generate()` with the client's graph, so the
job holds the API's compute lease (`/workspace/compute.lock`, shared with the HTTP API
and the Foley sidecar), its watchdog, ledger and telemetry. Nothing is deployed or
changed. **Source and tested with fakes only**: story
[428](https://work.haynesnetwork.com/work_packages/428) makes the first live call.

```python
from haynes_studio.adapters.runner import SubprocessRunner
from haynes_studio.adapters.wan import FileJournal, ImageToVideo, SpeechToVideo, WanClipClient

client = WanClipClient(SubprocessRunner(), journal=FileJournal(run_dir / "wan-journal.jsonl"))
# tests: WanClipClient(FakeRunner(FakeWan()), journal=MemoryJournal())
clip = client.render(ImageToVideo(image_png=png, prompt=text, seed=101, story=STORY_URL))
talk = client.render(SpeechToVideo(image_png=png, drive_wav=drive, board_frames=94,
                                   prompt=text, seed=501, story=STORY_URL))
clip.data, clip.record  # the MP4 bytes and its provenance record
```

| Request | Fields (defaults) | What is sent |
|---|---|---|
| `ImageToVideo` | `image_png`, `prompt`, `seed`, `story`, `width` 576, `height` 1024, `length` 121, `negative` (the PoC's) | the deployed template with `poc/wan.py`'s edits, 20 steps, 24 fps; preset `studio-e0-i2v-<w>x<h>-<length>f` |
| `SpeechToVideo` | `image_png`, `drive_wav`, `board_frames`, `prompt`, `seed`, `story`, `width` 576, `height` 1024, `negative` | `poc/s2v.py graph(..., lightning=True)`: the 4-step LoRA at cfg 1 on one GPU, 16 fps; `length` from TIME-9, Extend chunks of 77 frames seeded `seed + k`; preset `studio-e0-s2v-lightning-<w>x<h>-<length>f` |

`story` is a full `https://work.haynesnetwork.com/work_packages/<id>` URL; the Wan
ledger records the job under it (the PoC hard-coded 387 and 394). A speech-to-video
request needs a drive track of `board_frames / 24` seconds to one sample (TIME-9).

### Guards, in order

Each guard stops before anything is submitted unless the row says otherwise. Tests
are in [`test_wan_clips.py`](../../tests/adapters/test_wan_clips.py) unless a file is
named. A mutation run removed each client-side guard in turn (42 mutations), and a
named test failed every time (story 842's PR). The fixes for the three cross-family
reviews of that PR (findings 1 to 7 of the first, R2-1 to R2-9 of the second, R3-1 of
the third, marked below) were checked the same way: 83 mutations of the new and
changed guards, the fetch snippet's redirect check among them, each failing a named
test. The other
in-pod guards are the PoC's snippets byte for byte
([`test_wan_compat.py`](../../tests/adapters/test_wan_compat.py)), and the fake pod runs
them.

| # | Guard | PoC line | Client | Test |
|---|---|---|---|---|
| 1 | Template and snippets pinned, checked before any command; the template's edited nodes have their classes | `poc/wan.py` 107-111 (the PoC checked after uploading, from a mutable checkout) | `_check_pins`, `i2v_graph` | `test_g10_a_changed_template_or_snippet_is_refused_before_anything_runs` |
| 2 | The client needs a journal and loads it when made. Each `render` and `recover` holds it for its whole length by a lock on its `.lock` sibling (a second process on the path, or a second `FileJournal` on it, is `adapter.busy` before anything runs, whether or not the journal file still exists) and reads it once; while held it is read and appended only through one descriptor, and before each read, append and each step that sends a command both paths must still name the held files, else `adapter.journal_failed` and nothing more is sent, the job staying unsettled in memory; a journal missing beside its lock file (removed between runs) is `adapter.journal_failed`, one missing with no lock file a first use: a job or halt an earlier process left there blocks this one as its own; what memory holds from that journal follows it (another process may have settled it); a held job or halt the journal no longer names (the file was replaced or cut), a journal that is not read exactly (a malformed or incomplete line, two unsettled jobs, a settle or clear of something not set) or cannot be read is `adapter.journal_failed`; a journal job other than the one the process holds is `adapter.busy` | new (findings 6, R2-2, R3-1) | `__init__`, `_exclusive`, `_adopt`, `render`, `Journal.read_state`, `FileJournal.hold`, `FileJournal.check`, `MemoryJournal` | `test_g17_*` (a real second process after the journal is unlinked, renamed or replaced, and after the lock file is removed), `test_g12_*`, `test_g13_a_journal_another_holder_has_is_refused_before_anything_runs`, `test_g13_a_second_process_on_the_file_journal_is_refused`, `test_g13_one_read_of_the_journal_per_call`, `test_g13_a_job_another_process_settled_is_dropped_not_settled_twice`, `test_g13_a_journal_that_no_longer_names_what_the_process_holds_is_refused` |
| 3 | `clear_in_flight()` and `clear_halt()` take the one-job lock without waiting: while a `render` or `recover` runs in this process (another thread, or the runner itself) they are `adapter.busy` and change nothing. They hold the journal too, and write nothing for what another process already settled or cleared | new (R2-1) | `clear_in_flight`, `clear_halt`, `_process_lock` | `test_g13_the_clears_refuse_while_a_render_runs_in_another_thread`, `test_g13_the_clears_refuse_when_called_from_inside_the_run`, `test_g13_a_clear_after_another_process_settled_the_job_writes_nothing`, `test_g13_a_clear_halt_after_another_process_cleared_it_writes_nothing` |
| 4 | One job per process (`adapter.busy`) | new (the `ImageClient` rule; the PoC ran one job per script) | `render`: `WanClipClient._lock` | `test_g1_one_job_per_process` |
| 5 | Nothing after foreign engine work was seen, by this process or a later one on the same journal, until `clear_halt()` (`adapter.competing_work`) | `poc/wan.py` 146-147, `poc/s2v.py` 137-138 (the script stops) | `_check_halt`, `_latch_halt` | `test_g5_foreign_work_keeps_the_output_and_stops_further_submissions`, `test_g12_the_halt_outlives_the_process` |
| 6 | Nothing while an earlier job may be running: only its ledger reading `failed` settles it (row 7 when its prompt was accepted); `succeeded` makes it uncollected (row 8); a missing ledger or a failed read keeps it, until `clear_in_flight()` | new (scope c; services.md: read the job before resubmitting) | `_settle_in_flight` | `test_g7_*` |
| 7 | A failed job whose prompt was accepted (its answer or ledger has a `prompt_id`) keeps blocking until a probe shows both engine queue lists present and empty, then settles `failed`; a probe that fails or shows work is `adapter.busy`. One with no `prompt_id` (a busy lease, or a refusal before `/prompt`) settles at once | new (R2-4) | `render`, `_settle_in_flight`, `_engine_idle`, `recover` | `test_g14_*`, `test_g9_a_failed_job_is_an_error`, `test_g11_recover_reports_a_failed_job_as_failed` |
| 8 | Nothing while a succeeded job's clip is uncollected (a lost answer, fetch or clip check): refused at once, naming the job and `recover(request, job_id)`, until `recover` fetches and checks the clip or a person calls `clear_in_flight()` | new (finding 2) | `_settle_in_flight`, `_mark_uncollected`, `render`, `recover` | `test_g7_a_lost_fetch_keeps_the_job_uncollected_and_blocks_the_next_render`, `test_g7_a_lost_answer_whose_ledger_reads_succeeded_waits_for_recover`, `test_g7_a_clip_that_fails_its_checks_stays_uncollected_until_a_person_clears_it`, `test_g11_a_recover_whose_fetch_fails_leaves_the_job_uncollected` |
| 9 | A probe answer without `accepting_jobs` or the `active_job` key, without both queue lists (null, missing, another type, an error body), or whose GPUs are not exactly the two approved ones (`pinned.WAN_GPU_UUIDS`, haynes-ops `api.py` `EXPECTED`; the count is the constant 2) is `adapter.response_invalid`, never idle | new (findings 4 and 7, R2-5, R2-6: the PoC read a missing list as empty and passed any GPU) | `probe` | `test_g2_a_queue_answer_without_both_lists_is_an_error_never_idle`, `test_g2_a_health_answer_without_accepting_jobs_or_active_job_is_an_error`, `test_g2_a_sample_with_other_than_two_gpus_is_an_error`, `test_g2_a_sample_whose_gpus_are_not_the_two_approved_ones_is_an_error`, `test_g2_the_gpu_count_is_not_configurable` |
| 10 | API busy or holding: refuse at once | `poc/wan.py` 82-83 | `wait_cool` | `test_g2_a_busy_or_holding_api_is_refused_at_once` |
| 11 | Any engine work queued or running: refuse, preserve it | 84-85 | `wait_cool` | `test_g2_queued_unknown_work_is_refused_and_preserved` |
| 12 | Wait (reading only) until every GPU is under 62 C and at most 5 % busy, a probe every 10 s; a sample with no GPU is an error | 86-88, 91 | `wait_cool`, `probe`, `Probe.cool` | `test_g2_hot_gpus_are_waited_for_reading_only`, `test_g2_an_unreadable_probe_is_an_error_not_a_pass` |
| 13 | Not cool after 1800 s: refuse | 77, 89-90 | `wait_cool` | `test_g2_gpus_that_never_cool_stop_before_submission` |
| 14 | Inputs created once under `studio-e0/<16 hex>`; another file of that name is refused, never overwritten; the read-back hash must match | 29-37, 102-106; `poc/s2v.py` 21-26 | `upload`, `wan_upload.py` | `test_g8_*` |
| 15 | Cool idle again right before the run (rows 9 to 13): at once when still cool, else the same wait or refusal; the record's `cooldown_s` and `start_temps` are this probe's, `cool_before_upload` the first's | new (finding 3) | `render`, `wait_cool` | `test_g2_cool_idle_is_checked_again_right_before_the_run`, `test_g2_work_a_hold_or_heat_that_starts_during_the_uploads_stops_before_the_run` |
| 16 | The job is journalled as in flight before the first probe (a journal that cannot be held or written runs nothing, not even a probe). Only what certainly submitted nothing settles it `no_submission`: a refusal or failure before the run (either cool check, an upload), a run that never started, the admission readback's refusal. Otherwise only row 6, 7 or 8 settles it | new (scope c; finding 6, R2-2) | `render`, `_remember`, `_submit` | `test_g13_the_journal_is_held_and_the_job_on_record_from_the_first_probe`, `test_g13_a_failure_before_the_run_settles_the_job_as_no_submission`, `test_g12_the_job_is_journalled_before_the_run_starts`, `test_g12_a_journal_that_cannot_be_written_runs_nothing`, `test_g7_*`, `test_g3_*` |
| 17 | Admission readback of `/health` just before submission; its refusal submits nothing (`adapter.busy`) | `RUN` 43-46 | `wan_run.py`; `_submit` | `test_g3_*` |
| 18 | The API's compute lease: busy is a failed job, never a wait (`adapter.busy`) | haynes-ops `api.py` `generate` 154-157 | `wan_run.py`; `render` | `test_g4_a_busy_lease_is_a_refusal_never_a_wait` |
| 19 | The API's own GPU and queue checks before it submits | `api.py` 158-163 | `wan_run.py` | `test_g4_gpus_busy_at_generate_*`, `test_g4_work_queued_after_the_probe_*` |
| 20 | A slow engine read is retried (6 tries, 5 s apart) and counted; a write never | `RUN` 47-55 | `wan_run.py` | `test_g6_*` |
| 21 | Foreign prompt IDs seen during the job are recorded | `RUN` 56-61 | `wan_run.py` | `test_g5_*` |
| 22 | A lost answer, timeout or non-zero exit leaves the job in flight; never resubmitted | new (scope c) | `_submit` | `test_g7_a_lost_answer_is_never_followed_by_a_resubmission` |
| 23 | Foreign work latches the halt (journalled) before the job is settled, whatever happens next | 146-147 | `render`, `_settle_in_flight`, `recover` | `test_g5_*`, `test_g7_a_settled_job_that_saw_foreign_work_halts` |
| 24 | A job that did not succeed is an error (`adapter.job_failed`); the ledger's `error` text is redacted, as stderr is, before it reaches any message | 125-126; `poc/s2v.py` 115-116; redaction new (R2-8) | `render`, `recover` | `test_g9_a_failed_job_is_an_error`, `test_g15_*` |
| 25 | The clip is fetched read-only, its bytes equal to the pod's own hash and size and to the ledger's size; a read redirected to any other URL is refused in the pod, with nothing written to stdout | 127-128 (the hash and the redirect check are new; R2-9) | `_fetch`, `wan_clip_fetch.py` | `test_g9_a_clip_cut_in_transfer_is_an_error`, `test_g9_a_clip_of_another_size_than_the_ledger_is_an_error`, `test_g16_a_redirected_clip_read_is_refused_and_writes_nothing` |
| 26 | The clip decodes, with exactly the frames (image-to-video `length`; speech-to-video `s2v_frames_delivered` for its chunks, as every E0 clip), the size and the measured rate (24 fps; 16 fps) its graph makes; anything else is an error, never a clip, and the job stays uncollected | 131-136 (decode); the rest new (TIME-8; finding 5) | `_check_clip` | `test_g9_a_corrupt_clip_is_an_error`, `test_g9_a_short_*`, `test_g9_a_clip_of_another_size_is_an_error`, `test_g9_a_clip_with_other_frames_than_its_graph_makes_is_an_error`, `test_g9_a_clip_at_another_rate_is_an_error`, `test_g9_a_clip_with_no_measured_rate_is_an_error` |
| 27 | Foreign work during a job: the clip is checked and kept on the error | 146-147 | `render` | `test_g5_foreign_work_keeps_the_output_and_stops_further_submissions` |
| 28 | A finished job whose answer, fetch or clip check failed is collected, read-only, with `recover(request, job_id)`, never rendered again. The ledger's `graph_sha256` must equal the graph rebuilt for `request` and `job_id` (it holds the prompt, negative, seed, size, length, input names and output prefix), and its `story`, preset, seed and inputs must match; a ledger without `graph_sha256` (every E0 job) is refused | new (finding 1) | `recover`, `job` | `test_g11_*` |
| 29 | No snippet deletes, moves, interrupts or overwrites; the only open is `'xb'` | snippet text | pins | `test_no_snippet_deletes_moves_interrupts_or_overwrites` |

`api.generate()` is the installed code the PoC ran; when its own job fails after
submission it removes or interrupts *its own* prompt (`api.py` 211-223). That is the
API's behaviour, kept; the client itself never cancels or interrupts anything.

**What `/health` does not see.** Its `active_job` names only a job started through the
API's own HTTP route (`POST /videos` sets it in the server process). A job this route
starts runs `api.generate()` in its own snippet process, so `active_job` stays `null`
while it runs, and rows 10 and 17 refuse only HTTP-route jobs and holds. What protects
this route's jobs is the engine queue check (rows 11 and 19: the job's prompt is on
ComfyUI's queue while it runs), the API's compute lease taken inside `generate()` (row
18), and the journal (rows 2, 6, 7, 8 and 16). One window stays: GPUs that heat between
row 15's probe and the admission readback are caught only by `generate()`'s own check,
which reads utilization and memory, not temperature. Closing it would change
`wan_run.py`, which stays the PoC's byte for byte. Story 428 treats a hot card at 0 %
inside `generate()` as outside this client's hands.

**What the API's queue check misses.** `generate()` checks the engine queue by
truthiness, so an answer with null lists reads as idle and it submits; its observer and
its cleanup then fail on the same nulls, the job is saved `failed`, and its prompt can
be left on the engine. The client cannot change that check (it is `wan_run.py` and the
installed `api.py`); it keeps such a job blocking until a probe shows the queue empty
(row 7). The durable fix is in haynes-ops: the API should refuse a queue answer that is
not two lists.

**Redirects.** `wan_clip_fetch.py` is this story's own snippet and refuses a redirected
read (row 25). `wan_ledger_read.py`, which `recover` and the in-flight check use, still
follows one; it is story 425's snippet, kept byte for byte, and the same fix belongs
there.

### The journal

`WanClipClient(runner, journal=...)` requires a `Journal`. `FileJournal(path)` is the
one for real runs: an append-only JSON-lines file, one line per event, each written with
one `os.write` to a descriptor opened `O_APPEND`, then `fsync` (and the directory's
`fsync` when the file is created). It is never rewritten, truncated or deleted; a
missing file is an empty journal. `MemoryJournal()` keeps the same lines in memory, for
tests, and models the same hold.

**One process at a time.** Every `render` and `recover` holds the journal for its
whole length, and the clears hold it while they write. The lock is a sibling file,
`<journal>.lock`, created if missing and never written, replaced or deleted by the
client: `FileJournal` takes an exclusive `flock` on it without waiting
(`LOCK_EX | LOCK_NB`), after the process's one-job lock, and releases it when the call
returns. A second process on the same path is refused with `adapter.busy`, naming the
journal, before it probes, uploads or submits, whether or not the journal file itself
still exists. `flock` needs a local file system: keep the journal on one (not NFS).

While it holds the lock, a `FileJournal` reads and appends only through one descriptor
on the journal file. Before each read, each append, and each step of a `render` that
sends a command (the uploads, the second probe, the run), the journal's path and the
lock file's path must still name the files the call holds (`os.stat` against
`os.fstat`: same device and inode). A journal or lock file removed, renamed or replaced
while in use is `adapter.journal_failed`: nothing more is probed, uploaded or submitted,
the job stays unsettled in this process, and none of its later lines land in another
file at that path. Each call reads the journal once, so the job and the halt it sees
come from the same read; what this process holds from that journal follows it, since
another process may have settled or cleared it in between. An append outside a call
holds the journal for that one append.

| Event | Written | Keys besides `v`, `event`, `at` |
|---|---|---|
| `remember` | before the first probe (`state` `in_flight`), and when its ledger reads `succeeded` (`uncollected`) | `job_id`, `state`, `graph_sha256` |
| `settle` | when the job stops blocking: `collected` (a clip fetched and checked), `failed` (its ledger, and if its prompt was accepted a probe showing the queue empty), `no_submission` (a refusal or failure before the run, a run that never started, or the admission readback refused), `cleared` (`clear_in_flight()`) | `job_id`, `outcome` |
| `halt` | foreign engine work seen | `job_id`, `unexpected_work_seen` |
| `clear_halt` | `clear_halt()` | `job_id` |

`journal.read_state()` replays the lines in one read: the job that blocks
(`InFlightJob`: ID, code `journal`, state, `graph_sha256`), the halt, and every job ID
the lines name; `load()` and `load_halt()` return the first two. A new client loads the
journal when it is made, so a new process behaves as the one that submitted. The memory
and the journal change together: remembering a job writes the journal first (a job
whose line could not be written never runs); a state change, settle or halt keeps the
job or sets the halt in memory if its write fails.

A journal that does not read exactly, or no longer names a job or halt this process
holds, submits nothing. A person must inspect the journal and the Wan service (its
engine queue and the ledger of every job the journal names). Replacing the file
discards the only record of a job the engine queue may not show yet.

**Known limit: one journal per store.** The client sees only the journal it was given.
Another `WanClipClient` given another path does not see this one's job, and only the
engine queue and the API's lease stand between them.

**A missing journal.** A journal file that is missing when a call starts is an empty
journal only on first use, with no lock file beside it (the first hold creates both).
A missing journal beside its lock file was removed between runs: that is
`adapter.journal_failed`, when the client is made and when a call holds it. A person
checks the Wan service (its engine queue and ledgers) and may then delete the lock file
as well, to start afresh. Moving the journal or its lock while a call holds them is
refused as above. So every run against a store uses one journal path under its store
root, the same path every time (story
[406](https://work.haynesnetwork.com/work_packages/406) sets that path); a lease shared
by every agent session is dev-env work
([839](https://work.haynesnetwork.com/work_packages/839)).

### The provenance record

`WanClip.record` is plain JSON: `kind`, `engine` (`wan-api/ti2v-5b` or
`wan-api/s2v-14b-lightning`), `job_id`, `prompt_id`, `preset`, `story`,
`graph_sha256` (SHA-256 of `json.dumps(graph, sort_keys=True)`), `template_sha256`
(image-to-video), `run_snippet_sha256`, `model_files_sha256` (the graph's model files
with the [licence register](model-licences.json)'s SHA-256; not re-hashed on the
volume), `seed`, `width`, `height`, `fps` (as measured, which row 26 holds to the
graph's), `frames_requested`, `frames_delivered`,
`measured` (decoded size and rate), `inputs` (each upload's name, SHA-256 and size),
`prompt`, `negative`, `clip_sha256`, `clip_bytes`, `cooldown_s` and `start_temps` (each
GPU's temperature and utilization at the passing probe right before the run),
`cool_before_upload` (the first passing probe's `cooldown_s` and `start_temps`; `null`
for a recovered clip), `render_s`, `fetch_s`,
`wall_s`, the job's `created`, `started` and `finished` times, `admission_readback_at`,
`engine_read_retries`, `poll_misses`, `unexpected_work_seen`, `telemetry_tail` (last
three GPU samples), `peak_gpu_mib`, `recovered`, `at`; for speech-to-video also `method`, `chunks`,
`board_frames`, `frames_needed` (TIME-8), `drive_samples` and `drive_rate`. For the
clip-source interfaces of stories 426 and 427, `WanClip` exposes `engine`, `job_id`,
`files_sha256` and `start_image_sha256`.

### Differences from the PoC

- The job handed to `api.generate()` is the PoC's plus one key, `graph_sha256` (the
  SHA-256 of the graph sent with it). The PoC already stored fields of its own on the
  job (`reference_image`, `story`, `live_admission_readback`); the API saves the whole
  job, so the ledger keeps it. The compatibility tests hold the job to exactly the
  PoC's plus this key.
- After a lost answer or a failed fetch or clip check, `recover(request, job_id)`
  collects a finished job's clip read-only, once the ledger's `graph_sha256` and story
  match the request; the PoC stopped and a person fetched it.
- The client returns bytes; writing the clip create-only, its first and last frame
  PNGs and a records file is the caller's job (`render` in the PoC did it).
- The graph and the pins are checked before anything runs; the PoC read the template
  from a mutable haynes-ops checkout after uploading.
- The fetch snippet takes the job ID as an argument (the PoC built the code around
  it), refuses a redirected read, and states the SHA-256 and size it read; the client
  checks both and the ledger's `bytes`.
- A clip whose frame count, size or measured rate is not exactly what its graph makes,
  an undecodable clip and a cut transfer are errors (the PoC wrote whatever came).
- A probe whose GPUs are not exactly the two approved ones (none included: the PoC's
  `all()` passed it), without both queue lists, or without `accepting_jobs` or the
  `active_job` key is an error (the PoC read a missing list or key as idle and checked
  no GPU ID; `api.gpu_sample()` itself requires the two IDs).
- A failed job whose prompt the engine accepted keeps blocking until a probe shows the
  engine queue empty (the PoC stopped at any failure and a person looked).
- The ledger's `error` text is redacted before it reaches a message (the PoC printed
  the state only).
- Cool idle is probed twice, before the uploads and right before the run (the PoC
  probed once, before the uploads).
- Foreign work in a failed job latches the halt as well (the PoC stopped at the failure).
- The one-job lock is process state, as in `ImageClient`. The job that blocks (in
  flight, or succeeded with its clip uncollected) and the halt are process state written
  through to a journal file, so a later process inherits them, and the journal is held
  (`flock`) for each call, so a second process on it is refused; the job is on record
  from before the first probe. The clears refuse while a call runs. The PoC stopped its
  script instead.
- Probe, fetch and job reads send empty stdin (the PoC's `remote()` inherited it).
- `story` comes from the request; speech-to-video uses `board_frames` and TIME-9
  (`poc/s2v.py` with pad 0) instead of `--pad-s`; only the lightning profile is built
  (the one 20-step whole-frame clip, `s2-s2v-b`, is out of scope, contract section 5).

### Fake Wan pod

`FakeWan` (in `fakes`) runs the pinned snippets themselves. Each run gets a fresh
namespace (each `kubectl exec` is a new process) whose `sys`, `time`, `pathlib`,
`urllib.request` and `api` belong to the fake pod, and whose builtins have no `open`,
`exec`, `eval` or `compile`. Its `api.generate()` is a port of the installed one (the
lease, GPU and queue checks, one submission, the 12-miss and 90 s poll rules, and the
cleanup of its own prompt), on a pod clock where a timed-out engine read takes the API's
20 s. A small engine makes synthetic MP4s (speech-to-video delivers as many frames as
every E0 clip did, `s2v_frames_delivered`). It can be busy or holding, hold only at the
admission readback, hold the lease, run hot or busy GPUs, queue foreign work before or
during the job, time out reads or the `/prompt` write, fail, deliver short, odd-sized
or corrupt clips, lose the run's answer (timeout, empty, non-zero exit, never started),
encode a clip at another rate (`deliver_fps`), answer the run's own `/queue` reads with
null lists (`null_queue_in_run`), redirect the clip read (`redirect_fetch`, through a
response whose `geturl()` names another URL) and cut a fetch. The GPU sample uses the
approved IDs in `pinned.WAN_GPU_UUIDS`. It records every run
payload, graph submitted, engine call and volume write. Speech-to-video frame counts
come from `wan.s2v_frames_delivered`, the client's own exact rule, which the
compatibility tests hold to all 11 E0 speech clips.

### Before the first live job (story 428)

Run these read-only checks with the coordinator watching, then one job:

0. Construct the client with `journal=FileJournal(<store root>/wan-journal.jsonl)` on a
   local file system, never `MemoryJournal`, and use that same path for every run of the
   store (the known limit beside P-842-08). If the journal is held by another process
   (`adapter.busy` naming it), find that process; never point a run at another file.
   Never delete, move or replace the journal or its `.lock` file while a build runs; a
   journal missing beside its lock file is a stop until a person has checked the
   service.
1. `git -C ~/repos/haynes-ops fetch` and check that
   `kubernetes/main/apps/ai/wan-video/app/workflow.json` still hashes to
   `88fe79ad...136b` and that `api.py` still has `acquire_compute`, `gpu_sample`,
   `engine`, `save` and `generate(job, prompt, lease=None)` with the checks in rows 18
   and 19, that `save` still writes the whole job and `GET /videos/<id>` still returns it
   (row 28 needs `graph_sha256` back), that `/health`'s `active_job` is still set only
   by `POST /videos`, and that `EXPECTED` is still the two IDs in
   `pinned.WAN_GPU_UUIDS` (last changed in `429473c8`, 2026-11-04). A change there is a
   stop. If the API's queue check now refuses non-list answers, note it: row 7 can then
   be revisited.
2. `kubectl -n ai get deploy wan-video` is ready with containers `api`, `app`, `foley`,
   and `/config/video/api.py` in the `api` container is the haynes-ops file.
3. One `client.probe()`: it passes only with `accepting_jobs` and the `active_job` key,
   both queue lists and exactly the two approved GPUs; check by eye that
   `accepting_jobs` is true, no active job, the queue empty, and temperatures and
   utilization read sensibly.
4. Free space on PVC `ai/wan-video` (80 Gi, no retention) for the inputs and clips.
5. `WanClipClient.in_flight()` and `halted()` are `None` once the client is made (it
   loads the journal).
6. Run one `ImageToVideo` at 576x1024 and 121 frames, watching the GPUs during the job:
   a card that heats while 0 % busy inside `generate()` is outside this client's hands
   (it checks temperature only in its own probes). Check the record (121 frames
   delivered, 576x1024, `fps` 24 as measured, `cool_before_upload`,
   `engine_read_retries`, no `unexpected_work_seen`), then read `/videos/<job_id>` and
   confirm the ledger shows `succeeded` with the same `bytes` and `graph_sha256`, and the
   journal ends with that job's `settle collected` line.
7. Only then one `SpeechToVideo`, on a board of at most one chunk first.

If any call fails, stop and read the journal before anything else (the file, or
`FileJournal(path).read_state()`), then `/videos/<job_id>` for the job it names and the
engine queue; a finished job's clip is collected with `recover(request, job_id)`; a
failed job whose prompt was accepted clears itself once a probe shows the queue empty;
never resubmit to recover, never call a clear while another call runs (it refuses), and
never start a new journal file to get past a blocked one: replacing it discards the only
record of a job the queue may not show yet.

### Proposals (story 842)

- **P-842-01** Request limits: sides multiples of 32 from 64 to 1280; image-to-video
  `length` 4k + 1 up to 121 (what E0 ran); speech-to-video at most 3 chunks (boards up
  to 342 frames; the longest E0 job took 716 s of the API's 1200 s); prompts up to 4096
  characters and seeds up to 2^53 - 1 (the API's own limits on `POST /videos`); inputs
  under 20 000 000 bytes (the upload snippet's assertion).
- **P-842-02** A job that blocks is settled only by its ledger reading `failed` (and,
  if its prompt was accepted, a probe showing the engine queue empty), by its clip
  fetched and checked (`render` or `recover`), by a refusal or failure that certainly
  submitted nothing, or by `clear_in_flight()` after a person checks. A ledger reading `succeeded` is not collection. A missing ledger (the
  run may never have started) is not taken as proof and needs `clear_in_flight()` after
  a person checks the `api` container.
- **P-842-03** Foreign work latches a per-process halt that only `clear_halt()` lifts.
- **P-842-04** The fetch states the SHA-256 and size it read, and the client checks
  them and the ledger's size.
- **P-842-05** A clip whose frame count is not exactly what its graph makes
  (image-to-video `length`, as every E0 clip; speech-to-video `s2v_frames_delivered`,
  as every E0 clip, whose extra frames TIME-8 trims later), of another size, or at
  another measured rate is an error. The measured rate of a live Wan clip is not in the
  E0 evidence; story 428's first clip shows it.
- **P-842-06** The upload folder and presets keep the PoC's `studio-e0` names, so the
  jobs match E0's byte for byte; renaming them is a separate change.
- **P-842-07** `recover(request, job_id)` collects a finished job's clip after a lost
  answer or a failed fetch or clip check, read-only, once the ledger matches the
  request (`graph_sha256`, story, preset, seed, input names and hashes); its record says
  `recovered: true`. E0 jobs, whose ledgers have no `graph_sha256`, are imported another
  way.
- **P-842-08** The journal is a JSON-lines file on a local file system, one path per
  store, held with `flock` on its `.lock` sibling by one process at a time for each call,
  read and appended through the held descriptor while the paths still name it; a journal that does
  not read exactly is a stop for a person, never skipped. Known limit: a client given
  another path does not see it (see the journal section); story 406 fixes the path, and
  a cross-agent lease is dev-env work
  ([839](https://work.haynesnetwork.com/work_packages/839)).
- **P-842-09** A failed job whose prompt was accepted settles only after a probe shows
  both engine queue lists present and empty, because the API's own queue check reads null
  lists as idle; the durable fix (refuse a queue answer that is not two lists) belongs in
  haynes-ops `api.py`.
