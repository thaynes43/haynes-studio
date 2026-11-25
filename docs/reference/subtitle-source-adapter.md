# Subtitle source adapter

[Story 444](https://work.haynesnetwork.com/work_packages/444) adds a Python
read-only source and staging helper. The source tests use invented subtitles
created at run time. A real source read and Tom's creative review are **Expected**.

## Discovery and scene reads

`FilesystemSubtitleSource(root, source_id=...)` takes one explicit absolute
Linux directory. It expects title directories directly beneath the root and
episode files directly beneath their title. `list_titles()` and
`list_episodes(title)` return sorted names for private, in-memory selection.
Discovery inspects at most 512 entries per directory and opens no episode
content. An episode selector is the discovered basename, including its
case-insensitive `.srt` or `.vtt` extension.

`read_scene(title, episode, selection, scene_number=..., principal=...)` returns
cues from one file. Supply `CueRange(start, end)` for one-based, half-open cue
positions in file order, independent of any written cue ID. For
`TimeRange(start_ms, end_ms)`, every returned cue must start at or after
`start_ms` and end at or before `end_ms`. Both return the full selected cues
in chronological start order, with ties in file order. The parser retains
overlaps. Empty ranges fail. A scene may cover up to 120 seconds and contain
up to 80 cues and 8,192 characters of parsed text. Parsing inspects the file
in memory, up to 1 MiB, 10,000 cues and 4,096 input characters per cue.

The adapter refuses absolute or multi-component selectors, dot segments,
symlinks including root ancestors, nested mounts below the root (including
bind mounts), non-regular episode files, multiply linked files and over-limit
files. It opens components relative to verified descriptors and reads the
checked inode. A changed file fails closed. Permission errors return
`subtitle.access_denied`; other refusals use stable `adapter.source_*` or
`subtitle.*` codes. Errors carry no source path or text. The filesystem
adapter uses Linux procfs and opens data read-only with access-time updates
disabled. For an access-time flag denied by Linux, it can use an already
read-only or no-atime mount. Source-server metadata semantics depend on the
filesystem and must be verified during a real trial.

SubRip and WebVTT accept UTF-8 with or without a BOM, CRLF, bare CR,
overlapping and out-of-order cues, and common caption markup. The parser
removes tags, speaker annotations and positioning overrides and decodes
entities. It ignores WebVTT header metadata, NOTE, STYLE, REGION and cue
settings. SubRip additionally accepts BOM-marked UTF-16 and an explicitly
enabled Windows-1252 fallback for non-BOM input that fails UTF-8. Enable that
fallback only for a source known to use Windows-1252. WebVTT requires UTF-8.
The parser refuses unsupported encodings when detected, control characters,
invalid times and malformed cue boundaries. Bazarr's network API remains
a gap.

## Private provenance

`SceneRead.cues` holds cue times, file-order numbers and text in memory. Use
`scene.provenance.as_record()` for a private receipt. It contains only the
configured source ID, opaque title and episode IDs, requested range and unit,
passage SHA-256, opaque principal ID and UTC read time. The title and episode
IDs are SHA-256 hashes over the source ID and relevant selector names, encoded
as compact UTF-8 JSON. The IDs are stable within a source and belong in private
records. The principal is caller-supplied attribution. The adapter creates
no audit file or log entry.

The passage hash covers the compact UTF-8 JSON array of
`[start_ms, end_ms, text]` triples in returned order. The archive request
locator is `{"label":"sampleSource-7","sha256":"…"}`. Use an opaque source
ID of one ASCII letter followed by up to 29 ASCII letters or digits and a
scene number from 1 to 999999999. Assign a distinct scene number for each
passage within a source. The archive persists the label and the existing
production-keyed HMAC of the passage hash. The receipt has the unkeyed hash
and stays private. [Staging archive](staging-archive.md)

## Situation summary and archive writes

Use `SceneStaging(scene)` with an abstract description of who is in conflict
and what they want. Supply one or more paraphrased `SituationBeat(cue_count,
description)` values covering the cues in time order. `summarize(conflict=...,
beats=...)` adds the timing envelope for each beat from the cue times. Give
the drafting agent the summary. The person or creative session describing the
beats supplies the interpretation.

Use `staging.archive_payload(title=..., text=...)` for the final text of a
create. For an append, call `staging.archive_payload(text=...)` with the same
passage available in memory. Add the other arguments for the existing
`studio_create_archive_record` or `studio_add_archive_version` operation
(or its HTTP equivalent) and submit the returned fields as prepared. The
helper supplies `adapted` provenance. The same guard checks each summary and
archive write prepared through this helper, including storyboard JSON string
values. The archive itself receives only the prepared text and locator and
does not have source cues for comparison. [Archive operations](staging-archive.md#operations)

By default, five consecutive source words trigger `subtitle.verbatim`.
`max_source_words` sets the number of permitted consecutive words (1–8).
The comparison folds Unicode case, normalizes compatibility characters,
accounts for markup and punctuation, and checks across cue boundaries in
both time and file order. It can flag coincidental matches and miss short
quotations or reworded dialogue. It is a mechanical floor. Use only the
situation, invent names, team names, logos and dialogue, and leave the creative
verdict with Tom. [Original content and review rules](../../AGENTS.md#human-review-gates)

## Real read (Expected)

Before a real read, Tom must designate all four:

1. The authorized source and its opaque source ID.
2. The exact existing read-only root path that the authorized environment can use.
3. The allowed discovery scope, exact title and episode, and one cue or time
   range. The scope must cover inspecting that file in memory to select the scene.
4. Who may run that read and the opaque principal ID to record for them.

Use the designated path and scope only after that authorization. Keep the
receipt private and stage only the original draft. Record Tom's creative
feedback separately from the adapter and archive checks.
