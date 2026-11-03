# Proposal 0001: tooling backlog after the manual PoC

Status: **proposal for grooming with Tom.** Nothing here is filed in OpenProject or
started. Written 2026-11-03 from the
[Winter Menu run log](../../titles/the-winter-menu/run-log.md), the first doll short
made entirely with in-cluster tools.

## What the manual run showed

It took about 80 minutes from the first image render to a delivered 27.6 s short. Compute
was a small part of that (18 image renders at about 70 s each, two 3.5-minute renders,
seconds for voices, cues, checks and delivery). The rest was hand work, in this order
of cost:

1. **Image cleanup:** three rounds of chroma-key tuning, a hand-placed box to stop green
   eyes keying out, and edits returning at a different size than their base.
2. **Layout:** eight previews of hand-edited numbers to stage four dolls in a
   vertical frame, and a log edge measured off a ruler overlay.
3. **Choosing:** contact sheets built by hand. Voices and cues picked without anyone
   listening.
4. **Gluing:** prompts copied between files, graphs converted by hand, waiting on the
   shared GPU queue, records typed up afterwards.

Tom's verdict on revision 1 added a fifth item, **performance**: the fire must move,
the dolls must bounce to their lines as if someone is playing with them, and the ending
has to land. Revision 2 added talk bounce driven by the voice envelope, scripted
lunges, an animated campfire with firelight, loudness-targeted mastering with a
limiter, and re-muxing audio-only fixes. The render takes about 6.5 minutes for 34 s.

Steps that are already one command and should stay that way: voices, the mix, the
render, the checks, the transcript and the private delivery.

## Target

Tom opens a private web page, picks or creates a title, builds a storyboard (shots,
dolls, expressions, lines, voices, cues) on a live frame, hears the voices, renders, and
compares saved revisions side by side. Agents use the same API to do the legwork.
Everything stays private and in-cluster unless Tom approves otherwise.

## Epics, in order

Each epic must end in something Tom can use and demo. Later epics build on earlier
ones, and the order is chosen so the costliest hand work goes first, once there is a
foundation to build on.

### E1. One-command production from a manifest

**Usable end state:** `studio make titles/<slug>/manifest.json` produces and privately
delivers a short from existing cast assets, stopping on any failed check. It resumes
from completed stages, and every attempt is a numbered revision.

- Package `poc/` as a tested Python module with a CLI. Unit tests cover timeline maths,
  occlusion checks, ledger validation, and manifest schema validation with clear
  errors.
- Stages speech, cue, audio, render, validate, transcript, deliver, each **atomic**
  (no partial output on failure), idempotent and create-only, with a run record
  (timings, hashes) written automatically instead of by hand. Audio-only changes never
  re-render the picture.
- Performance in the manifest: talk bounce, scripted moves, idle wobble and animated
  set elements (fire), as revision 2 does.
- Checks include loudness against target; transcript tolerances are phrase-level.
- Dialogue as a per-shot sequence (several lines, cues and moves anchored to lines)
  and shot types (single, group, close-up with a camera push-in), as revision 3 does.
- Fail fast: validate placements, anchors and cues before any long render. Delivery
  also makes a phone review proxy (the 45 s master was over the 30 MiB send limit).
- Render speed: cache static layers per shot (r3 took 8.7 min for 45 s on 2 threads).
- Per-shot re-render: a one-line change (r4) re-rendered all 45 s. Render shots
  separately and splice, so only changed shots are redone.
- **Demo:** rebuild The Winter Menu from its manifest as revision 2 in one command,
  and change a line to show only the affected stages rerun.

### E2. Cast and set library with clean cutouts

**Usable end state:** dolls and sets are reusable records. Adding a new doll (identity,
costume, expressions, voice) or set takes minutes with no hand keying.

- A doll record: look and costume prompt parts, expression list, chosen images and
  cutouts, voice, facing. A set record: image, focal prop position, and an occlusion
  mask instead of a measured polyline.
- Generation commands: base candidates, expression edits, contact sheet, pick, all on
  the shared ComfyUI through a polite queue (warm-model aware, one in flight).
- Cutouts: a per-doll backdrop color chosen against the doll's palette, or an
  in-cluster matting model, plus automatic size matching to the base. This removes
  the protect box and the keying iterations.
- **Demo:** add a fifth Yellowbird and a new set, then use both in a manifest.

### E3. Studio API in the cluster

**Usable end state:** a private service holds titles, revisions, shots, assets and jobs,
and runs E1 and E2 work as queued jobs. Agents and the future UI use it instead of
local job directories.

- Deployed through haynes-ops GitOps. Its own storage with a backup and retention
  policy, rather than living on the unbacked Wan PVC. Authentication matches Tom's
  other private apps.
- GPU work goes through one scheduler that respects household renders and the Wan
  lease.
- **Demo:** create a revision through the API and get back a private video link.

### E4. Storyboard web UI

**Usable end state:** Tom builds and edits a short in the browser and compares
revisions. This is the product he described.

- Shot list per title. Drag dolls on a live 9:16 preview of each shot, with the set's
  occlusion shown. Choose the expression per shot.
- Performance controls per shot: bounce strength, lunges and recoils on a timeline,
  previewed in motion (a few seconds of low-resolution video), not only as stills.
- A per-shot line timeline (who speaks when, gaps, beats) with cue markers that snap to
  line ends. Revision 3's vote gag needed six lines, a gavel and a group jump in one
  shot.
- Lines and voices with **playback**, and cue audition, closing the "nobody listened"
  gap.
- Render a revision, watch it, keep notes per revision, compare two side by side.
- Works on a phone for review, and on a desktop for layout.
- **Demo:** storyboard and render a new short end to end without an agent.

### E5. From idea to script

**Usable end state:** pick a situation (a popular-media premise or a subtitle scene)
and get a few original pitches. One becomes a title brief and manifest.

- Read-only discovery of Tom's subtitle sources (HaynesTower or Bazarr): paths,
  formats, access. Subtitle text stays private and is used only as inspiration;
  scripts are original.
- An in-cluster LLM drafts pitches, lines sized to the doll format, and a starter
  manifest.
- **Demo:** three pitches from one scene, one turned into a storyboard in E4.

### E6. Batches and winners

**Usable end state:** produce a batch of N candidates, review them in a gallery with
ratings and notes, pick winners, and feed outcomes into the next batch.

- **Demo:** a batch of five, two winners picked, with reasons recorded.

### E7. Release (approval-gated)

**Usable end state:** an approved winner becomes a release package (captions, cover
frame, description), ready for Tom to publish or schedule with his explicit
approval.

- Licence and terms check for every model used: Qwen-Image, Kokoro and Stable Audio's
  commercial terms are not yet established. Disclosure, channel and cadence decisions
  belong to Tom.
- No autonomous publishing, accounts or keys without Tom.

## Suggested first stories (E1)

1. Package `poc/` as `studio/` with a CLI, tests and a manifest schema; no behavior
   change. Acceptance: the tests pass, and a rebuilt Winter Menu matches revision 1's
   timeline and validation.
2. Stage runner with resume and automatic run records. Acceptance: the line-change demo
   reruns only the affected stages, and the run record matches the hand-written one.
3. Image commands (`studio cast generate`, `edit`, `cutout`, `sheet`) wrapping today's
   helpers. This starts E2.

## Decisions for Tom

- **Order:** E1 → E2 → E3 → E4 as above, or jump to a thin E4 prototype on top of E1
  sooner?
- **UI access:** LAN-only like the other private apps, or behind Authentik so it works
  off the home network (the PoC delivery link does not)?
- **Storage:** a dedicated studio volume with backups, separate from the Wan PVC?
- **Paid image APIs:** still a fallback only? Qwen-Image 2.1 kept identity across
  expressions well in this run.
