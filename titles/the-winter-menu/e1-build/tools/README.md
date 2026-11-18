# One-off drivers of the first live build (story 428)

These five scripts ran once, on 2026-11-14, during the first live build of The Winter
Menu. They are kept as a record of what the build needed beyond the studio's command
line. They are not maintained and are not a supported way to run a build; the
[run log](../run-log.md) says what each one did.

| Script | What it did | Writes |
|---|---|---|
| `draft.py` | Published the new fire bed as a new sound version and wrote the buildable draft | New store blobs, create-only; new files in a new output folder |
| `redraft.py` | Wrote a new draft version with the decisions of 2026-11-14 04:02Z | One new `story.json` in a folder that must not exist |
| `probe.py` | Probed the Wan service once: health, GPU sample, engine queue | Nothing |
| `clips.py` | Read each speech clip's record and its Wan job ledger, and wrote one summary per clip | New files in its output folder |
| `decal.py` | Printed the lettering track scores of every keyed-frames artifact | Nothing |

## Not here: `private_view.py`

A sixth driver put the finished film on private viewing by copying it to the shared Wan
volume. It is **not on `main`**. A review by another model family
([PR 70](https://github.com/thaynes43/haynes-studio/pull/70)) found that its check for an
unused folder does not hold through the later copies and the link, so a second writer
on the volume could make the link serve another film. It also found that the run
record it ships is picked by sort order and not checked. The driver ran once without
such a writer, and what it delivered was read back and hash-checked
([`production.json`](../production.json)). The studio command that replaces it, with
both findings as requirements, is story
[863](https://work.haynesnetwork.com/work_packages/863). The driver as it ran stays
readable at the commit the run log links to.

## Known limits

Left as they are because the scripts are records. The run log lists the others it
found under "Known defects in `tools/`".

`decal.py`: its sort raises on a clip with two or more unscored frames. No clip of the
2026-11-14 build had one.

`clips.py`, found by the same review:

- Two clips with the same frame count and seed share their output file names. The
  second is skipped without a word, while the summary still names it. The 2026-11-14
  export had no such pair.
- If its output folder is inside the store it reads, it adds its files there. It never
  replaces a file.

Do not reuse either script without fixing these.
