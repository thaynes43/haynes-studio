# Motion clip records

`haynes_studio.motion` (story [457](https://work.haynesnetwork.com/work_packages/457),
epic [373](https://work.haynesnetwork.com/work_packages/373)): the record of a reusable
doll clip, set loop or speech-to-video clip, its identity, and the resolver that gives
a board one pinned clip per cast still and for the set. Built against
[contract v1](../contracts/studio-contracts-v1.md) sections 3 (TIME-8, TIME-8a), 4, 5 and
9, on the [library](studio-library.md) of story 382 and the [cache keys](cache-and-splice.md)
of story 380. Nothing here generates, keys or composites a frame (story
[426](https://work.haynesnetwork.com/work_packages/426)), reads media or calls a service.
**Everything below that the contract does not say is a proposal** for the contract owner.

| Module | What |
|---|---|
| `motion.record` | `MotionRecord`: the block, read-only; `board_frame(n, phase=)` (which file frame a board frame shows) |
| `motion.identity` | `motion_identity(record, clip_sha256)`: the clip key, the keyed key and the identity |
| `motion.check` | the block's code rules (the schema holds the rest) |
| `motion.resolve` | `resolve_board`, `resolve_story`, `resolve_timed`, `candidates` |
| `motion.winter_menu` | the E0 clips from public text: `load_e0_sources`, `build_e0_motion`, the tables below |

## The record

A `motion` block on a `studio.asset-version/v1` of kind `motion` (only there:
`schema.invalid` at `/motion` elsewhere). It is immutable content, like a board voice's
`voice` block: it never changes, and `content_fields` compares it on re-import. It is
optional, so every motion version written before it stays valid; such a version cannot
be played (`motion.record_missing`).

| Field | Content | Comes from | Feeds |
|---|---|---|---|
| `use` | `loop` (TIME-8a: a doll clip or set loop) or `timed` (TIME-8: made for one board's speech) | the generation request | identity |
| `subject` | `doll` (keyed over the set; capability `motion_clip`) or `set` (an opaque set loop; `set_loop`) | the request | identity |
| `still_sha256` | the cast still or set image the clip stands in for, as a board names it; absent when no record ties the clip to one | the cast still's version | identity; the unpinned search |
| `frames`, `fps`, `width`, `height` | the clip as returned | the engine's result | identity |
| `trim` | `{start, frames}`: the source frames played. A loop's `N`; a timed clip's `floor((F - 1) * fs / 24) + 1` from frame 0, the rest trimmed | TIME-8, TIME-8a | identity |
| `playback` | `loop` (`pingpong` or `none`), `period` (`2N - 2` or null), `board_longer`, `board_shorter`: a loop ping-pongs both ways; a timed clip trims a shorter board and fails a longer one (`time.source_short`, P-05) | fixed by `use` and `trim` | (derived) |
| `source.image_sha256` | the start image the engine animated (for E0, the doll on green, not the cutout) | the request | clip key, keyed key |
| `source.prompt`, `seed`, `profile` | as sent; the profile names model, size, length, fps and (for a loop) the adapter | the request | clip key |
| `source.negative_prompt` | as sent, or null for none | the request | clip key (timed); identity (loop: `motion_clip_key` has none) |
| `source.adapter` | a timed clip's S2V adapter (a loop's profile names its own) | the adapter | clip key (timed) |
| `source.engine_job_id` | the engine's job | the engine | nothing (provenance) |
| `drive_track` | timed only: `{sha256, board_frames}`, the track it was made from and its board's frames | the drive track artifact (TIME-9) | clip key (`sha256`); identity (`board_frames`) |
| `keying` | doll clips: `keyer`, `key_thresholds`, `protect_boxes`, `decal_box`, `decal_version` (boxes in clip pixels), optional `decal_min_ecc` (the decal gate); absent for a set loop, and for a doll clip whose keying no record holds | the keyer | keyed key; identity (`decal_min_ecc`) |
| `keys` | `clip`, `keyed` (with keying), `identity`: what the identity function gives; checked on write and on resolution | `motion.identity` | (the result) |
| `note` | free text | anyone | nothing |

Code rules beyond the schema (`motion.check`): the period is `2N - 2`; the trim lies in
the clip; a timed trim is TIME-8's and the clip is long enough (`time.source_short`,
failed); a timed clip names its adapter and a loop does not; boxes lie inside the frame;
the content's size and the generator's seed, prompt and engine job agree with the block;
a doll clip is a `motion_clip` and a set loop a `set_loop`, never both
(`asset.capability_mismatch`); the keys are the computed ones (`motion.identity_mismatch`). Text that cannot be written as canonical
JSON (a lone surrogate) is `schema.invalid`; a malformed block never raises.

## Identity

`motion_identity(record, clip_sha256)` is one pure function of the record's inputs,
built on story 380's keys, called and never copied:

- **clip key:** `motion_clip_key(still=image, prompt, seed, profile)` for a loop;
  `s2v_clip_key(drive_track, start_still=image, prompt, negative_prompt, seed, profile,
  adapter)` for a timed clip, since the loop key has no drive track (proposal);
- **keyed key:** `keyed_frames_key(clip=content sha256, still=image, key_thresholds,
  protect_boxes, decal_box, decal_version, keyer)`, the decal's still being the clip's
  start image as legacy `DollClip.cache_dir` hashed it (proposal); none without keying;
- **identity:** `sha256:` of section 4's canonical JSON (integral floats read as
  integers, as the validators read them) of both keys plus what neither covers: scheme `studio.motion-record/v1`, use, subject, still, the clip's bytes,
  frames, fps, size, trim, negative prompt, the drive track's board frames, the decal
  gate.

A changed setting, seed, start image, still, key or decal input, or other bytes, gives a
new identity; an engine job, note, label or name does not (tests change each one). A
motion version with a block **pins its identity** (`model.pin`, proposal), so importing
the same record again returns the same version, and the same clip keyed another way is
the next version of its asset: nothing is overwritten (D15, D17). A run snapshot still
lists the version's `sha256` (its bytes); the version ID fixes the rest.

## Resolution

`resolve_board(board, library, verify, story=None)` returns a `BoardMotion`: one
`PinnedClip` per cast entry that plays a loop, the set loop, and the problems. A
`PinnedClip` answers story 426's questions: which version and bytes (`version_id`,
`sha256`, `locator`), which frames (`source_frame(n)`: TIME-8a with the board's
`loop_phase(board_id, slot, period)`, or TIME-8), and which keying inputs
(`record.keying`, `keyed_key`).

*Superseded in part by story 426 ([layered adapter](layered-adapter.md#the-cache-plans-layered-path)):*
the build plays a loop with the pinned record's own `N` (`trim.frames`), trim start and
fps, and the phase this resolver gives (`loop_phase` over the record's period), never
the toolchain's. It keys the frames with the record's keying inputs, the decal's still
being the clip's start image (`source.image_sha256`), but writes the keyer as
`<keyer>@<build>` (`layered.keyed.keyer_build`), so the cache key it uses is
`keyed_key`'s inputs with the build added, not `keyed_key` itself
([keyed frames](layered-adapter.md#keyed-frames-keyed_frames_key)).

- **Cast still:** the entry's new optional `motion_asset_version_id`, else the one
  promoted doll loop whose `still_sha256` is the entry's still, in the production (the
  story's, or `production_id=`) or the global library; a pin of another production is
  `asset.scope_mismatch`. Layered I2V: every entry; layered S2V: every entry
  with no line on the board (speakers get a timed clip); whole-frame: none. A pin is
  checked wherever it stands. *Superseded by story 426 for the build
  ([layered adapter](layered-adapter.md#the-cache-plans-layered-path)):* `resolve_board`
  called on its own still skips a speaker on a layered S2V board (`needs_loop`), but the
  build calls it through `layered.pin.pin_board`, which resolves every layered board as
  layered I2V. So every cast entry of a layered board resolves a loop, a speaker's
  included: her loop's `source.image_sha256` is her speech-to-video start image and its
  `keying` keys her clip. A speaker's still without a loop is `motion.clip_absent`, and
  the plan stops on it.
- **Set** (a layered board, given the story): the story's `set.motion_asset_version_id`,
  else the one promoted set loop of the set still, else none: a static plate, as
  `cache.plan` builds it (proposal).
- `resolve_timed(library, verify, still_sha256=, drive_track_sha256=, board_frames=,
  slot=)` gives a speaker the one promoted timed clip made from that drive track; a
  loop is never returned.
- `verify(locator, sha256)` is the store's `Store.verify`, asked once per distinct clip
  in one call. A `PinnedClip` is returned only when its entry has no blocking problem,
  so a returned clip is always playable.
- The same board and library give the same answer every time (a test resolves one board
  twice).

| Code | Status | When | Source |
|---|---|---|---|
| `ref.unknown` | invalid | the pinned version, or the entry's still, is not in the library | story 404 (proposal) |
| `asset.kind_mismatch` | invalid | the pin is not a `motion` version | story 382 (proposal) |
| `asset.scope_mismatch` | invalid | the pin belongs to another production | story 382 (proposal) |
| `asset.capability_mismatch` | invalid | a set loop pinned for a doll, a doll clip for the set; a board's motion pin without `motion_clip` (story 404's validator, with facts) | contract 5, 9 |
| `motion.record_missing` | invalid | a motion version without a block | proposal, section 9 |
| `motion.clip_absent` | invalid | no pin, and no promoted loop (or timed clip) of that still | proposal, section 9 |
| `motion.clip_ambiguous` | invalid | no pin, and several promoted clips of that still | proposal, section 9 |
| `motion.timed_not_loop` | invalid | a timed clip pinned where a loop plays | proposal, section 3 |
| `motion.still_mismatch` | invalid | the pinned clip stands in for another still | proposal, section 9 |
| `motion.keying_missing` | invalid | a doll clip with no keying inputs | proposal, section 9 |
| `motion.identity_mismatch` | invalid | a recorded key is not what the inputs give: a corrupt record | proposal, section 4 |
| `motion.drive_track_mismatch` | invalid | a timed clip made for another board length | proposal, section 3 |
| `asset.bytes_missing` | invalid | the store does not hold the clip | story 382 (proposal) |
| `store.hash_mismatch` | failed | the store holds other bytes at the clip's locator | story 379 (proposal) |
| `time.source_short` | failed | (on write) a timed clip shorter than its board | contract 3 |

## The E0 clips

`build_e0_motion(load_e0_sources(repo), production_id=, licences=, by=, now=,
library=)` reads the three clip record files, the three clipmaps, `decal-scores.json`
(whose boxes must match), `assembly-wf.json`, `keyframes.json`, r4's manifest and
timeline, the [recovery map](legacy-recovery-map.md) (the cutouts' and the set's
hashes) and two literals of the PoC code, and imports one motion version per clip by
source key `legacy:winter-menu-video-e0:<loop|set-loop|s2v>:...`. Building again
returns the same versions. Doll loops are one asset per cutout, versions in recording
order; the clips the layered v2 and layered S2V films used are `promoted`, the three
they replaced are `candidate`. Locators are in r4's production folder; licences come
from the [model licence register](model-licences.md) (Wan TI2V-5B and S2V-14B).

Checks against the public text: every clipmap still is the record's start image; every
timed clip's drive track lasts its r4 board's frames / 24 s and its requested length is
TIME-9's; its trim is section 3's worked example (102, 63, 97, 56, 55, 81, 167, 72 source
frames for boards 1 to 9 without 7).

With the r4 story as imported (layered S2V), boards 7 (D) and 9 (A, C) resolve their idle
dolls to `layer-d-shocked-v2-green`, `layer-a-green` and `layer-c-suspicious-green`, as
the layered S2V film did, and each of the 11 speakers resolves its timed clip. Made
layered I2V with the set pinned, every r4 board resolves; every promoted doll loop is
used except D cheerful (r4 places no D cheerful; the search finds it for that still).

Values taken from the PoC code, not from a clip record: the keyer (`poc/cutout.py key`)
and its thresholds 20/70 and the decal version `erase-v2` (`DollClip.cache_dir`), the
decal gate 0.8 (`poc/decal.py MIN_ECC`, unless a clipmap sets `decal_min_ecc`), the
S2V negative prompt (`poc/wan.py NEGATIVE`, which `poc/s2v.py` sends) and LoRA
(`poc/s2v.py LORA`), 4 steps at cfg 1 (`--lightning`), the adapters (the script that
made the clip) and the loops' 24 fps (section 3). `NEGATIVE` has not changed since the
clips were made (commit e33f4fb); `erase-v2` came in commit 8f16830, before the v2 and
S2V films.

Every line of the three clip record files:

<!-- motion-e0:begin -->
| File | Line | Clip | Outcome | State | Stands in for | Board, slot | Note |
|---|---|---|---|---|---|---|---|
| `clip-records.jsonl` | 1 | `s1-wf-a` | not a motion clip |  |  |  | whole-frame image-to-video clip of the 15-clip film (assembly-wf.json); story 427's whole-frame clip, not a library motion asset |
| `clip-records.jsonl` | 2 | `s1-wf-x1` | not a motion clip |  |  |  | whole-frame image-to-video clip of the 15-clip film (assembly-wf.json); story 427's whole-frame clip, not a library motion asset |
| `clip-records.jsonl` | 3 | `s2-wf-a` | not a motion clip |  |  |  | whole-frame image-to-video clip of the 15-clip film (assembly-wf.json); story 427's whole-frame clip, not a library motion asset |
| `clip-records.jsonl` | 4 | `s3-wf-a` | not a motion clip |  |  |  | whole-frame image-to-video clip of the 15-clip film (assembly-wf.json); story 427's whole-frame clip, not a library motion asset |
| `clip-records.jsonl` | 5 | `s3-wf-x1` | not a motion clip |  |  |  | whole-frame image-to-video clip of the 15-clip film (assembly-wf.json); story 427's whole-frame clip, not a library motion asset |
| `clip-records.jsonl` | 6 | `s4-wf-a` | not a motion clip |  |  |  | whole-frame image-to-video clip of the 15-clip film (assembly-wf.json); story 427's whole-frame clip, not a library motion asset |
| `clip-records.jsonl` | 7 | `s5-wf-a` | not a motion clip |  |  |  | whole-frame image-to-video clip of the 15-clip film (assembly-wf.json); story 427's whole-frame clip, not a library motion asset |
| `clip-records.jsonl` | 8 | `s6-wf-a` | not a motion clip |  |  |  | whole-frame image-to-video clip of the 15-clip film (assembly-wf.json); story 427's whole-frame clip, not a library motion asset |
| `clip-records.jsonl` | 9 | `s7-wf-a` | not a motion clip |  |  |  | whole-frame image-to-video clip of the 15-clip film (assembly-wf.json); story 427's whole-frame clip, not a library motion asset |
| `clip-records.jsonl` | 10 | `s8-wf-a` | not a motion clip |  |  |  | whole-frame image-to-video clip of the 15-clip film (assembly-wf.json); story 427's whole-frame clip, not a library motion asset |
| `clip-records.jsonl` | 11 | `s8-wf-x1` | not a motion clip |  |  |  | whole-frame image-to-video clip of the 15-clip film (assembly-wf.json); story 427's whole-frame clip, not a library motion asset |
| `clip-records.jsonl` | 12 | `s8-wf-x2` | not a motion clip |  |  |  | whole-frame image-to-video clip of the 15-clip film (assembly-wf.json); story 427's whole-frame clip, not a library motion asset |
| `clip-records.jsonl` | 13 | `s9-wf-a` | not a motion clip |  |  |  | whole-frame image-to-video clip of the 15-clip film (assembly-wf.json); story 427's whole-frame clip, not a library motion asset |
| `clip-records.jsonl` | 14 | `layer-set-loop` | set loop | promoted |  |  | pinned only: its still is a gap |
| `clip-records.jsonl` | 15 | `layer-a-green` | doll loop | promoted | `cutouts/a-proud.png` |  |  |
| `clip-records.jsonl` | 16 | `s2-s2v-b` | not a motion clip |  |  |  | whole-frame speech-to-video test from keyframe s2.png (method.unavailable, section 5); its drive track is the bare line (2.688 s), not a board-length track (TIME-9), so it is no board's timed clip |
| `clip-records-layers.jsonl` | 1 | `layer-a-staring-green` | doll loop | promoted | `cutouts/a-staring.png` |  |  |
| `clip-records-layers.jsonl` | 2 | `layer-b-deadpan-green` | doll loop | candidate | `cutouts/b-deadpan.png` |  | superseded by layer-b-deadpan-v2-green (sleeves-fixed still) |
| `clip-records-layers.jsonl` | 3 | `layer-c-suspicious-green` | doll loop | promoted | `cutouts/c-suspicious.png` |  |  |
| `clip-records-layers.jsonl` | 4 | `layer-c-staring-green` | doll loop | promoted | `cutouts/c-staring.png` |  |  |
| `clip-records-layers.jsonl` | 5 | `layer-d-cheerful-green` | doll loop | candidate | `cutouts/d-cheerful.png` |  | superseded by layer-d-cheerful-v2-green (sleeves-fixed still) |
| `clip-records-layers.jsonl` | 6 | `layer-d-shocked-green` | doll loop | candidate | `cutouts/d-shocked.png` |  | superseded by layer-d-shocked-v2-green (sleeves-fixed still) |
| `clip-records-layers.jsonl` | 7 | `layer-b-deadpan-v2-green` | doll loop | promoted | `cutouts/b-deadpan.png` |  |  |
| `clip-records-layers.jsonl` | 8 | `layer-d-cheerful-v2-green` | doll loop | promoted | `cutouts/d-cheerful.png` |  |  |
| `clip-records-layers.jsonl` | 9 | `layer-d-shocked-v2-green` | doll loop | promoted | `cutouts/d-shocked.png` |  |  |
| `clip-records-s2v.jsonl` | 1 | `s2-b-lightning` | timed clip | promoted | `cutouts/b-deadpan.png` | 2, b |  |
| `clip-records-s2v.jsonl` | 2 | `s1-a-lightning` | timed clip | promoted | `cutouts/a-proud.png` | 1, a |  |
| `clip-records-s2v.jsonl` | 3 | `s3-c-lightning` | timed clip | promoted | `cutouts/c-suspicious.png` | 3, c |  |
| `clip-records-s2v.jsonl` | 4 | `s4-a-lightning` | timed clip | promoted | `cutouts/a-proud.png` | 4, a |  |
| `clip-records-s2v.jsonl` | 5 | `s5-d-lightning` | timed clip | promoted | `cutouts/d-shocked.png` | 5, d |  |
| `clip-records-s2v.jsonl` | 6 | `s6-c-lightning` | timed clip | promoted | `cutouts/c-suspicious.png` | 6, c |  |
| `clip-records-s2v.jsonl` | 7 | `s8-a-lightning` | timed clip | promoted | `cutouts/a-staring.png` | 8, a |  |
| `clip-records-s2v.jsonl` | 8 | `s8-b-lightning` | timed clip | promoted | `cutouts/b-deadpan.png` | 8, b |  |
| `clip-records-s2v.jsonl` | 9 | `s8-c-lightning` | timed clip | promoted | `cutouts/c-staring.png` | 8, c |  |
| `clip-records-s2v.jsonl` | 10 | `s8-d-lightning` | timed clip | promoted | `cutouts/d-shocked.png` | 8, d |  |
| `clip-records-s2v.jsonl` | 11 | `s9-b-lightning` | timed clip | promoted | `cutouts/b-deadpan.png` | 9, b |  |
<!-- motion-e0:end -->

The 14 lines that are not motion clips are the whole-frame image-to-video clips (story
[427](https://work.haynesnetwork.com/work_packages/427)'s whole-frame clips, not library
assets) and one whole-frame speech-to-video test.

Fields left out because no public text records them (never guessed):

<!-- motion-e0-gaps:begin -->
| Field left out | Why | Clips |
|---|---|---|
| `provenance.generator.workflow_sha256` | the clip record holds no workflow or graph hash (the first E0 batch, before poc/wan.py recorded one) | `layer-a-green`, `layer-set-loop` |
| `motion.keying` | the layered v1 film keyed it with the decal of poc at 6ea34aa, which had no version name (its box is in clipmap-layered.json) | `layer-b-deadpan-green`, `layer-d-cheerful-green`, `layer-d-shocked-green` |
| `motion.still_sha256` | no public record ties set-plate.png to r4's cutouts/set.png; a story uses this loop only by pinning it | `layer-set-loop` |
| `content.bytes` | the clip record holds no byte count | `s1-a-lightning`, `s2-b-lightning`, `s3-c-lightning`, `s4-a-lightning`, `s5-d-lightning`, `s6-c-lightning`, `s8-a-lightning`, `s8-b-lightning`, `s8-c-lightning`, `s8-d-lightning`, `s9-b-lightning` |
| `provenance.generator.workflow_sha256` | the clip record holds no workflow or graph hash (poc/s2v.py builds its graph in code) | `s1-a-lightning`, `s2-b-lightning`, `s3-c-lightning`, `s4-a-lightning`, `s5-d-lightning`, `s6-c-lightning`, `s8-a-lightning`, `s8-b-lightning`, `s8-c-lightning`, `s8-d-lightning`, `s9-b-lightning` |
<!-- motion-e0-gaps:end -->

Story [428](https://work.haynesnetwork.com/work_packages/428) checks the private files:
publishing a clip through the store returns its `sha256` and byte count; importing the
record again under its source key returns the same version when the bytes match (a
recorded measurement the public files lack matches any value, as in the library).

## Proposals and open points

- The `motion` block, its fields and code rules; the cast entry's optional
  `motion_asset_version_id`; the `motion.*` codes above.
- A motion version with a block pins its identity, not its bytes.
- The timed clip key is `s2v_clip_key`; the loop identity adds the negative prompt,
  which `motion_clip_key` lacks.
- The decal's still is the clip's start image.
- An unpinned set with no promoted set loop is a static plate, not an error.
- Unpinned resolution reads the library's state (the one promoted loop of a still), so
  promoting a second loop makes a board ambiguous until it pins one; the run snapshot
  records the version it resolved.
- Capabilities: a doll clip is `motion_clip`, a set loop `set_loop`.
