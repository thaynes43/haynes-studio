# Board inspector

The editor works on the selected draft board. **Save board** sends the edited
fields with the revision the editor read. Studio mints new line and note IDs and
stamps the edit with the signed-in person. Current children keep their IDs.

| Inspector field | Draft operation or read |
|---|---|
| Script and speakers | `PATCH /v1/boards/{id}` with ordered `lines`. Speaker choices come from the story cast and narrator. The patch updates the board voice style and timing shape when needed. |
| Voice generation | `POST /v1/boards/{id}/voice-jobs` with `{}` and an `Idempotency-Key` unique to the press. The server freezes the saved board. A line edit can reuse the other takes through the worker's signature check. |
| Job status and lane | `GET /v1/boards/{id}/jobs` and `GET /v1/queue/lanes`. A paused lane still accepts requests. The inspector reads the board again as jobs progress. |
| Track and line playback | The board's current selection and `GET /v1/boards/{id}/voice-versions` supply the version and hashes. Native audio reads `/v1/asset-versions/{id}/media/{sha256}` with the session cookie and byte ranges. |
| Timing | `PATCH` with integer milliseconds for spoken lead, tail and line gaps or for a silent hold. The backend measures spoken length and supplies the revised storyboard timeline. |
| Method | `PATCH` with the layer and motion pair. The choices follow the capability matrix and the shot type read from the pinned `GET /v1/format-versions/{id}` recipe, if present. |
| Direction | `PATCH` with the edited `notes` and, when changed, typed `cues`. Only cues contribute executable build fields. |

A stale write reloads the board and shows the unsaved and latest saved values.
Review the changed fields before choosing which version to keep. A new save is
explicit and uses the latest read revision. An API refusal leaves the editor
populated and shows the error code. For a voice job, the inspector marks a result
stale when its API currency flag or board selection fails to match, or when the
editor has newer voice input. Saving that input and generating again updates the
length from Studio's timing record.

Unsaved fields and an unadded note stay in the open page and in browser session
storage scoped to the signed-in account and board. They survive reloads in the
same tab for the tab's session. When storage is blocked, the page keeps its
in-memory copy while it is open. An ambiguous voice submission also retains the
press key and the saved input it targeted. A retry uses that key, while a new
press uses a new key. A changed saved input requires a new press.
