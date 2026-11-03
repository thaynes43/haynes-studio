# Run log: The Winter Menu, revision 1

Job ID `the-winter-menu-r1`, job directory `~/studio-jobs/the-winter-menu-r1/` (session
volume, not in git). Times are UTC. Times taken from `records.jsonl` (`at`, finish
time) or file timestamps are exact; times marked "about" were not measured. Story
[368](https://work.haynesnetwork.com/work_packages/368) for stages 0 and 2.

## Stage 0: setup (2026-11-03)

- About 15:40: story 368 filed under Epic 366. The claim was refused (the agent role
  has no transition out of Ungroomed in `haynes-studio`); proceeding on Tom's direct
  go-ahead.
- About 15:41: worktree `~/work/winter-menu-images` (branch `agent/winter-menu-images`)
  and the job directory created.
- About 15:42: venv `~/.cache/studio-venv` installed from the runbook's pins. Clean on a
  fresh pod (Python 3.11.2), about 1 min. **Stage 0 venv step: Proven.**
- About 15:43: ComfyUI check showed version 0.39.0, RTX 2000 Ada 16 GB, and 1 job
  running that was not ours.

## Stage 2: cast and set images

- About 15:45: prompts written for dolls A to D and the set (`prompts/`), following
  the OP345 prompt structure, with a flat chroma-green backdrop for keying.
  `poc/comfy.py` written: submits one graph from inside `comfyui-0`, waits for an idle
  queue, saves create-only, appends `records.jsonl`.
- 15:51:16: first attempt with the runbook's suggested
  `image_qwen_Image_2512_API.json`. **Changed / failed:**
  - The stored 2512 graph hard-codes KSampler `steps: 50`. Its Lightning switch only
    changes cfg and the LoRA, so "fast mode" would still run 50 steps.
  - The 2512 fp8 model is 19.5 GB on a 16 GB card. Cold-loading it off NFS sat at
    "Model Initializing" for more than 10 minutes, while two Home Assistant renders
    (Qwen-Image 2.1 int8) queued behind it.
  - About 16:02: interrupted **our own** prompt `b29c53cb` by ID
    (`POST /interrupt {prompt_id}`, client ID checked first) so the household renders
    could go through. No output.
- About 16:03: switched to Qwen-Image 2.1 int8 for text-to-image and edits, the model
  Home Assistant keeps warm, so neither side evicts the other. No API-format 2.1
  text-to-image graph existed, so `poc/graphs/qwen_image_2_1_t2i_API.json` was
  hand-converted from the UI template (25 steps, cfg 1, euler/simple, same models).
- 16:08:44: `a-base-s101` done after waiting 280 s behind household renders, rendered in
  **69 s** at 1104x1472. Good quality: clearly a plastic doll with joints, feral hair
  and twig crown, smug smile, moss, and "YELLOWBIRDS" spelled correctly (the zipper
  splits it, which reads fine).
- 16:10:02 to 16:22:11: batch of 9 (second seed for A, two each for B, C and D, two
  sets), one at a time, 66 to 75 s each, with 140 s total waiting behind household
  renders. All 8 dolls spell **YELLOWBIRDS** correctly; some stack it on two lines.
  D came out with one side ponytail rather than pigtails on both seeds.
- 16:10 to about 16:20, while the batch ran: **cutout (chroma key), three iterations**
  with `poc/cutout.py` on `a-base-s101`:
  1. A plain dominance key left a green halo in frizzy hair.
  2. A despill band with lower thresholds still left olive hair tips, and A's **green
     eyes went partly transparent** (they key as green).
  3. Final version: the background is green connected to the frame edge, large
     enclosed pockets, or strongly green islands (gaps in the hair). In a band around
     the background, the backdrop color is subtracted out of semi-transparent pixels,
     followed by a stronger despill. Needs `scipy` (`scipy==1.16.3` added to the venv).
  - Painted green eyes and the green gaps in the hair have the same color statistics
    (median RGB about 75,140,55 for both), so no color rule separates them. The
    workaround is a manual `--protect X0,Y0,X1,Y1` box around the eyes, per image.
  - **Tooling requirement:** choose the backdrop per doll so it clashes with nothing on
    her (magenta for a green-eyed doll), or use a proper matting model.
- 16:22:18: base and set contact sheets built. The agent's picks: A `s101` (more feral
  hair), B `s101` (half-lidded and facing left, as specced), C `s101` (suspicious;
  `s102` reads angry), D `s101` (biggest grin, visible joints). Both sets were good, but
  the campfire sat in the center, where the dolls would hide it. Sheets sent to Tom
  at about 16:23.
- 16:24:31 to 16:26:44: expression edits A-staring, C-staring and D-shocked (Qwen-Image
  2.1 edit graph, 63 to 66 s each). Identity held very well: same hair, jacket,
  lettering, prop and pose, with only the face changed. **Changed:** the edit graph
  scales its input to about 1 megapixel, so edits come back at 896x1184 instead of
  1104x1472. Cut out unscaled, a doll would shrink when her expression changes at a
  cut, and the eye-protect box would miss. Added `cutout.py --resize 1104x1472`.
- 16:29:04 and 16:30:14: the first fire-left sets (`s211`, `s212`) each had **a doll
  painted into the scene**. The prompt said "visible beside a doll standing in the
  centre" (the original wording is kept in `prompts/set-fire-left-v1.txt`). Reworded
  and re-rendered as `s221` (16:31:38) and `s222` (16:33:58). Picked
  **`set-left-s221`**: fire in the left third, lean-to and pot on the right, log across
  the bottom.
  - **Editor requirement:** OP345 scales dolls to nearly the full frame width, which
    would hide the fire. Place dolls smaller or off-center in stage 5.
- 16:30:32 to 16:30:56: seven cutouts made (`a-proud`, `a-staring`, `b-deadpan`,
  `c-suspicious`, `c-staring`, `d-cheerful`, `d-shocked`), and redone with `--resize` for
  the three edits. Clean at video scale over a forest color. Hashes and settings are in
  `prompts.json`.
- **Tom's verdicts** (exact message times not captured):
  - On the base sheet: "Great", then "Yes I like the sheet I said Great. You have a
    green light this exercise is more around documenting what tooling we need to use
    and automate." Read as: **the agent's base picks are approved**, and the run may go
    on without stopping for routine approvals. It is not a sign-off on the finished
    cut: gate 3 still goes to Tom.
  - The final cutouts and `set-left-s221` were sent to Tom after that (about 16:50) for
    information. No separate verdict on them is recorded yet.

### Stage 2 summary

- 18 ComfyUI jobs: 17 completed (8 chosen) and 1 interrupted. 63 to 75 s per render
  once warm, plus 600 s of waiting behind household renders in total. Stage 2 wall
  time was about 15:45 to 16:35, roughly 50 minutes, much of it hand work: writing
  prompts, judging candidates, tuning the key.
- Hand work that tooling should absorb, in order of cost:
  1. **Cutouts:** three keying iterations, a manual eye-protect box, and the
     edit-size mismatch. Needs a matting model or a per-doll backdrop color, plus
     automatic size matching to the base.
  2. **Candidate review:** contact sheets built by hand, picks typed into notes. A
     review UI with pick and reject that writes `prompts.json` automatically.
  3. **Prompt assembly:** costume and style text copied between files. Needs a cast
     library (doll identity, costume, expression list) that composes prompts.
  4. **Graph handling:** no stored API-format 2.1 text-to-image graph; the 2512
     graph's steps are hard-coded. Needs a small graph library with named
     parameters.
  5. **Shared-GPU etiquette:** queue waits, and choosing a model that does not evict
     the household's. Needs a job queue that knows which models are warm.
