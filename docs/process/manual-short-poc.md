# Manual PoC: making a doll short by hand

This runbook covers making one doll short from brief to private delivery using
in-cluster services, with an agent driving each step and Tom approving at the gates.
It is meant to be repeated: the first run on "The Winter Menu"
([`titles/the-winter-menu/`](../../titles/the-winter-menu/brief.md)) will correct it.

Each step is marked:

- **Proven**: done before and delivered a result (the evidence is linked).
- **Expected**: the plan, not yet run in this setup.
- **Changed**: what the run actually did differently. Add these as you go.

Stages marked Proven worked for OP345, two dolls in four 5 s shots, using that
production's scripts. Everything else is Expected until a run in this repo proves it.
The first manual run updates every stage it touches.

Read first: [services](../reference/services.md), [doll format](../reference/doll-format.md),
[OP345 baseline](../reference/baseline-op345.md), and [AGENTS.md](../../AGENTS.md).

OP345 evidence (all in haynes-ops): `.agents/evidence/crunchy-butter-dolls-2026-11-01/`
([on GitHub](https://github.com/thaynes43/haynes-ops/tree/main/.agents/evidence/crunchy-butter-dolls-2026-11-01)).

## Overview

| # | Stage | Output | Who | Status |
|---|---|---|---|---|
| 0 | Set up the job | story, worktree, job directory, venv, copied scripts | agent | Expected |
| 1 | Brief and script | `titles/<slug>/brief.md` | agent drafts, **Tom approves** | Expected |
| 2 | Cast and set images | doll cutouts, expression variants, set plate | agent, **Tom approves** | **Changed**, worked in-cluster for the Winter Menu ([run log](../../titles/the-winter-menu/run-log.md)) |
| 3 | Voices | one WAV per line, `speech.json` | agent | Proven for OP345 (`speech.json` in the evidence) |
| 4 | Sound effects | cue WAVs, `sfx.json` | agent | Service proven ([OP343](https://work.haynesnetwork.com/work_packages/343)); new cues Expected |
| 5 | Edit | `picture.mp4`, master WAV, final MP4 | agent | Proven for 2 dolls x 4 shots (`timeline.json`, `validation.json`); multi-doll Expected |
| 6 | Check | `validation.json`, transcript, contact sheet | agent | Proven for OP345 (`validation.json`, `dialogue-transcript.json`) |
| 7 | Deliver | private link, production ledger | agent | Proven for OP345 (`production.json`, `delivery.json`) |
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
5. **Copy the OP345 scripts** into this repo under `poc/` (the editor and its helpers
   import each other by module name, so copy all of them):

   ```bash
   mkdir -p poc
   for f in doll_speech butter_speech edit_doll_short edit_butter edit_short \
            check_doll_dialogue check_butter_dialogue preserve_doll_short; do
     cp ~/repos/haynes-ops/scripts/wan-video/$f.py poc/
   done
   ```

   `butter_speech.py` holds the Kokoro client (`CODE`) and `check_butter_dialogue.py`
   the ASR client (`CODE`). What has to change in each is listed in
   [the baseline](../reference/baseline-op345.md#what-is-fixed-in-the-code).
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
   ~/.cache/studio-venv/bin/python poc/cutout.py $JOB/a-base-s101.png $JOB/cutouts/a-proud.png \
     --protect 540,380,760,520                 # eye box, only for a green-eyed doll
   ~/.cache/studio-venv/bin/python poc/cutout.py $JOB/a-staring-s301.png $JOB/cutouts/a-staring.png \
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

## Stage 3: voices (Proven for OP345)

1. **List the voices** installed now and pick one clearly different stock voice per
   doll. Record the choice in the brief. A Wyoming `Describe` returns them (Expected,
   not yet run):

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
                   for p in Info.from_event(e).tts:
                       for v in p.voices:
                           print(v.name)
                   return
   asyncio.run(main())
   PY
   ```

2. **Synthesize each line.** Edit `poc/doll_speech.py`: set `OUT` to the job directory
   and `LINES` to `(character, voice, text)` tuples, one per line. It sends each line
   through the Kokoro client (`CODE` from `butter_speech.py`), checks the WAV length,
   and writes `voice-N.wav` and `speech.json` with voice, text, duration and SHA256:

   ```bash
   cd poc && python3 doll_speech.py
   ```

   It refuses to run if any `voice-N.wav` already exists. It asserts each line is
   under 5 s; raise that bound if a shot is longer. To send one line by hand instead:

   ```bash
   CODE=$(cd poc && python3 -c 'from butter_speech import CODE; print(CODE)')
   echo '{"voice":"af_bella","text":"Hello."}' |
     kubectl exec -i -n ai deploy/kokoro -c app -- python -c "$CODE" > test.wav
   ```

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

The editor is a CPU compositor in Python (Pillow, NumPy, PyAV, ffmpeg):
`poc/edit_doll_short.py`, copied in stage 0. See [the baseline](../reference/baseline-op345.md).

1. **Change as little as possible**, and make every change in the copy under `poc/`.
   The baseline lists the values fixed for OP345: total length, 5 s shots, two
   characters, the set mirroring, the foreground strip height, the cue path, frame
   counts in the checks. For the Winter Menu the editor also needs a group shot
   (several cutouts in one frame). Record every change in the run log: each one is a
   requirement for the renderer epic.
2. **Audio stage.** Places each line at its shot start plus offset, normalizes per
   line, adds cues, then masters (target -20 LUFS integrated, -3.5 dBTP) to a 48 kHz
   24-bit WAV.
3. **Picture stage.** For each shot: fits the cutouts to the frame, places them,
   applies the rigid held-pose motion, pastes the foreground strip back on top, and
   streams raw frames to ffmpeg (`libx264`, CRF 18, `-threads 2`). Writes a contact
   sheet (3 frames per shot) and a per-frame transform log, then muxes picture and
   master into the final MP4 (AAC 192 kbit/s, `+faststart`).
4. Run with bounded CPU, from `poc/`:

   ```bash
   cd poc
   OPENBLAS_NUM_THREADS=2 "$HOME/.cache/studio-venv/bin/python" edit_doll_short.py audio
   OPENBLAS_NUM_THREADS=2 "$HOME/.cache/studio-venv/bin/python" edit_doll_short.py render
   ```

Stages refuse to run over their own outputs. To redo a stage, start a new revision
directory and copy in the inputs you are keeping.

## Stage 6: check

Run both, from `poc/`:

```bash
OPENBLAS_NUM_THREADS=2 "$HOME/.cache/studio-venv/bin/python" edit_doll_short.py validate
OPENBLAS_NUM_THREADS=2 "$HOME/.cache/studio-venv/bin/python" check_doll_dialogue.py
```

`validate` writes `validation.json`; it checks:

- decoded frame count equals duration x 24, and duration is within 0.05 s of the plan
  (OP345 hard-codes 480 frames: change it to the new length);
- each shot uses one source image per doll, so the face changes only at cuts (OP345
  also requires a new expression whenever a doll returns: drop that rule if the
  script keeps a doll's expression, as the Winter Menu does for doll B);
- true peak at or below -2.5 dBTP and zero clipped samples (aim for about -20 LUFS
  integrated).

`check_doll_dialogue.py` sends the movie's audio (16 kHz mono) to the Whisper pod
and writes `dialogue-transcript.json`. It fails unless the normalized transcript
matches the script.

Then by eye and ear (the agent, before Tom sees it):

- watch the contact sheet and the whole movie: hair edges, foreground strip, framing;
- listen for clipped or overlapping lines and cues landing on the wrong beat.

## Stage 7: deliver

Save the production to private storage so Tom can watch it. `poc/preserve_doll_short.py`
does this; it was written for OP345, so first:

- replace every `op345`/`OP345` path, story and title;
- rewrite the `provenance` text so it is true for this title (which models made the
  images, voices and cues; OP345's text names a different image tool and voices);
- update the asserted frame count and the list of file names (it expects exactly
  four voices and OP345's image names).

What it does:

1. Copies each asset create-only to `/workspace/output/productions/<job-id>/` on PVC
   `ai/wan-video`, verifying SHA256 on arrival.
2. Links a ledger JSON into `/workspace/jobs/<ledger-id>.json`. **The ledger must be
   valid**: the Wan API reads every ledger in that folder when it starts, without
   error handling, so a malformed file would crash the shared video service on its
   next restart. Required fields: `id` (32 lowercase hex characters, the same as the
   file name), `state: "succeeded"`, `output` (path relative to `/workspace/output`,
   ending in `.mp4`), plus `kind: "edited_production"`, `title`, `story`, `assets`,
   `bytes`, `sha256`, `created_at`, `finished_at`, `telemetry: []`, `preset` and
   `provenance`. Check the JSON before linking it.
3. Prints `https://video.haynesops.com/videos/<ledger-id>/file` for Tom.

That link is for Tom's devices on the home network. A session pod cannot open it
(the name resolves to a LAN address its egress does not allow). Confirm delivery from
inside the API container instead:

```bash
kubectl exec -n ai deploy/wan-video -c api -- python3 -c \
  'import urllib.request;print(urllib.request.urlopen("http://127.0.0.1:8080/videos/<ledger-id>").read().decode())'
```

## Stage 8: review and record

1. **Gate 3:** send Tom the link. Record his verdict in the run log, word for word,
   separate from the technical checks.
2. Commit to `titles/<slug>/`: `brief.md` (final), `prompts.json`, `speech.json`,
   `sfx.json`, `timeline.json`, `validation.json`, `dialogue-transcript.json`,
   `production.json` and `run-log.md`. Text and hashes only; the media stays on the
   PVC. Commit the changed `poc/` scripts too.
3. Update this runbook: mark each stage **Proven** with a link to the evidence, or
   add a **Changed** note.
4. Comment on the story with the link, commit and verdict, and list proposed tooling
   stories (from the run log's slowest and most manual steps) for Tom to groom.

## Known gaps before the first run

- The editor supports only one doll per shot, four 5 s shots and a 20 s total.
- Subtitle sources (HaynesTower or Bazarr) are not connected; this title does not need
  them.
- Delivery depends on the Wan API pod and its unbacked PVC, and agents cannot open
  the delivery link themselves.
