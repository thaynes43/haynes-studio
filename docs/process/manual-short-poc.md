# Manual PoC: making a doll short by hand

This runbook covers making one doll short from brief to private delivery using
in-cluster services, with an agent driving each step and Tom approving at the gates.
It is meant to be repeated: the first run on "The Winter Menu"
([`titles/the-winter-menu/`](../../titles/the-winter-menu/brief.md)) will correct it.

Each step is marked:

- **Proven**: done before and delivered a result (the evidence is linked).
- **Expected**: the plan, not yet run in this setup.
- **Changed**: what the run actually did differently. Add these as you go.

Right now everything that has never run outside OP345 is **Expected**. The first
manual run updates every stage it touches.

Read first: [services](../reference/services.md), [doll format](../reference/doll-format.md),
[OP345 baseline](../reference/baseline-op345.md), and [AGENTS.md](../../AGENTS.md).

## Overview

| # | Stage | Output | Who | Status |
|---|---|---|---|---|
| 0 | Set up the job | story, worktree, job directory, venv | agent | Expected |
| 1 | Brief and script | `titles/<slug>/brief.md` | agent drafts, **Tom approves** | Expected |
| 2 | Cast and set images | doll cutouts, expression variants, set plate | agent, **Tom approves** | Expected (OP345 used Codex's own image tool) |
| 3 | Voices | one WAV per line, `speech.json` | agent | Proven (OP345) |
| 4 | Sound effects | cue WAVs, `sfx.json` | agent | Proven service (OP343); new cues Expected |
| 5 | Edit | `picture.mp4`, master WAV, final MP4 | agent | Proven for 2 dolls x 4 shots (OP345); multi-doll Expected |
| 6 | Check | `validation.json`, transcript, contact sheet | agent | Proven (OP345) |
| 7 | Deliver | private link, production ledger | agent | Proven (OP345) |
| 8 | Review and record | Tom's verdict, run log, evidence in git | **Tom**, agent | Expected |

Keep a **run log** (`titles/<slug>/run-log.md`) from stage 0 onward. For every step
record: start and end time, the exact command or request, inputs and outputs with
SHA256 hashes, failures and retries, and how much hand work it took. The tooling
backlog is written from these notes.

## Stage 0: set up the job

1. **Story.** Save a Story in OpenProject under the right Epic (see AGENTS.md), with
   scope, acceptance, budget and stop criteria, and link the title.
2. **Worktree.** Clone with `git clone --filter=blob:none
   https://github.com/thaynes43/haynes-studio ~/repos/haynes-studio` if needed, then
   `git -C ~/repos/haynes-studio worktree add ~/work/<slug> -b agent/<slug>`.
3. **Job ID and directory.** Pick a job ID `<slug>-r<N>` (revision N, starting at 1)
   and a job directory outside the repo: `~/studio-jobs/<slug>-r<N>/`. Never reuse a
   directory that already holds outputs; a new attempt is a new revision.
4. **Python venv** for editing (no system packages needed):

   ```bash
   python3 -m venv "$HOME/.cache/studio-venv"
   "$HOME/.cache/studio-venv/bin/python" -m pip install \
     av==18.1.0 numpy==2.4.6 Pillow==13.0.0 imageio-ffmpeg==0.7.0
   ```

   These versions worked on Python 3.11 for OP345. They have not been checked on a
   fresh pod yet.
5. **Reference assets (optional).** To reuse OP345's cast or audio, recover them
   read-only with the checksummed script in the haynes-ops handoff
   (`.agents/handoffs/2026-11-03-haynes-studio-video-generation.md`, "Recover the
   existing private cast"). It writes into `~/artifacts/haynes-studio-reference/` and
   refuses to overwrite. Treat recovered files as inputs, never as a place to render.
6. **Service check.** Before any generation, confirm the pods are up and idle:

   ```bash
   kubectl get pod -n ai comfyui-0
   kubectl get deploy -n ai kokoro whisper wan-video
   kubectl exec -n ai comfyui-0 -c app -- python3 -c \
     'import urllib.request;print(urllib.request.urlopen("http://127.0.0.1:8188/queue").read().decode())'
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

Rules of thumb from OP345:

- About 6 to 12 words per line. Each line starts about 0.5 s into its shot and must end
  at least 0.25 s before the cut.
- Expression changes and the punchline land on cuts.
- Avoid words a recognizer will mishear. OP345 changed one line after the
  transcript heard "once" for "one".

**Gate 1:** Tom approves the script before any assets are generated. Record his reply
in the run log.

## Stage 2: cast and set images

Goal: for each doll, one base cutout plus one image per expression the script needs,
all showing the same doll; and one empty 9:16 set plate.

**Plan (Expected):** generate in-cluster with ComfyUI.

1. **Base doll.** Text-to-image with Qwen-Image 2.1 (or 2512) on a plain flat
   background (one solid color that does not appear on the doll, such as pure green
   or mid-gray), waist-up or full body as the shot list needs, with the whole hair
   silhouette in frame and padding around it. Reuse the OP345 prompt structure from
   haynes-ops `.agents/evidence/crunchy-butter-dolls-2026-11-01/prompts.json`:
   "original fashion doll, glossy molded plastic, visible joints, exaggerated
   sculpted expression, not a real person, no text, no logos", plus the title's
   costume.
2. **Expressions.** Image edit with Qwen-Image-Edit (2509, optionally the Lightning
   4-step LoRA) on the base doll: "change only the molded facial expression to ...;
   keep identity, hair, costume, pose, lighting and background". Check each result
   side by side with the base: same doll, different face, nothing else moved.
3. **Set.** Text-to-image of the empty miniature location in 9:16 with the middle
   70% clear, plus a foreground strip (log, rock, table edge) across the bottom 15 to
   20% to hide the dolls' cut-off bodies.
4. **Cutouts.** Qwen output has no alpha channel. Remove the flat background with a
   chroma key in Pillow and NumPy (color distance, then a small feather and despill),
   or with a matting model if keying fails on frizzy hair. Note which method worked
   and where it broke: hair edges are the hard part.
5. **Submit through the in-pod API**, one prompt at a time:
   - Start from a stored API-format graph in haynes-ops
     `kubernetes/main/apps/ai/stable-diffusion/comfyui/resources/api-workflows/`.
     There is no API-format Qwen-Image 2.1 text-to-image graph yet, so either export
     `image_qwen_image_2_1_t2i.json` to API format or start from
     `image_qwen_Image_2512_API.json`.
   - POST the graph JSON to `http://127.0.0.1:8188/prompt` from inside `comfyui-0`
     (`kubectl exec -i ... python3 -c ...` reading the graph from stdin), poll
     `/history/<prompt_id>`, then fetch the image with `/view?filename=...`, piped
     back over the same exec.
   - Put source images for edits into ComfyUI's input folder through
     `POST /upload/image`.
   - Save every graph you submit, its seed and prompt, and the output's SHA256 into
     `titles/<slug>/prompts.json`. ComfyUI also embeds the graph in each PNG.
6. **Copy outputs out at once.** ComfyUI deletes outputs after 30 days. Keep the
   chosen and rejected images in the job directory with hashes.
7. **Contact sheet.** Make one image of all candidates (Pillow) for Tom.

**Gate 2:** Tom approves the cast and the set. Iterate here, not in the edit.

**Fallback:** if Qwen cannot keep a doll consistent across expressions or the cutouts
are unusable, write down the specific failure with examples and ask Tom whether to
use Gemini or OpenAI image APIs. That needs his approval, a cost cap and a key he
provisions. Do not use an agent harness's built-in image tool as a quiet substitute:
it does not leave a repeatable record.

## Stage 3: voices (Proven, OP345)

1. List the installed voices with a Wyoming `Describe` to the Kokoro pod and pick one
   clearly different stock voice per doll. Record the choice in the brief.
2. For each line, send `{"voice": ..., "text": ...}` through the Wyoming client
   (`CODE` in haynes-ops `scripts/wan-video/butter_speech.py`):

   ```bash
   kubectl exec -i -n ai deploy/kokoro -c app -- python -c "$CODE" \
     < line.json > voice-N.wav
   ```

   OP345's `doll_speech.py` loops over the lines, checks each WAV is 0.5 to 5 s long,
   and writes `speech.json` with voice, text, duration and SHA256.
3. Listen to every line. If a word comes out wrong, rephrase the line; Kokoro has no
   per-word controls in this setup.
4. Check the timing: each line's duration plus its start offset must fit its shot
   with 0.25 s to spare. If not, lengthen the shot in the shot list. Do not trim the
   speech.

## Stage 4: sound effects

1. For each cue in the brief, call `generate_sound` on the audio-authoring MCP server
   with a short descriptive prompt, a duration and a fixed seed. Poll
   `get_generation`, then download `/artifacts/<job-id>/output.wav` and verify its
   checksum. A few candidates per cue is enough.
2. Trim each cue to the moment you need, and record source job ID, seed, trim points
   and SHA256 in `sfx.json`.
3. Keep cues quiet and sparse. OP345 placed one cue at about -34 dBFS RMS.

Video-conditioned Foley (ControlFoley, OP344) exists but shares the Wan GPU lease and
its listening verdict is still open. Do not use it for this PoC unless Tom asks.

## Stage 5: edit

The editor is a CPU compositor in Python (Pillow, NumPy, PyAV, ffmpeg). The OP345
version is haynes-ops `scripts/wan-video/edit_doll_short.py`, see
[the baseline](../reference/baseline-op345.md).

1. **Copy, then change as little as possible.** Copy the editor and its helpers into
   this repo under `poc/` for the run, and change the hard-coded parts: job
   directory, shot list, characters, voice offsets, cue placement. For the Winter Menu
   the editor also needs a group shot (several cutouts in one frame) and shot lengths
   other than 5 s. Record every change in the run log: each one is a requirement for
   the renderer epic.
2. **Audio stage.** Place each line at its shot start plus offset, normalize per line,
   add cues, then master (target -20 LUFS integrated, -3.5 dBTP) to a 48 kHz 24-bit
   WAV.
3. **Picture stage.** For each shot: fit the cutouts to the frame, place them, apply
   the rigid held-pose motion, put the foreground strip back on top, and stream raw
   frames to ffmpeg (`libx264`, CRF 18, `-threads 2`). Write a contact sheet (3 frames
   per shot) and a per-frame transform log.
4. **Mux** picture and master into the final MP4 (AAC 192 kbit/s, `+faststart`).
5. Run with bounded CPU:

   ```bash
   OPENBLAS_NUM_THREADS=2 "$HOME/.cache/studio-venv/bin/python" poc/edit_doll_short.py audio
   OPENBLAS_NUM_THREADS=2 "$HOME/.cache/studio-venv/bin/python" poc/edit_doll_short.py render
   ```

Stages refuse to run over their own outputs. To redo a stage, start a new revision
directory and copy in the inputs you are keeping.

## Stage 6: check

Automated, all must pass before delivery:

- decoded frame count equals duration x 24 and duration is within 0.05 s of the plan;
- every shot shows the intended cutouts, and the face image changes only at cuts;
- integrated loudness about -20 LUFS, true peak at or below -2.5 dBTP, zero clipped
  samples;
- transcript of the final movie matches the script after normalization (Whisper pod,
  client `CODE` in haynes-ops `scripts/wan-video/check_butter_dialogue.py`, 16 kHz
  mono input).

By eye and ear (the agent, before Tom sees it):

- watch the contact sheet and the whole movie: hair edges, foreground strip, framing;
- listen for clipped or overlapping lines and cues landing on the wrong beat.

Write the results to `validation.json` and `dialogue-transcript.json`.

## Stage 7: deliver

Save the production to private storage so Tom can watch it:

1. Copy each asset create-only to `/workspace/output/productions/<job-id>/` on PVC
   `ai/wan-video`, verifying SHA256 on arrival.
2. Link a ledger JSON into `/workspace/jobs/<ledger-id>.json` with kind
   `edited_production`, the title, the story, the asset list and provenance (which
   models made the images, voices and cues, and that faces are not animated).
3. The Wan API then serves `https://video.haynesops.com/videos/<ledger-id>/file`.

`preserve_doll_short.py` in haynes-ops does exactly this for OP345. Copy it and
replace every `op345`/`OP345` path, story and title, or it will collide.

Check free space on the PVC first (80 Gi, no backup).

## Stage 8: review and record

1. **Gate 3:** send Tom the link. Record his verdict in the run log, word for word,
   separate from the technical checks.
2. Commit to `titles/<slug>/`: `brief.md` (final), `prompts.json`, `speech.json`,
   `sfx.json`, `timeline.json`, `validation.json`, `dialogue-transcript.json`,
   `production.json` and `run-log.md`. Text and hashes only; the media stays on the
   PVC.
3. Update this runbook: mark each stage **Proven** with a link to the evidence, or
   add a **Changed** note.
4. Comment on the story with the link, commit and verdict, and list proposed tooling
   stories (from the run log's slowest and most manual steps) for Tom to groom.

## Known gaps before the first run

- No in-cluster image step has been tried for this format. Doll consistency across
  expressions and hair-edge cutouts are the main risks.
- No API-format Qwen-Image 2.1 text-to-image graph is stored.
- The editor supports only one doll per shot and four 5 s shots.
- The venv versions have not been checked on a fresh pod.
- Subtitle sources (HaynesTower or Bazarr) are not connected; this title does not need
  them.
- Delivery depends on the Wan API pod and its unbacked PVC.
