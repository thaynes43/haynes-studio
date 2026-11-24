# Apply an agent draft

A sanctioned frontier session writes a `studio.agent-draft/v1` JSON document.
The `studio draft apply` command uses the scoped [Studio MCP](studio-mcp.md) to
place its boards in one prepared story for creative review. The applicator makes
zero model calls. A [staging work order](agent-drafting-work-order.md) gives the
session its brief, target and boundaries.

## Prepare and apply

The coordinator supplies a story ID and production ID, the story's pinned set
and cast slots, its layout names, visible library version IDs and a key with
`read` and `draft:write` for that production. The key reaches the command through
a mounted file or `STUDIO_AGENT_KEY`. Set `STUDIO_MCP_URL` to the coordinator's
MCP endpoint. It must use HTTPS except on loopback; `STUDIO_MCP_CA_FILE` accepts
a private CA bundle if needed. Keep the draft and receipt in a private job
directory.

```sh
studio draft apply "$JOB/draft.json" --story "$STORY_ID" \
  --key-file "$STUDIO_KEY_FILE" --out "$JOB/applied.json"
studio draft apply "$JOB/revision.json" --story "$STORY_ID" \
  --key-file "$STUDIO_KEY_FILE" --previous "$JOB/applied.json" \
  --out "$JOB/revised.json"
```

The [JSON schema](../../src/haynes_studio/schemas/studio.agent-draft.v1.schema.json)
and [three-board example](../../tests/drafting/fixtures/first.json) show the
input. The application uses the SHA-256 of the exact UTF-8 file bytes. The
production and story IDs bind the draft to its target. `set` asserts the story's
existing still and optional motion version IDs, or is null when there are no
pins. The applicator uses the story's existing cast, layouts and set; board
`cast` and `photo.input_asset_version_ids` carry the immutable pins the draft
uses. A board describes one clip. Its `key` stays stable across documents and
maps to a server-assigned board ID in the receipt.

- Each line names a cast slot or `narrator`. An optional line `key` lets a cue's
  anchor name `after_line` and `offset_ms`; the applicator resolves it to the line
  ID in the same write. A board-clock anchor uses `at_ms`. Write direction in
  `notes[].text` and executable cues in `cues`.
- Use `voice: "cast"` or `"narrator"` on a spoken board and null on a silent
  board. The applicator writes the board fields as a complete proposal. Voice
  and photo current-version pins start empty on a drafted board.
- The entire document passes schema, board/method and reference checks before
  the first write. Layered S2V needs dialogue and an on-screen speaker.
  Layered I2V needs cast. Whole-frame I2V supports sound cues and no picture
  cues. A layered board permits up to one camera cue. Whole-frame S2V is
  unavailable. Build still checks for generated takes, motion, photo versions
  and media bytes.
- The v1 command accepts 1–50 boards within a 4 MiB file. Each planned write must
  fit the existing 64 KiB MCP argument limit.

## Re-drafts and receipts

A first apply appends boards in document order to a story that has never had
boards. For a re-draft, pass the most recent receipt, keep the keys of the
boards you want to change, and leave out proposals for any boards you want to
leave as they are. A re-draft patches the eligible targets in place. It never
creates, deletes or reorders a board. New keys are unbound and reported in the
receipt. People can add boards in the editor.

Studio writes the authenticated key ID in `drafted_by` and adds
`draft_application` with the board key, declared model/session, server
timestamp, draft hash and resulting board revision. A signed-in person's
subsequent patch, reorder or tombstone of that board records `person_edit`.
Reorder protects agent-drafted boards whose positions changed, even if the old
order is later restored. An unrelated append or removal leaves the revisions
of the surviving boards alone.

An eligible target must still match the receipt's board ID, revision and draft
hash and Studio's recorded board key and applied revision. Reports name
changed, reordered, removed and untracked boards by ID, including removed
boards whose proposals were omitted. The previous receipt carries forward
their last confirmed state. Already-applied document bytes are skipped. Each
write also fences on the story revision under the API's story lock. A race
stops further writes and reports the failed board, confirmed earlier writes and
skipped later proposals. A missing response is `uncertain`. Inspect the boards
before proceeding. Keep the receipt, even when the command exits with a
conflict. A lost first-apply receipt plus a story with previous boards requires
coordinator reconciliation.

An invocation that reaches apply writes one create-only, mode-`0600` receipt.
`studio.agent-draft-receipt/v1` includes the production and story IDs, draft
hash, usage, each result and the usable baseline for the next re-draft. Exit
status is 0 for success (including already-applied skips), 1 for a failed,
partial or conflicted apply, and 2 for invocation or input errors.

The receipt records the model/session and `input_tokens`, `output_tokens`
and `cost_usd`. Missing or explicitly null numbers are recorded as JSON null
(unknown). A declared zero stays zero. This version keeps draft usage in the
receipt. A later migration can add `production_draft_applications.usage` as
JSONB, with one append-only attempt row keyed by production and an idempotent
attempt ID. Expose it through
`POST /v1/productions/{id}/draft-applications` and MCP
`studio_record_draft_application`, authorized for that production's
`draft:write`. Run usage remains run provenance.

The applicator calls only story reads, board reads, asset metadata searches and
board adds or patches. The MCP server has no media-byte, approval or
publication tool. Expose only MCP to the drafting session; direct API media
reads have their own production-scoped behavior.
