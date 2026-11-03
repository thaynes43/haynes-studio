# Titles

One folder per title, named by a short slug (`the-winter-menu`). Text only: the media
stays on private cluster storage (see [AGENTS.md](../AGENTS.md)).

| File | When | What |
|---|---|---|
| `brief.md` | before any generation | premise, cast, voices, shot list and script; Tom approves it |
| `prompts.json` | stage 2 | every image prompt, graph, seed and output SHA256, chosen and rejected |
| `speech.json`, `sfx.json` | stages 3 and 4 | voice and cue sources, timings and hashes |
| `timeline.json`, `validation.json`, `dialogue-transcript.json` | stages 5 and 6 | edit timing and check results |
| `production.json` | stage 7 | the delivery ledger: private link and asset hashes |
| `run-log.md` | throughout | what was done, how long it took, what failed, Tom's verdicts |

A new attempt at the same title is a new revision (`<slug>-r2`) with its own job
directory and production ID. Record each revision in the run log, with what changed
and why.

| Title | Status | Brief |
|---|---|---|
| The Winter Menu | script agreed in chat 2026-11-03; assets not started | [brief](the-winter-menu/brief.md) |
