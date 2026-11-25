# Doll-short drafting benchmark

D46 sets the pilot bar. All five cases must pass every applicable automated
structural and safety check, and Tom must label at least four drafts usable as is
or with light edits. Frontier remains the default until Tom explicitly decides
to switch. Re-run the same benchmark for each new local model. [Studio plan,
D14, D40 and D46](../proposals/0003-studio-plan.md#decisions-so-far)

## Frozen inputs

Each case supplies a versioned original brief, a prepared `studio.story/v1`,
and explicit board keys and assertions in the manifest. The pinned
doll-short recipe uses the application's shot methods. The catalog contains
synthetic, production-scoped metadata for the supplied set, cast, voice, prop and
sound pins. Keep the same inputs across writers. The second set in After-Hours
Return is a whole-frame photo input. The story pins one layered set.
[Corpus manifest](../../src/haynes_studio/drafting_benchmark_data/manifest.json) ·
[Doll-short recipe source](fixtures/doll-short-v1.json)

| Case | What it exercises | Frontier baseline |
| --- | --- | --- |
| `chorus` | Four visible dolls with one speaking turn each | Absent |
| `two-sets` | A new set in a silent insert and preservation of two existing boards | Absent |
| `focal-prop` | A named miniature in the insert's photo inputs | Absent |
| `dense-dialogue` | Six alternating lines in one board and preservation of two existing boards | Absent |
| `timed-button` | A 2000 ms silent hold with the pinned sound at 1250 ms | Absent |

The manifest records SHA-256 for each brief, starting story, recipe and asset
catalog. The corpus version hashes the canonical manifest without its
`version` field, using hashes computed from the listed files' exact bytes.
A change to an input changes the computed version. The scorer refuses a
mismatch. Preserve the old revision for comparisons.

Existing frontier-written material belongs to two different titles. Their
committed briefs, prompts and production records are historical provenance.
Frontier token use and cost are unknown for this comparison. The scoring
examples are hand-written fixtures with synthetic evidence.
[The Winter Menu brief](../../titles/the-winter-menu/brief.md) ·
[Prompts](../../titles/the-winter-menu/prompts.json) ·
[Run log](../../titles/the-winter-menu/run-log.md) ·
[One More Meeting brief](../../titles/one-more-meeting/brief.md) ·
[Prompts](../../titles/one-more-meeting/prompts.json) ·
[Manifest](../../titles/one-more-meeting/manifest.json)

## Score a file

Run this example from the repository root with the locked Python environment
installed.

```sh
uv run --no-sync python -m haynes_studio.drafting_benchmark score \
  tests/drafting_benchmark/fixtures/two-sets.draft.json --case two-sets \
  --evidence tests/drafting_benchmark/fixtures/two-sets.evidence.json
```

The scorer reads a native `studio.agent-draft/v1` file. It checks the compiled
boards, recipe methods, timing, cast and asset references, case assertions,
write scope and, on the two revision cases, edit preservation. It prints JSON
with the corpus version, exact draft SHA-256, case ID, check statuses, rule
codes and paths, and verdict. Exit 0 means a case passed, 1 means it failed, and
2 means the command or its input files could not be processed. An unparseable
draft fails its schema check and leaves dependent checks unevaluated.
[Draft format](agent-drafting.md)

Keep capture separate from model output. A trusted runner must supply the
`studio.drafting-benchmark-evidence/v1` JSON, bound to the exact draft bytes by
`draft_sha256`. Record every attempted mutation in `writes`, with its `tool`,
resolved `production_id`, `story_id`, `board_id`, stable `board_key`, and boolean
`applied`. Get target identity from the runner's observations. The scorer uses
the application's production grant check and requires exactly the case's board
adds or patches. Missing, incomplete or out-of-scope evidence fails the check.

For a revision, start from the frozen story under the same fixture key as the
mutable board. The runner can seed the previous receipt's baseline from the
starting boards' stamps. The applicator can report protected or untracked
boards while a permitted patch succeeds. Capture the persisted protected boards
with Studio's canonical JSON serialization at the storage boundary. Supply the
exact UTF-8 strings keyed by board ID in `protected_boards`. Each string is
compared as bytes with its frozen starting board. A missing board or a byte
change fails, including on unstamped boards. New-draft cases report preservation
as `not_applicable`. [Example revision evidence](../../tests/drafting_benchmark/fixtures/two-sets.evidence.json)

## Summarise five results

Save one JSON result per case for the summary command.

```sh
uv run --no-sync python -m haynes_studio.drafting_benchmark summarise \
  chorus.result.json two-sets.result.json focal-prop.result.json \
  dense-dialogue.result.json timed-button.result.json
```

The JSON reports `structural_and_safety_all_pass` and the quality status
`pending: Tom's labels`. To report the quality count, pass `--labels` with Tom's
private JSON file. The following shows one entry. Supply all five, with their
case IDs and the exact hashes from the results.

```json
{
  "schema": "studio.drafting-benchmark-labels/v1",
  "reviewer": "Tom",
  "corpus_version": "<corpus_version from the case results>",
  "cases": {
    "chorus": {
      "draft_sha256": "<draft_sha256 from the chorus result>",
      "label": "usable_with_light_edits"
    }
  }
}
```

A result describes these five drafts against the frozen inputs and the evidence
the runner captured. Spoken timing without measured takes, render quality and
model quality outside these cases remain unmeasured. A pass supplies evidence
for Tom's switch review.

## Labelling sheet for Tom

**Proposed 2026-11-25.** Read the brief and its board sequence. Choose one label
for the draft.

| Label | What fits |
| --- | --- |
| Usable as is · `usable_as_is` | The board sequence, beats and dialogue can go to staging as written. |
| Usable with light edits · `usable_with_light_edits` | Local fixes such as tightening a line, nudging a pause or clarifying a cue leave the cast, board sequence, main beats and ending intact. |
| Not usable · `not_usable` | The draft needs a rewritten exchange, changed staging, a new cut or a different payoff before it can go to staging. |

Calibrate once by labelling a few representative examples. Aim for an example
of each label where available, and note the smallest change that would make a
borderline draft usable. Use those examples as anchors when labelling the five
drafts for each model. Keep the labels with the private results.

## Repeat for a new local model

1. Seed the prepared stories, their pins and the fixture key identity into an
   isolated fixture store with the frozen IDs. Give the runner the five briefs
   and the same write limits. Keep the corpus version and model/profile revision
   with the run. The drafting harness story owns fixture setup, model execution
   and independent write capture. [Story 421](https://work.haynesnetwork.com/work_packages/421)
2. Score the five outputs with their captured evidence, then summarise them.
   Matched model baseline runs and their provenance belong to the
   [baseline story](https://work.haynesnetwork.com/work_packages/463).
3. Attach Tom's labels when available. Carry results and profile revisions
   forward to the [scoreboard story](https://work.haynesnetwork.com/work_packages/464).
