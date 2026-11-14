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
