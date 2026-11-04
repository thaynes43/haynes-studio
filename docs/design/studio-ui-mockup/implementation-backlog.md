# Studio UI implementation backlog

This page maps every surface of the mockup ([index.html](index.html), v6) to the OpenProject story that builds it. The stories were filed on 2026-11-04 from story [401](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/401). All of them are Ungroomed and wait for Tom to start them. Decisions D25 to D38 are in [proposal 0003](../../proposals/0003-studio-plan.md).

## Mockup surface to story

| Mockup surface | Decisions | UI story (E6) | Backend stories |
| --- | --- | --- | --- |
| Shell: Productions and Editor nav, button breadcrumb, user menu, theme, saved selections | D28, D32, D36, D37 | [E6.1](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/413) | [E3.1](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/409) |
| Productions tree, media types a production uses, media list with status filters, story review page | D28, D29, D31 | [E6.2](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/414) | [E3.1](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/409), [E9.1](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/412) |
| Editor landing; create production, media type and story | D36 | [E6.3](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/415) | [E1.6](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/404), [E3.1](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/409) |
| Stage and panel timeline: add, remove and reorder boards; running length | D27, D37 | [E6.4](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/416) | [E1.6](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/404), [E1.7](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/405) |
| Inspector: script, voice and timing, method badges, direction notes | D33, D35, D38 | [E6.5](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/417) | [E1.6](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/404), [E1.7](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/405) |
| Reference photo composer; asset library with the board as a filter; generate and promote | D28, D34 | [E6.6](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/418) | [E2.1](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/407), [E2.2](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/408) |
| Build, queued runs, progress, estimate, compare | D30 | [E6.7](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/419) | [E3.2](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/410), [E1.8](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/406) |
| Agent-drafted boards | D27, D29, D40 | covered by E6.4 and E6.5 | [E5.1](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/411), [E5.2](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/421) |
| Phone pass and E6 acceptance demo | | [E6.8](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/420) | |

## Order

1. **Model and render path.** E1.1 to E1.5 ([378](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/378) to [382](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/382)), then E1.6, E1.7 and E1.8. E1.8 also waits for the E0 findings ([395](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/395)).
2. **Generation.** E2.1 and E2.2 depend on the library (E1.5) and the board model (E1.6).
3. **Service.** E3.1 follows the storage decision D39. E3.2 comes after E3.1 and E1.8. E9.1 and E5.1 build on E3.1, and E5.2 follows E5.1 once a local model is hosted (E4).
4. **UI.** E6.1 to E6.7 run in order, each after its backend stories. E6.8 closes the epic.

Stories that touch the same files or the GPUs run one after another. The rest can run in parallel only when their prerequisites are merged.

## Decisions that unblocked stories

- **Storage (D39):** media in `gasha01:/hdd-nfs-repl/data/studio`, records in a `studio` database on `database/postgres16`. Unblocks E3.1.
- **Access and availability (D41):** LAN-only for now but online-ready, Authentik OIDC sign-in, stateless web app and API with at least two replicas across nodes. Applies to E3.1 and E6.1.
- **Board writer (D40):** a frontier agent through dev-env v2 until a local LLM is reliable. Unblocks E5.1. [E5.2](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/421) builds and evaluates the local writer harness, toward a purely local loop on talosw01.
