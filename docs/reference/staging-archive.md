# Staging archive

The staging archive keeps private briefs, scripts and storyboard drafts for one
production. A record has an immutable `arc_` ID, kind and title. Its first
version and subsequent revisions have immutable `arv_` IDs. Store the version
ID in a handoff so the next reader can retrieve the same text after another
revision arrives.

## Operations

| MCP tool | HTTP under `/v1` | Agent grants on the production |
| --- | --- | --- |
| `studio_create_archive_record` | `POST /productions/{id}/archive-records` | `archive:write` |
| `studio_add_archive_version` | `POST /archive-records/{id}/versions` | `archive:write` |
| `studio_list_archive_records` | `GET /productions/{id}/archive-records` | `archive:read` |
| `studio_get_archive_record` | `GET /archive-records/{id}` | `archive:read` |
| `studio_get_archive_version` | `GET /archive-versions/{id}` | `archive:read` |
| `studio_apply_archive_storyboard` | `POST /archive-versions/{id}/apply` | `archive:read` and `draft:write` |

Signed-in people can call all six HTTP operations. Browser writes require the
session's CSRF header. Worker tokens receive 401.

Create takes `kind`, `title`, `text`, `provenance` and an optional
`format_version_id`. The kind is `brief`, `script` or `storyboard`. The title
has 1 to 80 characters. Format IDs refer to exact saved [format versions](formats.md).
Text may be up to 262,144 UTF-8 bytes. Tabs, line feeds, carriage returns and
Unicode text are preserved exactly. Other control characters and credential
shapes detected by the Studio prose check are refused.

Use `{"origin":"original"}` for original work. Adapted work uses
`{"origin":"adapted","source_locator":{"label":"fixture-scene:12","sha256":"…"}}`.
The label has 1 to 128 ASCII letters, digits, dots, underscores, colons or
hyphens, starting with a letter or digit. Supply the lower-case 64-character
SHA-256 of the private source passage. The locator stores only the opaque label
and digest.

A revision takes the same version fields plus `revises_version_id`. Supply the
current `head_version_id`. If another revision arrived first, the API returns
409 `archive.stale_version` with the current version ID in
`error.existing_entity_id`. Use `Idempotency-Key` for create and append
(`idempotency_key` in MCP). The same principal, operation, target and request
return the original receipt with HTTP 200. A new write returns 201. Reusing a
key with different input returns 422 `idempotency.mismatch`.

List records and version metadata with `cursor` and `limit`. Record detail
lists newest versions first. Version metadata includes the writer, timestamp,
parent ID, byte count, digest, provenance and optional format pin. An exact
version read adds the original `text`. For example, a local shepherd calls
`studio_get_archive_version` with the `version_id` from its handoff. Its
`archive:read` grant allows it to check the returned `sha256` over the UTF-8
bytes and retrieve an earlier version after another revision is staged.

For example, call `studio_create_archive_record` with these arguments after
substituting the production ID. Save `version.id` from the result.

```json
{
  "production_id": "prd_00000000000000000000000001",
  "kind": "script",
  "title": "Hat Inspector",
  "text": "Inspector Tâve counts seventeen hats.\n",
  "provenance": {"origin": "original"},
  "idempotency_key": "hat-inspector-script-v1"
}
```

Pass the saved ID as `revises_version_id` to `studio_add_archive_version`
or as `version_id` to `studio_get_archive_version`.

## Apply a storyboard

Store a complete `studio.agent-draft/v1` JSON document as storyboard text
for its named production. Studio validates the compiled boards at staging.
Apply supplies `version_id`, the document's `story_id` and the current story
`revision` to MCP. HTTP uses a JSON body with `story_id` and the matching
`If-Match` header. The version and target story must share a production.
Studio checks the target's set pins and uses the regular draft mutations to
validate board fields and references against the story.

The first apply can populate a story that has never had boards. Later applies
match each proposal to one current board by its stamped board key. A person
edit, a missing stamp, an ambiguous key, or a stamp the key cannot revise
produces a per-board conflict. Unbound proposals are reported on an existing
story. Apply preserves board order, skips a version already applied to a
current board and performs eligible writes in one transaction. If validation
fails during the transaction, all board writes roll back. A stale story
revision returns 409 `conflict.revision`.

The receipt lists each outcome with the board key and ID when available and
returns the resulting story revision. Applied boards carry
`draft_application.archive_version_id` along with the draft hash and current
stamp. Use the normal [drafting workflow](agent-drafting.md) for board-specific
edits and acknowledgments. The story can proceed to Build under the existing
Build rules.

The runtime role can select and insert archive records and versions. Audit
lines for writes, exact reads and applies include the production, record and
version IDs, kind, byte count, digest and request ID. Apply also records the
story ID.
