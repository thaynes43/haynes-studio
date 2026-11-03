# Manual PoC: making a doll short by hand

This runbook covers making one doll short from brief to private delivery using
in-cluster services, with an agent driving each step and Tom approving at the gates.
It is meant to be repeated: the first run on "The Winter Menu"
([`titles/the-winter-menu/`](../../titles/the-winter-menu/brief.md)) will correct it.

Each step is marked:

- **Proven**: done before and delivered a result (the evidence is linked).
- **Expected**: the plan, not yet run in this setup.
- **Changed**: what the run actually did differently. Add these as you go.

Every stage below has now run once, end to end, for **The Winter Menu** revision 1
(2026-11-03): four dolls, six shots, 27.6 s, delivered privately. Evidence is in
[`titles/the-winter-menu/`](../../titles/the-winter-menu/), and the
[run log](../../titles/the-winter-menu/run-log.md) has timings, failures and the hand work at each step. The
scripts are in [`poc/`](../../poc/README.md).

Read first: [services](../reference/services.md), [doll format](../reference/doll-format.md),
[OP345 baseline](../reference/baseline-op345.md), and [AGENTS.md](../../AGENTS.md).

OP345 evidence (all in haynes-ops): `.agents/evidence/crunchy-butter-dolls-2026-11-01/`
([on GitHub](https://github.com/thaynes43/haynes-ops/tree/main/.agents/evidence/crunchy-butter-dolls-2026-11-01)).

## Overview

| # | Stage | Output | Who | Status |
|---|---|---|---|---|
| 0 | Set up the job | story, worktree, job directory, venv | agent | **Proven** ([run log](../../titles/the-winter-menu/run-log.md)) |
| 1 | Brief and script | `titles/<slug>/brief.md`, `manifest.json` | agent drafts, **Tom approves** | **Proven** ([brief](../../titles/the-winter-menu/brief.md), [manifest](../../titles/the-winter-menu/manifest.json)) |
| 2 | Cast and set images | doll cutouts, expression variants, set plate | agent, **Tom approves** | **Changed**, worked in-cluster for the Winter Menu ([run log](../../titles/the-winter-menu/run-log.md)) |
| 3 | Voices | one WAV per line, `speech.json` | agent | **Proven** ([speech.json](../../titles/the-winter-menu/evidence/speech.json)) |
| 4 | Sound effects | cue WAVs, recorded in `manifest.json` | agent | **Proven** (crow cue; [timeline.json](../../titles/the-winter-menu/evidence/timeline.json), source in [manifest](../../titles/the-winter-menu/manifest.json)) |
| 5 | Edit | master WAV, `final.mp4` | agent | **Proven**, multi-doll and group shots ([shots.json](../../titles/the-winter-menu/evidence/shots.json), [timeline.json](../../titles/the-winter-menu/evidence/timeline.json); r2 with motion, fire and limiter: [shots.json](../../titles/the-winter-menu/evidence-r2/shots.json), [timeline.json](../../titles/the-winter-menu/evidence-r2/timeline.json)) |
| 6 | Check | `validation.json`, transcript, contact sheet | agent | **Proven** ([validation.json](../../titles/the-winter-menu/evidence/validation.json), [dialogue-transcript.json](../../titles/the-winter-menu/evidence/dialogue-transcript.json); r2 with motion, fire and limiter: [validation.json](../../titles/the-winter-menu/evidence-r2/validation.json), [dialogue-transcript.json](../../titles/the-winter-menu/evidence-r2/dialogue-transcript.json)) |
| 7 | Deliver | private link, production ledger | agent | **Proven** ([production.json](../../titles/the-winter-menu/evidence/production.json); r2 with motion, fire and limiter: [production.json](../../titles/the-winter-menu/evidence-r2/production.json)) |
| 8 | Review and record | Tom's verdict, run log, evidence in git | **Tom**, agent | Expected |

Keep a **run log** (`titles/<slug>/run-log.md`) from stage 0 onward. For every step
record: start and end time, the exact command or request, inputs and outputs with
SHA256 hashes, failures and retries, and how much hand work it took. The tooling
backlog is written from these notes.

## Stage 0: set up the job

1. **Story.** Save a Story in OpenProject under the right Epic (see AGENTS.md), with
   scope, acceptance, budget and stop criteria, and link the title.
2. **Worktrees.** You need this repo and a haynes-ops checkout (for the source scripts
   and stored ComfyUI graphs):

   ```bash
   git clone --filter=blob:none https://github.com/thaynes43/haynes-studio ~/repos/haynes-studio
   git -C ~/repos/haynes-studio worktree add ~/work/<slug> -b agent/<slug>
   # haynes-ops is normally already at ~/repos/haynes-ops; otherwise clone it the same way
   ```

3. **Job ID and directory.** Pick a job ID `<slug>-r<N>` (revision N, starting at 1)
   and create a job directory outside the repo:

   ```bash
   mkdir -p ~/studio-jobs/<slug>-r1   # fails nothing if new; never reuse one with outputs
   ```

   A new attempt is a new revision. The job directory is on the session volume:
   rescue does not cover it (rescue only saves git worktrees) and archiving the
   session deletes it. Deliver to the PVC (stage 7) before the session ends, and copy
   chosen images out to safety as soon as Tom approves them.
4. **Python venv** for editing (no system packages needed):

   ```bash
   python3 -m venv "$HOME/.cache/studio-venv"
   "$HOME/.cache/studio-venv/bin/python" -m pip install \
     av==18.1.0 numpy==2.4.6 Pillow==13.0.0 imageio-ffmpeg==0.7.0
   ```

   Plus `scipy==1.16.3` for cutouts. Proven on a fresh session pod (Python 3.11.2),
   2026-11-03, in about a minute.
5. **Scripts.** Use this repo's `poc/` scripts, driven by a title manifest
   (`titles/<slug>/manifest.json`). They replace hand-patching OP345's scripts in
   haynes-ops, which hard-code that production's paths, shot count and length. Set
   `job_dir` in the manifest to the job directory.
6. **Reference assets (optional).** To reuse OP345's cast or audio, recover them
   read-only with the checksummed script in the haynes-ops handoff, section "Recover
   the existing private cast". The handoff is on haynes-ops PR
   [#4621](https://github.com/thaynes43/haynes-ops/pull/4621) and may not be on
   `main` yet; read it with
   `git -C ~/repos/haynes-ops fetch origin agent/haynes-studio-handoff && git -C ~/repos/haynes-ops show 1401a2ee:.agents/handoffs/2026-11-03-haynes-studio-video-generation.md`.
   Run the script from the root of a haynes-ops checkout (it reads relative
   `.agents/evidence/...` paths). It writes into `~/artifacts/haynes-studio-reference/`
   and refuses to overwrite. Treat recovered files as inputs, never as a place to
   render.
7. **Service check.** Before any generation, confirm the pods are up and idle:

   ```bash
   kubectl get pod -n ai comfyui-0
   kubectl get deploy -n ai kokoro whisper wan-video
   kubectl exec -n ai comfyui-0 -c app -- python3 -c \
     'import urllib.request;print(urllib.request.urlopen("http://127.0.0.1:8188/queue").read().decode())'
   kubectl exec -n ai deploy/wan-video -c api -- df -h /workspace
   ```

   An earlier success is not a readiness check. If a queue is busy with someone
   else's work, wait; never cancel it.

## Stage 1: brief and script

Write `titles/<slug>/brief.md` (copy the shape of the Winter Menu brief):

- premise in two or three sentences, and the parody source if there is one;
- cast: one line of look and personality per doll, plus the voice you intend;
- shot list: shot number, framing (single or group), who speaks, the line, the
  expression, and any sound cue;
- what stays original (names, team names, logos, dialogue).

Then write `titles/<slug>/manifest.json`: the cast and their voices, the shots (dolls
and cutout per shot, layout, line, start offset, tail, cues), the set and its
foreground edge, the cue files, and the mastering target. See the Winter Menu manifest.

Rules of thumb from OP345:

- About 6 to 12 words per line. Each line starts about 0.5 s into its shot and must end
  at least 0.25 s before the cut.
- Expression changes and the punchline land on cuts.
- Avoid words a recognizer will mishear. OP345 changed one line after the
  transcript heard "once" for "one".

**Gate 1:** Tom approves the script and every detail the images depend on (cast
looks, costume text such as a team name, the set) before any assets are generated.
Record his reply in the run log. Line wording may still be tuned after hearing the
voices (stage 3); note any change and let Tom see it at gate 3.

## Stage 2: cast and set images

Goal: for each doll, one base cutout plus one image per expression the script needs,
all showing the same doll; and one empty 9:16 set plate.

**Done for the Winter Menu (Changed from the plan):** in-cluster with ComfyUI and
**Qwen-Image 2.1 int8** for both text-to-image and edits. The helpers live in `poc/`:
`comfy.py` (submit and fetch), `cutout.py` (keying) and `contact_sheet.py`. Records
are in `titles/the-winter-menu/prompts.json`.

1. **Use the model the household keeps warm.** Home Assistant's renders use Qwen-Image
   2.1 int8 on the same 16 GB card. The stored 2512 graph's fp8 model is 19.5 GB,
   cold-loaded for 10+ minutes, and blocked their renders; its steps are also
   hard-coded at 50. Use `poc/graphs/qwen_image_2_1_t2i_API.json` (hand-converted
   from the UI template: 25 steps, cfg 1) and haynes-ops'
   `qwen_image_2_1_edit_API.json` for edits. About 70 s per image once warm.
2. **Base doll**, text-to-image at 1104x1472, two seeds per doll:

   ```bash
   python3 poc/comfy.py t2i --job $JOB --name a-base-s101 \
     --prompt-file titles/<slug>/prompts/a-base.txt --seed 101 --size 1104x1472
   ```

   `comfy.py` waits for an idle queue, sends `{"prompt": graph, "client_id": ...}`
   from inside `comfyui-0`, polls `/history`, fetches through `/view`, writes
   `<name>.png` create-only, and appends `records.jsonl` (seed, timings, sha256).
   Prompt structure: toy material, hair, eyes and facing, fixed expression, costume,
   pose and prop, then framing, lighting, a flat **#00FF00** backdrop and exclusions.
   Qwen-Image 2.1 spelled a team name on the costume correctly 8 times out of 8.
3. **Expressions**, edit the chosen base:

   ```bash
   python3 poc/comfy.py edit --job $JOB --name a-staring-s301 \
     --image $JOB/a-base-s101.png --prompt-file titles/<slug>/prompts/a-staring.txt --seed 301
   ```

   Say "change only the molded facial expression to ..." and list everything to keep.
   Identity held very well. The edit graph returns about 1 MP (896x1184), so scale
   edits back to the base size when cutting out (below).
4. **Set**, text-to-image at 928x1664 (the editor fits it to 1080x1920). Put the
   focal prop (the campfire) in a side third, or the dolls will hide it. Never mention
   a doll in a set prompt, not even "beside a doll": Qwen paints one in.
5. **Cutouts:**

   ```bash
   OPENBLAS_NUM_THREADS=2 ~/.cache/studio-venv/bin/python poc/cutout.py $JOB/a-base-s101.png $JOB/cutouts/a-proud.png \
     --protect 540,380,760,520                 # eye box, only for a green-eyed doll
   OPENBLAS_NUM_THREADS=2 ~/.cache/studio-venv/bin/python poc/cutout.py $JOB/a-staring-s301.png $JOB/cutouts/a-staring.png \
     --resize 1104x1472 --protect 540,380,760,520
   ```

   It keys green connected to the frame edge, large pockets, and gaps in the hair;
   subtracts the backdrop out of semi-transparent edge pixels; and despills a band
   around the edge. Painted green eyes key like hair gaps, so protect them, or better,
   pick a backdrop color the doll does not wear. It needs `scipy==1.16.3` in the venv.
6. **Contact sheets** with `poc/contact_sheet.py` for each review. Send them to Tom.
7. **Copy outputs out at once.** ComfyUI deletes outputs after 30 days; `comfy.py`
   already writes every result into the job directory.

**Gate 2:** Tom approves the cast and the set. Iterate here, not in the edit.

**Fallback:** if Qwen cannot keep a doll consistent across expressions or the cutouts
are unusable, write down the specific failure with examples and ask Tom whether to
use Gemini or OpenAI image APIs. That needs his approval, a cost cap and a key he
provisions. Do not use an agent harness's built-in image tool as a quiet substitute:
it does not leave a repeatable record.

## Stage 3: voices

1. **List the voices** installed now (54 on 2026-11-03) and cast one clearly different
   stock voice per doll in the manifest's `cast`:

   ```bash
   kubectl exec -i -n ai deploy/kokoro -c app -- python - <<'PY'
   import asyncio
   from wyoming.client import AsyncTcpClient
   from wyoming.info import Describe, Info
   async def main():
       async with AsyncTcpClient('127.0.0.1', 10210) as c:
           await c.write_event(Describe().event())
           while True:
               e = await asyncio.wait_for(c.read_event(), 10)
               if Info.is_type(e.type):
                   print(' '.join(v.name for p in Info.from_event(e).tts for v in p.voices)); return
   asyncio.run(main())
   PY
   ```

2. **Synthesize and pre-check every line:**

   ```bash
   cd poc && python3 speech.py ../titles/<slug>/manifest.json
   ```

   Writes `voices/line-<shot>.wav` and `speech.json` (voice, text, duration, SHA256)
   create-only, and transcribes each line on its own. About 1 s per line.
3. **Listen.** An agent cannot; Tom or a person must. A transcript mismatch on one
   line may be the recognizer's spelling (digits for numbers, "MOS" for "moss"). Declare
   known ones in the manifest's `asr_tolerances`, which apply word by word.
4. Shot lengths come from these durations in stage 5 (start + speech + tail), so lines
   are never trimmed to fit.

## Stage 4: sound effects

1. For each cue, call `generate_sound` on the audio-authoring MCP server with a short
   descriptive prompt, a length (5 to 30 s) and a fixed seed; two candidates is enough.
   About 6 s each on CPU. Poll `get_generation`, then download and verify:

   ```bash
   curl -sf -o $JOB/sfx/<cue>-s<seed>.wav \
     http://audio-authoring.dev.svc.cluster.local:8000/artifacts/<job-id>/output.wav
   echo "<sha256>  $JOB/sfx/<cue>-s<seed>.wav" | sha256sum -c -
   ```

2. Find the useful moment (an energy envelope shows where the sound is) and record the
   file, `trim` window, `gain_db`, source job, seed and prompt in the manifest's `sfx`.
   Reject candidates that are continuous noise.
3. Keep cues quiet and sparse (the crow sat at -26 dBFS RMS before mastering).

Video-conditioned Foley (ControlFoley, OP344) exists but shares the Wan GPU lease, and
its listening verdict is still open. Do not use it unless Tom asks.

## Stage 5: edit

`poc/edit.py` is OP345's rigid puppet editor, driven by the manifest. Each stage is
create-only in `$JOB/<out>/`, and each attempt gets its own `--out` folder:

```bash
cd poc; M=../titles/<slug>/manifest.json
~/.cache/studio-venv/bin/python edit.py $M audio   --out edit     # mix and master, under 1 s
~/.cache/studio-venv/bin/python edit.py $M preview --out edit     # one still per shot, about 5 s
nice -n 19 ~/.cache/studio-venv/bin/python edit.py $M render --out edit   # about 3.5 min for 27 s
```

0. **Revision 2 features** (`manifest-r2.json` shows each one in use):
   - `motion` (talk hop, tilt, shuffle, idle scale): the speaking doll bounces on her
     syllables, taken from her voice envelope at 12 poses/s.
   - Per-shot `moves` (`doll`, `at`, `dur`, `dx`, `dy`, `angle`): jerky held-step
     lunges and recoils, for example the group turning on someone.
   - `set.fire` (`box`, `glow_center`, `glow_radius`, `strength`, `doll_glow`,
     `seed`): animated flame and firelight.
   - `beds`: a looped ambience under the whole film.
   - `render --picture-from <out>`: re-mux new audio onto an existing picture when the
     shot timing is unchanged.
   Revision 3 (`manifest-r3.json`) added:
   - `lines`: several lines per shot, each after a `gap`, each speaker bouncing on her
     own line.
   - `after_line` and `offset` on cues and moves: anchor a gavel or a jump to the end
     of a line.
   - The close-up shot type: a slot `crop`, `foreground: false`, and a `camera` push-in
     (`zoom`, `over`, `center`).
   - `asr_phrase_tolerances`: exact word sequences only.
   - `render` checks every placement before encoding.
1. **Layout first, with previews.** For each layout, set doll `height`, `x` and
   `bottom` (per doll in group layouts; the order of `dolls` is back to front). Preview
   until every face reads and the set's focal prop shows. Then render.
2. **Occlusion edge.** The dolls are cut off at the waist, so the set's foreground
   prop (a log) is pasted back over them. Measure its top edge on the fitted
   1080x1920 set with a ruler overlay and give it as a polyline
   (`set.foreground_edge: [[x, y], ...]`, plus `foreground_feather`). The editor
   refuses a doll whose waist is not hidden across her whole width.
3. **Audio** places each line at its shot start plus `start`, normalizes it to
   -22 dBFS RMS, adds cues and beds, leaves headroom, then masters to the loudness
   target (-20 LUFS) with a peak limiter 1 dB under the true-peak target, as 48 kHz
   24-bit. Without the limiter, one loud transient (a crunch) held r2 at -28.7 LUFS.
4. **Render** applies the rigid held-pose motion (12 poses/s inside 24 fps, one phase
   per doll), pastes the foreground over the dolls, encodes H.264 CRF 18 with 2
   threads, writes a contact sheet and a per-frame transform log, then muxes
   `final.mp4` (AAC 192 kbit/s).

## Stage 6: check

```bash
~/.cache/studio-venv/bin/python edit.py $M validate   --out edit
~/.cache/studio-venv/bin/python edit.py $M transcript --out edit
```

`validate` checks frame count against the timeline, duration, size, face art fixed
within each shot, motion present, loudness within 1.5 LU of target, true peak at or
below -2.5 dBTP, and no clipping.
`transcript` sends the movie's audio to the Whisper pod and requires a match with the
script after the declared tolerances. Then watch the contact sheet and the movie.

## Stage 7: deliver

```bash
python3 deliver.py ../titles/<slug>/manifest.json --out edit
```

It refuses unless both checks passed, checks free space, copies every asset
create-only (each file is written to a temp name, hash-checked, then hard-linked into
place, so an interrupted copy leaves nothing behind; a file already there with the same
SHA256 is skipped, so a delivery that failed partway can simply be rerun; a different
file at that path stops it) to `/workspace/output/productions/<job>/` on PVC `ai/wan-video` (SHA256
verified per file), validates the ledger fields the Wan API depends on, hard-links the
ledger into `/workspace/jobs/`, reads it back through the API in the pod, and writes
`$JOB/production.json`. About 5 s. **A malformed ledger would crash the shared Wan API
on its next restart**, which is why the script validates it first.

The printed `https://video.haynesops.com/videos/<id>/file` opens only on the home
network. A session pod cannot open it: verify from inside the API container
(`127.0.0.1:8080/videos/<id>`), and send Tom the movie file directly as well.

## Stage 8: review and record

1. **Gate 3:** send Tom the link. Record his verdict in the run log, word for word,
   separate from the technical checks.
2. Commit to `titles/<slug>/`: `brief.md`, `manifest.json`, `prompts.json`,
   `run-log.md`, and `evidence/` (`speech.json`, `timeline.json`, `shots.json`,
   `validation.json`, `dialogue-transcript.json`, `production.json`). Text and hashes
   only; the media stays on the PVC.
3. Update this runbook: mark each stage **Proven** with a link to the evidence, or
   add a **Changed** note.
4. Comment on the story with the link, commit and verdict, and list proposed tooling
   stories (from the run log's slowest and most manual steps) for Tom to groom.

## Known gaps

- Voices, cues and comic timing are chosen without listening; a person has to.
- Layout and occlusion are hand-tuned numbers. Four fixed-pose cutouts crowd a 9:16
  frame.
- Cutouts need hand-tuned keying (and an eye-protect box for green-eyed dolls).
- Subtitle sources (HaynesTower or Bazarr) are not connected; this title did not need
  them.
- Delivery depends on the Wan API pod and its unbacked 80 Gi PVC.
- The proposed tooling that closes these gaps is in
  [`docs/proposals/0003-studio-plan.md`](../proposals/0003-studio-plan.md).
