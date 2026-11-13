# Contracts

The canonical contract every E1 story and later work builds against:
[`studio-contracts-v1.md`](studio-contracts-v1.md) (story
[423](https://work.haynesnetwork.com/work_packages/423)). The E1 coordinator ratified it
at the review of PR 37 on 2026-11-13; that is not Tom's acceptance, and its proposals
stay open to him. Tom answered its owner questions Q-01 to Q-04 on 2026-11-13 (D49 to
D52). A story that depends on it pins the merged commit on `main`.

| Read | When |
|---|---|
| [Sections 1 and 2](studio-contracts-v1.md#1-vocabulary-and-the-legacy-mapping) | mapping a legacy manifest, naming an entity, minting an ID, a job |
| [Section 3](studio-contracts-v1.md#3-the-time-contract) | anything with durations, frames, fps or line offsets |
| [Section 4](studio-contracts-v1.md#4-cache-clocks-and-invalidation) | caching, splicing, deciding what an edit rebuilds |
| [Section 5](studio-contracts-v1.md#5-method-capability-matrix) | choosing or validating a board's method |
| [Sections 6 to 11](studio-contracts-v1.md#6-direction-and-executable-cues) | cues, provenance, runs, store, library, voices, go-live |
| [Section 12](studio-contracts-v1.md#12-api-ui-and-mcp-boundaries) | API endpoints, MCP tools, scopes |
| [Sections 13 and 14](studio-contracts-v1.md#13-stack-pin) | packaging, frameworks, tests and CI |
| [Sections 16 to 18](studio-contracts-v1.md#16-held-owner-questions) | owner questions, answered and open, proposals, where sources disagree |

## Examples

Text only: IDs, hashes and numbers. No media.

- [`examples/valid/`](examples/valid/): documents that satisfy the contract, used as-is
  as fixtures. The Winter Menu examples are computed from the public r4 manifest and
  evidence, so their frame totals match the recorded timeline. Placeholders in angle
  brackets (`<commit>`) and the `example` principals are not real values.
- [`examples/invalid/`](examples/invalid/): one broken rule each, in a wrapper:

```json
{
  "schema": "studio.invalid-case/v1",
  "rule": "time.hold_on_spoken_board",
  "expect": "invalid",
  "context": "write",
  "path": "/timing/hold_ms",
  "why": "One sentence naming the rule and its source.",
  "document": {}
}
```

`document` is the offending instance; `path` is a JSON Pointer into it. A `write` case
is a document as a client sends it, so it carries no `derived` block; the valid examples
are documents as the server returns them, so they do. `expect` is
`invalid`, `unavailable` (a valid design the studio cannot build yet) or `forbidden`.
`context` says where the rule fires: `write` (schema and write validation) or
`queue_run` (the document saves, and queueing a run fails). In that context a validator
must fail the document with exactly `rule`; specific rules take precedence over
`schema.unknown_field`. The rule index is
[section 15](studio-contracts-v1.md#15-rule-index).

`run-snapshot.json` is pretty-printed; the snapshot's `sha256` in the run examples is
computed over its canonical form (sorted keys, no whitespace, UTF-8).
