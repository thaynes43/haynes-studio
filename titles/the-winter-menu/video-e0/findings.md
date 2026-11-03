# E0 findings: The Winter Menu as Wan video

Epic [387](https://work.haynesnetwork.com/work_packages/387). Job `winter-menu-video`
(session volume), r4 script, cast, voices and soundtrack. Times UTC, 2026-11-03.

## Setup

- Renders use the OP342 path through the Wan API's own `generate()` under
  `/workspace/compute.lock` (`poc/wan.py`): cool-idle gate (API idle, queue empty, both
  GPUs < 62 C and <= 5 % busy), keyframe uploaded create-only, ledger and telemetry kept.
  No API change, no pod restart.
- Model: Wan2.2 TI2V-5B (the only Wan model deployed), 576x1024, 121 frames (5.04 s at
  24 fps), 20 steps, cfg 5, two-GPU CFG split.
- Keyframes: composed from r4's cutouts, set and layouts by `poc/keyframes.py`.

## Whole-frame (E0.2)

### Shot 1 (`s1-wf-a`, seed 101)

- **152 s** to render 5.04 s; card C (GPU-d8a856f1) peaked at **88 C**, about 2 min of
  cooldown back to the 62 C gate. Effective rate about 4.5 min per 5 s clip.
- **Motion: good.** The doll sways and turns as if handled; frizzy hair moves; the fire
  flickers and dances.
- **Identity: drifts.** The molded smile reshapes and the face turns from three-quarter to
  frontal and back. Wan treats the doll as a person, not a rigid toy.
- **Text: destroyed.** "YELLOWBIRDS" becomes "YELLOW BHBD" within a second at 576 px.

### Rate (shots 1 to 3)

- `s1-wf-x1` 122 s render + 75 s cooldown; `s2-wf-a` 122 s + 146 s; `s3-wf-a` 127 s + 156 s.
  **Steady state about 4.5 min per 5 s clip, and the cooldown costs more than the render.**
  The 62 C start gate (from OP342) is conservative; card C reaches 84 to 88 C under load.
  **Scheduler requirement:** a measured thermal policy (for example start below 70 C, with
  a hard stop at 88 C), not a fixed cool-idle wait.

### Drift (end frames vs keyframes)

- **Shot 1, two chained clips:** A's face goes fully frontal, her hair restyles, the jacket
  reads "YELLOWBHBDS", the moss shrinks, and the lean-to disappears from the set.
  **Chaining compounds drift**; longer cuts need another method (first-last-frame
  conditioning back to the keyframe, a slower clip, or shorter cuts).
- **Shot 2 (B):** nearly perfectly stable, lettering intact. A frontal, simple pose with
  hands folded holds up.
- **Shot 3 (C):** the face turns toward camera and the expression hardens; **a plant
  appears** bottom-right that was never in the set. Wan invents objects.
- **Requirement:** automatic drift checks per clip: face similarity to the keyframe
  (embedding distance), text OCR on costume lettering, and a set-difference check for new
  objects, with re-roll or method switch on failure. This is exactly the shepherd's
  technical-check job (E5) and needs a vision model or classical CV in E2.

### Hard shots

- **Shot 5 (D protests, single):** good protest motion (recoil, shake), but by frame 120 the
  **yellow squishy has become a glowing orange flame** and the campfire behind her has
  gone. **Props drift too**, especially toward visually similar elements (a bright yellow
  prop next to a fire).
- **Shot 7 (close-up):** the face holds almost perfectly (little motion), but **the camera
  push-in in the prompt never happens.** Camera moves belong in the compositor (as in r3),
  not in the prompt.
- **Shot 8 (four dolls):** the group **rearranges**. By the end the squishy is held by a
  different doll, A faces the camera, and B's face has changed. **Multi-character
  whole-frame shots are the least reliable**, and the vote gag (who said "Nay!") depends on
  exactly that identity.
- **Pattern so far:** single, frontal, simple poses survive. Three-quarter poses turn
  toward camera, props migrate, groups reshuffle, lettering decays, and chaining
  compounds all of it.
- **Rate:** steady at 121 to 127 s render plus about 156 s cooldown (card C) per clip,
  about 4.7 min per 5 s of footage. A 45 s film needs about 14 clips, about 66 min of GPU
  wall time per whole-frame version.

### Whole-frame film

- Assembled from 15 clips (shots 1, 3 and 8 chained) in **40 s** of CPU: with Wan supplying
  the motion, there's no per-frame compositing; the CPU only scales (576x1024 to 1080x1920,
  Lanczos) and encodes. Master 64 MB, review copy 24 MB. Sent to Tom.
- Total GPU wall time for the 15 clips: about 70 min (render plus cooldown).

## Layered (E0.3), shot 1

- Inputs: one Wan clip of the empty set (`layer-set-loop`) and one of A on flat green
  (`layer-a-green`), 121 frames each; both ping-ponged to the shot's 153 frames.
- **Identity much better than whole-frame:** on a plain green background Wan moves the doll
  and her hair but keeps the face (three-quarter pose and smile hold through the shot).
- **Lettering still decays** ("YELLOW BIRD"). It's Wan re-rendering the doll that loses
  text, whatever the method. **Requirement:** for branded costumes, protect lettering (a
  decal layer composited rigidly over the jacket, or no text at Wan sizes), or accept the
  drift.
- **Keying Wan output works** with `cutout.key` (20/70 thresholds, eye-protect box for the
  green-eyed doll); faint green spill in the hair, as in the PoC.
- **Prompt side effect:** "an unseen child plays with her" made Wan **draw a child's hand** at
  the frame edge in the green clip (hidden by the log here). **Never mention hands or people
  in motion prompts.**
- **Syllable-synced bounce works on top of Wan motion**, which is the combination Tom asked
  for in r1.
- CPU compositing: 58 s for 6.4 s of footage at 2 threads (about 9 s per second), plus keying.
- Cost per single-doll shot: one set loop (reusable across every shot on that set) plus one
  doll clip per doll per expression. **Set loops are reusable assets**, which suits the
  library (E2).
- Side-by-side of shot 1 (whole-frame vs layered) sent to Tom.

## Speech-to-video (E0.4)

- Provisioned by haynes-ops [PR 4625](https://github.com/thaynes43/haynes-ops/pull/4625)
  (prepared by a Sonnet worker, merged by the driver once the Wan pod was idle):
  `wan2.2_s2v_14B_fp8_scaled` (16.4 GB), `wav2vec2_large_english_fp16` (0.63 GB),
  `wan_2.1_vae` (0.25 GB), Apache-2.0, pinned with sha256. Merging rolled the Wan pod
  (Reloader, Recreate); its init container downloaded about 15.9 GiB at about 23 MiB/s,
  **about 12 min of Wan downtime.** **Requirement:** model changes are scheduled
  maintenance with the queue drained; the studio should show "GPU service provisioning"
  rather than fail jobs.
- ComfyUI 0.39 core nodes cover S2V (`WanSoundImageToVideo`, `...Extend`,
  `AudioEncoderLoader`/`Encode`). Its own template: 20 steps, cfg 6, uni_pc/simple, shift 8,
  **16 fps**, 77-frame chunks with Extend nodes for longer audio. 16 fps differs from our
  24 fps delivery, so the assembler must resample.
- `poc/s2v.py`: the same lease path as `wan.py`; uploads the keyframe and line WAV; length
  is sized to the line plus 0.4 s (4k+1 frames).
- **First S2V attempt failed (shot 2, 576x1024, 53 frames, one GPU):** about **61 s per step**
  on card C alone (100 %, 88 C; card A idle at 310 MiB), 20 steps, so about 20.6 min. It was
  killed by the Wan API's 20-minute job limit at step 19. The API's timeout path worked: it
  sent a global interrupt, the queue cleared within about 15 s, no hold was raised, and the
  job is recorded as failed. Nothing was delivered.
  - **Requirements:** (1) the scheduler must know model size and speed per job type and
    set realistic timeouts (14B S2V is about 12x slower per frame than 5B TI2V); (2) S2V
    must use both cards (CFG split), and the template's 4-step lightx2v LoRA is worth
    provisioning (about 5x fewer steps); (3) the API's interrupt is global, not by
    prompt ID, which is safe today only because one job runs at a time.
- Retry with `MultiGPU_WorkUnits` (two model copies, CFG split) and 49 frames.
- **Retry succeeded (shot 2, 576x1024, 49 frames, 16 fps, two-GPU CFG split):** **724 s
  (12 min) for 3.06 s**, peak 21.4 GB per card. That's about **4 min of GPU per second of
  footage, about 4x whole-frame TI2V.** A 45 s film all in S2V would be about 3 hours.
- **What it does:** the body follows the speech: hand gestures, head turns and nods on the
  phrases, and the lettering mostly holds. **It lip-syncs**: B's molded mouth opens and
  shows teeth on the words, which breaks the fixed-face doll look (a creative call for Tom).
  The first frame has a brief exposure and eye artifact; trim 1 to 2 frames.
- **Requirements:** S2V is a premium shot type (talking close-ups, punchlines), not the
  default; the scheduler budgets it explicitly; the 4-step LoRA should be tested to cut it
  about 5x; 16 fps output needs frame-rate conversion for 24 fps delivery.

## Not measured in E0

- **NFS write contention with nas01:** the gasha01 studio folder doesn't exist yet, and a
  session pod has no LAN egress to the NAS. This is open, and is measured when E3
  provisions the folder.
- **Upscaling quality:** Lanczos 576x1024 to 1080x1920 (1.875x) is visibly soft on hair and
  lettering in the assembled film. No AI upscaler is deployed. **Open:** test an upscaler
  model in E2 (on the studio GPUs, with its licence recorded), or render Wan at 720x1280
  where the model allows it.

## Foley (E0.5)

- `poc/foley.py`: POST `/foley` on the Foley service with the Wan job ID of `s1-wf-a`
  (0 to 5 s, seed 3441); its own lease and cool-idle guards. **Succeeded in 83 s**, checksum
  verified. This is the first full post-fix HTTP generation (open since OP344).
- Levels: peak -4.6 dBFS, -31.7 LUFS integrated, envelope median -36.6 dB, p95 -29.9 dB
  (sparse events over a low bed). A demo of the Foley take under A's line was sent to Tom;
  **listening verdict pending**, since ear judgment is the gap here.

## What E0 means for the plan

1. **The method is per shot, not per film.** **Layered** (Wan set loop plus a Wan doll layer
   on green, keyed, with syllable-synced bounce) best keeps identity and gives the bounce
   Tom asked for. **Whole-frame** suits ambient, establishing and single simple-pose
   shots, and assembles in seconds. **Speech-to-video** is a premium talking shot (about
   4x the GPU, and it moves mouths). The render engine (E1) needs per-shot methods and a
   compositor for **animated** layers, generalizing the PoC editor's still cutouts.
2. **Drift checks are mandatory.** Faces turn, props morph (the squishy became fire), groups
   reshuffle, sets lose objects or gain new ones, and chaining compounds all of it. The
   shepherd (E5) needs automatic checks (face similarity to the keyframe, OCR on lettering,
   new and missing object detection) with re-roll and method-switch policies. E2 provides
   the tools: a vision model and/or classical CV.
3. **Lettering never survives Wan.** Branded costume text needs a rigid decal layer
   composited after Wan, or no text.
4. **Prompts are assets with rules.** Never mention hands or people (Wan drew a child's
   hand); camera moves go to the compositor (Wan ignored the push-in); reusable prompt
   fragments live in the library.
5. **The GPU scheduler is the heart of throughput** (E3), extending the one Wan lease:
   - Job types with known costs: TI2V 5B about 2 min per 5 s clip; S2V 14B about 12 min
     per 3 s; Foley about 1.5 min per 5 s window.
   - Per-type timeouts (a fixed 20 min killed S2V).
   - Two-GPU CFG split by default.
   - A **thermal policy** instead of the 62 C start gate (cooldown cost more than render).
   - Prompt-ID interrupts, not global ones.
   - Model provisioning as scheduled maintenance (about 12 min of downtime per 16 GB).
6. **Reusable motion assets** (E2): set loops (render once per set) and per-doll,
   per-expression motion clips on a chroma colour chosen against the doll's palette.
   **Rough throughput for a 45 s short:** whole-frame about 70 min of GPU; layered less
   once set loops and doll clips are reused; all-S2V about 3 h. Every extra 5 s cut is
   about 4.7 min whole-frame at current thermals.
7. **Delivery quality:** an upscaler for 576x1024 to 1080x1920 (Lanczos is soft), and
   16 fps to 24 fps conversion for S2V.
8. **The Wan API needs real job types** (E0.1 becomes product work in E3): image-to-video
   portrait, S2V, Foley-on-clip, each a sanctioned job with its own cost model. The OP342
   in-pod path was fine for a PoC but isn't a product interface.
9. **Ear and taste stay with Tom:** S2V mouths, Foley sound, voice and timing. The storyboard
   (E6) must make A/B listening and watching quick.
