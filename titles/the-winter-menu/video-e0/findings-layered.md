# E0 follow-up: full layered film and lettering decals

Tom, 2026-11-03, after the first E0 videos: "I didn't say whole frame never will work I was
just commenting on that one video. I think we can get away with a lot of layering with this
doll format - it looks great and they are dolls so layering makes sense but the shirt issue
is present in both. How much video work are you doing for that approach? I need a full
length w/ layering to compare."

## Video work for layered

- One Wan set loop per set (reused under every shot; already made in E0).
- One Wan doll-on-green clip **per doll per expression**: The Winter Menu needs 7 (A proud,
  A staring, B deadpan, C suspicious, C staring, D cheerful, D shocked). 6 new clips, about
  148 s render each, plus cooldowns.
- CPU: key each clip once (cached), then composite every frame with the layouts, talk
  bounce, moves and camera (`poc/layered_film.py`).

## Lettering decal (`poc/decal.py`)

- OpenCV ECC (affine) tracks the jacket from the clip's first frame, which is Wan's start
  image, to each frame, and pastes the still's lettering warped by that motion.
- **Tracking:** ECC 0.89 to 0.95 over all 121 frames of A's clip.
- **Mask:** a full-box paste left a visible rectangle (the still's cloth differs from
  Wan's). A **letter-shaped mask** (the yellow letters plus a 4 px jacket band, 2 px
  feather) is invisible and keeps "YELLOWBIRDS" crisp and steady. **About 4 s of CPU per
  5 s clip.**
- **Detection pitfall:** a colour-based lettering finder picked D's **yellow squishy**
  instead of her lettering. A product tool needs region hints or a proper detector
  (shape and aspect, or OCR).
- **Requirement (E2):** a decal tool for costume text and logos (tracked, letter-masked),
  run on doll clips before keying. Needs `opencv-python-headless` (Apache-2.0).

## Full layered film (`winter-menu-layered.mp4`, 45.3 s)

- **GPU:** 6 new doll clips at about 122 to 147 s render plus 125 to 156 s cooldown each
  (about 26 min), plus the set loop and A's clip from E0. **8 Wan clips in total for the
  whole film**, against 15 for whole-frame. Layered reuses a doll clip across every shot
  showing that expression.
- **CPU:** about 17 min at 2 threads for decals, keying 7 x 121 frames (cached) and
  compositing 1087 frames with up to 4 animated dolls. **Requirement:** render workers
  (24 vCPUs once E3 exists) make this about 2 min; the keyed-frame cache is reusable.
- **Decal tracking (min ECC; re-scored with the fixed summary, failed frames counted):**
  B 0.97, C 0.99/0.99, D cheerful 0.97, A 0.89/0.85, D shocked 0.72 (mean 0.86). **0 failed
  frames in all 7 clips** (120 tracked each). I judged D's lettering readable; Tom saw it moving (see his verdict below), so that judgment was wrong. A **min-ECC threshold** is a
  natural automatic check (re-roll or disable the decal below it).
- **Look:** faces hold in every shot, the lettering reads "YELLOWBIRDS" in every clip except D's reaction (doubled letters) and B's zipper split (see below), and the
  four-doll vote keeps everyone in place (each doll is a separate layer, so nobody swaps).
  Hair and fabric move from Wan; the bounce and lunges come from the editor; the fire is
  Wan's.
- Delivered privately (ledger `d81353cdf8f84f999a9c41b43c4be569`); review copy sent to Tom.
  Tom's comparison verdict is below.

## Tom's verdict (2026-11-04) and the two defects

> "The layered looks better, moves more like dolls and less is off. Not perfect though. The
> dolls sleeves were a bit off, maybe intentional but looked weird. Also one scene a doll had
> the letters on her shirt moving around."

Layered becomes the default for doll talking shots (D23 in proposal 0003). Both defects were
traced from the keyed frames:

- **Sleeves: a casting defect, not a video defect.** The r1 character stills already had it:
  B wears a jacket with bare upper arms and a loose forearm cuff on one side, and D wears a
  sleeveless vest, while A and C have full sleeves. Qwen-Image invented it, every revision
  inherited it, and Wan faithfully animated it, where motion makes it more noticeable. Nothing
  checked costume consistency across the cast. **Requirement (E2, character cards):** a
  costume spec per team or cast (garment, sleeves, lettering, colours) and a **wardrobe
  check** on every cast still and keyframe (a vision-model question per garment attribute,
  locally in E4), failing before any GPU video time is spent.
- **Moving letters: D's reaction clip (`layer-d-shocked`), the weakest track (min ECC 0.72; next is A staring at 0.85, which Tom did not flag).** She
  lifts the squishy and turns, ECC fell to 0.72, the decal slid by a few pixels and Wan's own
  warped lettering showed beside it ("YELLOWBIRDSS"). Two fixes: **erase the generated
  lettering first** (fill the letter band with jacket colour, then paste the decal), so a
  small slide never doubles letters; and **gate on track quality** (reject below about 0.8
  min ECC, then re-roll the clip, use a stronger tracker such as homography or optical flow,
  or fall back to a held still for that doll). On this film the line sits between 0.72 (bad)
  and 0.85 (accepted), so **about 0.8** is the starting threshold. One clip pair is thin evidence:
  E2 should also measure the decal's frame-to-frame drift against the jacket, and calibrate both
  numbers on more clips. B's zipper also splits her lettering
  ("YELLO|WBIRDS") in the still itself: the casting check should catch that too.
- Neither defect needs a whole-frame fallback; both are checks the factory must run without
  Tom.
