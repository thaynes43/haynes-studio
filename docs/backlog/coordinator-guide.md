# Haynes Studio coordinator guide

Start here without prior chat context. Review handoff:
https://work.haynesnetwork.com/work_packages/422 and
[2026-11-05 review](review-2026-11-05.md) (24 findings: 3 critical, 12 high,
7 medium, 2 low). This is a dispatch guide, not authority to start work.

## Truth and readiness

| Source | Use |
|---|---|
| OpenProject project `haynes-studio` (ID 11), saga https://work.haynesnetwork.com/work_packages/362 | Canonical scope, current holds, owner, budget, state and human verdict. Read current history; the review's export is a snapshot. |
| [AGENTS.md](../../AGENTS.md) and current work order | Authorization, hard rules, resource/stop limits. A review proposal grants no execution permission. |
| [Proposal 0003](../proposals/0003-studio-plan.md), D1–D44 | Product decisions. D29 supersedes creative approval gates; D39/D41 supersede old RBD/no-login/storage text; D40 frontier writer; D42 image lane/uploads; D43/D44 release labels/credits. Later rulings beat older prose. |
| [Implementation map](../design/studio-ui-mockup/implementation-backlog.md), [review edits](review-2026-11-05.md#tracker-edits--existing-work-packages) | Mockup-to-story ownership and proposed field repairs. R01–R39 are now tracker items 423–461 (R*n* = 422 + *n*); see the [label table](review-2026-11-05.md#review-labels-in-the-tracker). |
| [v6 mockup](../design/studio-ui-mockup/index.html) and [review.md](../design/studio-ui-mockup/review.md) | Interaction reference, not real generation/auth/storage. Old question defaults are history. |
| [E0 findings](../../titles/the-winter-menu/video-e0/findings.md), [layered](../../titles/the-winter-menu/video-e0/findings-layered.md), [S2V](../../titles/the-winter-menu/video-e0/findings-s2v.md) | Measured inputs/limits. D24/latest S2V addendum wins over early premium-only recommendation. Not fresh service health. |

**Artifact-ready:** link merged commit + compatible schema/API version + relevant
passing checks and unresolved findings. **Built:** immutable image digest/revision.
**Installed:** authorized GitOps reconciliation + runtime health/auth/path checks.
**Usable:** named end-to-end flow works with private real artifacts. **Accepted:**
Tom/authorized accepter's explicit verdict. Track these separately. A dependency
requiring installed/usable evidence is not ready because its source PR merged.
Do not turn artifact dependencies into whole-epic Accepted barriers: E3 source can
start from E1 source contracts; E1 live acceptance can use partial E3 installation.

## Vocabulary and fixed infrastructure

| Term | Meaning |
|---|---|
| Production / media type / story | Themed collection (Yellowbirds) / enabled Short 9:16 or Video 16:9 / one video. Story in this domain differs from a tracker work package. |
| Board / run | One intended clip with stable ID / immutable queued snapshot of a story plus outputs. Draft edits never mutate queued or finished runs. |
| Revision / candidate / drop | Versioned edit / a run presented for a target / actual publication after exact-run go-live. Legacy production IDs map explicitly to run/delivery IDs. |
| Format | Immutable recipe authored by Tom + staging agent; shepherd reads only. Length enforcement is unresolved; no invented script/photo approval. |
| Method | Exactly one layer (layered, whole-frame) × one motion (S2V, I2V). Spoken boards default S2V, disabled without lines; only implemented combinations are buildable. |
| Voice/photo asset | Immutable version made before Build, with input signature/hash. Measured voice sets duration plus agreed pad; silent board uses hold. Mockup's 0.25 s/25 fps are not production decisions. |
| Direction | Editable notes. Free text is not an executable shell, guaranteed cue interpretation or new renderer capability. Structured cue mapping belongs to R01. |
| Lease / image lane | The existing Wan API compute lease, including unknown-work checks, governs Wan/Foley/local load/infer/unload on talosw01; no second GPU scheduler. Comfy images use a separate household-first lane on comfyui-0/talosm03. |
| studio-render | Existing `ai/deploy/studio-render` on talosw01, <=24 vCPUs, low priority, <=22 workers; media `/studio`. Session CPU <=2 threads, render workers 1, ffmpeg threads 2. |
| Stores / access | Media `gasha01:/hdd-nfs-repl/data/studio`, metadata/queue in `studio` on 3-instance `database/postgres16`. No app-local state volumes. LAN-only, every request authenticated; human Authentik OIDC, scoped agent MCP keys. |
| Availability | API/web >=2 replicas spread across nodes with PDBs. talosw01 loss pauses builds while app stays up. NFS availability/backup is a separate dependency, not guaranteed by replicas. |

## Order and parallel work

Apply/reconcile the review first; Tom/Meatball grooms and explicitly starts each story.
All execution items in the supplied export are Ungroomed. No dispatch from that snapshot.
The story blocks are the detailed edge list; the following groups are not whole epics
assigned to one worker.

1. R01 contracts -> R02 test foundation -> [378](https://work.haynesnetwork.com/work_packages/378) legacy core -> [404](https://work.haynesnetwork.com/work_packages/404) canonical boards.
   R03 adapters follows [378](https://work.haynesnetwork.com/work_packages/378). After [404](https://work.haynesnetwork.com/work_packages/404), [379](https://work.haynesnetwork.com/work_packages/379) atomic stages and [382](https://work.haynesnetwork.com/work_packages/382) library can run
   independently only if schema files stay fixed. Then [380](https://work.haynesnetwork.com/work_packages/380) cache / [381](https://work.haynesnetwork.com/work_packages/381) delivery,
   [405](https://work.haynesnetwork.com/work_packages/405) voice, [407](https://work.haynesnetwork.com/work_packages/407) photo -> [408](https://work.haynesnetwork.com/work_packages/408) promotion, R35 motion records.
2. R04 layered and R05 whole-frame adapters -> [406](https://work.haynesnetwork.com/work_packages/406) orchestration. R36 provides typed
   Wan product operations; existing PoC pod-exec monkeypatches are not that API.
   [409](https://work.haynesnetwork.com/work_packages/409) source API follows [404](https://work.haynesnetwork.com/work_packages/404)/[382](https://work.haynesnetwork.com/work_packages/382); R07 MCP -> [411](https://work.haynesnetwork.com/work_packages/411) frontier draft -> R33 rubric.
   [410](https://work.haynesnetwork.com/work_packages/410) durable queue follows [409](https://work.haynesnetwork.com/work_packages/409)/[406](https://work.haynesnetwork.com/work_packages/406); R08 operations follows [405](https://work.haynesnetwork.com/work_packages/405)/[407](https://work.haynesnetwork.com/work_packages/407)/[408](https://work.haynesnetwork.com/work_packages/408)/[410](https://work.haynesnetwork.com/work_packages/410)/R07.
3. [413](https://work.haynesnetwork.com/work_packages/413) shell follows [409](https://work.haynesnetwork.com/work_packages/409) contract; [412](https://work.haynesnetwork.com/work_packages/412) approval can proceed separately in backend
   files. [414](https://work.haynesnetwork.com/work_packages/414) review follows [413](https://work.haynesnetwork.com/work_packages/413)/[412](https://work.haynesnetwork.com/work_packages/412)/[409](https://work.haynesnetwork.com/work_packages/409). [415](https://work.haynesnetwork.com/work_packages/415) creation follows [413](https://work.haynesnetwork.com/work_packages/413)/[409](https://work.haynesnetwork.com/work_packages/409) -> [416](https://work.haynesnetwork.com/work_packages/416) stage
   (also [405](https://work.haynesnetwork.com/work_packages/405)/R08) -> [417](https://work.haynesnetwork.com/work_packages/417) inspector -> [418](https://work.haynesnetwork.com/work_packages/418) photo -> R34 library. [419](https://work.haynesnetwork.com/work_packages/419) runs follows
   [417](https://work.haynesnetwork.com/work_packages/417)/[410](https://work.haynesnetwork.com/work_packages/410)/R08. UI feature owners add tests; R16 later completes cross-feature journey.
4. R09 DB, R10 OIDC **source configuration**, R11 built images -> R12 deployment.
   R10/R12 agree LAN origin first, then activate/test redirects serially; no circular
   “both must already be installed.” R13 backup -> R14 restore. R15 integration/HA;
   R06 private build requires R08/R12/R36 installed. R16 app end-to-end -> R17/R18
   references/runbooks (R17 can start earlier after API/MCP contracts). [420](https://work.haynesnetwork.com/work_packages/420) requires
   all UI, installed/technical evidence, docs and Tom's demo window.
5. R19 tested lease source -> R20 authorized lease rollout + hosting -> [421](https://work.haynesnetwork.com/work_packages/421) local evaluation, also requiring
   [411](https://work.haynesnetwork.com/work_packages/411)/R07/R33. [411](https://work.haynesnetwork.com/work_packages/411) never waits for E4. R25 format recipes -> R21 archive -> R22
   authorized subtitle adapter. R23 escalation contract -> R24 sanctioned drill.
   R37–R39 supply one approved matting/detection/upscale backend each. R29–R31
   wait for those profile contracts, then installed evidence for real quality checks.
   R28–R31 quality work uses bounded fixtures; do not
   declare those installed from source adapters. R32 shepherd uses these existing
   contracts; it is separate from writer quality. R26 feedback follows [414](https://work.haynesnetwork.com/work_packages/414)/[419](https://work.haynesnetwork.com/work_packages/419)/R25;
   R27 private release package follows [412](https://work.haynesnetwork.com/work_packages/412)/R25/R26 and actual run provenance.

**Serialize:** all mutable GPU/model work on the Wan lane; one prompt on shared
ComfyUI; schema/migration writers; live DB/backup/restore operations; shared web
shell/router files; each dependent source change until prerequisite merge. Image
work may overlap a Wan build only with separate lane ownership and household queue
readiness. No same-file parallel edits disguised as independent stories.

**Potential parallel groups:** after contracts, source photo client versus API CRUD;
after API, UI shell versus isolated approval backend; after prerequisites, separate
method adapter files with fixed shared interfaces. GitOps DB/OIDC tasks are best run
serially due to shared configuration/identity. Propose at most two workers total,
one per story, only after combined quota/time and isolated paths/resources are known;
unknown quota is not capacity. No dispatch merely because slots exist.

## Work type, tier and review

H = hard design or risky; U = user-visible UI/UX; I = routine implementation;
T = testing; D = documentation; G = infrastructure through GitOps.
Opus handles unresolved/high-risk work; Sol is the normal implementation/test tier;
Terra gets fixed-schema mechanical work; Sonnet gets routine CI/build work. The table
is a planning recommendation, not permission to route across providers. A Codex
coordinator retains UX/design/user-facing prose on Astra under the current policy;
authorized Claude story ownership can use Opus. No cross-provider fallback on quota.

| Story | Type | Tier | Why / safeguard | Required review before merge |
|---|---|---|---|---|
| https://work.haynesnetwork.com/work_packages/378 | I | Sol | Extraction is bounded by legacy fixtures. | Compatibility/schema review |
| https://work.haynesnetwork.com/work_packages/379 | I | Sol | Multi-file publish needs adversarial failure cases. | Atomicity/concurrent-failure review |
| https://work.haynesnetwork.com/work_packages/380 | H | Opus | Audio and film-time effects create subtle invalidation. | Media/cache clock review |
| https://work.haynesnetwork.com/work_packages/381 | I | Sol | Existing create-only design plus synthetic proxy fixtures bounds it. | Storage/delivery review |
| https://work.haynesnetwork.com/work_packages/382 | I | Sol | Fixed immutable-ID contract makes record work routine. | Library/provenance review |
| https://work.haynesnetwork.com/work_packages/404 | H | Opus | This contract controls every later layer. | Architecture/timing review |
| https://work.haynesnetwork.com/work_packages/405 | I | Sol | Frozen sample/line-offset fixtures prevent timing guesses. | Audio/timing review |
| https://work.haynesnetwork.com/work_packages/406 | H | Opus | Method failures, run immutability and provenance cross layers. | Media/orchestration review |
| https://work.haynesnetwork.com/work_packages/407 | I | Sol | Fixed generation/import signatures make it bounded. | Provenance/stale-race review |
| https://work.haynesnetwork.com/work_packages/408 | I | Terra | Explicit state transitions and fake client suit a cheaper tier. | Sol checks promotion/version tests |
| https://work.haynesnetwork.com/work_packages/409 | H | Opus | Scopes, migrations and content access are risk boundaries. | API/DB/security review |
| https://work.haynesnetwork.com/work_packages/410 | H | Opus | Duplicate GPU work after restart is costly. | Concurrency/lease recovery review |
| https://work.haynesnetwork.com/work_packages/411 | H | Opus | Generated changes must preserve human edits. | Edit-conflict/agent-scope review |
| https://work.haynesnetwork.com/work_packages/412 | H | Opus | Only Tom can authorize the exact finished run. | Identity/rights/disclosure review |
| https://work.haynesnetwork.com/work_packages/413 | U | Opus | Navigation, identity errors and phone shell are visible. | Coordinator UX/OIDC review |
| https://work.haynesnetwork.com/work_packages/414 | U | Opus | Filters and run identity affect release decisions. | Coordinator UX/approval review |
| https://work.haynesnetwork.com/work_packages/415 | U | Opus | Creation/history/context must feel coherent. | Coordinator UX/API review |
| https://work.haynesnetwork.com/work_packages/416 | U | Opus | Stable board context and real timing need care. | Coordinator UX/timing/accessibility review |
| https://work.haynesnetwork.com/work_packages/417 | U | Opus | Forms must preserve drafts during asynchronous jobs. | Coordinator UX/stale-response review |
| https://work.haynesnetwork.com/work_packages/418 | U | Opus | Versions and stale photos drive expensive builds. | Coordinator UX/provenance review |
| https://work.haynesnetwork.com/work_packages/419 | U | Opus | Compare must show the intended frozen inputs. | Coordinator UX/queue review |
| https://work.haynesnetwork.com/work_packages/420 | T | Opus | Phone/accessibility fixes remain user-visible work. | Coordinator technical evidence; Tom usability verdict |
| https://work.haynesnetwork.com/work_packages/421 | H | Sol | Safe only after R33 rubric, hosted profile and frozen corpus. | Opus eval/tool-safety review; Tom switch verdict |
| [R01 · 423](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/423) | H | Opus | Cross-layer semantics must be settled before cheaper implementation. | Coordinator architecture/security review; Tom on unresolved choices |
| [R02 · 424](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/424) | T | Sonnet | Routine harness work once interfaces are fixed. | Sol reviews fixture realism and CI permissions |
| [R03 · 425](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/425) | I | Sol | Mechanical extraction is safe only with frozen fake-service fixtures. | Coordinator plus compatibility reviewer |
| [R04 · 426](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/426) | H | Opus | Timing, cache and sample/frame conversion can silently corrupt output. | Coordinator media/timing review with independent frame checks |
| [R05 · 427](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/427) | I | Sol | A fixed supported method and tiny fixtures make this bounded. | Media/timing reviewer checks decoded boundaries |
| [R06 · 428](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/428) | T | Sol | Execution audit is routine only after all interfaces and caps exist. | Coordinator technical evidence review; Tom watches/listens separately |
| [R07 · 429](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/429) | H | Opus | Scopes and cross-production mutation are access boundaries. | Security and API contract review |
| [R08 · 430](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/430) | H | Opus | Upload and side-effect retries need adversarial review. | Security/API review including upload resource limits |
| [R09 · 431](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/431) | G | Opus | Shared database and credentials require precise scope. | Infrastructure/security review and Tom action gate |
| [R10 · 432](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/432) | G | Opus | A login success alone does not prove approval authorization. | OIDC/security review; Tom identity/access authorization |
| [R11 · 433](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/433) | I | Sonnet | Mechanical builds after entry points and locks are fixed. | Build/security review checks image contents and workflow permissions |
| [R12 · 434](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/434) | G | Opus | Replicas, OIDC, storage and network must agree. | Infrastructure/security review; Tom ingress/access gate |
| [R13 · 435](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/435) | G | Opus | CNPG backups alone cannot recover media. | Storage/recovery review; Tom retention/backup gate |
| [R14 · 436](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/436) | T | Sol | A bounded drill is routine after the recovery plan is reviewed. | Storage/security reviewer checks target isolation and evidence |
| [R15 · 437](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/437) | T | Sol | Targeted failure cases need independent evidence, not more implementation. | Coordinator queue/security review; infra owner for disruption |
| [R16 · 438](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/438) | T | Sol | Explicit mockup behaviors make test work safe for a cheaper worker. | UI owner checks behavioral fidelity; coordinator checks real/fake boundary |
| [R17 · 439](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/439) | D | Grok | Mechanical contract reference is low risk with generated schema checks; use only a verified sanctioned Grok path. | Sol verifies every example/schema; coordinator reviews public text |
| [R18 · 440](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/440) | D | Opus | User-facing instructions and recovery boundaries require careful judgment. | Coordinator user-copy/operability review |
| [R19 · 441](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/441) | G | Opus | Load/inference/unload must all remain inside one compute authority. | Lease/concurrency/security review |
| [R20 · 442](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/442) | G | Opus | Hosting changes the shared GPU runtime and consumes storage. | Infrastructure/model/lease review; Tom resource gate |
| [R21 · 443](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/443) | I | Sol | Structured archive operations are routine with a fixed contract. | Coordinator provenance/edit-conflict review |
| [R22 · 444](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/444) | H | Opus | Read-only data can still exceed source rights or leak private text. | Privacy/originality review; Tom source authorization and creative feedback |
| [R23 · 445](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/445) | H | Opus | A responder request conveys bounded action, never broader authority. | Coordinator/dev-env owner security and budget review |
| [R24 · 446](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/446) | T | Sol | A single synthetic drill is bounded once the external contract is installed. | Coordinator/dev-env owner verifies launch authority and patch scope |
| [R25 · 447](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/447) | H | Opus | Recipe authority must not become shepherd taste judgment. | Coordinator domain review; Tom actual format choice |
| [R26 · 448](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/448) | U | Opus | User feedback must target the intended immutable run. | Coordinator UX/domain review |
| [R27 · 449](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/449) | H | Opus | Rights and disclosure affect whether release is permitted. | Coordinator rights/security review; Tom go-live only |
| [R28 · 450](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/450) | H | Opus | E0 proves correlation scores can reject good clips and miss visible defects. | Media/check reviewer; Tom labels and taste separate |
| [R29 · 451](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/451) | H | Opus | A plausible alpha output can erase eyes or alter cast scale. | Media/licence review |
| [R30 · 452](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/452) | H | Opus | False visibility checks waste full video builds. | Media/geometry reviewer checks occlusion and failure modes |
| [R31 · 453](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/453) | I | Sol | Explicit conversion fixtures make source work bounded. | Media/timing review; Tom visual comparison |
| [R32 · 454](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/454) | H | Opus | An agent workflow must not expand retries or overwrite human edits. | Coordinator workflow/lease/provenance review |
| [R33 · 455](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/455) | T | Sol | Scoring invariants are routine once taste criteria are explicitly owned. | Coordinator evaluation review; Tom switch bar/rubric |
| [R34 · 456](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/456) | U | Opus | Board filters and promotion are visible state with costly mistakes. | Coordinator UX/API review |
| [R35 · 457](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/457) | I | Terra | Mechanical record import with a strict schema suits a cheaper tier. | Sol checks immutable IDs/clock fixture tests |
| [R36 · 458](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/458) | G | Opus | PoC in-pod imports are not a stable product service interface. | Wan owner/lease/API review; Tom maintenance gate if disruptive |
| [R37 · 459](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/459) | G | Opus | Backend availability needs an owner; a source adapter alone cannot supply it. | Model/licence, resource and infrastructure review; Tom action gate |
| [R38 · 460](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/460) | G | Opus | Backend availability needs an owner; a source adapter alone cannot supply it. | Model/licence, resource and infrastructure review; Tom action gate |
| [R39 · 461](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/461) | G | Opus | Backend availability needs an owner; a source adapter alone cannot supply it. | Model/licence, resource and infrastructure review; Tom action gate |

A cheaper tier is unsafe for H/U work without the listed contract, negative fixture
or reference implementation. Never ask Terra/Grok to discover architecture, change
scopes, reconcile leases or judge media taste. Escalate a shallow/mismatched result
within the assigned story budget; do not silently expand scope or change provider.
Grok is proposed only for R17's schema-checkable reference work: no Grok launcher or
full model ID is supplied here, so keep that dispatch held until a sanctioned path
is verified; Sonnet is the recommended already-described alternative if authorized.

## Tom and external gates

| Gate | Matching work / stop |
|---|---|
| Groom/start and Accepted | Every item: Tom/Meatball handles Ungroomed transition; authorized accepter handles Accepted. Preserve explicit holds. |
| GPU/worker allocation, model profile/download, capacity | R06/R20/R28/R31/R32/R37–R39/[421](https://work.haynesnetwork.com/work_packages/421) and any real generation: explicit bounded window/job count/bytes/lease time; busy/unknown work stops. D2/D18 placement is already decided; no need to re-ask placement. |
| DB role/credentials, OIDC approver identity, ingress/network/NFS access | R09/R10/R12: Tom-authorized action and owner-managed secrets, all config through haynes-ops. No new login, grant or bypass after denial. |
| Backup route/retention/objectives and isolated restore | R13/R14: NAS/DB owner and Tom authorize path/target/caps; never overwrite originals. |
| Subtitle source | R22: named sanctioned read-only path and one scene; no source text in public git. |
| Responder launch, MCP reachability and usage cap | R23/R24: external dev-env owner verifies path; one launch only after its authorization. No fake route or borrowed credentials. |
| Taste, format/rubric choices and writer switch | R01/R25/R28/R33/[421](https://work.haynesnetwork.com/work_packages/421)/[420](https://work.haynesnetwork.com/work_packages/420): record Tom's feedback separately from tests. No switch or Accepted from a pass-rate alone. No creative gate before Build. |
| Rights/disclosure, channel ownership and go-live | [412](https://work.haynesnetwork.com/work_packages/412)/R27: verified exact-run approval by Tom; every video AI-labelled, video/sound-only public credits. Tom creates channel. No account or live-platform calls in these stories. |
| Paid inference / broader access / publishing integration | Any story: explicit Tom approval, provisioned key and cost cap; separate authorized integration story. D42 subscription-session uploads are allowed only within that session's sanctioned scope, never a paid API key in studio. |

The review's three unresolved grooming questions, options and recommendations are
[recorded here](review-2026-11-05.md#questions-for-tom--headless-handoff-no-live-ask).
Do not re-ask D39 storage, D41 login or D42 image placement.

## Tracker and dispatch mechanics

Use `opwork --project haynes-studio search ...`, `show ID --history`, then claim only
a started, artifact-ready bounded story. Default project is wrong. Agents cannot
move out of Ungroomed (HTTP 422); report the hold, do not change grants. The R-label stories already exist (423–461); Tom/Meatball grooms them like any other item. Keep full
`https://work.haynesnetwork.com/work_packages/ID` links and record progress/handoff on
the canonical item. This review session is expressly forbidden tracker writes.

Dispatch shapes supplied by the work order (verify current supported CLI before use):

```bash
agent-run --project haynes-studio --agent claude --model claude-opus-5-5 --effort xhigh --prompt-file /path/to/work-order.md
agent-run --project haynes-studio --agent claude --model claude-sonnet-5-5 --effort high --prompt-file /path/to/work-order.md
agent-run --project haynes-studio --agent codex --model gpt-6.1-sol --effort xhigh --prompt-file /path/to/work-order.md
agent-run --project haynes-studio --agent codex --model gpt-5.6-terra --effort xhigh --prompt-file /path/to/work-order.md
```

No Codex `--sandbox` flag. No invented Grok flag/model ID. A verified CLI rejection
is a blocker for that launch, not permission to update credentials or route elsewhere.
A separate pod is appropriate only for an authorized worker story. Native Codex
subtasks, where permitted, use collaboration tools; they are not agent-run sessions.

Give a worker one full tracker URL and all seven fields, pinned source SHA/worktree,
latest applicable decisions, exact files/ops, fixture and private artifact locators,
ready prerequisite evidence, measurable tests/state, allowed resources, inference and
storage caps, concurrency, checkpoint and stop. Say explicitly: <=2 CPU threads in
session, no stress/load/wide loops; ready PR, no self-merge. Include headless questions
with options/recommendation in PR; stop only dependent work at a real hold.

Require handoff: branch/commit/ready PR, changed contract/schema/digests, exact tests
and results, private output locators/hashes, source/built/installed/usable/accepted
states, measured time/usage/cost or unknown, decisions, failed retries, remaining
findings/gates and next safe step. Text only in public repo; no raw test/env dumps,
media, subtitles, voice samples, weights, secrets or full email addresses.

Coordinator reviews diff/docs and required checks, fixes or answers every emitted
advisory finding, then merges authorized worker PRs. Claude review is optional and
never required; skipped/failed/unavailable is recorded, not retried indefinitely.
Keep current holds: a ready PR does not authorize deployment or creative acceptance.

Stop the dependent action at an unresolved product/security contract, missing
artifact/access, denied tool, unknown GPU work, missing budget/capacity, explicit
hold/pause or session cap/context threshold. Save a durable checkpoint/PR and report
the exact owner/next step. Do not extend a story, invent an approval, start its
follow-up or reopen a completed worker to keep the session moving.
