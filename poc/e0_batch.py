"""E0 GPU batch: whole-frame clips for every cut (chained when a cut is longer than one
clip), then the layered set-loop and doll-on-green clips. Sequential, cool-idle between
jobs, stops at the first failure. Create-only: finished clips are skipped on rerun."""
import json, sys
from pathlib import Path
from wan import render

JOB = Path.home() / 'studio-jobs/winter-menu-video'; P = Path(__file__).resolve().parent.parent / 'titles/the-winter-menu/video-prompts'
KEY = JOB / 'keyframes'; LAY = JOB / 'layers'
CLIP_S = 121 / 24
plan = []
durations = {1: 6.38, 2: 3.92, 3: 6.08, 4: 3.5, 5: 3.46, 6: 5.08, 7: 1.92, 8: 10.38, 9: 4.5}
for shot, dur in durations.items():
    prompt = (P / f's{shot}.txt').read_text().strip()
    plan.append((f's{shot}-wf-a', KEY / f's{shot}.png', prompt, 100 + shot))
    extra = 0; covered = CLIP_S
    while dur > covered + 0.1:
        extra += 1; covered += CLIP_S
        prev = f's{shot}-wf-a' if extra == 1 else f's{shot}-wf-x{extra - 1}'
        plan.append((f's{shot}-wf-x{extra}', JOB / 'clips' / f'{prev}-last.png', prompt, 200 + shot * 10 + extra))
SET = ('Stop-motion style miniature campsite in a frosty pine forest, empty, no people and no dolls. The small campfire '
       'flickers and its flames dance, thin smoke rises, pine branches sway slightly. Static locked-off camera, same framing.')
DOLL = ('Stop-motion style toy video. The same plastic fashion doll with feral ash-blonde hair and a twig crown, in the same '
        'blue YELLOWBIRDS jacket, holding the same moss, on a flat solid bright green screen background. An unseen child plays '
        'with her: the whole doll bobs and rocks gently, her synthetic hair shifts with each bob. Her face is hard molded '
        'plastic: painted eyes and smug closed smile never change and the mouth does not move. The green background stays flat '
        'and uniform. Static locked-off camera, same framing.')
plan += [('layer-set-loop', LAY / 'set-plate.png', SET, 301), ('layer-a-green', LAY / 'a-base-s101-green.png', DOLL, 302)]
for name, image, prompt, seed in plan:
    if (JOB / 'clips' / f'{name}.mp4').exists():
        continue
    if not Path(image).exists():
        sys.exit(f'missing input {image} for {name}')
    rec = render(JOB, name, image, prompt, seed, 576, 1024, 121)
    print(json.dumps({k: rec[k] for k in ('name', 'cooldown_s', 'render_s', 'wall_s')}), flush=True)
print('batch done', flush=True)
