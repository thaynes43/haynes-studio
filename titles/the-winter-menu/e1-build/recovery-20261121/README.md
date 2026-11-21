# Recovering the quieter-gavel cut, 2026-11-21

Story https://work.haynesnetwork.com/work_packages/941 (from story
https://work.haynesnetwork.com/work_packages/428, comment 9467). Session
`haynes-studio-1121-002318`, claude-opus-5-5. No media is in this folder: only the
hashes, the key documents and the three one-off scripts that ran.

**States.** Source: no package code changed. Tested: every rebuilt artifact matches
its committed hash (below). Installed: **not done.** No private link exists for this cut
yet (see "Delivery"). Accepted: Tom's verdict is pending and separate.

## What was lost

The edited run `run_01M7C5CJA7XKBCRPM0ZRP2P5RS` (board 8 gavel cue
`cue_01M7BVBVSBHA26B6V3F90A35N9`, -20 to -23 dBFS RMS; [run log step m](../run-log.md))
lived only in the store on session `haynes-studio-1114-013021`. On 2026-11-21 that
Session, its PVC and its PV were gone (`agent-run show`: 404; `kubectl get pvc,pv`:
none). There is no rescue bundle under `~/.shared/rescue/`. The Wan volume has no
ledger, production or file naming the run, its delivery
`dlv_01M7C5D3KFX3MFVWCXBCVJHMG7` or the hashes `92d1efa3...` and `0212a7de...`. Its
newest ledger is still `d009d615...` (2026-11-14). `/studio` on `ai/studio-render`
holds only E0 files. **No verified copy survived.**

## What was done — Proven

All reads were read-only. The takes, the sounds and the first delivery's
`final.mp4` and `proxy.mp4` came from `/workspace/output/productions/` with
`kubectl exec ... cat`. The fire bed came from the audio service's stored output of
the build's own job `ebe4a478...` (`GET /artifacts/<job>/output.wav`). Nothing new was
generated. Everything went into a new job folder in this session's home
(`~/studio-jobs/winter-menu-quieter-gavel-20261121/`). Every input re-hashed equal to
the hash its run record names ([`files.sha256`](files.sha256)). CPU only: `nice -n 10`,
two threads.

| Step | Script | Control: first run `run_01M7C56SZ6...` | Edit: `run_01M7C5CJA7...` |
|---|---|---|---|
| 8 board voice tracks, `voice.track.assemble` from the 13 takes and the placement's spans | `rebuild_mix.py` | 8 of 8 equal | 8 of 8 equal |
| Mix key document from the placement record (story mix: line -22, master -20 LUFS, true peak -3.5) | `rebuild_mix.py` | `e3e04183...` = recorded | `7859a266...` = recorded |
| Mix, `mix.mixer.mix` (`studio.mixer/1:74339957ebf46e78`) | `rebuild_mix.py` | `5a13ee14...` = recorded | **`af68dea8...` = recorded** |
| Master, `mix.master.mux` over the video packets of the surviving first master | `rebuild_master.py` | `f6fd041a...` = the served file | **`92d1efa3...` = recorded** |
| Phone proxy, `delivery.media.make_proxy` at 720x1280, two threads | `rebuild_proxy.py` | `22287356...` = the served file | **`0212a7de...` = recorded**, 12 986 556 bytes |

The edit's picture is the first run's picture: same key `ed390fb9...` and hash
`adb7b091...` (run log step m). `mux` copies only the picture's video packets, so
`rebuild_master.py` first remuxes the surviving master's video stream into a video-only
MP4. That file (`e92ee998...`) is not the original picture file, but the control shows
the master depends only on the packets: the first master rebuilt byte for byte.

**Result:** the master `92d1efa3a30c4de10c62298cd25c20671f729ab1acf257ad7cdfaecd9edb09bc`
and the proxy `0212a7de9d6b7816c4c4d3c98bfd6d8e80fc112163944152e399b3e980a6748d` are the
historical quieter-gavel outputs, byte for byte. This is not an approximation. The
recorded run's checks (mix and master loudness, true peak, clipping, and the transcript
`pass`) were measured on these same bytes on 2026-11-14. They were not re-run: the
transcript check needs the Whisper service, which runs on a GPU.

Timings: copying the inputs took seconds (77 MB); each mix and master took under a
minute; each proxy took 6.3 s of wall time.

## Delivery — blocked, needs a decision

- `studio private-view` (story 863) publishes only from a store that holds a
  `studio build` run record and its verified delivery. These files have neither.
- A new `studio build` in a fresh store cannot recreate that record without GPU work.
  It would ask for 11 new Wan jobs, because there is no journal to collect the old
  ones from, so its picture would be a new film. It would also make one Whisper request.
- `poc/deliver.py` (runbook stage 7) takes a PoC job folder: a manifest,
  `validation.json`, a transcript file, shot images and speech files. Feeding it means
  hand-made PoC records for a studio cut. Its folder check is also the one the PR 70
  review found weak against a second writer.

Writing a store and run record by hand to satisfy `studio private-view` would invent
provenance, so it was not done. The options are on story 941.
