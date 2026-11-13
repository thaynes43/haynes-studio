# 0001: Repo scope, manual first, in-cluster images first

Date: 2026-11-03. Decided by Tom in a Remote Control session with Claude, except the
license, which Tom left open and Claude chose.

## Decisions

1. **A dedicated repo.** Haynes Studio's code, prompts, runbooks and later its API
   and web UI live in `thaynes43/haynes-studio`. haynes-ops keeps only cluster
   deployments (ComfyUI, Wan, Kokoro, Whisper, Foley, and any future studio service
   manifests). The OP339 to OP345 scripts stay in haynes-ops as history; this repo
   starts from copies.
2. **Public repo, text only.** Media, voices, reference photos, weights and secrets
   stay on private cluster storage. The license is MIT, chosen by Claude after Tom
   said on 2026-11-03 that he did not mind which; it replaced the initial AGPL-3.0.
   MIT is the simplest permissive license and puts no obligations on a future hosted
   API or UI. It covers the code and docs, not the media. (*Amended by D48 in
   [proposal 0003](../proposals/0003-studio-plan.md), 2026-11-13: the code stays MIT,
   and the creative work is all rights reserved wherever it appears in the repository,
   docs included; see [RIGHTS.md](../../RIGHTS.md).*)
3. **Manual first.** One short is made by hand and documented step by step before
   any tooling is built. The tooling backlog is then written from the run log, with
   each epic ending in something Tom can use and demo, building toward an API and a
   web UI for storyboards and saved revisions of each title. Requirements go into
   OpenProject (`haynes-studio`), fully specified.
4. **In-cluster image generation first.** Cast and set images come from the cluster's
   ComfyUI (Qwen-Image 2.1 and Qwen-Image-Edit). Gemini or OpenAI image APIs are a
   fallback only if in-cluster quality is not good enough, and need Tom's approval, a
   cost cap and a key he provisions. An agent harness's built-in image tool is not
   the pipeline.

## Why

- The tooling is an application with its own tests and images; it does not belong in
  a public GitOps repo.
- Writing tooling before a manual run means guessing the steps; the run log replaces
  guesses with observed work.
- In-cluster generation is free per image, private, and repeatable from a stored
  graph and seed; a harness's built-in tool is none of those.
