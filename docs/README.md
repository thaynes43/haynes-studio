# Docs

| Doc | Read it when |
|---|---|
| [backlog/coordinator-guide.md](backlog/coordinator-guide.md) | you are coordinating without prior chat context: truth, readiness, order, worker tiers and gates |
| [backlog/review-2026-11-05.md](backlog/review-2026-11-05.md) | you are grooming the exported backlog: ranked findings, tracker repairs and splits (applied to the tracker on 2026-11-05; R01 to R39 are items 423 to 461) |
| [process/manual-short-poc.md](process/manual-short-poc.md) | you are making a short by hand, or turning a manual step into a tool |
| [process/testing.md](process/testing.md) | you are running or adding tests, registering a contract validator, or reading a CI check: suites, commands, limits, fixtures and check names |
| [reference/studio-cli.md](reference/studio-cli.md) | you are running the `studio` command or building on the `haynes_studio` package: commands, the legacy manifest schema and version map, its rules, and the timeline check against r1 to r4 |
| [reference/services.md](reference/services.md) | you need to know which in-cluster service does what and how to reach it |
| [reference/legacy-adapters.md](reference/legacy-adapters.md) | you are calling Kokoro, Whisper, ComfyUI or the legacy Wan ledger from code (runner, clients, pinned graphs and snippets, fakes), or recovering The Winter Menu's private inputs with the [recovery map](reference/legacy-recovery-map.md) |
| [reference/doll-format.md](reference/doll-format.md) | you are writing a brief, prompting art or editing; the style rules |
| [reference/baseline-op345.md](reference/baseline-op345.md) | you want to see how the first doll short was made and which scripts it used |
| [proposals/0003-studio-plan.md](proposals/0003-studio-plan.md) | you are planning or building the studio: decisions, product model, pipeline, epics |
| [contracts/README.md](contracts/README.md) | you are building any E1 or later story: the canonical contract (vocabulary and legacy mapping, IDs, time, cache, methods, provenance, store, API and MCP operations, stack, tests) with JSON examples |
| [reference/model-licences.md](reference/model-licences.md) | you need a model's licence terms, whether what it makes may be used commercially, or a licence object to fill: the register (JSON beside it), its limits, and how the library uses it |
| [reference/studio-library.md](reference/studio-library.md) | you are building on assets or asset versions: the library schemas and validators, version and pin rules, import, promotion, labels, the resolver, the facts it supplies, and the Winter Menu library from public files |
| [reference/motion-clips.md](reference/motion-clips.md) | you are recording, pinning or resolving a doll loop, set loop or speech-to-video clip: the motion block, its identity, the board resolver and its codes, and the E0 clips with their gaps |
| [reference/studio-voice.md](reference/studio-voice.md) | you are building on board voices or jobs: take and version signatures, what an edit costs in speech calls, measured takes and the track, the `studio.job/v1` type and its state machine, and what the API needs to generate, list and play a board's voice |
| [reference/studio-delivery.md](reference/studio-delivery.md) | you are delivering a finished master or reading a delivery: the `studio.delivery/v1` schema and validator, the master and proxy checks, the phone proxy and its size rule, publication as one stage, idempotence and races, and legacy deliveries from the Wan ledger |
| [reference/studio-model.md](reference/studio-model.md) | you are building on productions, stories or boards: the canonical schemas, validators and their contexts, derived timing, the facts the asset library supplies, and the legacy import |
| [reference/store-and-stages.md](reference/store-and-stages.md) | you are publishing or reading media, committing a build stage, or checking a story before a build: the store layout and locators, create-only publication, stage records, `store doctor` and the pre-build check |
| [reference/cache-and-splice.md](reference/cache-and-splice.md) | you are keying, caching or splicing build artifacts: every cache key and its inputs, the board clock and seeds, the segment cache on the store, the renderer interface, encoding, the splice and the invalidation matrix as tested |
| [reference/whole-frame-adapter.md](reference/whole-frame-adapter.md) | you are building or running whole-frame image-to-video boards: the clip length and chain policy, the clip source interface and what a live Wan source must do, the clip set record, the renderer, refusals and codes |
| [design/studio-ui-mockup/index.html](design/studio-ui-mockup/index.html) | you are building the studio UI (E6) or its API (E3, E9): the clickable storyboard mockup, with API notes per panel |
| [design/studio-ui-mockup/implementation-backlog.md](design/studio-ui-mockup/implementation-backlog.md) | you are picking up UI or API work: each mockup surface mapped to its OpenProject story, with order and blockers |
| [proposals/0002-agentic-studio.md](proposals/0002-agentic-studio.md) | history: the first plan and where the PoC's assistance went (superseded by 0003) |
| [proposals/0001-tooling-backlog.md](proposals/0001-tooling-backlog.md) | you want the requirements list drawn straight from the manual run (superseded by 0002) |
| [decisions/](decisions/) | you wonder why something is the way it is |

Add a decision record (`decisions/NNNN-short-title.md`) whenever a choice would
otherwise be relitigated: what was decided, by whom and when, and why.
