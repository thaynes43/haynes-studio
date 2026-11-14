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
- **State:** source and records in this folder; tested (every check below); **delivered privately** (ledger `d009d61541774a429fcabfeedadd8b51`, <https://video.haynesops.com/videos/d009d61541774a429fcabfeedadd8b51/file>, home network only); **accepted: no**. **Tom's verdict: pending** (recorded below when he gives it).

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
| During the job | one GPU worked (S2V runs on one card): `GPU-d8a856f1` peaked at **87 C** at 100 %, 22 622 MiB peak; the other stayed at 49 to 50 C, 0 % (ledger telemetry, 38 samples) | |
| `engine_read_retries`, `poll_misses` | 0, 0 | |
| `unexpected_work_seen` | null (none) | empty |
| Inputs | drive track `studio-e0/d063c1b4e6868396.wav` (188 044 bytes, 94 000 samples at 24 kHz); start image `studio-e0/342960b60079923d.png` (E0's start image of B, already on the volume) | |
| Ledger (`GET /videos/<job>` in the API pod) | `succeeded`, 1 254 010 bytes, `graph_sha256` `9f4e7c0e...85c30` (the journal's), output `video/95372414..._00001_.mp4` | succeeded, same bytes |
| Journal | `created`, `remember in_flight`, `remember uncollected`, **`settle collected`** (01:57:56) | settled |
| Wan volume | 26 G free | |

Records: [`clips/94f-seed501.s2v-clip-record.json`](clips/94f-seed501.s2v-clip-record.json) (the
adapter's provenance record with the whole Wan record),
[`clips/94f-seed501.wan-ledger.json`](clips/94f-seed501.wan-ledger.json),
[`wan-journal-after-h.jsonl`](wan-journal-after-h.jsonl). The job's own times are in the
record as `job_created_at`, `job_started_at` and `job_finished_at`, equal to the ledger's
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
lines after step i: the first 31 lines of [`wan-journal-final.jsonl`](wan-journal-final.jsonl)) has one `remember
in_flight`, one `remember uncollected` and one `settle collected` per job, and no `halt`.

### Every clip of steps h and i

From [`clips.jsonl`](clips.jsonl) (one line per clip, by `tools/clips.py`) and
`clips/<board frames>f-seed<seed>.{s2v-clip-record,wan-ledger}.json`. All at 576x1024,
measured 16 fps, `engine_read_retries` 0, `poll_misses` 0, `unexpected_work_seen` null,
ledger `succeeded` with the record's bytes and `graph_sha256`, `recovered` false, the
cool check right before the run passing at once (`cooldown_s` 0.4). "Wait" is the cool
wait before the uploads (`cool_before_upload.cooldown_s`). Peak is the working card's
(`GPU-d8a856f1`) highest temperature in the ledger telemetry; the other card stayed at
49 to 54 C in every job.

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
each job that followed a hot one (3 to 11) first waited 84 to 146 s for the working card to
cool under 62 C; jobs 1 and 2 started cool. Every
job ran on one card (the S2V lightning graph uses one GPU), so the second 3090 sat idle
for the whole phase (observation O-428-5). Board 9's render (203.9 s) is 0.8 s over E0's
range for one chunk. The peak of 89 C is 1 C above E0's recorded range (84 to 88 C); the
coordinator set no temperature stop for part 2.

Clips 2 (board 1, seed 510) and 11 (board 9, seed 520) were later refused by the decal
gate and re-rolled (step j); they stay in the store, unused by the film.

## j. The offline phase — Proven after three refusals and their decisions

The section below is in the order it happened: the first run was blocked, a blocker note
went to the coordinator, and the phase finished under its decisions.

**Where it runs: the session pod**, one worker at two threads (`--workers 1`,
`STUDIO_THREADS=2`, `OMP/OPENBLAS/MKL_NUM_THREADS=2`, `nice -n 10`). The `ai/studio-render`
worker was inspected read-only first (`kubectl exec -n ai deploy/studio-render -c app --
...`): image `python:3.13-slim-bookworm`, 24 CPUs (limit 24, 32 Gi), `/studio` on gasha01
NFS with 94 T free, nothing else running (load 0.9; only `sleep infinity`); packages av
19.0.2, numpy 2.5.4, opencv-python-headless 5.0.0.93, pillow 13.0.0, scipy 1.18.1,
imageio-ffmpeg 0.8.1, **no jsonschema or referencing**. The package needs Python 3.11 or
3.12 (`requires-python >=3.11,<3.13`), jsonschema and referencing, av <19, numpy <2.5,
scipy <1.17 and OpenCV <5, and the keyer's and encoder's builds are cache-key inputs (a
picture keyed there would not match the pod's keys). It cannot run there without
installing into the cluster, which the work order forbids, so nothing was copied to
`/studio` and no folder was made there. **Changed** from the runbook's heavy-CPU rule:
the work order allows the pod in this case (observation O-428-7: the worker image no
longer matches services.md's "python 3.12, pinned requirements").

```sh
nice -n 10 uv run studio build --store $J/store --story $J/voiced/story.json \
  --library $J/voiced/library.json --operator-iss ... --operator-sub ... \
  --toolchain $J/toolchain.json --studio-commit ec8c3869e8e699b4f7cf58bb3d1485f4cdb4af5e \
  --offline --workers 1 --json
```

- 03:43:54 UTC: the first attempt wrapped the command in `/usr/bin/time -v`, which the
  pod lacks: exit 127, nothing ran, no run made. Re-run with the shell's `time`.
- 03:44:15 to 03:44:39 UTC (24.4 s), exit 1: run `run_01M7C2FS3G1YMAVKMSBES6N6YY`
  `failed`, **`layered.decal_weak` at board 1, stage `segment`**: "slot a: the decal
  track is too weak (min 0.7167, 0 failed; floor 0.8); re-roll the clip or record a lower
  decal_min_ecc". The speaker's clip was keyed (one `keyed_frames` stage), and the
  gate refused the segment before its first frame.
- To give the coordinator the whole picture in one note, boards 2 to 9 were then run
  the same way, each alone on a one-board copy of the draft (`per-board/board<n>.json`,
  as for the first clips; CPU only, no service). A board that passes leaves its keyed
  frames and segment in the cache, under the same keys the whole story uses.
  ([`offline-per-board.json`](offline-per-board.json), [`offline-per-board.txt`](offline-per-board.txt),
  [`runs/`](runs/)):

| Board | Result | Wall s | What it made |
|---|---|---|---|
| 1 | **`layered.decal_weak`**, slot a: min ECC 0.7167, floor 0.8 | 24.4 | keyed frames |
| 2 | passes; stops at the transcript check (`build.offline_missing`, `check_result`), as an offline run must | 54.3 | keyed frames, segment, picture, master (this copy's mix was made in step h) |
| 3 | passes, as 2 | 82.5 | the same |
| 4 | passes | 48.6 | the same |
| 5 | passes | 36.5 | the same |
| 6 | passes | 61.7 | the same |
| 7 | **`layered.layout_invalid`**: "slot 'd' puts the doll more than 240 px off the frame" | 17.7 | keyed frames |
| 8 | passes (four speakers) | 412.1 | 4 keyed frames, segment, picture, mix, master |
| 9 | **`layered.decal_weak`**, slot b: min ECC 0.6867, floor 0.8 | 41.6 | 3 keyed frames |

- **Boards 1 and 9 (the decal gate).** A clip the build makes is gated at the default
  0.8 (Q-426-1, the contract owner's ruling); the draft has no field for a build-made
  clip's floor. E0 met the same two: its `s1-a` scored 0.71 and `s9-b` 0.80, both failed
  the gate, and both were overridden by eye with a recorded reason (`clipmap-s2v.json`
  `decal_min_ecc` 0.7 and 0.78; `video-e0/findings-s2v.md`). With E0's overrides board 1
  (0.7167) would pass and board 9 (0.6867) still fail.
- **Board 7 (the close-up).** r4's `closeup` preset puts D at `x` 0.56, height 2300, crop
  `[0.27, 0, 0.9, 0.75]`. Her loop's keyed box is 548x730 (of 576x1024), so the cropped
  sprite is 345x548, scaled to 1448x2300; its left edge is at -119 px and its right edge
  at 1329 px, **9 px past** the 1320 px the 240 px margin allows. The rule is
  `poc/edit.py place`'s assert for still cutouts, which the port also applies to keyed
  frames (`layered/compose.py place`); E0's `poc/layered_film.py`, which rendered this
  board from the same loop, made no such check. The r4 still gives the same width to a
  few pixels, so the preset itself sits at the edge.
- Nothing was retried, no GPU job was asked for, no code changed. Step j stops here: a
  `blocker` note to the coordinator (below).

### The blocker and the coordinator's decisions

Note `op428-blocker-1` (`message.799ebd692122b42d74861742ebacd5a1...`, kind `blocker`,
04:00:21 UTC). **Answer** (`message.e1d92cccbbd1f1360b0e3d3418dda1d9...`, from
`haynes-studio-1113-064439`, 04:02:27 UTC), the coordinator's decisions as contract owner
(proposals Tom may overrule; each is a difference from r4 and E0):

1. **Board 7:** the draft's `closeup` preset (only board 7 uses it), slot `d` `x` 0.56 ->
   **0.55**. Edges before: -119 and 1329 px (9 px past 1320); after: -130 and 1318 px,
   both inside. Whether keyed frames should carry the still-cutout limit at all is on the
   coordinator's list for the contract.
2. **Boards 1 and 9:** a re-roll by a draft seed edit, board 1 `s2v:a` 510 -> **610**,
   board 9 `s2v:b` 520 -> **620**; no floor is lowered (check overrides stay with
   people). The dry run must list exactly those two jobs; one more re-roll (seed 611 or
   621) only if exactly one is still below 0.8 and the GPU total stays at or under 150
   min; otherwise a blocker with each clip's lowest scores for a person to judge.
3. All three pass: the whole offline phase in the pod, then steps j to n.
4. The render worker's versions against the lock are an observation (O-428-7) for
   haynes-ops; nothing there changed.
5. If the ready PR and handoff are not started by 06:00 UTC, stop at a safe point and hand
   off what is done.

[`tools/redraft.py`](tools/redraft.py) `$J/voiced $J/voiced2` wrote the new draft version
`voiced2/story.json` (04:02 UTC): those three edits, the story's `revision` 1 -> 2 and
boards 1 and 9 `revision` 1 -> 2, nothing else (checked by a JSON diff). The weak clips
stay in the store (create-only); the voices and the library are unchanged.

- **Board 7 alone** (`per-board2/board7.json`, 04:02:58 to 04:03:17 UTC, 18.9 s): passes; segment
  rendered, stopping only at the transcript check.
- **Service dry run** on `voiced2` (`run_01M7C3JVRA64QSP1434YWAXEXW`): exactly two jobs,
  board 1 a (154 frames, 2 chunks, seed 610) and board 9 b (73 frames, 1 chunk, seed
  620), every other clip a cache hit; E0 estimate 605.5 to 669.7 s, at most 911.1 s.

### The re-rolls — Proven

- **Re-roll 1** (one command on `voiced2`, 04:03:33 to 04:17:12 UTC (13 min 38 s), run
  `run_01M7C3K4WZKZZPKMMXY706WA47` `cancelled`, "service phase complete", 2 clips made):
  board 1 a seed 610, job `0d99ac1e`, 158 of 154 frames, `render_s` 462.5, `wall_s`
  464.5, no cool wait, start 52 / 50 C, peak 88 C; board 9 b seed 620, job `9d4ce7d3`, 74
  of 73, `render_s` 201.6, `wall_s` 340.5, cool wait 135.8 s, start 61 / 52 C, peak 88 C.
  Both: 16 fps, 576x1024, ledger `succeeded` with the record's bytes and graph hash, no
  foreign work, retries 0. One-board offline checks (`per-board2/`): **board 9 passes**
  (min ECC 0.9889); **board 1 still weak**, 0.6827 over the frames it shows (0.6517 over
  the whole clip), 22.9 s.
- **Re-roll 2**, the 14th and last job, as the go allows for exactly one weak board:
  [`tools/redraft.py`](tools/redraft.py) `$J/voiced2 $J/voiced3 --no-layout --seed 1:a:611`
  (story revision 3, board 1 revision 3); its dry run (`run_01M7C4GPQFCZR5TXQGDVD6G0KX`)
  listed exactly board 1 a seed 611. One command, 04:20:39 to 04:28:35 UTC (7 min 56 s), run
  `run_01M7C4JEJ2PQ5KR9HS6M2BQ4WH` `cancelled`: job `bdb9e41bfe494aa3a996c135e6348101`,
  158 of 154 frames, 16 fps, `render_s` 470.9, `wall_s` 472.8, no cool wait, start 59 /
  52 C, **peak 89 C on `GPU-d8a856f1`, 1 C over the coordinator's 88 C line** (the other
  card 52 C); ledger `succeeded`, 5 688 951 bytes, graph hash as the journal; `settle
  collected`; no foreign work; retries 0. Board 1 alone offline (`per-board3/`, 73.5 s):
  **passes**. Note `op428-heat-1` (04:30:27 UTC) asked about the 89 C peak; answer
  (`message.84167fa303f3567c072ca712e0322cb5...`, 04:31:00 UTC): go on with steps j to n,
  no more Wan or Foley job, record the heat plainly (an observation for the hardware
  owner, not interpreted here).
- **Board 1 slot a, all three clips** ([`decal-scores.jsonl`](decal-scores.jsonl), whole
  clip; the gate reads the frames the board shows): seed 510 (job `8638520a`) min ECC
  0.7167 over the shown frames (0.7167 whole clip, lowest at source frames 19, 18, 22),
  keyed key `sha256:959c337b...`; seed 610 (job `0d99ac1e`) 0.6827 shown (0.6517 whole,
  frames 144, 145, 143), `sha256:646f8265...`; **seed 611 (job `bdb9e41b`) passes and is
  the clip the film plays**. The two weak clips and their keyed frames stay in the store.
- **Totals:** 14 Wan jobs of 14; Wan GPU wall time **7529.4 s = 125.5 min** of 150. The
  journal ([`wan-journal-final.jsonl`](wan-journal-final.jsonl), 43 lines) ends with
  `settle collected` for job 14: no unsettled job, no halt.

### The whole offline phase — Proven

`studio build ... --story $J/voiced3/story.json ... --offline --workers 1` (04:31:10 UTC,
7.1 s, exit 1 as expected): run `run_01M7C55PHSHZ9RTR3DH0SC0JXN` stops at
`build.offline_missing`, stage `check_result`, the transcript check of the new master
`f6fd041a...`. Every keyed frame and segment was already in the cache from the one-board
runs (same keys), so this run spliced the film picture and muxed the master; nothing was
rendered again. **Timings** (no run that made them recorded stages: a run that ends at
`build.offline_missing` keeps no stage list, observation O-428-6): keying and segment
render per board, as each one-board command's wall time in the pod at two threads,
board 1 73.5 s (seed 611), 2 54.3, 3 82.5, 4 48.6, 5 36.5, 6 61.7, 7 18.9 (x 0.55), 8
412.1 (four speakers, 251 frames), 9 97.5 s (seed 620): about 15 min of CPU work for the
picture, plus 7 s for the splice and master.

## k. The transcript check and the delivery — Proven

- **Dry run** on `voiced3` (`--phase service --dry-run`): 0 clip jobs. **Service phase**
  (04:31:35 UTC, 2.2 s, exit 0): run `run_01M7C56FGG1XJBAEANF07EYY2Z` `cancelled`, "0 clip
  artifacts made and 1 transcript checks run". One Whisper request (of 30); no Wan client
  was made (the journal stayed at 43 lines). `master.transcript`: **`pass_with_tolerances`**
  (the story's `asr_tolerances`: "340" heard as "three hundred forty", "mos" for "moss"),
  key `sha256:4c975df5...`, result `2c8ad0bc...`.
- **Delivery** (04:31:46 UTC, 13.5 s, exit 0): run **`run_01M7C56SZ6TAHTJSW413RFZYQP`
  `succeeded`**, "delivered and verified", delivery **`dlv_01M7C576EAX9NY1S0JHFYW2QQS`**.
  1087 frames at 24 fps. Checks: `mix.length`, `mix.loudness` (-20.296 LUFS against -20 ±
  1.5), `mix.true_peak` (-4.082 dBTP, at most -2.5), `mix.clipping` (0), `master.loudness`,
  `master.true_peak`, `master.clipping`: pass; `master.transcript`: pass with tolerances;
  `frame_count`: pass.
- **Read back** (`read_delivery`, [`delivery-readback.json`](delivery-readback.json)):
  master `f6fd041afc837a3a050da4ad5a574e96798b4014b5e9b67ca1d9966039b0621e`, 60 562 847
  bytes, 1080x1920, H.264 and AAC, 1087 frames; phone proxy
  `222873565e1df9f0e2ca61a7632b5c9c92be707e683173e4208eaabe7ea13c01`, 12 986 068 bytes,
  720x1280, under its 25 000 000-byte limit; decoded 1087 of 1087 expected,
  `sha256_verified: true`. Picture `adb7b091...`, mix `5a13ee14...`. The run record:
  [`runs/k-delivered.run.json`](runs/k-delivered.run.json) (`studio run show ... --json`).

## l. Private viewing — Proven

```sh
uv run python titles/the-winter-menu/e1-build/tools/private_view.py $J/store \
  prd_01M79V9FC00000000000000001 run_01M7C56SZ6TAHTJSW413RFZYQP the-winter-menu-e1-build-1 $J/view --check-only
uv run python titles/the-winter-menu/e1-build/tools/private_view.py $J/store \
  prd_01M79V9FC00000000000000001 run_01M7C56SZ6TAHTJSW413RFZYQP the-winter-menu-e1-build-1 $J/view
```

The runbook's delivery route (stage 7) as story 840 used it:
[`tools/private_view.py`](tools/private_view.py) imports `poc/deliver.py` unchanged for its
`REMOTE`, `WRITE` (create-only, temp file, hash check, hard link), `PUBLISH`, `READ`,
`SPACE` and `check_ledger`; only the file list differs, since a studio delivery is not a
PoC job folder (**Changed**: the PoC script itself needs a manifest and `edit/` files).

- **Before anything was written** (04:33 UTC, `--check-only`): `read_delivery` re-hashed the
  master and the proxy; 27 657 875 456 bytes free for 73 614 971; the folder
  `productions/the-winter-menu-e1-build-1` and the ledger's file unused; the ledger checked
  locally by `check_ledger` and by story 425's `record_from_document`.
- **The delivery** (04:34:16 to 04:34:18 UTC): the master as `final.mp4` (the ledger's
  `output`; 60.6 MB is within the route), the phone proxy as `proxy.mp4`, the delivery
  document and the run record, each copied create-only and hash-checked in the pod; the
  ledger checked again, then linked: **`/workspace/jobs/d009d61541774a429fcabfeedadd8b51.json`**.
- **Read back:** `LedgerReader.get` serves it `succeeded` with the master's `output`,
  bytes and SHA-256; `GET 127.0.0.1:8080/videos/<id>/file` inside the API container
  answers **200 `video/mp4`, 60 562 847 bytes, SHA-256 `f6fd041a...0621e`**, the master's;
  `LedgerReader.list` lists 23 edited productions and **no unreadable ledger**.
  [`production.json`](production.json) holds the ledger and the read-back.
- **The ledger's wording:** its `provenance.video` says "14 jobs on the studio's RTX 3090s";
  11 of the 14 clips are in the film (the three the decal gate refused stay in the store).
  The ledger is create-only and was not changed.
- **The link (home network only):**
  <https://video.haynesops.com/videos/d009d61541774a429fcabfeedadd8b51/file>. A session pod
  cannot open it; it was verified inside the API container as above.

## m. One edit — Proven

The board 8 gavel cue (`cue_01M7BVBVSBHA26B6V3F90A35N9`, sound `gavel`) from -20 to **-23
dBFS RMS** in a new draft version, `voiced4/story.json` (story revision 4, board 8 revision
2; a JSON diff shows nothing else changed). Then the service dry run (04:34:42 UTC, run
`run_01M7C5C521H5DF4ZY68TMS2VTS`, 0 clip jobs) and **one full build** (`studio build ...
--wan-story ... --workers 1`, no phase flag, 04:34:55 UTC, 18.3 s, exit 0): run
**`run_01M7C5CJA7XKBCRPM0ZRP2P5RS` `succeeded`**, delivery `dlv_01M7C5D3KFX3MFVWCXBCVJHMG7`
([`runs/m-edited.run.json`](runs/m-edited.run.json)). One Whisper request; no Wan client
was made (the journal stayed at 43 lines).

What was made, from the two runs' committed stages, against the first delivered run:

| Artifact | Made by the edit | Evidence |
|---|---|---|
| clips, drive tracks, keyed frames | **no** | no board stage lists a made artifact |
| segments (9) | **no** | every `segment_sha256` equals the first run's |
| film picture | **no** | same key `sha256:ed390fb9...` and hash `adb7b091...` |
| mix and its placement | yes, by the dry run | `mix-*`, `mix_placement-*` stages of `run_01M7C5C5...`; mix `af68dea8...` |
| mix checks (4) | yes, by the dry run | four `check_result-*` stages of the same run |
| master | yes | `master-*` stage; `92d1efa3a30c4de10c62298cd25c20671f729ab1acf257ad7cdfaecd9edb09bc` |
| master checks (3) and the transcript check | yes | four `check_result-*` stages of `run_01M7C5CJ...` |
| proxy and delivery | yes | the `delivery` stage; proxy `0212a7de9d6b7816c4c4d3c98bfd6d8e80fc112163944152e399b3e980a6748d` |

All checks pass; the transcript check now reads `pass` (an exact match) where the first
build's read `pass_with_tolerances`. The edited build is in the store only: the story
allows one new production on the Wan volume, so it was not delivered for viewing.

## n. The record — Proven

This folder: the run log, [`import-report.json`](import-report.json) (and its dry run),
[`clips.jsonl`](clips.jsonl) and `clips/` (each Wan clip's provenance record and ledger),
[`decal-scores.jsonl`](decal-scores.jsonl), [`timings.json`](timings.json), the run records
in `runs/`, [`offline-per-board.json`](offline-per-board.json), the dry runs, the probe,
the journal before and after, [`delivery-readback.json`](delivery-readback.json),
[`production.json`](production.json), the Wan volume's hashes before and after, and the
one-off drivers in `tools/` (none changes package code). No media.

## The Wan volume after the run

The same listing as step a (04:36 UTC, [`wan-volume-after.sha256.txt`](wan-volume-after.sha256.txt)):
501 files. **All 482 earlier lines are unchanged.** New: 15 ledgers in `jobs/` (the 14
Wan jobs of this story, each matched to a clip record, and the production ledger
`d009d615...`) and the production's four files. Nothing was deleted, moved or overwritten.
Outside the listing, the jobs' clips are under `output/video/` and the client's uploads
under `input/studio-e0/` (create-only; the start images already existed from E0). Free
space at the end: 26 G.

## Budget

| | Used | Cap |
|---|---|---|
| Elapsed | 01:33 to about 05:00 UTC for the build; the PR after | 5 h |
| Wan jobs | 14 | 14 |
| Wan GPU wall time | 125.5 min (7529.4 s; `render_s` 6173 s) | 150 min |
| Sound-model jobs | 1 | 3 |
| Speech requests | 0 | 60 |
| Transcript requests | 2 (one per film checked) | 30 |
| Store | 1.8 G | 8 GiB |
| `/studio` | nothing written | 8 GiB |
| Paid inference | $0 | $0 |

## Observations

- **O-428-1** The command line records the operator as `{kind: human, iss, sub}`; an agent
  session runs it here under a stand-in issuer. The model has an `agent_session`
  principal (used by `tools/draft.py`), the command line has no flag for it.
- **O-428-2** The regenerated fire bed is byte-identical to the r4 bed, so the r4 bed's
  version now resolves from the same content-addressed blob as well; the build plays
  the new version.
- **O-428-3** One S2V prompt for every board; E0 described each doll in her own prompt. A
  known difference from E0 for Tom to weigh (coordinator's decision).
- **O-428-4** The reference ([legacy-adapters.md](../../../docs/reference/legacy-adapters.md),
  "The provenance record") names the job's times `created`, `started` and `finished`; the
  record names them `job_created_at`, `job_started_at` and `job_finished_at`. (A first draft
  of this log called them null: `tools/clips.py` looked for the reference's names.)
- **O-428-5** Every speech job ran on one of the two 3090s; the other idled, and each job that
  followed a hot one (3 to 11, and 13) waited 84 to 146 s for the working card to cool first.
- **O-428-6** A run that ends at `build.offline_missing` (the documented offline step)
  keeps no stage list, so the keying, segment and picture times are in no run record;
  here they are command wall times.
- **O-428-7** `ai/studio-render` runs Python 3.13 with av 19.0.2, numpy 2.5.4, scipy
  1.18.1, opencv 5.0.0.93 and no jsonschema; the package's lock needs Python 3.11 or 3.12
  and older ranges, so the offline phase cannot use the worker (for haynes-ops).
- **O-428-8** The decal gate refused three build-made speech clips at the default 0.8
  (board 1 seeds 510 and 610, board 9 seed 520), as E0's own clips of those boards failed;
  re-rolls cost three jobs (12 to 14: 1277.8 s, 21.3 GPU min). Board 7's close-up needed an 11 px move to pass
  the off-frame rule the port applies to keyed frames.
- **O-428-9** Heat, for the hardware owner: the working card peaked at 87 to 89 C in every
  job; job 14 (`bdb9e41b`) peaked at 89 C with no cool wait, starting at 59 and 52 C.

## Known defects in `tools/`

The drivers are kept as they ran. `draft.py` stamps the new bed version `created_at`
2026-11-14T01:45:00Z, a fixed value, although it ran at 01:44 (before `studio voice` at
01:44:36). `decal.py` would raise on a clip with two or more unscored frames (no clip here
has one). `clips.py` looked for the reference's names of the job's times (O-428-4).
Found by an independent read of these records (a Sonnet subagent), which also caught
the job order of `timings.json`, the re-roll GPU minutes, two temperature ranges, two
times and the board 2 row, all corrected here.

Further evidence: [`toolchain.json`](toolchain.json), [`fire-bed-job.json`](fire-bed-job.json),
the dry runs [`dry-run-board1.json`](dry-run-board1.json), [`dry-run-part2.json`](dry-run-part2.json),
[`dry-run-reroll-1.json`](dry-run-reroll-1.json), [`dry-run-reroll-2.json`](dry-run-reroll-2.json),
[`dry-run-transcript.txt`](dry-run-transcript.txt) and [`dry-run-edit.txt`](dry-run-edit.txt). Step a's
reads (file hashes, deployment, free space) are recorded in this log only.

## Tom's verdict

Pending. Recorded here, word for word and apart from the checks, when he gives it.
