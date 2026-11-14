# The Winter Menu: the first live E1 build (story 428)

Story [428](https://work.haynesnetwork.com/work_packages/428) (E1.14), epic
[372](https://work.haynesnetwork.com/work_packages/372). The first build of The Winter Menu
by the studio's own code (`studio legacy import`, the private input import, `studio voice`,
`studio build`), privately, from the command line, on the two RTX 3090s, under Tom's
rulings of 2026-11-13 (D50, D52 to D56 in
[proposal 0003](../../../docs/proposals/0003-studio-plan.md); his words are in comment 7995
on [372](https://work.haynesnetwork.com/work_packages/372)).

- **Run:** 2026-11-14 from 01:33 UTC, by the dev-env agent session
  `haynes-studio-1114-013021` (Claude Code, `claude-opus-5-5`), a worker for the E1
  coordinator `haynes-studio-1113-064439`.
- **Checkout:** `main` at `ec8c3869e8e699b4f7cf58bb3d1485f4cdb4af5e`; Python 3.11 from
  `UV_PYTHON_DOWNLOADS=never uv sync --locked --python 3.11` (4 min 1 s on a fresh pod).
- **Job folder:** `~/studio-jobs/winter-menu-e1-20261114/` on the session volume (ext4,
  local), with the store root at `~/studio-jobs/winter-menu-e1-20261114/store` and its one
  journal at `store/wan-journal.jsonl`. Nothing under it is in git.
- **Operator:** every command records `--operator-iss https://agent-session.invalid/dev-env
  --operator-sub agent-session:haynes-studio-1114-013021`. The operator field names an
  agent session, not a person: the command line has no agent-session operator yet
  (observation O-428-1).
- **State:** in progress. **Tom's verdict: pending.**

Status markers: **Proven** (it produced its result, with the evidence named), **Expected**
(not run), **Changed** (it differed from the plan, and how).

## a. Read-only checks before anything — Proven

01:33 to 01:39 UTC.

| Check | Command | Result |
|---|---|---|
| haynes-ops at `main` | `git -C ~/repos/haynes-ops fetch origin main` | `bab21e1497c41be303e9b8cc4773f185176b6f84`, the commit the references name |
| Wan template | `git show origin/main:kubernetes/main/apps/ai/wan-video/app/workflow.json \| sha256sum` | `88fe79ad543a93febd6f72e0dc86eecdb27b70c73e54d4553917f72cb95a136b`, the pin |
| `api.py` | read at haynes-ops `main` (last changed `429473c8`, 2026-11-04) | `acquire_compute`, `gpu_sample`, `engine`, `save` (writes the whole job), `generate(job, prompt, lease=None)` with the lease, GPU and queue checks; `EXPECTED` is the two IDs of `pinned.WAN_GPU_UUIDS`; `ACTIVE` set only in `POST /videos`; `GET /videos/<id>` returns the job file; `/file` serves `/workspace/output/<output>`; ledgers at `/workspace/jobs/<id>.json` |
| Deployed files | `kubectl exec -n ai deploy/wan-video -c api -- sha256sum /config/video/api.py /config/video/workflow.json` | `1d6704a6...a4633` (the haynes-ops file) and `88fe79ad...136b` |
| Deployment | `kubectl -n ai get deploy wan-video` | 1/1 ready, containers `api`, `app`, `foley`; pod `wan-video-f67b97c8f-rx8q5` on `talosw01`, 0 restarts, 9 days; `kokoro`, `whisper`, `studio-render` 1/1 |
| Wan volume | `kubectl exec ... -c api -- df -h /workspace` | 79 G, 53 G used, **26 G free**; inodes 1 % |
| Session pod | `df -h ~`, `df -i ~` | 19 G free of 20 G; inodes 4 % |
| Journal | the store root did not exist | new: no journal, no lock file |
| Wan volume before the run | `kubectl exec ... -c api -- sh -c 'cd /workspace && find jobs output/productions -type f -print0 \| sort -z \| xargs -0 sha256sum'` | 482 files (78 ledgers, 404 production files): [`wan-volume-before.sha256.txt`](wan-volume-before.sha256.txt), compared again at the end |

## b. Private inputs — Proven

### The draft's import (first part of step d)

```sh
uv run studio legacy import titles/the-winter-menu/manifest-r4.json \
  --speech titles/the-winter-menu/evidence-r4/speech.json \
  --map docs/contracts/examples/valid/legacy-import-map.json \
  --operator-iss https://agent-session.invalid/dev-env \
  --operator-sub agent-session:haynes-studio-1114-013021 \
  --out ~/studio-jobs/winter-menu-e1-20261114/import
```

Story `sty_01M79V9FC00000000000000001`, production `prd_01M79V9FC00000000000000001`: 9
boards, 13 lines, 17 cues, 3 notes, 1 bed, 1087 frames (45.292 s); 24 IDs from the map, 45
minted. Every board is `layered`; boards 1 to 6, 8 and 9 are `s2v` (spoken), board 7 `i2v`
(silent). No board is whole-frame.

### The importer

```sh
uv run python -m haynes_studio.importer --story $J/import/story.json --map $J/import/legacy-import.json \
  --operator-iss ... --operator-sub ... --store $J/store --dry-run
uv run python -m haynes_studio.importer --story $J/import/story.json --map $J/import/legacy-import.json \
  --operator-iss ... --operator-sub ... --store $J/store --out $J/import-run1 \
  --authorized-by https://work.haynesnetwork.com/work_packages/428
```

- **Checklist step 2** (the code against haynes-ops `api.py`): `GET /videos/<id>/file`
  serves `/workspace/output/<output>` (`output_file`), and a ledger is
  `/workspace/jobs/<id>.json` with `id`, `state` and `output`. As the snippets assume.
- **Dry run** ([`import-dry-run.txt`](import-dry-run.txt)): 156 rows, 101 hashes,
  `to_read 132, not_read 24`, at most 129 reads; nothing read or written. As the checklist
  expects.
- **Run, once** (01:40:07 to 01:40:30 UTC, 23.4 s; exit 0; `stopped: null`):
  [`import-report.json`](import-report.json). 156 rows: **132 verified, 24 absent, 0
  mismatch**. 101 hashes, 79 read from the Wan volume, 105 049 370 bytes read and
  published. Every hash was read from its first source; no refusal, no retry.

| Role | Verified | Absent | Mismatch | Why absent |
|---|---|---|---|---|
| still | 25 | 0 | 0 | |
| set | 4 | 0 | 0 | |
| sfx | 11 | 0 | 0 | |
| take | 38 | 0 | 0 | |
| keyframe | 9 | 0 | 0 | |
| doll_loop | 10 | 0 | 0 | |
| set_loop | 1 | 0 | 0 | |
| timed_clip | 11 | 0 | 0 | |
| start_image | 11 | 0 | 0 | |
| drive_track | 11 | 0 | 0 | |
| render | 1 | 7 | 0 | `not_read`: ComfyUI renders, out of the import's scope (the eighth is the set's bytes) |
| bed | 0 | 3 | 0 | `never_delivered`: the fire bed, as expected |
| not_motion | 0 | 14 | 0 | `not_read`: whole-frame E0 clips and the whole-frame S2V test, no source |

`lacks.story` is exactly one `asset.bytes_missing` at `/beds/0/asset_version_id` (the fire
bed `0b33af45929b8cfb...`, version `asv_01M7BVBVSBHA26B6V3F90A35MT`); `lacks.layered_loops`
is empty. The library file `import-run1/library.json` holds 46 versions (24 Winter Menu, 22
E0 motion). Store size after the import: 101 MB.

- **Changed:** the work order gave the text "story 428, Tom's rulings D50 and D55, E1
  coordinator haynes-studio-1113-064439" for `--authorized-by`; the importer accepts only
  a full work package URL, so the run records
  `https://work.haynesnetwork.com/work_packages/428`, and the text is here.

## c. The new fire bed (D54) — Proven (one job)

01:41:47 to 01:41:55 UTC. Before submitting, `list_generations` showed no running or queued
job. One `generate_sound` on the `audio` MCP server with what r4 records for the old bed
(`manifest-r4.json` `beds.fire.source`): the prompt "A small campfire crackling and popping
softly outdoors in a quiet forest, steady gentle crackle, no wind, no music, no voices",
seed 701, 12 s, 8 steps.

- Job `ebe4a478d4cf44e3974fea1da6a179cb`, Stable Audio 3 Small SFX (weights
  `da6edc54ddba10bfd79a077102ded687f80e882b`, CPU, LiteRT/XNNPACK, 4 threads), 8.1 s,
  completed. 44.1 kHz stereo 16-bit, 12.0 s, 2 116 844 bytes, SHA-256
  `0b33af45929b8cfb3859bf1511a2738eef22944d431ee44257c33a1de42da72a`.
- Downloaded with `curl -sf` from
  `http://audio-authoring.dev.svc.cluster.local:8000/artifacts/<job>/output.wav` into
  `$J/sfx/fire-ebe4a478-s701.wav`; `sha256sum -c` OK.
- **Finding:** the new bed is byte-identical to the r4 bed (`0b33af45...`, the hash
  `timeline.json` records). The sound model is deterministic for the same prompt, seed,
  steps and length. The audio service also still lists the original job
  `c81dc201bdb043c1ba19b719dc19d40a` with that hash; per D54 it was not fetched.
- **Imported as a new sound version** by [`tools/draft.py`](tools/draft.py), a one-off
  driver over the package's own `LocalStore.publish` and `library.import_version` (no
  package code changed): the blob published create-only at
  `productions/prd_01M79V9FC00000000000000001/sha256/0b/0b33af45...wav` with the job's hash
  as the expected hash; version `asv_01M7BVM62CM89SV5SD0YVZPSZ4` (created), a new asset
  under source key `audio-authoring:job:ebe4a478d4cf44e3974fea1da6a179cb`, origin
  `generated`, the generator's service, model, seed, prompt, job and params, the licence
  from the register (Stability AI Community License, `conditional`), created by the agent
  session (`agent_session` principal). The r4 bed's version
  `asv_01M7BVBVSBHA26B6V3F90A35MT` is unchanged and still names the same hash; because
  locators are content-addressed, the store now holds its bytes too, so it would resolve
  as well (observation O-428-2). Jobs used: 1 of 3.

## d. The draft — Proven

`tools/draft.py $J $J/draft` (01:44 UTC) wrote `draft/story.json` and
`draft/library.json` (47 versions) create-only, from the legacy import's story and the
private import's library:

- **Bed:** `/beds/0/asset_version_id` from `asv_01M7BVBVSBHA26B6V3F90A35MT` to the new
  `asv_01M7BVM62CM89SV5SD0YVZPSZ4`; level -40 dBFS RMS as r4.
- **Set loop:** `set.motion_asset_version_id` = `asv_01M7BVCF7QZG0E27A6CQZ458AA`, E0's
  promoted set loop (`legacy:winter-menu-video-e0:set-loop:set-plate.png`, the loop the
  layered films played). The import found no cast motion pin missing
  (`lacks.layered_loops` empty), so none was written.
- **Seeds:** `s2v:<slot>` on the 8 spoken boards, each E0's seed for that board and slot
  (`video-e0/clip-records-s2v.jsonl`): board 1 a 510; 2 b 501; 3 c 512; 4 a 513; 5 d 514;
  6 c 515; 8 a 516, b 517, c 518, d 519; 9 b 520. Board 7 is silent and layered I2V
  (its idle doll plays a loop; no `i2v:frame` seed is needed). **Why E0's seeds:** no
  server exists yet to assign them (E3), and with E0's seeds the new clips compare with
  E0's. They do not reuse E0's clips: E0's drive tracks in the store are 48 kHz and not
  exactly `F / 24` s (`8063d3e5...`: 188 002 samples at 48 kHz for a 94-frame board), and
  the build makes 24 kHz tracks of exactly `F / 24` s, so no drive track can match
  (Q-426-2 (a): a library timed clip is reused only for the board's own drive track).
- **Voices:** r4's cast voices (`bf_emma` A, `af_heart` B, `af_nicole` C, `af_bella` D).
  Story [840](https://work.haynesnetwork.com/work_packages/840) delivered the audition
  reels on 2026-11-13, but Tom has not named other voices there (his verdict is pending),
  so the r4 voices stand.
- **Toolchain** (`$J/toolchain.json`, SHA-256 `2096b232...11796`): `s2v_negative_prompt`
  is the client's `NEGATIVE` (E0's); `s2v_prompt` is E0's speech prompt with the per-doll
  description removed ("Stop-motion style toy video. The same plastic fashion doll, in the
  same blue YELLOWBIRDS team jacket ... Static locked-off camera, same framing."). Every
  other field is the default (E0's 576x1024 lightning profile). **Changed:** E0 sent one
  prompt per doll; the toolchain has one S2V prompt for every board (observation O-428-3).

## e. Voices — Proven (no speech request)

```sh
uv run studio voice --store $J/store --story $J/draft/story.json --library $J/draft/library.json \
  --operator-iss ... --operator-sub ... --out $J/voiced --json
```

01:44:36 UTC, 1.4 s, exit 0: `made` on all 8 spoken boards, `synthesized: []` on each.
Every take was held (the import verified all 38), so Kokoro was not called. Speech
requests: 0 of 60. New board voice versions: board 1 `asv_01M7BVMQADWKZKT5SNH52PABR8`, 2
`...MQC6C01AAGW4WJ80CSF8`, 3 `...MQEJVR7Y708JFBBJTQZ0`, 4 `...MQGHPV4QTS9YRSWG673F`, 5
`...MQM51C4MS5GYC55RX0DH`, 6 `...MQQ1PEXWKAWANYKRCVCS`, 8 `...MQXBFA4NM6KK5PDFPTHT`, 9
`...MR0JENY30SDM408W0KXG`.

## f. The pre-build check, offline — Proven

```sh
nice -n 10 uv run studio build --store $J/store --story $J/voiced/story.json \
  --library $J/voiced/library.json --operator-iss ... --operator-sub ... \
  --toolchain $J/toolchain.json --studio-commit ec8c3869e8e699b4f7cf58bb3d1485f4cdb4af5e \
  --offline --json
```

01:44:52 UTC, 1.5 s, exit 1, run `run_01M7BVN63V7700X92XR8GFVT4M` `failed` with
`build.offline_missing` at board 1, stage `s2v_clip`: the speech-to-video clip
`sha256:dfefe5c8...` (drive track `49231811f212...`, seed 510) is not in the cache. No
voice, photo, method, motion or adapter problem: the check stops only on the missing
clip, first time. `--studio-commit` names `main`'s commit, the package code every run
uses (this branch adds only records and the one-off driver).

## g. Gate before the first GPU job — Proven (the note sent; the answer below)

01:45 to 01:48 UTC.

- **Service dry run, whole story** ([`dry-run-service.txt`](dry-run-service.txt),
  [`dry-runs.json`](dry-runs.json)): `studio build ... --phase service --dry-run
  --wan-story https://work.haynesnetwork.com/work_packages/428`, run
  `run_01M7BVPSE1Q0QVG4FFMAMC0F9D` `cancelled` (1.8 s). The local pass, the check of every
  request and the mix passed (mix length, loudness, true peak, clipping: pass). **11 clip
  jobs**, all speech-to-video at 576x1024, in plan order: board 1 a (154 frames, 2 chunks,
  seed 510), 2 b (65, 1, 501), 3 c (154, 2, 512), 4 a (57, 1, 513), 5 d (57, 1, 514), 6 c
  (154, 2, 515), 8 a (231, 3, 516), 8 c (231, 3, 518), 8 d (231, 3, 519), 8 b (231, 3,
  517), 9 b (73, 1, 520). E0 estimate: GPU 3037 to 5077.4 s, at most 6431.4 s (107 min)
  with cool-down, against the 150 min budget.
- **The first clip's draft:** `first-clip/story.json`, the voiced draft with only board 2
  (`boards` and `board_order` cut to `brd_01M79V9FC00000000000000002`; a hand edit of a
  copy, nothing else changed). Its dry run ([`dry-run-first-clip.txt`](dry-run-first-clip.txt),
  run `run_01M7BVQD15TMV6RN3VZYT9TDBD`) lists exactly one job: s2v board 2 slot b, 65
  frames, 1 chunk, seed 501; GPU 142.5 to 203.1 s, at most 328.9 s. Its clip key
  `sha256:28d85807...` is board 2's key in the whole story (both `--json` dry runs), so the
  whole story's phase will find it cached. **Changed:** the references' checklist (item
  6) puts one `ImageToVideo` first; this story has no whole-frame board, so the first job
  is the single-chunk speech clip the work order names (step h).
- **Probe** ([`probe-gate.json`](probe-gate.json), [`tools/probe.py`](tools/probe.py),
  01:47:00 UTC): one `WanClipClient.probe()` with the store's own `FileJournal`. `api ok`,
  `accepting_jobs: true`, `active_job: null`; `queue_running: []`, `queue_pending: []`;
  exactly the two approved GPUs, `GPU-d8a856f1...` 50 C, 0 %, 266 MiB, 25.1 W and
  `GPU-6ff9702a...` 49 C, 0 %, 266 MiB, 25.7 W. `in_flight()` and `halted()` `None`; the
  journal and its lock file do not exist yet, and the probe created neither.
- **Free space:** Wan volume 26 G of 79 G; session pod 18 G; the store 122 MB.
- **Journal:** `/home/dev/studio-jobs/winter-menu-e1-20261114/store/wan-journal.jsonl`.
- Four dry runs left four `cancelled` run records in the store (two of them `--json`
  repeats to read the clip keys); they are records only.
- **The note:** `agent-run parent tell --key op428-gate --kind question` at 01:47:51 UTC
  (`message.1c4eb0209a1c5689f6f4148bc51af61b.324765b5...`), then `agent-run parent wait
  ... --for 15m`. **The answer** (reply `message.55d70d0fcc6750355186a535a517f3d3...`, key
  `op428-gate-answer-1`, from the recorded parent session `haynes-studio-1113-064439`,
  01:54:32 UTC): **go for step h only**, one GPU job (board 2 slot b, 65 frames, 1
  chunk, seed 501, on the one-board copy, through `studio build --phase service` with
  `--wan-story https://work.haynesnetwork.com/work_packages/428`); step i needs its own
  written go after a second note (`op428-gate-2`) with the first job's values. The
  coordinator accepted the four points above; the one speech prompt for every board is
  **a known difference from E0** for Tom to weigh (E0 described each doll in her own
  prompt), and the new fire bed is a new version byte-identical to the old one, with its
  own job's provenance.

## h. The first clip alone — Proven

```sh
nice -n 10 uv run studio build --store $J/store --story $J/first-clip/story.json \
  --library $J/voiced/library.json --operator-iss ... --operator-sub ... \
  --toolchain $J/toolchain.json --studio-commit ec8c3869e8e699b4f7cf58bb3d1485f4cdb4af5e \
  --phase service --wan-story https://work.haynesnetwork.com/work_packages/428 --json
```

01:54:44 to 01:57:56 UTC, 3 min 11 s, exit 0. Run `run_01M7BW79TF5CR3J6QP6ARGGRQ7`
`cancelled`, reason "service phase complete: the mix passed its 4 checks; 1 clip
artifacts made and 0 transcript checks run, the rest found in the cache". One Wan job,
through the client under the API's lease:

| Value | Read | Expected |
|---|---|---|
| Job | `95372414266440f387298aeb282c921f`, prompt `25871362-a6a3-4a23-b0b8-48ea483ecc49`, preset `studio-e0-s2v-lightning-576x1024-65f`, story 428's URL | |
| Frames | 65 requested, **66 delivered**, 63 needed (TIME-8), 3 trimmed; board 94 frames | 66 |
| Rate, size | measured **16 fps**, **576x1024** | 16, 576x1024 |
| Clip | `8f460514570af84b3abf4cf55514b0dd600a03febf137eee7ed0f50b099e4dee`, 1 254 010 bytes | |
| Times | `render_s` 188.3, `fetch_s` 0.3, `wall_s` 189.9 (E0's range 142.5 to 203.1 s); `cooldown_s` 0.4 (no wait) | |
| Start temperatures | `GPU-d8a856f1` 50 C at 0 %, `GPU-6ff9702a` 49 C at 0 % (both probes) | under 62 C, at most 5 % |
| During the job | one GPU worked (S2V runs on one card): `GPU-d8a856f1` peaked at **87 C** at 100 %, 22 622 MiB peak; the other stayed at 49 C, 0 % (ledger telemetry, 38 samples) | |
| `engine_read_retries`, `poll_misses` | 0, 0 | |
| `unexpected_work_seen` | null (none) | empty |
| Inputs | drive track `studio-e0/d063c1b4e6868396.wav` (188 044 bytes, 94 000 samples at 24 kHz); start image `studio-e0/342960b60079923d.png` (E0's start image of B, already on the volume) | |
| Ledger (`GET /videos/<job>` in the API pod) | `succeeded`, 1 254 010 bytes, `graph_sha256` `9f4e7c0e...85c30` (the journal's), output `video/95372414..._00001_.mp4` | succeeded, same bytes |
| Journal | `created`, `remember in_flight`, `remember uncollected`, **`settle collected`** (01:57:56) | settled |
| Wan volume | 26 G free | |

Records: [`clips/94f-seed501.s2v-clip-record.json`](clips/94f-seed501.s2v-clip-record.json) (the
adapter's provenance record with the whole Wan record),
[`clips/94f-seed501.wan-ledger.json`](clips/94f-seed501.wan-ledger.json),
[`wan-journal-after-h.jsonl`](wan-journal-after-h.jsonl). The Wan record's `created`,
`started` and `finished` fields are null, although the ledger has all three
(observation O-428-4). GPU wall time so far: 3.2 min of 150.
- **Gate 2:** note `op428-gate-2` (`message.f5f85cb44ed4dae66a11de2b38c06ee0...`, 01:59:29
  UTC) with the values above. **Answer** (`message.13f8f012516f176a013ceb31d170c361...`,
  from `haynes-studio-1113-064439`, 02:00:15 UTC): the 87 C peak is the card's E0 range
  (84 to 88 C, `video-e0/findings.md`), not a stop; **go for step i in two parts**: part
  1 board 1 slot a alone (the first two-chunk job), then, if it holds and no card peaks
  above 88 C, part 2 the remaining nine in one command, whose dry run must list exactly
  board 3 c, 4 a, 5 d, 6 c, 8 a, 8 c, 8 d, 8 b, 9 b; then steps j to n without asking
  again.

## i. The service phase — Proven

### Part 1: board 1 slot a alone — Proven

`board1-clip/story.json`, the voiced draft cut to board 1 (as for board 2); its dry run
(`run_01M7BWHMTB8ZFQM2CJCR3PQN1H`) listed one job with board 1's key in the whole story
(`sha256:dfefe5c8...`). Then the same `studio build ... --phase service` on it, 02:00:33
to 02:08:29 UTC (7 min 55 s), exit 0; run `run_01M7BWHYF16GQX6RCD5W0P1Z25` `cancelled`
("service phase complete", 1 clip made).

Job `8638520a12ba4bb2af7f635987df54dd`: 154 requested, **158 delivered** (102 needed, 56
trimmed), **16 fps**, 576x1024, clip `e8d18705...56b0`, 6 039 663 bytes; `render_s` 468.5
(E0 463 to 466.6), `wall_s` 473.2; `cooldown_s` 0.4, start 59 C and 50 C at 0 %; retries
0, poll misses 0, no foreign work; peak **88 C** on `GPU-d8a856f1` (the other 51 C),
21 662 MiB; ledger `succeeded`, bytes and graph hash as the record; journal `settle
collected` 02:08:28. Not above 88 C, so part 2 followed without another note, as the go
says. Records: `clips/153f-seed510.*` ([`tools/clips.py`](tools/clips.py) reads each clip
record from the store and its ledger by `GET /videos/<job>` in the API pod, read-only).

### Part 2: the remaining nine in one command

Dry run (`run_01M7BX1PTSYPM3E0MJN3CFGH9X`, 02:09 UTC): exactly the nine jobs the go
names, in its order; E0 estimate GPU 2431.5 to 4407.7 s, at most 5520.3 s with
cool-down. Then the same command on `voiced/story.json` from 02:09 UTC.

02:09:22 to 03:42:52 UTC, **93 min 31 s**, exit 0. Run `run_01M7BX20VY53HFCV376P8RNVD0`
`cancelled`: "service phase complete: the mix passed its 4 checks; 9 clip artifacts made
and 0 transcript checks run, the rest found in the cache". Nine Wan jobs, one at a time,
in the dry run's order; no refusal, no held run, nothing resubmitted. The journal (31
lines, [`wan-journal-after-i.jsonl`](wan-journal-after-i.jsonl)) has one `remember
in_flight`, one `remember uncollected` and one `settle collected` per job, and no `halt`.

### Every clip of steps h and i

From [`clips.jsonl`](clips.jsonl) (one line per clip, by `tools/clips.py`) and
`clips/<board frames>f-seed<seed>.{s2v-clip-record,wan-ledger}.json`. All at 576x1024,
measured 16 fps, `engine_read_retries` 0, `poll_misses` 0, `unexpected_work_seen` null,
ledger `succeeded` with the record's bytes and `graph_sha256`, `recovered` false, the
cool check right before the run passing at once (`cooldown_s` 0.4). "Wait" is the cool
wait before the uploads (`cool_before_upload.cooldown_s`). Peak is the working card's
(`GPU-d8a856f1`) highest temperature in the ledger telemetry; the other card stayed at
49 to 53 C in every job.

| # | Board, slot | Job | Asked | Delivered | Wait s | Start C | `render_s` | `wall_s` | E0 `render_s` | Peak C |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2 b | `95372414` | 65 | 66 | 0.4 | 50 / 49 | 188.3 | 189.9 | 142.5-203.1 | 87 |
| 2 | 1 a | `8638520a` | 154 | 158 | 0.4 | 59 / 50 | 468.5 | 473.2 | 463-466.6 | 88 |
| 3 | 3 c | `44c42581` | 154 | 158 | 83.8 | 61 / 52 | 474.0 | 559.2 | 463-466.6 | 89 |
| 4 | 4 a | `5a438d01` | 57 | 58 | 146.3 | 61 / 52 | 142.0 | 289.6 | 142.5-203.1 | 88 |
| 5 | 5 d | `f742e358` | 57 | 58 | 135.8 | 61 / 52 | 142.2 | 279.2 | 142.5-203.1 | 88 |
| 6 | 6 c | `63c0a32c` | 154 | 158 | 125.3 | 61 / 52 | 478.0 | 604.8 | 463-466.6 | 89 |
| 7 | 8 a | `976dbb34` | 231 | 238 | 135.8 | 61 / 52 | 735.3 | 875.9 | 269.5-716.3 | 89 |
| 8 | 8 c | `3c114ac9` | 231 | 238 | 125.4 | 61 / 53 | 735.5 | 862.4 | 269.5-716.3 | 89 |
| 9 | 8 d | `412bf434` | 231 | 238 | 146.1 | 61 / 53 | 736.0 | 883.6 | 269.5-716.3 | 89 |
| 10 | 8 b | `3cec64ee` | 231 | 238 | 146.2 | 61 / 53 | 734.3 | 881.9 | 269.5-716.3 | 89 |
| 11 | 9 b | `7dfdfb11` | 73 | 74 | 146.2 | 61 / 53 | 203.9 | 351.9 | 142.5-203.1 | 89 |

**Totals:** 11 Wan jobs of 14; Wan GPU wall time (the sum of `wall_s`, cool waits
included) **6251.6 s = 104.2 min** of 150; the three commands' wall time 104.6 min
(3:11, 7:55, 93:31). Inside the dry runs' upper bound (6431.4 s).

**What fell short of a goal:** the four 3-chunk clips each took 734 to 736 s to render,
above E0's longest (716.3 s) and 2.7 times E0's fastest 3-chunk job (269.5 s, `s8-a`);
each later job first waited 84 to 146 s for the working card to cool under 62 C. Every
job ran on one card (the S2V lightning graph uses one GPU), so the second 3090 sat idle
for the whole phase (observation O-428-5). Jobs 10 and 11 are E0's 9 b and the board 9
job; 9 b's render (203.9 s) is 0.8 s over E0's range. The peak of 89 C is 1 C above E0's
recorded range (84 to 88 C); the coordinator set no temperature stop for part 2.
