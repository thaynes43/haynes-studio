# Run log: The Winter Menu, revision 1

Job ID `the-winter-menu-r1`, job directory `~/studio-jobs/the-winter-menu-r1/` (session
volume, not in git). Times are UTC. Story
[368](https://work.haynesnetwork.com/work_packages/368) for stages 0 and 2.

## Stage 0: setup (2026-11-03)

- 15:40 Story 368 filed under Epic 366. Claim refused (agent role has no transition
  out of Ungroomed in `haynes-studio`); proceeding on Tom's direct go-ahead.
- 15:41 Worktree `~/work/winter-menu-images` (branch `agent/winter-menu-images`).
  Job directory created.
- 15:42 Venv `~/.cache/studio-venv` from the runbook's pins: installed cleanly on a
  fresh pod (Python 3.11.2), about 1 min. **Stage 0 venv step: Proven.**
- 15:43 ComfyUI check: version 0.39.0, RTX 2000 Ada 16 GB, 1 job running (not ours).

## Stage 2: cast and set images

- 15:45 Prompts written for dolls A to D and the set (`prompts/`), following the
  OP345 prompt structure, flat chroma-green background for keying.
- 15:46 Wrote `poc/comfy.py`: submits one graph from inside `comfyui-0`, waits for an
  idle queue, saves create-only, appends `records.jsonl`.
- 15:51 First attempt with the runbook's suggested `image_qwen_Image_2512_API.json`.
  **Changed / failed:**
  - The stored 2512 graph hard-codes KSampler `steps: 50`. Its Lightning switch only
    changes cfg and the LoRA, so "fast mode" would still run 50 steps.
  - The 2512 fp8 model is 19.5 GB on a 16 GB card. Cold-loading it off NFS sat at
    "Model Initializing" for 10+ minutes, while two Home Assistant renders (Qwen-Image
    2.1 int8) queued behind it.
  - 16:02 Interrupted **our own** prompt by ID (`POST /interrupt {prompt_id}`, verified
    client ID first) to let the household renders through. No output.
- 16:05 Switched to Qwen-Image 2.1 int8 for text-to-image and edits: the model Home
  Assistant keeps warm, so neither side evicts the other. No API-format 2.1
  text-to-image graph existed, so `poc/graphs/qwen_image_2_1_t2i_API.json` was
  hand-converted from the UI template (25 steps, cfg 1, euler/simple, same models).
- 16:08 First Qwen-Image 2.1 render (`a-base-s101`): waited 280 s for household
  renders, rendered in **69 s** at 1104x1472, 25 steps. Quality is good: clearly a
  plastic doll with joints, feral hair and twig crown, smug smile, moss, and
  "YELLOWBIRDS" spelled correctly. The zipper splits the lettering, which reads fine.
- 16:10 Batch of 9 more candidates queued (A, B, C, D second seeds and the set), one at
  a time.
- 16:10–16:30 **Cutout (chroma key), three iterations** with `poc/cutout.py`:
  1. Plain dominance key: frizzy hair kept a green halo.
  2. Despill band around the background with lower thresholds: hair tips still
     olive, and A's **green eyes went partly transparent** (they key as green).
  3. Final: background = green regions touching the frame edge, large enclosed
     pockets, or strongly green islands (hair gaps). In a band around the background,
     the backdrop color is subtracted out of semi-transparent pixels, then a stronger
     despill. Needs `scipy` (added to the venv: `scipy==1.16.3`).
  - Painted green eyes and the green gaps in the hair have the same color statistics
    (median RGB about 75,140,55 for both), so no color rule separates them. The
    workaround is a manual `--protect X0,Y0,X1,Y1` box around the eyes, per image.
  - **Tooling requirement:** choose the backdrop per doll so it clashes with nothing
    on her (magenta for a green-eyed doll), or use a proper matting model. Hand-tuned
    keying is the slowest manual step so far.
- 16:12–16:35 Batch: 7 doll candidates and 2 sets rendered sequentially (about 70 s
  each, plus waits behind household renders). All 8 dolls spell **YELLOWBIRDS**
  correctly. Some stack it on two lines, and the zipper splits it on others.
  - Picks (agent): A `s101` (more feral hair), B `s101` (half-lidded, facing left, as
    specced), C `s101` (suspicious; `s102` reads angry), D `s101` (biggest grin,
    visible joints). D came out with one side ponytail, not pigtails, on both seeds.
  - Sets: both look good, but the campfire sits in the center, where the dolls will
    stand and hide it. Re-rendering with the fire in the left third
    (`prompts/set-fire-left.txt`; the editor mirrors the set for other characters, so
    the fire alternates sides).
- 16:37 Base and set contact sheets sent to Tom. Expression edits (A staring, C
  staring, D shocked) queued with the Qwen-Image 2.1 edit graph.
- 16:38 Tom on the base sheet: "Yes I like the sheet I said Great. You have a green
  light this exercise is more around documenting what tooling we need to use and
  automate." Picks approved, and the remaining stages may proceed without stopping at
  each gate.
- 16:40 Expression edits (Qwen-Image 2.1 edit graph, about 65 s each). Identity held
  very well: same hair, jacket, lettering, prop and pose, with only the face changed.
  **Changed:** the edit graph scales its input to about 1 megapixel, so edits come
  back at 896x1184 instead of 1104x1472. Cut out unscaled, a doll would shrink when
  her expression changes at a cut, and the eye-protect box would miss. Added
  `cutout.py --resize 1104x1472`.
- 16:45 The first fire-left sets (`s211`, `s212`) each had **a doll painted into the
  scene**. The prompt said "visible beside a doll standing in the centre". Reworded
  and re-rendered (`s221`, `s222`). Picked **`set-left-s221`**: fire in the left
  third, lean-to and pot on the right, log across the bottom.
  - **Editor requirement:** OP345 scales dolls to nearly the full frame width, which
    would hide the fire. Place dolls smaller or off-center in stage 5.
- 16:55 Seven cutouts made: `a-proud`, `a-staring`, `b-deadpan`, `c-suspicious`,
  `c-staring`, `d-cheerful`, `d-shocked`. Clean at video scale over a forest color.
  Hashes and settings are in `prompts.json`.

### Stage 2 summary

- 18 ComfyUI jobs: 17 completed (8 chosen) and 1 interrupted. About 70 s each,
  plus about 8 min of waiting behind household renders. Roughly 70 minutes of wall
  time, of which at least 30 minutes was hand work: writing prompts, judging
  candidates and tuning the key.
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
