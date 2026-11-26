# AGENTS.md

Instructions for any agent (Claude Code, Codex or others) working in
`thaynes43/haynes-studio`. `CLAUDE.md` imports this file, so keep it the single source.

## What this repo is

Haynes Studio makes short-form comedy videos (currently the **doll short** format)
on in-cluster GPU, TTS and ASR services. The manual proof of concept is complete.
The saga has been in execution since 2026-11-24. [Saga 362, comment 9653](https://work.haynesnetwork.com/work_packages/362/activity#comment-9653).
E1 archived two shorts privately and Tom's acceptance remains open.
[Epic 372, comment 9654](https://work.haynesnetwork.com/work_packages/372/activity#comment-9654).
Scoped range reads of both imports passed. Human sign-in and phone playback
remain open. [Story 957, comment 9914](https://work.haynesnetwork.com/work_packages/957/activity#comment-9914) · [Story 944, comment 9915](https://work.haynesnetwork.com/work_packages/944/activity#comment-9915).
Each epic ends with a usable demo.

The LAN app's fourth pin is Studio `470a90af73a2201e6542b5d867853dce6facad04`
at haynes-ops `59dc8678`, with schema `0013_matte_jobs` and PyAV 18.1.1
read back at all six encoder locations.
[Story 967, comments 10322](https://work.haynesnetwork.com/work_packages/967/activity#comment-10322), [10327](https://work.haynesnetwork.com/work_packages/967/activity#comment-10327) and [10329](https://work.haynesnetwork.com/work_packages/967/activity#comment-10329).
The matte isolation policy is installed and selects zero pods. A cutout
request is accepted and waits. Activation is held on Tom's decision and
haynes-ops PR 5096 stays open and unmerged. Its independent review found a
blocking defect in the launcher's isolation proof, so it is not mergeable as it stands
([comment 10358](https://work.haynesnetwork.com/work_packages/970/activity#comment-10358)).
[Story 970, comments 10332](https://work.haynesnetwork.com/work_packages/970/activity#comment-10332), [10333](https://work.haynesnetwork.com/work_packages/970/activity#comment-10333), [10335](https://work.haynesnetwork.com/work_packages/970/activity#comment-10335) and [10338](https://work.haynesnetwork.com/work_packages/970/activity#comment-10338).
Segmentation is provisioned and smoked with serving inactive. The client
adapter is on `main` with no caller.
[Story 460, comment 10228](https://work.haynesnetwork.com/work_packages/460/activity#comment-10228) · [Story 452, comment 10313](https://work.haynesnetwork.com/work_packages/452/activity#comment-10313).
Upscaling is comparison-only and delivery uses Lanczos.
[Story 461, comment 10229](https://work.haynesnetwork.com/work_packages/461/activity#comment-10229).
Wan local-model activation is held and haynes-ops PR 5064 stays open and
unmerged. [Story 442, comments 10134](https://work.haynesnetwork.com/work_packages/442/activity#comment-10134) and [10152](https://work.haynesnetwork.com/work_packages/442/activity#comment-10152).
See the [installed evidence](docs/contracts/studio-contracts-v1.md#installed-and-published-state).

Start with:

1. [`README.md`](README.md): purpose and layout.
2. [`docs/process/manual-short-poc.md`](docs/process/manual-short-poc.md): the
   runbook.
3. [`docs/reference/services.md`](docs/reference/services.md): what runs where, and
   how to reach it.
4. The title you are working on, under [`titles/`](titles/).

## Work tracking

- OpenProject project `haynes-studio` (ID 11) is the work queue. Use
  `opwork --project haynes-studio ...`; the bare `opwork` default is a different
  project (`haynes-engineering`).
- Saga [362](https://work.haynesnetwork.com/work_packages/362) holds the roadmap.
  Its comment 9653 records Tom's start of execution on 2026-11-24. The saga coordinator
  grooms and starts bounded stories as dependencies are ready. Tom reviews
  provisional rulings and owns acceptance.
- Epic [366](https://work.haynesnetwork.com/work_packages/366) is the completed manual
  PoC. See [proposal 0003](docs/proposals/0003-studio-plan.md#epics-revised) for the
  execution snapshot and the other epics.
- Earlier proofs OP339 to OP345 live in `haynes-engineering` under Epic 124. Link them
  as history; do not move, reopen or change their holds.
- Always write full `https://work.haynesnetwork.com/work_packages/<id>` links. A bare
  `#123` in this repo reads as a GitHub issue.
- Do not start a Markdown or GitHub-issue backlog here. Requirements and stories go
  in OpenProject; this repo holds the docs those stories link to.

## Hard rules

These block a merge if broken.

- **No media or secrets in git.** The repo is public: its code is MIT, its creative work
  all rights reserved ([RIGHTS.md](RIGHTS.md)). Never commit video,
  audio, images, reference photos, voice samples, subtitle files, model weights,
  tokens, API keys, cookies or login material. `.gitignore` blocks the common media types; do not
  force-add past it. Commit prompts, manifests, SHA256 hashes and run notes instead.
  Files that must exist locally go in a job directory outside the repo (see the
  runbook).
- **Private by default.** Finished work goes to private cluster storage and is viewed
  through `https://video.haynesops.com`. Never upload, post or schedule anything to a
  public platform, and never create accounts or channels. Release is a separate,
  explicitly approved story.
- **No paid inference without approval.** In-cluster models come first. Gemini,
  OpenAI or other paid image/video/voice APIs need Tom's explicit go-ahead, a cost
  cap and a key he provisions. Do not create or borrow credentials.
- **Never overwrite a finished production.** Outputs are create-only. A new attempt
  gets a new job directory and a new production ID. Archived productions are an
  input library, never a resume target.
- **Share the GPUs politely.**
  - ComfyUI (images) is shared with Home Assistant camera renders and Open WebUI
    chat. Check its queue before submitting and keep one prompt in flight.
  - Wan (video) and the Foley sidecar share one compute lease. Never bypass the API
    lease or its unknown-work checks.
  - Never benchmark, load-test or change GPU power or clock settings.
  - **Heavy CPU work** (decals, keying, compositing, encoding) runs at low
    priority on the `ai/studio-render` worker on talosw01, with media on
    gasha01 NFS at `/studio`. Tom's 2026-11-04 decision D18 set the original
    24-vCPU cap. The original offline procedure allowed up to 22 workers
    under that cap. The installed split is 20 vCPUs for offline render and 4
    for the serial queue worker. Copy inputs in with `kubectl cp`, run under
    `nice -n 10` with `--workers` up to 18 to reserve two vCPUs for render
    coordination, and copy results out. Each worker also drives a small
    ffmpeg encoder. The pod's CPU limit caps their combined use. Demand
    beyond its allocation is throttled. In a session pod, keep CPU work to
    2 threads (`STUDIO_THREADS=2`, ffmpeg `-threads 2`, `--workers 1`).
    [Current render limits](docs/reference/services.md#studio-render-cpu-work) ·
    [Story 956, comment 9872](https://work.haynesnetwork.com/work_packages/956/activity#comment-9872) ·
    [Story 967, comment 10322](https://work.haynesnetwork.com/work_packages/967/activity#comment-10322).
- **Original content.** Parody may borrow a situation from popular media, but use
  invented names, team names, logos and dialogue. Do not reenact a subtitle file
  verbatim, and never use a real person's likeness or voice.
- **Cluster changes go through haynes-ops.** This repo does not deploy anything yet.
  Changes to ComfyUI, Wan, Kokoro, Whisper or storage are GitOps PRs in
  [thaynes43/haynes-ops](https://github.com/thaynes43/haynes-ops).

## Human review gates

Tom is the creative approver. The only formal approval is **go-live**: nothing is
published to a live social platform without his explicit sign-off (D29 in
`docs/proposals/0003-studio-plan.md`). Script and images iterate together with his
feedback; do not hold generation waiting for a script sign-off.

Record his verdict separately from technical checks. A transcript match, a loudness
reading or "it decodes" is not approval, and a casual "nice" is not a formal sign-off
unless he says so.

## Documentation rules

- The runbook describes **what was actually done**. Mark each step **Proven** (it
  produced a delivered result, with a link to the evidence), **Expected** (planned,
  not yet run here) or **Changed** (it differed from the plan, and how). Never upgrade
  a step to Proven without the run that proves it.
- Record timings, failures, retries and the hand work each step took. That record is
  what the tooling backlog will be written from.
- Keep docs short and concrete: commands, paths, inputs, outputs. No marketing.
- Each title gets `titles/<slug>/`: `brief.md` (premise, cast, script), and when it
  runs, `prompts.json`, `run-log.md` and evidence JSON with hashes. No media.

## Branches and pull requests

- Work on a branch `agent/<topic>` in its own worktree. Never push to `main`.
- Open PRs ready for review, not as drafts, so the advisory reviewer runs.
- A worker that a coordinator dispatched on a backlog story stops at a ready PR and
  its handoff. It does not merge. The coordinator reviews the PR, handles the review
  findings and squash-merges it. See
  [`docs/backlog/coordinator-guide.md`](docs/backlog/coordinator-guide.md).
- A session working directly for Tom, or the coordinator itself, squash-merges its
  own PR once required checks pass and any review findings are handled.
- Record what you validated in the PR body.

## Automated PR review (agents read this)

Every non-draft PR gets an advisory review from Claude Code
(`.github/workflows/claude-code-review.yml`); `@claude` mentions are handled by
`claude.yml`. Automated AI reviews and audits are **advisory and optional**, never
required checks. Failure, timeout, quota exhaustion or service unavailability cannot
block merge or deployment and does not require an owner waiver. Complete required
tests, builds and security checks. Review the diff and relevant documentation
yourself, and use an independent native agent review when available. Record the
review, validation and AI availability in the PR. Repeated retries are not required.
Read any findings emitted before merging. Fix each one, or answer it on the PR with a
concrete reason it is wrong; never "merging anyway". Both workflows need the Claude
GitHub App on the repo and the `CLAUDE_CODE_OAUTH_TOKEN` repo secret, otherwise they
skip green and review nothing.
