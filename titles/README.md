# Titles

One folder per title, named by a short slug (`the-winter-menu`). Text only: the media
stays on private cluster storage (see [AGENTS.md](../AGENTS.md)).

| File | When | What |
|---|---|---|
| `brief.md` | before any generation | premise, cast, voices, shot list and script; Tom approves it |
| `manifest.json` | stages 3 to 7 | machine-readable cast, voices, layouts, shots, cues and set occlusion; drives `poc/` |
| `prompts.json` | stage 2 | every image prompt, graph, seed and output SHA256, chosen and rejected |
| `evidence/` | stages 3 to 7 | `speech.json`, `timeline.json`, `shots.json`, `validation.json`, `dialogue-transcript.json`, `production.json` (the delivery ledger with every asset hash) |
| `run-log.md` | throughout | what was done, how long it took, what failed, Tom's verdicts |

A new attempt at the same title is a new revision (`<slug>-r2`) with its own job
directory and production ID. Record each revision in the run log, with what changed
and why.

| Title | Status | Brief |
|---|---|---|
| The Winter Menu | r4 (45.3 s): Tom "That's great" 2026-11-03, formal sign-off requested; r1 to r3 shaped by his notes | [brief](the-winter-menu/brief.md), [run log](the-winter-menu/run-log.md), manifests [r1](the-winter-menu/manifest.json), [r2](the-winter-menu/manifest-r2.json), [r3](the-winter-menu/manifest-r3.json) and [r4](the-winter-menu/manifest-r4.json) |
