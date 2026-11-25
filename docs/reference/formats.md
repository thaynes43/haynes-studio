# Studio format recipes

[Story 447](https://work.haynesnetwork.com/work_packages/447) adds a shared catalog of
immutable [format recipes](../../src/haynes_studio/schemas/studio.format-recipe.v1.schema.json).
A format has a stable slug and name. Each version has its own `fmv_` ID, a sequence
number within the format, and the SHA-256 of the recipe's canonical JSON.

The [doll short v1 request](fixtures/doll-short-v1.json) declares the portrait
delivery profile, the advisory range measured from the two E1 builds, shot methods,
Yellowbirds wardrobe attributes, Kokoro and mix defaults, and candidate checks.
Its notes cite the committed sources. The recipe keeps a placeholder for Tom's
YouTube Shorts channel with the vertical delivery aspect and required AI disclosure.
The account identifier and platform maximum are unset.

## API and scopes

| Method and path | Request and response | Access |
| --- | --- | --- |
| `POST /v1/formats` | Send `{id, name, recipe}`. Returns version 1 and its `Location`. | Person or `formats:write` |
| `POST /v1/formats/{id}/versions` | Send the complete new recipe. Returns the new version and its `Location`. | Person or `formats:write` |
| `GET /v1/formats` | Page of format slugs and names. | Person, `read`, or worker |
| `GET /v1/formats/{id}/versions` | Page of version IDs, numbers and hashes. | Person, `read`, or worker |
| `GET /v1/format-versions/{id}` | Version metadata and full recipe. | Person, `read`, or worker |
| `PATCH /v1/stories/{id}` | Send `{format_version_id}` with the story's `If-Match`. Pass null to clear the pin. | `draft:write` for the story's production, or a person |

List pages accept `limit` and `cursor`. Use `next_cursor` with the same path.
The create request reserves its slug and version 1 in a single transaction.
The slug and name stay fixed, and each successful append gets the next version
number. Each version stays addressable directly by ID.

The catalog is shared across productions. An agent's grant on any production opens
catalog access for that scope. `formats:write` is explicit on each staging key's
grant. A story edit still requires access to the story's own production. MCP exposes
the three catalog reads and uses `studio_patch_story` to pin a format version with
`draft:write`.

## Drafts and queued runs

The recipe's frame size must match the story's media type. The Studio delivery clock
is 24 fps. A board is `speaking` if a placed cast member has a line, `reaction` if
it has cast without an on-screen speaker, and `ambient` if it has no cast. The first
method in a recipe's list is the default for a new board of that type. Explicit
methods and existing boards retain their settings during edits. Preflight reports
`method.unavailable` for a board whose method falls outside its pinned recipe.
A recipe may omit a shot type.

The story summary, timing and run estimate show `format.length_exceeded` when the
known frame count exceeds the recipe's maximum. A longer story can still queue.
The snapshot includes `format_version: {id, sha256, recipe}`, and its own hash covers
that complete pin. The worker verifies the frozen recipe and snapshot with its claim.
Queued runs keep the recipe value and hash they received at queue time. Pre-existing
drafts can keep an unresolved reserved ID until a draft edit clears or replaces it.
Build requires a resolvable recipe for a story with a pin.

The recipe's check thresholds and creative settings are declarations for drafting and
candidate evaluation. Each team costume object maps attribute names to expected
strings for [wardrobe checking](wardrobe-decal-checks.md#wardrobe-attributes).
Go-live is the only declared human gate. Each target records an ID, platform, owner
note, state, optional public account identifier, maximum duration in milliseconds,
AI label requirement and aspect. A placeholder has a null account identifier. A
null rule means it is unset. The catalog stores local metadata. Release preparation
and platform limit enforcement belong to
[story 449](https://work.haynesnetwork.com/work_packages/449).
