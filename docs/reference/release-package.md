# Private release package

In **Productions**, open a successful Studio-built run, choose its frozen
YouTube Shorts target under **Release package**, and select **Prepare package**.
Use **Download master**, **Copy description** and **Copy checklist** for a
manual upload outside Studio. Review the licence evidence and confirm the target
account privately before uploading. An active go-live approval for the exact
run and master is required. A package prepared earlier reads **held** with the
approval reason. Withdrawal returns it to **held**.

After uploading, a go-live approver can use **Record publication** with the public
location and, if known, the publication time. Studio records the signed-in actor
and the server's recording time. The location appears as text and is never
fetched. A recorded drop remains in the history after withdrawal.

## Contents and checks

- The canonical JSON pins the run, snapshot hash, format version and recipe hash,
  target, delivery, and the master hash, byte count and media type. Studio uses
  the existing authenticated media route to download the master.
- The delivery's verification and exact-master binding, model licence rows,
  provenance, disclosure and canonical-run check are shared with go-live. The
  package description starts with `This video was AI-generated.` and credits
  only the video, voice and sound generators. Hardware appears when recorded as
  public provenance. The first package or exact-run approval supplies the shared
  evidence used by later records. The approval write still requires a person to
  confirm the synthetic-content setting.
- Each licence result displays the applicable engine and file rows and their
  recorded terms, notes and source evidence. A matching row is required (including
  its hash when the register pins the file). Non-commercial, conditional and
  unknown terms appear as recorded under D49. See the
  [local model licence register](model-licences.md).
- Package preparation compares the delivered frames and frame rate directly
  with the target's frozen millisecond maximum. The final frame counts toward
  the maximum. The checklist requires the synthetic-content setting and shows
  the aspect and maximum. A configured aspect must match the master. An unset
  aspect uses the master's aspect. The AI disclosure applies to every target.

## API

| Method and path | Access | Result |
| --- | --- | --- |
| `GET /v1/runs/{id}/release-packages` | Production `read` | Frozen YouTube Shorts targets and private package views with current eligibility. |
| `POST /v1/runs/{id}/release-packages` | Production `runs:queue` | Send `{target_id}`. Returns the hash and size with 201 on creation or 200 for the existing run and target. |
| `POST /v1/runs/{id}/publications` | Go-live approver with fresh sign-in and CSRF | Send `{package_sha256, location, published_at?}`. `published_at` accepts an ISO date and time with an offset. Returns the new drop with HTTP 201. |
| `GET /v1/media/{sha256}` | Production `read` | Verified delivery master through the existing authenticated, ranged media route. |

Out-of-scope package requests return 404. The
[go-live approvals reference](go-live.md) lists shared refusal codes.

| HTTP | Code | Meaning |
| --- | --- | --- |
| 422 | `release.format_missing`, `release.target_unknown` | Choose a YouTube Shorts target from the run's frozen recipe. |
| 422 | `release.maximum_unset` | The target must declare a platform maximum in the frozen recipe. |
| 422 | `release.over_length`, `release.aspect_mismatch` | The delivered master exceeds the maximum or differs from the declared aspect. |
| 422 | `release.location_invalid`, `release.publication_in_future` | Enter a single public location without credentials and a past publication time if known. |
| 409 | `release.approval_required` | An active approval must match the exact run, snapshot, delivery and master. |
| 409 | `release.already_published` | The package already has an immutable drop record. |
| 503 | `release.store_unavailable`, `release.package_changed` | Studio could not read or store the package, or the stored bytes differ from the reference. |

The production-scoped private store holds the canonical JSON under its SHA-256.
The database indexes the hash and byte count once per run and target. The response
keeps the derived state and publication outside the hashed record. Approve,
withdraw, prepare and record all serialize on the run row. If a package's blob
write succeeds before a database failure, the same bytes can be reused on retry.
Story `published` and approval `publication_ids` come from the appended drop.

Fixture runs cover preparation, permissions, withdrawal and publication. The
installed app has two imported legacy runs, which are ineligible under D52.
The first real package awaits the first finished run built by the new engine.
