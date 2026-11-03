# Baseline: how "Crunch Costs Extra" was made (OP345)

The only finished doll short so far, and the starting point for the manual runbook.
Tracking: [OP345](https://work.haynesnetwork.com/work_packages/345). Evidence:
haynes-ops `.agents/evidence/crunchy-butter-dolls-2026-11-01/`. Handoff: haynes-ops
`.agents/handoffs/2026-11-03-haynes-studio-video-generation.md` (commit `1401a2ee`).

## Result

- 20 s, 1080x1920, 24 fps, 480 frames. Two dolls, four 5 s shots (A, B, A, B), and
  each doll changes expression on her second shot.
- -20.03 LUFS, -5.62 dBTP, zero clipped samples. The transcript matched every
  intended word.
- Private link: `https://video.haynesops.com/videos/40999984239c44dab681347602c67cb8/file`.
  Files: `/workspace/output/productions/op345/` on PVC `ai/wan-video`.
- Tom: "That's great", and he wanted more in this style. That is encouragement, not
  a formal listening sign-off.

## Steps and scripts

All scripts are in haynes-ops `scripts/wan-video/`. They were written for this one
production and have its paths written into them.

| Step | Script | What it did | Ran on |
|---|---|---|---|
| Art | none (Codex built-in image tool) | 5 PNGs: 2 dolls x 2 expressions with transparent backgrounds, plus 1 kitchen set. Prompts in the evidence `prompts.json`. | Codex's own image tool, **not** in-cluster |
| Voices | `doll_speech.py` | 4 lines through Kokoro, voices `bf_emma` (A) and `af_bella` (B); writes `voice-N.wav` and `speech.json` with hashes | Kokoro pod |
| Audio mix | `edit_doll_short.py audio` | places each line in its shot, adds a 0.85 s Foley excerpt from OP344 at 10.1 s, masters to -20 LUFS | agent CPU |
| Picture | `edit_doll_short.py render` | composites the rigid puppet motion over the set and encodes H.264 with 2 threads; writes the contact sheet and per-frame transform log | agent CPU |
| Checks | `edit_doll_short.py validate` | frame count, duration, loudness, peak; writes `validation.json` | agent CPU |
| Transcript | `check_doll_dialogue.py` | sends the movie's audio to Whisper and compares it with the script | Whisper pod |
| Save | `preserve_doll_short.py` | checks hashes, copies every asset create-only to the Wan PVC, writes the ledger and prints the private link | Wan API pod |

Helpers the editor imports: `edit_short.py` (`ffmpeg`, `FFMPEG`) and
`edit_butter.py` (`read_audio`, `write_audio`).

## What is fixed in the code

- `OUT` (the job directory) is set in `doll_speech.py` and imported by the other
  three scripts.
- `SHOTS` in `edit_doll_short.py` is exactly four shots of 5 s with two characters,
  `a` and `b`. Voice start offsets within the shots are 0.5, 0.5, 1.35 and 0.5 s.
- The OP344 Foley WAV path is an absolute path from the old session.
- `preserve_doll_short.py` writes to `productions/op345/` with story `OP345` and the
  OP345 title. Running it again would collide by design (create-only).
- One doll per shot, positioned left or right by character. No group shots.

## What a new title needs

To make a different doll short, at minimum:

1. A new job directory and production ID, never OP345's.
2. New art (dolls, expressions, set) and its prompts and hashes.
3. A shot list with any number of shots, per-shot lengths, and more than one doll in
   a shot.
4. Per-line voice assignments and start offsets taken from the shot list.
5. Optional sound-effect cues placed by time.

The first title, "The Winter Menu", needs items 3 to 5, so the manual PoC copies the
scripts into this repo and generalizes them as little as it can. That is documented
in the run log, and it previews the first tooling epic.
