# Legacy recovery map: The Winter Menu r1 to r4

Story [425](https://work.haynesnetwork.com/work_packages/425) built this map; story
[428](https://work.haynesnetwork.com/work_packages/428) uses it. It lists every private
input file that The Winter Menu r1 to r4 used, with the SHA-256 the public evidence
records for it and the places the evidence says a copy was written.

**Nothing here has been checked.** Every row and every locator has status
`unverified`: nobody has looked to see whether a file exists at a locator or has the
expected hash. Private paths are written exactly as recorded (`~/studio-jobs/...` is
never expanded). The map claims no file exists.

- Data: [`legacy-recovery-map.json`](legacy-recovery-map.json), built from public files
  only by `python -m haynes_studio.adapters.recovery`
  ([`recovery.py`](../../src/haynes_studio/adapters/recovery.py)). A test fails if the
  committed JSON or the table below differs from the build, so a change to a manifest
  or evidence file means rebuilding both:
  `uv run python -m haynes_studio.adapters.recovery > docs/reference/legacy-recovery-map.json`.
- Sources: the four manifests, each revision's `production.json` (delivery ledger),
  `speech.json` and `timeline.json`, `prompts.json`, and E0's `keyframes.json` and
  `clip-records.jsonl`, all under [`titles/the-winter-menu/`](../../titles/the-winter-menu/).
  The JSON lists each with its SHA-256.
- The tool to read the Wan copies is the read-only
  [ledger reader](legacy-adapters.md#legacy-delivery-ledger-read-only).

## What a row holds

| Field | Meaning |
|---|---|
| `key` | `r<revision>:<role>:<file>`, unique |
| `role` | `render` (a ComfyUI image a still or the set was cut from), `still` (a keyed cast cutout), `set`, `sfx`, `bed`, `take` (one Kokoro line), `keyframe` (an E0 first frame composed from r4) |
| `file` | the path as recorded, relative to the job folder (keyframes: the file name `poc/keyframes.py` wrote) |
| `sha256` | the expected hash, or `missing` when no public file records one |
| `bytes` | the size the delivery ledger records, else `null` |
| `hash_recorded_in` | every public file that records the hash; the build fails if two disagree |
| `provenance` | what made it: render seed, graph and `graph_sha256`; sound service job and seed; take shot, line and voice; keyframe shot and layout |
| `locators` | where a copy was written, each `unverified`: `job_dir` (the job folder in an earlier session's home), `wan_pvc` (the delivery copy on PVC `ai/wan-video`, with its ledger ID), `wan_upload` (an E0 keyframe upload on the same PVC), `comfyui_output` (the render's ComfyUI output prefix). A locator with a `derivation` was worked out from code and recorded values, not recorded as a path |
| `locator_gaps` | what is known to be absent: beds were never delivered to the Wan PVC; keyframes' output folder was not recorded |

## Summary

98 rows, 43 distinct hashes, none `missing`:

| Role | Rows | Distinct hashes | Locators |
|---|---|---|---|
| render | 8 | 8 | `job_dir` (r1), `comfyui_output` |
| still | 25 | 7 | `job_dir`, `wan_pvc` |
| set | 4 | 1 | `job_dir`, `wan_pvc` (the same bytes as render `set-left-s221`) |
| sfx | 11 | 4 | `job_dir`, `wan_pvc` |
| bed | 3 | 1 | `job_dir` only |
| take | 38 | 16 | `job_dir`, `wan_pvc` |
| keyframe | 9 | 7 | `wan_upload` only |

28 distinct hashes have a `wan_pvc` locator: every still, the set, every effect and
every take. The fire bed (`sfx/fire-s701.wav`), the eight renders and the seven
keyframe images do not.

## Checklist for story 428

Work read-only, one call at a time, through the package's clients with the real
runner, inside 428's own authorization. Record outcomes in 428's own evidence, keyed by
row `key`; do not edit this map's statuses (it stays the plan, and its test compares it
with the build).

1. **Before anything:** confirm 428 authorizes `kubectl exec` into
   `ai/deploy/wan-video` container `api` (and, for step 5, `ai/comfyui-0`), and that the
   new store (stories [379](https://work.haynesnetwork.com/work_packages/379) and
   [381](https://work.haynesnetwork.com/work_packages/381)) is ready to take bytes
   create-only. Never write the Wan PVC or its ledger, never submit ComfyUI work, and
   stop at a denial.
2. **Ledgers:** `LedgerReader.get` each of the four ledger IDs (in the JSON's `wan_pvc`
   locators). Each answer must equal its committed `production.json` (output hash and
   every asset path and hash). A difference is a finding: record it and stop that
   revision.
3. **Delivered copies (78 rows, 28 hashes):** for each distinct hash, call
   `LedgerReader.fetch_asset(ledger_id, sha256)` once with any row's `wan_pvc`
   locator. The pod and the client both check the hash. Publish the bytes to the new
   store, then mark every row with that hash `verified` with the store locator. A
   refusal (`no asset`, `hash mismatch`, missing file) marks that row `absent` or
   `mismatch`; try the next row's ledger for the same hash before giving up.
4. **Fire bed (3 rows, 1 hash):** not on the Wan PVC (`poc/deliver.py` never copied
   beds). Its only recorded copies were in the r2 to r4 job folders, in an earlier
   session's home; this story had none. Ask the coordinator whether a rescue bundle or
   an old session volume holds `sfx/fire-s701.wav`, and verify any copy by hash. The
   audio-authoring job in its provenance made the file, but no record ties that job's
   artifact to this hash. If no copy turns up, mark it `absent`: a regenerated bed is a
   new version with a new hash (contract section 7), never a repointed old one.
5. **Renders (8 rows), time-sensitive:** made on 2026-11-03 under ComfyUI output prefix
   `studio/the-winter-menu-r1/<name>`. A CronJob deletes top-level ComfyUI outputs
   after 30 days (around 2026-12-03); whether it reaches the `studio/` subfolder is not
   recorded. Reading them needs a read-only snippet this story did not write (a `GET
   /view` for the prefix's `_00001_.png` file, pinned like the others). The exact file
   name was not recorded, so confirm it from ComfyUI's history for the row's
   `prompt_id` before reading. The stills and set made from them are already covered in
   step 3; renders matter only to regenerate a cutout.
6. **Keyframes (9 rows, 7 hashes):** the E0 uploads at
   `/workspace/input/studio-e0/<first 16 hex>.png` on the Wan PVC (derived from
   `poc/wan.py`, which named uploads that way). The ledger reader only fetches ledger
   assets, so reading these needs a new pinned read-only snippet in 428. Otherwise
   recompose them with `poc/keyframes.py` from r4's recovered inputs: that is a new
   version with a new hash, recorded as such.
7. **Close:** report rows `verified`, `absent` and `mismatch` by role, with the store
   locator of each verified hash and the elapsed time and bytes moved.

## Rows

Generated; the JSON holds full hashes, provenance and every locator.

<!-- recovery-map:begin -->
| Row | SHA-256 (first 16) | Bytes | Locators (all unverified) |
|---|---|---|---|
| `r1:render:a-base-s101.png` | `c71ba33b3e037a13` |  | job_dir, comfyui_output |
| `r1:render:b-base-s101.png` | `e8c238814ca74924` |  | job_dir, comfyui_output |
| `r1:render:c-base-s101.png` | `ff4713d78698b1d2` |  | job_dir, comfyui_output |
| `r1:render:d-base-s101.png` | `ca15cbee044fdf46` |  | job_dir, comfyui_output |
| `r1:render:a-staring-s301.png` | `4fb4f4572fb090be` |  | job_dir, comfyui_output |
| `r1:render:c-staring-s301.png` | `8e13cbdc905ff6d0` |  | job_dir, comfyui_output |
| `r1:render:d-shocked-s301.png` | `677b7a17adc90188` |  | job_dir, comfyui_output |
| `r1:render:set-left-s221.png` | `29ab6f47227cee7a` |  | job_dir, comfyui_output |
| `r1:still:cutouts/a-proud.png` | `4ea3005f4effebda` | 1850605 | job_dir, wan_pvc |
| `r1:still:cutouts/b-deadpan.png` | `d44fc8299598c56e` | 1615055 | job_dir, wan_pvc |
| `r1:still:cutouts/c-suspicious.png` | `a49b2c3046f385d4` | 1775253 | job_dir, wan_pvc |
| `r1:still:cutouts/d-cheerful.png` | `83bcdb10da26bb27` | 1846045 | job_dir, wan_pvc |
| `r1:still:cutouts/a-staring.png` | `022ac97a623c88bf` | 1616411 | job_dir, wan_pvc |
| `r1:still:cutouts/c-staring.png` | `b816a4f225e160a6` | 1547710 | job_dir, wan_pvc |
| `r1:still:cutouts/d-shocked.png` | `3d9c9d223ebc0137` | 1649760 | job_dir, wan_pvc |
| `r1:set:cutouts/set.png` | `29ab6f47227cee7a` | 2390590 | job_dir, wan_pvc |
| `r1:sfx:sfx/crow-s501.wav` | `78c5f69ff31758d2` | 882044 | job_dir, wan_pvc |
| `r1:take:voices/line-1.wav` | `b9fa04b49038c15c` | 247852 | job_dir, wan_pvc |
| `r1:take:voices/line-2.wav` | `7d5d2d890c1072a2` | 129068 | job_dir, wan_pvc |
| `r1:take:voices/line-3.wav` | `6efd27569ac328e1` | 233516 | job_dir, wan_pvc |
| `r1:take:voices/line-4.wav` | `24eb53ba095394e0` | 122924 | job_dir, wan_pvc |
| `r1:take:voices/line-6.wav` | `58f6812299d32034` | 119852 | job_dir, wan_pvc |
| `r2:still:cutouts/a-proud.png` | `4ea3005f4effebda` | 1850605 | job_dir, wan_pvc |
| `r2:still:cutouts/b-deadpan.png` | `d44fc8299598c56e` | 1615055 | job_dir, wan_pvc |
| `r2:still:cutouts/c-suspicious.png` | `a49b2c3046f385d4` | 1775253 | job_dir, wan_pvc |
| `r2:still:cutouts/d-shocked.png` | `3d9c9d223ebc0137` | 1649760 | job_dir, wan_pvc |
| `r2:still:cutouts/a-staring.png` | `022ac97a623c88bf` | 1616411 | job_dir, wan_pvc |
| `r2:still:cutouts/c-staring.png` | `b816a4f225e160a6` | 1547710 | job_dir, wan_pvc |
| `r2:set:cutouts/set.png` | `29ab6f47227cee7a` | 2390590 | job_dir, wan_pvc |
| `r2:sfx:sfx/crow-s501.wav` | `78c5f69ff31758d2` | 882044 | job_dir, wan_pvc |
| `r2:sfx:sfx/crunch-s601.wav` | `5515c7006ce09a1c` | 882044 | job_dir, wan_pvc |
| `r2:bed:sfx/fire-s701.wav` | `0b33af45929b8cfb` |  | job_dir |
| `r2:take:voices/line-1.wav` | `b9fa04b49038c15c` | 247852 | job_dir, wan_pvc |
| `r2:take:voices/line-2.wav` | `7d5d2d890c1072a2` | 129068 | job_dir, wan_pvc |
| `r2:take:voices/line-3.wav` | `6efd27569ac328e1` | 233516 | job_dir, wan_pvc |
| `r2:take:voices/line-4.wav` | `0063d7e0e0d8a551` | 118828 | job_dir, wan_pvc |
| `r2:take:voices/line-5.wav` | `f89e05a2c53e9be7` | 116780 | job_dir, wan_pvc |
| `r2:take:voices/line-7.wav` | `58f6812299d32034` | 119852 | job_dir, wan_pvc |
| `r2:take:voices/line-8.wav` | `4e12138ee373ac45` | 47148 | job_dir, wan_pvc |
| `r3:still:cutouts/a-proud.png` | `4ea3005f4effebda` | 1850605 | job_dir, wan_pvc |
| `r3:still:cutouts/b-deadpan.png` | `d44fc8299598c56e` | 1615055 | job_dir, wan_pvc |
| `r3:still:cutouts/c-suspicious.png` | `a49b2c3046f385d4` | 1775253 | job_dir, wan_pvc |
| `r3:still:cutouts/d-shocked.png` | `3d9c9d223ebc0137` | 1649760 | job_dir, wan_pvc |
| `r3:still:cutouts/a-staring.png` | `022ac97a623c88bf` | 1616411 | job_dir, wan_pvc |
| `r3:still:cutouts/c-staring.png` | `b816a4f225e160a6` | 1547710 | job_dir, wan_pvc |
| `r3:set:cutouts/set.png` | `29ab6f47227cee7a` | 2390590 | job_dir, wan_pvc |
| `r3:sfx:sfx/crow-s501.wav` | `78c5f69ff31758d2` | 882044 | job_dir, wan_pvc |
| `r3:sfx:sfx/crunch-s601.wav` | `5515c7006ce09a1c` | 882044 | job_dir, wan_pvc |
| `r3:sfx:sfx/gavel-s801.wav` | `a9c01ef381a0f0d0` | 882044 | job_dir, wan_pvc |
| `r3:sfx:sfx/sting-s901.wav` | `aadcc283d15fb7a0` | 882044 | job_dir, wan_pvc |
| `r3:bed:sfx/fire-s701.wav` | `0b33af45929b8cfb` |  | job_dir |
| `r3:take:voices/line-1.wav` | `b9fa04b49038c15c` | 247852 | job_dir, wan_pvc |
| `r3:take:voices/line-2.wav` | `7d5d2d890c1072a2` | 129068 | job_dir, wan_pvc |
| `r3:take:voices/line-3.wav` | `6efd27569ac328e1` | 233516 | job_dir, wan_pvc |
| `r3:take:voices/line-4.wav` | `0063d7e0e0d8a551` | 118828 | job_dir, wan_pvc |
| `r3:take:voices/line-5.wav` | `f89e05a2c53e9be7` | 116780 | job_dir, wan_pvc |
| `r3:take:voices/line-6.wav` | `46bf17ecaa3a9729` | 206892 | job_dir, wan_pvc |
| `r3:take:voices/line-8.wav` | `37e81c9db699303d` | 48172 | job_dir, wan_pvc |
| `r3:take:voices/line-8-1.wav` | `1dadd22ef158db12` | 38956 | job_dir, wan_pvc |
| `r3:take:voices/line-8-2.wav` | `1e5206395dc510de` | 42028 | job_dir, wan_pvc |
| `r3:take:voices/line-8-3.wav` | `5fc1718e8659568b` | 24620 | job_dir, wan_pvc |
| `r3:take:voices/line-8-4.wav` | `9b3ba267baecf440` | 49196 | job_dir, wan_pvc |
| `r3:take:voices/line-8-5.wav` | `3cd7c24827ff5c87` | 70700 | job_dir, wan_pvc |
| `r3:take:voices/line-9.wav` | `4e12138ee373ac45` | 47148 | job_dir, wan_pvc |
| `r4:still:cutouts/a-proud.png` | `4ea3005f4effebda` | 1850605 | job_dir, wan_pvc |
| `r4:still:cutouts/b-deadpan.png` | `d44fc8299598c56e` | 1615055 | job_dir, wan_pvc |
| `r4:still:cutouts/c-suspicious.png` | `a49b2c3046f385d4` | 1775253 | job_dir, wan_pvc |
| `r4:still:cutouts/d-shocked.png` | `3d9c9d223ebc0137` | 1649760 | job_dir, wan_pvc |
| `r4:still:cutouts/a-staring.png` | `022ac97a623c88bf` | 1616411 | job_dir, wan_pvc |
| `r4:still:cutouts/c-staring.png` | `b816a4f225e160a6` | 1547710 | job_dir, wan_pvc |
| `r4:set:cutouts/set.png` | `29ab6f47227cee7a` | 2390590 | job_dir, wan_pvc |
| `r4:sfx:sfx/crow-s501.wav` | `78c5f69ff31758d2` | 882044 | job_dir, wan_pvc |
| `r4:sfx:sfx/crunch-s601.wav` | `5515c7006ce09a1c` | 882044 | job_dir, wan_pvc |
| `r4:sfx:sfx/gavel-s801.wav` | `a9c01ef381a0f0d0` | 882044 | job_dir, wan_pvc |
| `r4:sfx:sfx/sting-s901.wav` | `aadcc283d15fb7a0` | 882044 | job_dir, wan_pvc |
| `r4:bed:sfx/fire-s701.wav` | `0b33af45929b8cfb` |  | job_dir |
| `r4:take:voices/line-1.wav` | `b9fa04b49038c15c` | 247852 | job_dir, wan_pvc |
| `r4:take:voices/line-2.wav` | `7d5d2d890c1072a2` | 129068 | job_dir, wan_pvc |
| `r4:take:voices/line-3.wav` | `6efd27569ac328e1` | 233516 | job_dir, wan_pvc |
| `r4:take:voices/line-4.wav` | `0063d7e0e0d8a551` | 118828 | job_dir, wan_pvc |
| `r4:take:voices/line-5.wav` | `f89e05a2c53e9be7` | 116780 | job_dir, wan_pvc |
| `r4:take:voices/line-6.wav` | `46bf17ecaa3a9729` | 206892 | job_dir, wan_pvc |
| `r4:take:voices/line-8.wav` | `37e81c9db699303d` | 48172 | job_dir, wan_pvc |
| `r4:take:voices/line-8-1.wav` | `1dadd22ef158db12` | 38956 | job_dir, wan_pvc |
| `r4:take:voices/line-8-2.wav` | `1e5206395dc510de` | 42028 | job_dir, wan_pvc |
| `r4:take:voices/line-8-3.wav` | `5fc1718e8659568b` | 24620 | job_dir, wan_pvc |
| `r4:take:voices/line-8-4.wav` | `9b3ba267baecf440` | 49196 | job_dir, wan_pvc |
| `r4:take:voices/line-8-5.wav` | `1be02e6d7b243b57` | 55340 | job_dir, wan_pvc |
| `r4:take:voices/line-9.wav` | `4e12138ee373ac45` | 47148 | job_dir, wan_pvc |
| `r4:keyframe:s1.png` | `e4772edc3fe3f0f9` |  | wan_upload |
| `r4:keyframe:s2.png` | `c146760e9f500194` |  | wan_upload |
| `r4:keyframe:s3.png` | `ba88a2f9ecf4a543` |  | wan_upload |
| `r4:keyframe:s4.png` | `e4772edc3fe3f0f9` |  | wan_upload |
| `r4:keyframe:s5.png` | `47146e2c14a27387` |  | wan_upload |
| `r4:keyframe:s6.png` | `ba88a2f9ecf4a543` |  | wan_upload |
| `r4:keyframe:s7.png` | `6c270139b4beb523` |  | wan_upload |
| `r4:keyframe:s8.png` | `e66494d67f4cc0fd` |  | wan_upload |
| `r4:keyframe:s9.png` | `f10f0460ba764d09` |  | wan_upload |
<!-- recovery-map:end -->
