# Studio HTTP and MCP operation parity

Source availability for the [contract section 12 operations](../contracts/studio-contracts-v1.md#operations).
HTTP paths are under `/v1` except for auth, probes and internal work.
An em dash indicates that the operation has no MCP tool.
See the [API reference](studio-api.md) and [MCP schemas](studio-mcp.md#tools-and-revisions)
for request and response details. This map covers the API used by
[416](https://work.haynesnetwork.com/work_packages/416),
[417](https://work.haynesnetwork.com/work_packages/417),
[418](https://work.haynesnetwork.com/work_packages/418),
[419](https://work.haynesnetwork.com/work_packages/419) and
[456](https://work.haynesnetwork.com/work_packages/456).

| Operation | HTTP | MCP | Access | Story |
| --- | --- | --- | --- | --- |
| `get_me` | `GET /me` | — | any | [409](https://work.haynesnetwork.com/work_packages/409) |
| `get_selections`, `put_selections` | `GET`, `PUT /me/selections` | — | human | [409](https://work.haynesnetwork.com/work_packages/409), [413](https://work.haynesnetwork.com/work_packages/413) |
| `list_productions` | `GET /productions` | `studio_list_productions` | read | [409](https://work.haynesnetwork.com/work_packages/409), [429](https://work.haynesnetwork.com/work_packages/429) |
| `create_production` | `POST /productions` | — | human | [409](https://work.haynesnetwork.com/work_packages/409) |
| `get_production` | `GET /productions/{id}` | `studio_get_production` | read | [409](https://work.haynesnetwork.com/work_packages/409) |
| `enable_media_type` | `PUT /productions/{id}/media-types/{kind}` | — | human | [409](https://work.haynesnetwork.com/work_packages/409) |
| `list_stories` | `GET /productions/{id}/media-types/{kind}/stories?publication=&approved=` | `studio_list_stories` | read | [409](https://work.haynesnetwork.com/work_packages/409), [414](https://work.haynesnetwork.com/work_packages/414) |
| `create_story` | `POST /productions/{id}/media-types/{kind}/stories` | `studio_create_story` | draft:write | [409](https://work.haynesnetwork.com/work_packages/409), [429](https://work.haynesnetwork.com/work_packages/429) |
| `create_archive_record` | `POST /productions/{id}/archive-records` | `studio_create_archive_record` | archive:write | [443](https://work.haynesnetwork.com/work_packages/443) |
| `add_archive_version` | `POST /archive-records/{id}/versions` | `studio_add_archive_version` | archive:write | [443](https://work.haynesnetwork.com/work_packages/443) |
| `list_archive_records` | `GET /productions/{id}/archive-records` | `studio_list_archive_records` | archive:read | [443](https://work.haynesnetwork.com/work_packages/443) |
| `get_archive_record` | `GET /archive-records/{id}` | `studio_get_archive_record` | archive:read | [443](https://work.haynesnetwork.com/work_packages/443) |
| `get_archive_version` | `GET /archive-versions/{id}` | `studio_get_archive_version` | archive:read | [443](https://work.haynesnetwork.com/work_packages/443) |
| `apply_archive_storyboard` | `POST /archive-versions/{id}/apply` | `studio_apply_archive_storyboard` | archive:read and draft:write | [443](https://work.haynesnetwork.com/work_packages/443) |
| `get_story` | `GET /stories/{id}` | `studio_get_story_summary` | read | [409](https://work.haynesnetwork.com/work_packages/409), [429](https://work.haynesnetwork.com/work_packages/429) |
| `update_story` | `PATCH /stories/{id}` | `studio_patch_story` | draft:write | [409](https://work.haynesnetwork.com/work_packages/409), [429](https://work.haynesnetwork.com/work_packages/429) |
| `get_story_timing` | `GET /stories/{id}/timing` | `studio_get_story_timing` | read | [404](https://work.haynesnetwork.com/work_packages/404), [409](https://work.haynesnetwork.com/work_packages/409) |
| `create_board` | `POST /stories/{id}/boards` | `studio_add_board` | draft:write | [409](https://work.haynesnetwork.com/work_packages/409), [429](https://work.haynesnetwork.com/work_packages/429) |
| `get_board` | `GET /boards/{id}` | `studio_get_board` | read | [409](https://work.haynesnetwork.com/work_packages/409), [429](https://work.haynesnetwork.com/work_packages/429) |
| `update_board` (lines, timing, method, cast, layout, cues, notes, photo prompt and inputs, current photo) | `PATCH /boards/{id}` | `studio_patch_board` | draft:write | [409](https://work.haynesnetwork.com/work_packages/409), [429](https://work.haynesnetwork.com/work_packages/429) |
| `reorder_boards` | `PUT /stories/{id}/board-order` | `studio_reorder_boards` | draft:write | [409](https://work.haynesnetwork.com/work_packages/409), [429](https://work.haynesnetwork.com/work_packages/429) |
| `remove_board` (tombstone) | `DELETE /boards/{id}` | `studio_remove_board` | draft:write | [409](https://work.haynesnetwork.com/work_packages/409), [429](https://work.haynesnetwork.com/work_packages/429) |
| `generate_board_voice` | `POST /boards/{id}/voice-jobs` | `studio_generate_voice` | assets:generate | [405](https://work.haynesnetwork.com/work_packages/405), [430](https://work.haynesnetwork.com/work_packages/430) |
| `list_board_voice_versions` | `GET /boards/{id}/voice-versions` | — | read | [405](https://work.haynesnetwork.com/work_packages/405), [430](https://work.haynesnetwork.com/work_packages/430) |
| `generate_board_photo` | `POST /boards/{id}/photo-jobs` | `studio_generate_photo` | assets:generate | [407](https://work.haynesnetwork.com/work_packages/407), [430](https://work.haynesnetwork.com/work_packages/430) |
| `upload_board_photo` (D42) | `POST /boards/{id}/photo-versions` | `studio_upload_photo` at `/mcp/upload` | Agent with `assets:upload` | [407](https://work.haynesnetwork.com/work_packages/407), [430](https://work.haynesnetwork.com/work_packages/430) |
| `list_board_photo_versions` | `GET /boards/{id}/photo-versions` | — | read | [407](https://work.haynesnetwork.com/work_packages/407), [430](https://work.haynesnetwork.com/work_packages/430) |
| `get_job` | `GET /jobs/{id}` | `studio_get_job` | read | [430](https://work.haynesnetwork.com/work_packages/430), [965](https://work.haynesnetwork.com/work_packages/965) |
| `search_assets` | `GET /assets?kind=&label=&production=&board=` | `studio_search_assets` | read | [382](https://work.haynesnetwork.com/work_packages/382), [409](https://work.haynesnetwork.com/work_packages/409) |
| `get_asset` | `GET /assets/{id}` | `studio_get_asset` | read | [382](https://work.haynesnetwork.com/work_packages/382), [409](https://work.haynesnetwork.com/work_packages/409) |
| `generate_asset_candidate` | `POST /asset-jobs` | — | Signed-in person | [408](https://work.haynesnetwork.com/work_packages/408), [430](https://work.haynesnetwork.com/work_packages/430) |
| `request_matte` | `POST /asset-jobs/matte` | — | Signed-in person | [965](https://work.haynesnetwork.com/work_packages/965) |
| `promote_asset_version` | `POST /asset-versions/{id}/promote` | — | Signed-in person | [408](https://work.haynesnetwork.com/work_packages/408) |
| `get_media` | `GET /media/{sha256}` | — | read | [409](https://work.haynesnetwork.com/work_packages/409) |
| `estimate_run` | `GET /stories/{id}/estimate` | `studio_estimate_run` | read | [410](https://work.haynesnetwork.com/work_packages/410), [430](https://work.haynesnetwork.com/work_packages/430) |
| `queue_run` | `POST /stories/{id}/runs` | `studio_queue_run` | runs:queue | [410](https://work.haynesnetwork.com/work_packages/410), [430](https://work.haynesnetwork.com/work_packages/430) |
| `list_runs` | `GET /stories/{id}/runs` | `studio_list_runs` | read | [410](https://work.haynesnetwork.com/work_packages/410), [419](https://work.haynesnetwork.com/work_packages/419) |
| `get_run` (status, progress, stages, checks) | `GET /runs/{id}` | `studio_get_run` | read | [410](https://work.haynesnetwork.com/work_packages/410), [430](https://work.haynesnetwork.com/work_packages/430) |
| `cancel_run` | `POST /runs/{id}/cancel` | `studio_cancel_run` | runs:queue | [410](https://work.haynesnetwork.com/work_packages/410) |
| `get_run_snapshot` (comparison pairs board IDs in the browser) | `GET /runs/{id}/snapshot` | — | read | [419](https://work.haynesnetwork.com/work_packages/419), [958](https://work.haynesnetwork.com/work_packages/958) |
| `record_check_override` (with a reason; never a release check) | `POST /runs/{id}/checks/{check}/overrides` | Reserved `studio_override_check` (people only in v1) | Signed-in person | [410](https://work.haynesnetwork.com/work_packages/410), [450](https://work.haynesnetwork.com/work_packages/450) |
| `get_delivery` | `GET /runs/{id}/delivery` | `studio_get_delivery` | read | [381](https://work.haynesnetwork.com/work_packages/381), [409](https://work.haynesnetwork.com/work_packages/409) |
| `get_go_live_approvals` | `GET /runs/{id}/go-live-approvals` | — | Signed-in person with production read access | [958](https://work.haynesnetwork.com/work_packages/958) |
| `approve_go_live` | `POST /runs/{id}/go-live-approvals` | — | go_live:approve | [412](https://work.haynesnetwork.com/work_packages/412) |
| `withdraw_go_live` | `POST /go-live-approvals/{id}/withdraw` | — | go_live:approve | [412](https://work.haynesnetwork.com/work_packages/412) |
| `record_publication` | `POST /runs/{id}/publications` | — | go_live:approve | [449](https://work.haynesnetwork.com/work_packages/449) |
| `claim_work`, `heartbeat_work`, `complete_work`, `fail_work` | `POST /internal/v1/work/{claim,heartbeat,resume,publish,complete,fail}` and Wan attempt routes | — | worker | [410](https://work.haynesnetwork.com/work_packages/410), [430](https://work.haynesnetwork.com/work_packages/430) |
| `login`, `callback`, `logout` | `GET /auth/login`, `GET /auth/callback`, `POST /auth/logout` | — | Sign-in entry points. Logout requires a session and CSRF. | [409](https://work.haynesnetwork.com/work_packages/409), [432](https://work.haynesnetwork.com/work_packages/432) |
| `healthz`, `readyz` | `GET /healthz`, `/readyz` | — | none | [434](https://work.haynesnetwork.com/work_packages/434) |
| `list_board_jobs` | `GET /boards/{id}/jobs` | — | read | [430](https://work.haynesnetwork.com/work_packages/430) |
| `get_job_result` | `GET /jobs/{id}/result` | — | Signed-in person | [430](https://work.haynesnetwork.com/work_packages/430) |
| `get_job_media`, `head_job_media` | `GET`, `HEAD /jobs/{id}/media/{sha256}` | — | Signed-in person | [430](https://work.haynesnetwork.com/work_packages/430) |
| `get_version_media`, `head_version_media` | `GET`, `HEAD /asset-versions/{id}/media/{sha256}` | — | Signed-in person | [430](https://work.haynesnetwork.com/work_packages/430) |
| `get_queue_lanes`, `set_queue_lane` | `GET /queue/lanes`, `PUT /queue/lanes/{lane}` | — | Signed-in person | [430](https://work.haynesnetwork.com/work_packages/430) |

Image candidate and shared-library matte status requires a person. Agent keys
can read board and matte job status and metadata with `read` on the job's
production. For photo and voice history, the web can get hashes
from the job result or board version lists, then use the people-only job or
version preview for ranged playback. A board-scoped version can be read via
`/v1/media/{sha256}` only while a current draft references it.

Agent patches, moves and removals through HTTP or MCP use the same draft
guard. Older and imported boards without server-recorded local creation
require the [revision acknowledgment](agent-drafting.md#re-drafts-and-receipts).
