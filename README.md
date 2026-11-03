# haynes-studio

Short-form comedy videos made on Tom's home-lab GPUs, along with the process and
tooling to make them.

The current format is the **doll short**: elaborate plastic fashion dolls with
uncanny synthetic hair, stock synthetic voices, stiff whole-doll puppet motion, and
expressions that change only on a cut. The first finished example is "Crunch Costs
Extra" (Nov 2026), made by hand from scripts that live in haynes-ops.

## Where this is going

1. **Manual proof of concept (done once, 2026-11-03).** "The Winter Menu" was made
   with in-cluster tools and every step was written down
   ([run log](titles/the-winter-menu/run-log.md)).
2. **Tooling.** Replace the hand steps with tools an agent or a person can drive:
   a manifest-driven renderer, a reusable cast library, then an API and a web UI for
   storyboards and saved revisions of each title.
3. **Batches and release.** Produce small batches, compare candidates, pick winners,
   and prepare releases.

Each tooling epic must leave Tom with something he can use and demo. The backlog
comes from what the manual run teaches us, not from guesses made in advance.

## Layout

| Path | What it holds |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Rules and working agreement for any agent in this repo. Read it first. |
| [`docs/process/manual-short-poc.md`](docs/process/manual-short-poc.md) | The manual runbook: brief to delivered video, stage by stage. |
| [`docs/reference/`](docs/reference/) | The in-cluster services, the doll format, and the baseline recipe. |
| [`docs/decisions/`](docs/decisions/) | Short decision records (ADRs). |
| [`titles/`](titles/) | One folder per title: brief, manifest, prompts, run log, evidence. No media. |
| [`poc/`](poc/README.md) | The manual PoC's helper scripts (images, voices, editor, delivery). Not the final tooling. |
| [`docs/proposals/`](docs/proposals/) | The studio design and backlog ([0003](docs/proposals/0003-studio-plan.md)). |

## Tracking

Work is tracked in OpenProject, project
[Haynes Studio](https://work.haynesnetwork.com/projects/haynes-studio/work_packages):

- Saga [#362](https://work.haynesnetwork.com/work_packages/362): repeatable
  doll-parody shorts production and winner selection.
- Epic [#366](https://work.haynesnetwork.com/work_packages/366): manual end-to-end
  PoC, one doll short, fully documented.

## What is not in this repo

Finished videos, voice audio, cast images, reference photos and model weights stay on
private cluster storage. This repo is public, so it holds only text: code, prompts,
manifests, hashes and run notes. The GPU services themselves (ComfyUI, Wan, Kokoro,
Whisper, the Foley sidecar) are deployed from
[thaynes43/haynes-ops](https://github.com/thaynes43/haynes-ops).

## License

[MIT](LICENSE). The license covers the code and docs in this repo, not the videos, voices or images produced with them.
