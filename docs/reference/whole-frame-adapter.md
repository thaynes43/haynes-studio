# The whole-frame image-to-video adapter

`haynes_studio.wholeframe` (story [427](https://work.haynesnetwork.com/work_packages/427),
epic [372](https://work.haynesnetwork.com/work_packages/372)) builds `whole_frame` + `i2v`
boards: the length policy for a board's clips, a clip source interface, the clips as one
cached artifact and a segment renderer. It covers
[contract v1](../contracts/studio-contracts-v1.md) TIME-8 (section 3) and sections 4 and 5,
on the cache and renderer interface of [cache-and-splice.md](cache-and-splice.md).

**State: source and tested with a fake clip source only.** No GPU or service call is made;
the live Wan client is a later story. Nothing here makes a claim about picture quality.
Every choice beyond the contract is a **proposal** of story 427.

| Module | What |
|---|---|
| `render.clock` | `i2v_clip_lengths` (the policy) and `i2v_chain_frames` |
| `wholeframe.chain` | `assemble`: a board's frames from a chain, by TIME-8, pure |
| `wholeframe.source` | `ClipSource`, `ClipRequest`, `ClipSpec`, `SourceClip`, `chain_seed`, `last_frame_png` |
| `wholeframe.fake` | `FakeClipSource`: small synthetic clips for tests and dry runs |
| `wholeframe.clips` | `WholeFrameClips`: the clip stage on `ArtifactCache`; `production_reader`, `IMAGE_TYPES`, `media_stage` |
| `wholeframe.renderer` | `WholeFrameRenderer` (compositor `COMPOSITOR`, `studio.wholeframe/1+pillow-<version>`), `fit_rule`, `check_segment` |
| `wholeframe.checks` | `check_board`: the refusals as violations, for the pre-build check |
| `wholeframe.errors` | the codes below |

## The length policy (proposal)

`i2v_clip_lengths(frames_needed, clip_frames=121, max_clips=3)`, where `frames_needed` is
TIME-8's `floor((F - 1) * fs / 24) + 1` (that is `F` at 24 fps):

| Rule | Reason (E0 evidence) |
|---|---|
| Every clip is a whole 121-frame clip | 121 frames at 24 fps is the only length E0 made (all 13 whole-frame clips in [`clip-records.jsonl`](../../titles/the-winter-menu/video-e0/clip-records.jsonl)). Whole clips keep the requested lengths, a key input, unchanged under hold and tail edits, so the clips are reused (section 4) |
| A board longer than one clip **chains** | E0 chained shots 1, 3 and 8 ([`assembly-wf.json`](../../titles/the-winter-menu/video-e0/assembly-wf.json): 241 and 361 source frames). Each later clip starts on the previous clip's last frame and adds 120 frames, so `n` clips cover `1 + 120 n` frames |
| One clip when `needed <= 121`, else `1 + ceil((needed - 121) / 120)` | the shared boundary frame is dropped, so two clips hold 241 frames, not 242 |
| Extra source frames are trimmed and recorded; a short chain fails | TIME-8 and P-05. E0 held the last frame of shot 6 (122 frames from one clip); this policy asks for a second clip |
| No stretch | E0 delivered no stretched cut (`"stretch": false`), and slowing a 24 fps clip breaks TIME-8's frame mapping |
| At most **3 clips** (361 source frames, 15.04 s); a longer board is refused | E0's longest delivered chain is 3 clips (shot 8). [`findings.md`](../../titles/the-winter-menu/video-e0/findings.md): "chaining compounds drift". Split the board or use the layered method |

Worked table (clips of 121 frames, the r4 board lengths among them):

| Board frames F | Clips requested | Frames used from each clip | Distinct chain frames | Trimmed |
|---|---|---|---|---|
| 46 | 1 | 46 | 121 | 75 |
| 94 | 1 | 94 | 121 | 27 |
| 108 | 1 | 108 | 121 | 13 |
| 121 | 1 | 121 | 121 | 0 |
| 122 | 2 | 121, 1 | 241 | 119 |
| 146 | 2 | 121, 25 | 241 | 95 |
| 153 | 2 | 121, 32 | 241 | 88 |
| 241 | 2 | 121, 120 | 241 | 0 |
| 242 | 3 | 121, 120, 1 | 361 | 119 |
| 251 | 3 | 121, 120, 10 | 361 | 110 |
| 361 | 3 | 121, 120, 120 | 361 | 0 |
| 362 | refused | | | |

Board 1 of r4 (153 frames): clip 0 gives source frames 0 to 120; clip 1's frame 0 repeats
clip 0's frame 120 and is dropped; its frames 1 to 32 are board frames 121 to 152; its
frames 33 to 120 (88) are trimmed. The requested lengths change only at 122 and 242 frames,
so a hold edit from 46 to 121 frames keeps the clip. For the nine r4 boards the policy asks
14 clips; E0 made 13 for the same cuts, the difference being board 6.

`plan_story` calls the policy; a board past the limit is `cache.key_input_invalid` there,
and `check_board` reports it as `wholeframe.chain_limit` first.

## Chain assembly

`assemble(frames, delivered, source_fps)` lays the clips end to end, drops frame 0 of each
clip after the first, and maps board frame `n` to source frame `floor(n * fs / 24)`
(TIME-8). It records, per clip, the frames delivered, dropped (1 at a boundary), offered,
used and trimmed. An empty clip or a chain with fewer distinct frames than needed is
`time.source_short`; nothing is held or padded.

## The clip source

A source gets one `ClipRequest` and returns one `SourceClip` per `ClipSpec`, in order:

| `ClipRequest` field | What |
|---|---|
| `key` | the whole-frame clip key's value (for naming or deduplicating jobs) |
| `photo`, `photo_sha256` | the board photo's bytes and hash, as the key names it (PNG, JPEG or WebP; the bytes' signature says which) |
| `prompt`, `seed` | the key's prompt and the board's `i2v:frame` seed |
| `profile` | the key's profile: `model`, `source_fps`, `size` `[width, height]`, `adapter`, `delivery` |
| `clips` | `ClipSpec(index, frames, seed)` per clip: the requested length and `chain_seed(seed, index) = seed + index` (proposal) |

| `SourceClip` field | What |
|---|---|
| `index`, `seed`, `frames_requested` | as asked |
| `data`, `media_type` | the clip, `video/mp4` |
| `start_image_sha256` | the image the engine started from |
| `engine`, `engine_job_id` | engine name and version, and its job ID |
| `files_sha256` | model files loaded, name to SHA-256 (section 7's `generator.files_sha256`) |
| `extra` | engine facts worth keeping (timings, temperatures, hardware), plain JSON |

What a **live source** (the Wan client) must do, so that it plugs in without changing the
cache or the renderer:

- Make the clips in order through the Wan API's compute lease, never around it. Clip 0
  starts on `photo`; clip *k* starts on `last_frame_png(<clip k - 1's bytes>)`, uploaded
  as a PNG. Use each `ClipSpec`'s seed and length and the profile's model, size and fps;
  pass the prompt as data.
- Return every clip or raise. Never return part of a chain, a clip of another length,
  size or start image, or a clip it did not make. The adapter checks all of these and
  fails the stage (below); a failure publishes nothing.
- Fill `engine`, `engine_job_id` and `files_sha256` (at least one file, each by SHA-256)
  from the engine's own record (the Wan ledger), not from configuration; `extra` must be
  plain JSON (no NaN). A clip without them fails `wholeframe.clip_invalid`.

The adapter measures everything else itself: each clip's hash, the frames it decodes to,
its size, and the start image a chained clip should have had.

## The clips as one cached artifact

`WholeFrameClips(cache, source, read_photo=...)` is the plan's `content` for
`whole_frame_clip` keys. One key is one artifact, the **clip set** (proposal): a JSON
record committed once as the completed stage `whole_frame_clip-<key hex>` through
`ArtifactCache` (outputs `whole_frame_clip` and `inputs`). The clips and chained start
images it names are committed just before it, in the same run, as the **media stage**
`whole_frame_media-<clip set hash>` (proposal; outputs `clip.<i>` and `start.<i>`), so
every blob is listed by a completed record and `store doctor` reports no orphan. The
media stage is named by the clip set's content, so a retry after a failure between the
two commits makes a new pair and never collides with the first.

| Case | What happens |
|---|---|
| Miss | refuse a profile it cannot serve; read the photo by hash and re-hash it; ask the source; check every clip and make the clip set record; commit the media stage (clips as `video/mp4`, start images as `image/png`); then commit the clip set. Blobs first, records last |
| Hit | read the completed record; check it is this key's clip set; read the media stage's record in the same run, which re-hashes every blob, and check that it lists exactly the clip set's clips and start images. A missing blob or record is `time.source_short`, other bytes `store.hash_mismatch`; nothing is repaired or regenerated |
| Bad answer | a missing or short clip is `time.source_short`; extra frames, an undecodable clip, another size, seed, length or start image, or incomplete provenance is `wholeframe.clip_invalid`. Nothing is published or committed |

The clip set (`studio.whole-frame-clips/v1`) holds `key`, `adapter`, `source` (the
source's name), `photo` (the first photo's hash), `prompt`, `seed`, `profile`,
`clip_lengths`, `source_fps` and one provenance record per clip:

| Field | What |
|---|---|
| `index`, `sha256`, `bytes`, `media_type` | the clip in the production's folder |
| `engine`, `engine_job_id`, `files_sha256`, `extra` | from the source |
| `seed`, `profile` | what the clip was made with |
| `start_image` | `{role: photo, sha256}` for clip 0; `{role: previous_last_frame, sha256, media_type}` after |
| `frames_requested`, `frames_delivered` | asked and measured by decoding |
| `width`, `height` | measured |

## The renderer

`WholeFrameRenderer` reads only the segment key document. Before the first frame it
refuses what it does not draw, reads the clip set and every clip it needs by hash
(re-hashed), and assembles; then it yields exactly the board's frames, decoding one clip at
a time. A clip that decodes to fewer frames than recorded fails mid-way, so the encoder
never finishes and nothing is committed.

| Segment input | Use |
|---|---|
| `method` | `whole_frame` + `i2v` only |
| `frames`, `width`, `height`, `fps` (24), `whole_frame_clip` | drawn |
| `voice_envelope`, `talk`, `procedural_stream` | accepted, draw nothing: whole-frame I2V has no talk bounce or procedural layer |
| `layout`, `layers`, `set_layer`, `motion_style`, `foreground`, `cues` | must be empty; anything else is refused |
| any other key | refused |

**Frame size rule (proposal):** a clip of the board's size is used as is; a clip of the
same aspect exactly (576x1024 to 1080x1920) is scaled with Pillow's Lanczos, as E0's
assembler did; any other aspect is refused. Nothing is cropped or padded.

`renderer.reports[segment key]` holds what each render used: the clip set, the clips'
hashes, the assembly (per-clip use and the trim) and the size rule. It is written only
after the last frame is made, so a failed render leaves none. It is not a cache input;
the run records it with the committed segment (story 406).

The compositor digest names the Pillow version, because Pillow's Lanczos draws the
pixels of a resized clip; a Pillow update makes new segment keys.

## Supported and refused

| Input | Result | Code |
|---|---|---|
| Whole-frame I2V board, silent or spoken, with sound cues | built | |
| Whole-frame + speech-to-video | refused | `method.unavailable` |
| A layered board | refused | `wholeframe.unsupported` |
| No current photo version | refused | `photo.absent` (`check_board`; the plan cannot key it) |
| A move or camera cue | refused | `wholeframe.unsupported` |
| Layout, layers, set, motion style or foreground in the segment key; fps other than 24; an unknown input | refused | `wholeframe.unsupported` |
| A clip of another aspect than the board | refused | `wholeframe.unsupported` |
| A profile naming another adapter, without a whole `source_fps` or even `size`, or whose size is not the media kind's aspect | refused before the source is asked | `wholeframe.unsupported` |
| A board needing more than 3 clips | refused | `wholeframe.chain_limit` (`cache.key_input_invalid` in the plan) |
| A stored clip that is missing, short or undecodable; a missing media stage; a segment key with no clip | failed stage | `time.source_short` |
| A source's answer that is not what was asked (above) | failed stage | `wholeframe.clip_invalid` |
| A clip set or clip that is not its hash | failed stage | `store.hash_mismatch` |

| Code | Status | Source |
|---|---|---|
| `method.unavailable` | unavailable | contract |
| `photo.absent` | invalid | contract |
| `time.source_short` | failed | contract |
| `wholeframe.unsupported` | invalid | proposal |
| `wholeframe.chain_limit` | invalid | proposal |
| `wholeframe.clip_invalid` | failed | proposal |

## How a build runs it (stories 406 and 428)

```python
from haynes_studio.cache import ArtifactCache, plan_story
from haynes_studio.cache.build import PictureBuilder
from haynes_studio.cache.keys import WHOLE_FRAME_CLIP
from haynes_studio.wholeframe import WholeFrameClips, WholeFrameRenderer, production_reader
from haynes_studio.wholeframe.clips import IMAGE_TYPES

cache = ArtifactCache(store, production_id=prd, run_id=run, earlier_runs=earlier)
clips = WholeFrameClips(cache, source,  # FakeClipSource() in tests; the live Wan source in 428
                        read_photo=production_reader(store, "library", IMAGE_TYPES))
builder = PictureBuilder(cache, WholeFrameRenderer(), open_input=production_reader(store, prd),
                         upstream=lambda key: clips(key) if key.kind == WHOLE_FRAME_CLIP else other(key))
plan = plan_story(story, ..., toolchain=toolchain, content=builder)
```

- The toolchain's `compositor` must be `wholeframe.COMPOSITOR` for these segments, its
  `i2v_profile` must name adapter `studio.i2v/1` with `source_fps` and `size`, and its
  `i2v_clip_frames` is the policy's clip length. Story 406 registers this renderer for
  whole-frame boards beside the layered one of story 426 and runs `check_board` at
  `queue_run`. Until it does, a move or camera cue on a whole-frame board is refused
  only by the renderer, after the clips were made (they stay cached for the corrected
  board).
- Story 428 swaps `FakeClipSource` for the live source; nothing else changes. A second
  build of an unchanged board asks the source for nothing and renders nothing. Record
  `renderer.reports` and the clip sets' provenance with the run.
- Tests: `tests/wholeframe/` (`uv run pytest tests/wholeframe`), at 360x640 with 25-frame
  clips and once with 121-frame clips; all media is made under `tmp_path`.
