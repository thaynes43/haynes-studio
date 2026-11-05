# Studio UI implementation backlog

This page maps the mockup ([index.html](index.html), v6) to its OpenProject stories.
They were filed on 2026-11-04 from
[401](https://work.haynesnetwork.com/work_packages/401). The 2026-11-05 export still
has them Ungroomed; check the current tracker before pickup. Tom/Meatball must groom
and start them. Decisions D25–D44 are in
[proposal 0003](../../proposals/0003-studio-plan.md).

The [adversarial review](../../backlog/review-2026-11-05.md) proposes field repairs
and bounded follow-ups; none has been applied to the tracker by this review.
R01–R39 below are review labels, not work-package IDs. Search/create under their
listed epics, substitute full tracker URLs, then dispatch only when authorized.
Use the [coordinator guide](../../backlog/coordinator-guide.md) for tier/review and
artifact-ready rules. The mockup simulates media, runs and identity; it is an
interaction reference, not a deployed API or test substitute.

## Mockup surface to story

| Mockup surface | Decisions | UI story (E6) | Backend stories |
| --- | --- | --- | --- |
| Shell: Productions and Editor nav, button breadcrumb, user menu, theme, saved selections | D28, D32, D36, D37, D41 | [E6.1](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/413) | [E3.1](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/409); proposed R10/R12 for installed OIDC/replicas |
| Productions tree, media types a production uses, media list with status filters, story review page | D28, D29, D31 | [E6.2](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/414) | [E3.1](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/409), [E9.1](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/412) |
| Editor landing; create production, media type and story | D36 | [E6.3](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/415) | [E1.6](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/404), [E3.1](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/409) |
| Stage and panel timeline: add, remove and reorder boards; running length | D27, D33, D37 | [E6.4](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/416) | [E1.6](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/404), [E1.7](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/405); proposed R08 voice/media operations |
| Inspector: script, voice and timing, method badges, direction notes | D33, D35, D38 | [E6.5](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/417) | [E1.6](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/404), [E1.7](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/405); proposed R08 operations and R01 timing/cue contract |
| Reference photo composer, versions and stale inputs; externally generated photo provenance | D28, D34, D42 | [E6.6](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/418), proposed photo-only scope | [E2.1](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/407); proposed R08 authenticated upload/job operations |
| Asset library with removable board/production filters; generate and promote | D28, D32, D34 | proposed R34 split from [E6.6](https://work.haynesnetwork.com/work_packages/418) | [E2.2](https://work.haynesnetwork.com/work_packages/408); proposed R08 operations |
| Build, queued runs, progress, estimate, compare | D30, D41 | [E6.7](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/419) | [E3.2](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/410), [E1.8](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/406); proposed R08 operations |
| Agent-drafted boards | D27, D29, D40 | covered by E6.4 and E6.5 | [E5.1](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/411), [E5.2](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/421) |
| Go-live on an exact finished run; Publish disconnected | D29, D43, D44 | [E6.2](https://work.haynesnetwork.com/work_packages/414) | [E9.1](https://work.haynesnetwork.com/work_packages/412); proposed R27 real rights/disclosure package |
| Phone pass and E6 acceptance demo | D20, D41 | [E6.8](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/420) | proposed R06 private build, R12 installed app, R15 integration/HA, R16 Playwright, R18 docs and R34 library; Tom's explicit verdict |

## Order

1. **Contracts and test foundation.** Proposed R01/R02 precede
   [378](https://work.haynesnetwork.com/work_packages/378), then
   [404](https://work.haynesnetwork.com/work_packages/404). E1.6 does not wait for all
   E1.2–E1.5. Proposed R03 preserves legacy adapters/input recovery. E1.2/E1.5 then
   follow the canonical model; voice/cache/delivery follow their explicit dependencies.
2. **Source backends.** E2.1/E2.2 follow library/boards. E3.1 follows the canonical
   model/library and D39/D41 contract. Proposed R07 builds missing MCP; E5.1 uses that
   frontier path without waiting for E4. E3.2 follows E1.8/E3.1; proposed R08 makes
   voice/photo/run operations callable. Proposed R04/R05 implement methods; R36 owns
   the typed Wan interface. Current E0 holds/readiness need a check of
   [395](https://work.haynesnetwork.com/work_packages/395), absent from the export.
3. **UI source.** E6.1 follows the API contract. E6.2 and E6.3 can separate after the
   shell if files are isolated; E6.2 also needs E9.1. E6.3 → E6.4 → E6.5 → E6.6 →
   proposed R34; E6.7 follows E6.5/queue. E6.4–E6.7 wait for callable operations,
   not just Python library functions. Contract mocks cannot prove installed behavior.
4. **Installed acceptance.** Proposed R09–R12 supply DB/OIDC/images/replicated LAN app;
   R13/R14 prove backup/restore; R15/R16 test integration and browser behavior.
   R06 supplies the private build and R17/R18 references/runbooks. Only then does
   E6.8 seek Tom's usability verdict. Source merge alone does not close the epic.
5. **Local writer.** Proposed R19/R20 supply E4's missing local lease/hosting stories;
   R33 fixes the rubric. E5.2 waits for these and E5.1, never blocks initial frontier
   drafting. E7/E8/E9 and remaining E2/E5 work are detailed in the review.

Shared files/migrations and each GPU lane serialize. Parallel source work needs ready
contracts, isolated ownership and a combined budget. Built, installed, usable and
accepted are separate states; prerequisites must meet the state their consumer needs.

## Decisions that unblocked stories

- **Storage (D39):** media in `gasha01:/hdd-nfs-repl/data/studio`, records in a `studio` database on `database/postgres16`. Unblocks E3.1.
- **Access and availability (D41):** LAN-only for now but online-ready, Authentik OIDC sign-in, stateless web app and API with at least two replicas across nodes. Applies to E3.1 and E6.1.
- **Board writer (D40):** a frontier agent through dev-env v2 until a local LLM is reliable. Unblocks E5.1. [E5.2](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/421) builds and evaluates the local writer harness, toward a purely local loop on talosw01.
- **Images (D42):** ComfyUI stays on talosm03; agents may upload versioned reference
  photos with provenance through authenticated API/MCP. Studio stores no paid API key.
- **Release (D29/D43/D44):** only go-live is formal approval; every video AI-labelled,
  public credits describe actual video/sound generation only. Upload stays manual.
