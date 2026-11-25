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
| `GET /v1/formats` | Page of format slugs and names. | Person or `read` |
| `GET /v1/formats/{id}/versions` | Page of version IDs, numbers and hashes. | Person or `read` |
| `GET /v1/format-versions/{id}` | Version metadata and full recipe. | Person or `read` |
| `PATCH /v1/stories/{id}` | Send `{format_version_id}` with the story's `If-Match`. Pass null to clear the pin. | `draft:write` for the story's production, or a person |

List pages accept `limit` and `cursor`. Use `next_cursor` with the same path.
The create request reserves its slug and version 1 in a single transaction.
The slug and name stay fixed, and each successful append gets the next version
number. Each version stays addressable directly by ID. The application provides no
way to change or remove a version.

Under provisional coordinator ruling CR-29, any signed-in person and any agent with
`read` on at least one production may read the shared catalog. Formats contain no
production links or identifiers. Workers receive the pinned recipe by value in the
claim snapshot. Catalog access requires a person or agent identity. API writes from
an agent require an explicit `formats:write` grant. MCP exposes only the three catalog
reads. A story edit, including a format pin through `studio_patch_story`, still
requires access to the story's own production.

## Recipe limits

Each version is limited to 64 KiB (65,536 bytes) of canonical UTF-8 JSON. A shot type
may declare up to 3 methods. Each list of notes or style or cast rules may contain
up to 32 entries. Each recipe may have up to 16 targets and must have exactly one
human gate, `go_live`. Free-text fields are limited to 1,000 characters. Slugs,
platform names and costume attribute names are limited to 64 characters, public
account IDs to 128 characters, and target aspects to 11 characters. The schema
tag, method names, gate and target states use fixed literals. The format name is
limited to 100 characters.

Check declarations use the check names and parameter names in the schema. The
decal, wardrobe and mix checks listed there have numeric thresholds. Frame count
comes from the build plan, and transcript tolerances come from the story. The
current checks have no recipe-level string or boolean parameters.

Keep credentials out of recipes and format names. The API refuses credential-like
property names and string values that match the service redaction patterns. If a
credential is stored, rotate it. An operator then removes the affected row using
the schema owner's role and records the manual removal.

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
