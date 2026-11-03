# AGENTS.md

Instructions for any agent (Claude Code, Codex or others) working in
`thaynes43/haynes-studio`. `CLAUDE.md` imports this file, so keep it the single source.

## What this repo is

Haynes Studio makes short-form comedy videos (currently the **doll short** format)
on in-cluster GPU, TTS and ASR services. The project is in its **manual proof of
concept phase**: one short is being made by hand, and every step goes into the
runbook. Tooling (a renderer, a cast library, then an API and a storyboard web UI)
comes later, one epic at a time, each with a usable demo at the end.

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
- Saga [#362](https://work.haynesnetwork.com/work_packages/362) holds the roadmap.
  Epic [#366](https://work.haynesnetwork.com/work_packages/366) is the manual PoC.
- Earlier proofs OP339 to OP345 live in `haynes-engineering` under Epic 124. Link them
  as history; do not move, reopen or change their holds.
- Always write full `https://work.haynesnetwork.com/work_packages/<id>` links. A bare
  `#123` in this repo reads as a GitHub issue.
- Do not start a Markdown or GitHub-issue backlog here. Requirements and stories go
  in OpenProject; this repo holds the docs those stories link to.

## Hard rules

These block a merge if broken.

- **No media or secrets in git.** The repo is public (MIT). Never commit video,
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
  - Run CPU editing with at most 2 worker threads (`OPENBLAS_NUM_THREADS=2`,
    ffmpeg `-threads 2`).
- **Original content.** Parody may borrow a situation from popular media, but use
  invented names, team names, logos and dialogue. Do not reenact a subtitle file
  verbatim, and never use a real person's likeness or voice.
- **Cluster changes go through haynes-ops.** This repo does not deploy anything yet.
  Changes to ComfyUI, Wan, Kokoro, Whisper or storage are GitOps PRs in
  [thaynes43/haynes-ops](https://github.com/thaynes43/haynes-ops).

## Human review gates

Tom is the creative approver. Stop and get his verdict at:

1. the script, before generating any assets;
2. the cast and set images, before editing;
3. the finished cut.

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
- Squash-merge your own PR once required checks pass and any review findings are
  handled. Record what you validated in the PR body.

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
