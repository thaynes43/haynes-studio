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
