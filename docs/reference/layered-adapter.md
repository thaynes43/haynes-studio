# The layered method adapter

`haynes_studio.layered` (story [426](https://work.haynesnetwork.com/work_packages/426),
epic [372](https://work.haynesnetwork.com/work_packages/372)) builds `layered` + `s2v` and
`layered` + `i2v` boards: the dolls' keyed frames, one drive track per speaker, the
speech-to-video clips, the segment renderer and the board's photo (D51). It covers
[contract v1](../contracts/studio-contracts-v1.md) TIME-8, TIME-8a and TIME-9 (section 3)
and sections 4, 5 and 6, on the cache and renderer interface of
[cache-and-splice.md](cache-and-splice.md) and the pinned motion records of
[motion-clips.md](motion-clips.md). It ports `poc/layered_film.py`, `poc/cutout.py`,
`poc/decal.py`, `poc/keyframes.py` and the parts of `poc/edit.py` they call.

**State: source and tested with synthetic clips and a fake speech-to-video source
only.** No GPU or service call is made; the live Wan client is story
[842](https://work.haynesnetwork.com/work_packages/842). Nothing here makes a claim about
picture quality. Every choice beyond the contract is a **proposal** of story 426.

| Module | What |
|---|---|
| `layered.keying` | `key` (`poc/cutout.py key`), `decal_frames` (`poc/decal.py`), `summarize`, `gate`, `alpha_box` |
| `layered.keyed` | `KeyedFrames`: the keyed-frames stage; the keyed artifact (`make_keyed`, `read_record`, `frame_pngs`) |
| `layered.drive` | `DriveTracks`: one speaker's drive track (TIME-9) |
| `layered.source`, `layered.fake` | `S2VSource`, `S2VRequest`, `S2VClip`; `FakeS2VSource` |
| `layered.s2v` | `S2VClips`: speech-to-video clips through the cache, with their provenance records |
| `layered.compose` | placement, crops, shadow, motion, foreground edge and camera (the PoC's drawing) |
| `layered.renderer` | `LayeredRenderer` (compositor `COMPOSITOR`, `studio.layered/1+pillow-<v>+numpy-<v>`), `check_segment` |
| `layered.photo` | `photo_inputs`, `compose_photo`, `PhotoInputs` (D51) |
| `layered.pin` | `pin_story`, `pin_board`: the motion records a story plays, for the plan |
| `layered.build` | `LayeredStages` (the stages as one `upstream`), `reader` |
| `layered.checks` | `check_board`: the refusals as violations, for the pre-build check |
| `layered.errors` | the codes below |

## Supported input and output profile

| | Profile |
|---|---|
| Boards | `layered` + `s2v`, `layered` + `i2v`; any length; 24 fps (P-20); the media kind's frame size |
| Doll loops, set loop | pinned library `motion` versions (story 457) at 24 fps (the schema's loop rate), any `N`; a set loop of the board's aspect, scaled with Lanczos; a set plate fitted (Lanczos, cover, centred) |
| Speech-to-video clips | a profile with whole `source_fps` (16 in E0), even `size` of the media kind's aspect, `chunk` 77 (TIME-9); MP4 the source returns; or a library timed clip made from the board's own drive track |
| Keying | keyer `legacy:poc/cutout.py key` (E0's records) or `studio.layered.keyer/1` (the same code), keyed under `<keyer>@<build>`; thresholds `{lo, hi}`; protect boxes; decal version `erase-v2`; boxes in clip pixels; a speaker's loop of the S2V profile's size |
| Drive tracks | 16-bit mono PCM at the takes' rate (Kokoro: 24 kHz), exactly `F / 24` s |
| Output | one segment of exactly the board's frames, 8-bit RGB, encoded by the cache (P-26); a photo as PNG at the frame size |

## Which source frame each board frame shows

All picture runs on the board clock (P-06): nothing reads a film frame, a film offset or
a neighbouring board.

| Layer | Clock | Board frame `n` shows | Clip longer than the board | Clip shorter than the board |
|---|---|---|---|---|
| Idle doll (a library doll loop), TIME-8a | board | `trim_start + pingpong(n + phase, N)`, `phase = loop_phase(board, slot, 2N - 2)` | ping-pong (never trimmed) | ping-pong (a loop is never short) |
| Set loop, TIME-8a | board | the same with slot `set` | ping-pong | ping-pong |
| Speaker, a clip the build makes (TIME-8) | board | `floor(n * fs / 24)` (`floor(2n / 3)` at 16 fps) | the extra frames are trimmed and recorded | fails, `time.source_short` (P-05: nothing is held) |
| Speaker, a library timed clip (TIME-8) | board | `trim_start + floor(n * fs / 24)` | trimmed and recorded | fails, `time.source_short` |
| Set plate | none | the plate | | |

A short clip fails **before the first frame is drawn**: the renderer checks the last
frame a timed layer needs and every frame of a loop's first period against the keyed
frames. A loop whose keyed frames are fewer than its record says fails the same way;
more is `layered.clip_invalid`. The PoC's two film-clock behaviours are not ported: its
set loop and doll loops played by film frame (plus `37 * k`), and its timed clips held
their last frame (`DollClip.frame_at`); both are contract violations (P-05, P-06). The
tests read every board frame's source frame off the decoded segment.

## Keyed frames (`keyed_frames_key`)

One key (clip, still, key thresholds, protect boxes, decal box, decal version, keyer)
names one artifact. The plan writes the keyer as `<record's keyer>@<build>`, the build
being the numpy, OpenCV, Pillow, scipy and decoder (PyAV, libavcodec) versions
(`keyed.keyer_build()`, **proposal**, P-07): a lock bump keys every clip again, and a
stage refuses a key made for another build (it cannot reproduce it). So the cache key
is the record's `keys.keyed` with the build added to its keyer. On a miss the clip is decoded one frame at a time; when the key has
a decal box the lettering is tracked and pasted (below), then every frame is keyed and
cropped to one box: the first keyed frame's doll (alpha over 8) plus 24 px, as
`DollClip` did. The decal's still is the clip's start image (story 457's proposal).

| Setting | Value | PoC source |
|---|---|---|
| Key | dominance `G - max(R, B)`; alpha 1 at or below `lo`, 0 at or above `hi`; background: green touching the edge, pockets over 3000 px, islands with median dominance 45 or more outside the protect boxes; 24 px band unmixed against the border's median colour and despilled; alpha `MinFilter(3)` then `GaussianBlur(0.8)` | `poc/cutout.py key`, called as `key(im, 20, 70, protect)` |
| Thresholds | `{lo: 20, hi: 70}` (E0's records) | `DollClip.cache_dir` `'key': [20, 70]` |
| Decal track | ECC, affine, 60 iterations, eps 1e-4, Gaussian 5, over the decal box grown by 40 px, from frame 0 | `poc/decal.py decal_frames` |
| Decal paste | the still's yellow letters (`R > 170`, `G > 130`, `B < 100`, `R - B > 110`) in the box, dilated 4 px, feathered 2 px | the same |
| Erase | Wan's own yellow lettering inpainted (Telea, radius 4, dilated 5x5) over the tracked zone where it started and where the track puts it | the same, decal version `erase-v2` (commit 8f16830) |
| Gate | no failed frame and the lowest score at or above the floor: the record's `decal_min_ecc`, else 0.8 | `poc/decal.py MIN_ECC`, `DollClip` |
| Threads | OpenCV 2 (`cv2.setNumThreads(2)`); scipy and numpy single-threaded here | `poc/decal.py` |

**The artifact (proposal): one APNG** (`image/png`, which the store knows): lossless with
alpha, frames in order, each replacing the whole canvas, and a `tEXt` chunk `studio`
holding the record `studio.keyed-frames/v1`: key, frame count, clip size, crop box,
keyer, thresholds, protect boxes, the decal (box, version, every frame's score and the
summary) and the tool builds (numpy, OpenCV, Pillow, scipy). One file, so the frames and
their scores cannot part; each frame is Pillow's PNG encoding of the cropped RGBA, so the
same frames give the same bytes in one build, and a renderer reads any frame without
decoding the others. **Cost:** at most `box_w x box_h x 4` bytes a frame before deflate
(1.2 MB for a 338x888 doll box of a 576x1024 clip); flat synthetic frames deflate to
37 KB, a real felt doll will deflate far less, so expect tens of MB per 121-frame clip,
less than the PoC's keyed folder, which held uncropped 576x1024 PNGs. Story 428 records
the real sizes. Keying took 0.09 s a frame at 576x1024 on two threads (synthetic).

**The gate runs on every use, not when keying** (proposal, as `DollClip` did): the floor
is a record's, not a key input, so the artifact keeps every score and the renderer
applies the floor of each layer, **over the source frames the board shows** (proposal:
the PoC gated every frame, including the 56 of 158 an E0 speech clip's board trims). A track below it fails the segment before any frame
(`layered.decal_weak`) and the check result is kept: `{check: layered.decal_gate,
version: 1, artifact, key (check_result_key), thresholds: {min_ecc}, result, passed}`, in
the error (`error.check`) and in `renderer.checks[segment key]`. A weak artifact is
cached but never drawn; a record with a lower floor makes it pass without keying again.

## Drive tracks (TIME-9, `s2v_drive_track_key`)

One per on-screen speaker: her takes at their TIME-2 starts, silence elsewhere, exactly
`F / 24` s (`F * 1000` samples at 24 kHz). Proposal: assembled at the takes' own rate,
like the board voice track, so nothing is resampled; the toolchain's `drive_rate` is now
24 000 (it was a 16 kHz placeholder, which cannot hold `F / 24` s for most `F`). A take of
another rate or format, a take past the board's end, or a rate that cannot hold the board
or a millisecond in whole samples is `layered.drive_invalid`. The key is the speaker's
own takes and starts (P-25), so a line edit rebuilds her track and, when a take's length
changes, those of speakers with later lines.

## The speech-to-video source

A source gets one `S2VRequest` and returns one `S2VClip`:

| `S2VRequest` | What |
|---|---|
| `key` | the S2V clip key's value (to name or deduplicate the job) |
| `drive_track`, `drive_track_sha256` | the WAV and its hash |
| `start_image`, `start_image_sha256` | the start image: the speaker's cast still's loop's `source.image_sha256` (proposal, below) |
| `prompt`, `negative_prompt`, `seed` | the key's; the seed is the board's `s2v:<slot>` |
| `profile`, `adapter` | the key's profile (model, LoRA, steps, cfg, `size`, `chunk`, `source_fps`, `delivery`) and adapter `studio.s2v/1` |
| `frames` | TIME-9's `L = 4 * ceil(F / 6) + 1`, then multiples of 77 |
| `board_frames`, `frames_needed` | `F`, and TIME-8's `floor((F - 1) * fs / 24) + 1` |

| `S2VClip` | What |
|---|---|
| `data`, `media_type` | the clip, `video/mp4` |
| `seed`, `frames_requested`, `start_image_sha256`, `drive_track_sha256` | what the engine was given |
| `engine`, `engine_job_id`, `files_sha256`, `extra` | the engine and version, its job, the model files it loaded (name to SHA-256) and plain-JSON facts (timings, hardware) |

What a **live source** (story 842's Wan client) must do, so that it plugs in without
changing the cache or the renderer:

- Make the clip through the Wan API's compute lease, never around it: upload the start
  image and the drive track as given, use the profile's model, LoRA, steps, cfg, size and
  fps, ask for `frames` (`L`), and pass the prompts as data. E0's path is `poc/s2v.py
  --lightning` with pad 0.
- Return the clip it made or raise. Never a clip of another size, seed, start image,
  drive track or requested length, never one it did not make, never part of one.
- Fill `engine`, `engine_job_id` and `files_sha256` (at least one file, each by SHA-256)
  from the engine's own record (the Wan ledger), not from configuration; `extra` must be
  plain JSON (no NaN).
- It may deliver more frames than `L` (E0: 154 asked, 158 returned); the adapter keeps
  them and trims what the board does not show.

The adapter measures the rest itself (the hash, the frames it decodes to, the size). A
clip with fewer frames than TIME-8 needs is `time.source_short`; bytes that do not
decode, another size, seed, length asked, start image or drive track, or missing engine
facts are `layered.clip_invalid`. A failure publishes nothing.

## Speech-to-video clips through the cache (`s2v_clip_key`)

The cached artifact is the clip itself (`video/mp4`, outputs `s2v_clip` and `inputs`),
so its hash is the keyed frames' `clip`, as a library clip's is. Its **provenance record**
(`studio.s2v-clip/v1`, proposal) is committed first, in the same run, as the stage
`s2v_clip_record-<clip SHA-256>` (output `record`). A retry in the same run that gets
other bytes records them under their own name; one that gets the same bytes keeps the
first record (it names the same key and clip) and commits the clip. A hit reads the completed clip (re-hashed by the ledger) and its record stage in
the same run, which must name this clip and key (`layered.clip_invalid` otherwise); it
asks the source nothing. On a miss, the board's `F` is read from the drive track's length,
and a profile whose `source_fps` TIME-9's `L` cannot cover (it is sized for 16 fps) or a
source with no name is refused before the source is asked.

| Provenance field | What |
|---|---|
| `key`, `adapter`, `source` | the clip key, `studio.s2v/1`, the source's name |
| `drive_track` | `{sha256, board_frames}` |
| `start_image`, `prompt`, `negative_prompt`, `seed`, `profile`, `source_fps` | what was asked |
| `clip` | `sha256`, `bytes`, `media_type`, `frames_requested`, `frames_delivered`, `frames_needed`, `trimmed`, `width`, `height`, `engine`, `engine_job_id`, `files_sha256`, `extra` |

A speaker whose drive track is the one a promoted library timed clip of her still was
made from, **with the board's `s2v:<slot>` seed**, plays that clip
(`motion.resolve_timed`): the plan names it, the source is not asked, and its own
record's trim, fps, keying and gate floor apply. Another seed is a re-roll: the build
makes a new clip (section 4, "Seed"). The toolchain's S2V prompt and profile do not apply
to a library clip; its record says what made it, as a loop's does. A timed clip that cannot be
played (its bytes missing, its record corrupt, two candidates) stops the plan with its
code; it is never silently made again.

## The renderer

`LayeredRenderer` reads only the segment key document. Before the first frame it refuses
what it does not draw, reads every keyed artifact, the set and the voice track by hash
(re-hashed; missing is `time.source_short`, other bytes `store.hash_mismatch`), applies
every decal gate, places every doll and checks every layer's frame range. Then it yields
exactly the board's frames: the set frame; each doll in draw order (its keyed frame,
cropped by the slot, scaled to its height with Lanczos, its soft shadow, its motion);
the foreground edge over the current set frame; the camera.

| Segment input | Use |
|---|---|
| `method` | `layered` + `s2v` or `i2v` (whole-frame + S2V: `method.unavailable`; other: `layered.unsupported`) |
| `frames`, `width`, `height`, `fps` (24) | drawn |
| `layout` | the preset's values: per slot `x` (fraction of the width), `height`, `bottom`, optional `crop` (fractions); a preset without `slots` is the single framing |
| `layers` | per cast slot in draw order: `slot`, `still`, `clip`, `keyed`, `role`, `play` (`loop`, `timed`), `phase`, `trim_start`, `trim_frames`, `source_fps`, `clip_frames`, `decal_min_ecc` |
| `set_layer` | `plate`, `loop`, `phase`, `trim_start`, `trim_frames`, `clip_frames` |
| `motion_style` | idle scale, talk hop, tilt and shuffle (PoC defaults 0.3, 34, 3.2, 7); another key or a value that is not a number is refused |
| `voice_envelope`, `talk` | the board voice track and each line's speaker and span: the bounce curve |
| `cues` | `move` (a slot on the board) and at most one `camera` (`ease_out_cubic`); any other is refused |
| `foreground` | the edge polyline and feather |
| `procedural_stream` | accepted, draws nothing (no procedural layer in the layered method) |
| `whole_frame_clip` | must be null |
| any other key | refused |

Constants are the PoC's: the 240 px plate margin, the shadow (blur 22, 16 %, offset 12, 6,
one per doll per board from its first frame), the pivot 80 px above the slot's bottom, the
trajectory knots, 12 poses a second, the motion factor 1.4 for the single framing and 0.8
otherwise, idle 1.0 or 0.6 and hop 1.0 or 0.7. What differs, and why:

- **Single framing (proposal):** the PoC read it from the preset's name (`single`); the
  segment key holds the preset's values, so a preset with no `slots` is single. In r4 the
  only such preset is `single`.
- **Exact pose time:** the pose of board frame `n` is `n // 2` (12 a second), and a line's
  or move's position is computed in fractions of a millisecond; the PoC's float arithmetic
  could take a held step one pose early (contract section 3: floats never carry time).
- **Anchored cues:** a move or camera push starts at its cue's resolved `start_ms`
  (before it the camera holds `zoom_from`); the PoC's camera started at the shot's first
  frame. `steps` is the cue's.
- **Refusals instead of asserts:** a slot the preset does not place, a value that is not a
  number, a crop outside 0..1 or a doll more than 240 px off the frame is
  `layered.layout_invalid`, before the first frame.
- **Speakers bounce too:** as in the PoC's S2V film, every doll on the board, its S2V
  layer included, gets the idle wobble, the talk bounce and its moves (observation below).

`renderer.reports[segment key]` (written after the last frame) holds, per layer, its clip
and keyed hashes, how it plays, its phase, its first and last source frame, how many
distinct frames it showed and how many it trimmed, and the set's; `renderer.checks` holds
the decal checks. Neither is a cache input; the run records them (story 406).

## The layered board's photo (D51)

`photo_inputs(story, board, blobs=, width=, height=)` names what a layered board's
reference photo is made from: the story's set still, the board's cast stills in draw
order, the layout preset's values, the foreground edge (when the board shows it) and the
framing (the last camera cue's `zoom_to` and `center_px`). `compose_photo(inputs, read)`
composes it as `poc/keyframes.py` did: the set fitted to the frame, each cutout placed by
the preset with its shadow and no motion, the foreground, the camera at its end; a PNG
at the frame size with no metadata. The same inputs give the same bytes in one Pillow
build; a changed cast still, set, layout or framing gives a new photo and a new
`PhotoInputs.signature` (what story 407 compares for `photo_state: stale`). A note or a
seed changes neither. No image model, no GPU, no clip and no motion record is read; the
build never reads the photo. A cast still with no transparent pixel is refused.

## The cache plan's layered path

`plan_story(..., motion=pin_story(story_document, library, store.verify))` plans every
layered board from pinned records (story 457's resolver, run as if the board were
layered I2V so every cast entry has its loop):

- an idle doll's clip is its loop's bytes (planned as `<board>/doll_clip/<slot>` with the
  record's clip key, never asked of a source), its keyed frames are the record's keyed
  key, its `N`, fps and phase are the record's;
- a speaker's start image and keying are her loop's (proposal); her drive track and S2V
  clip are planned as before, unless a library timed clip of her still was made from
  that drive track;
- the set is the story's pinned set loop, else the one promoted loop of the set still,
  else the plate.

A blocking motion problem stops the plan with its own code (`motion.clip_absent` for a
cast still without a loop: Build generates no loop, Q-457-1). Without `motion`, the plan
keeps story 380's placeholders (the toolchain's motion and keying fields) for key-only
callers, and the renderer refuses those layers (`layered.unsupported`), so such a plan
cannot be built. The invalidation rows the pinned path changed are listed in
[cache-and-splice.md](cache-and-splice.md#invalidation-matrix-as-tested).

## Supported and refused

| Input | Result | Code |
|---|---|---|
| Layered S2V or I2V board with pinned loops, cues, foreground, motion style | built | |
| Whole-frame + speech-to-video | refused | `method.unavailable` |
| Whole-frame I2V board, or any other method | refused | `layered.unsupported` |
| A cast still with no loop | refused (plan, pre-build check) | `motion.clip_absent` |
| A plan without motion records; an unknown segment input; a sound or unknown cue in the segment; two camera cues; another easing; a move of a slot not on the board; no set; fps other than 24; a motion style with another key or a non-number | refused | `layered.unsupported` |
| A set loop of another aspect than the board | refused | `layered.unsupported` |
| An unknown keyer or decal version; thresholds not `{lo < hi}`; a box that is not four pixels; a decal box outside the clip | refused before keying | `layered.unsupported` |
| An S2V profile without whole `source_fps`, even `size` of the media kind's aspect, or `chunk` 77, or whose fps `L` cannot cover; another adapter or drive assembler; a keyer made for another build | refused before the source is asked | `layered.unsupported` |
| A speaker's loop of another size than the S2V profile (her keying boxes are in its pixels) | refused by the plan and `check_board` | `cache.key_input_invalid`, `layered.unsupported` |
| A slot the preset does not place; a crop outside 0..1; a doll more than 240 px off the frame | refused | `layered.layout_invalid` |
| Takes that cannot make an exact drive track | refused | `layered.drive_invalid` |
| A missing clip, keyed artifact, set loop or drive track; a clip shorter than TIME-8 needs; keyed frames fewer than recorded | failed stage | `time.source_short` |
| A source's answer that is not what was asked; a clip or keyed artifact that does not decode; nothing left after keying; an S2V clip without its provenance record | failed stage | `layered.clip_invalid` |
| A decal track below the layer's floor, or with a failed frame | failed segment, with its check result | `layered.decal_weak` |
| A blob that is not its hash | failed stage | `store.hash_mismatch` |

| Code | Status | Source |
|---|---|---|
| `method.unavailable` | unavailable | contract |
| `time.source_short` | failed | contract |
| `motion.clip_absent` | invalid | story 457 |
| `layered.unsupported` | invalid | proposal |
| `layered.layout_invalid` | invalid | proposal |
| `layered.drive_invalid` | invalid | proposal |
| `layered.clip_invalid` | failed | proposal |
| `layered.decal_weak` | failed | proposal |

## The E0 records against the proposals

Story 457 imported the E0 clips; `tests/layered/test_r4.py` checks the two proposals a
speaker's layer stands on against them (from `clipmap-s2v.json`):

- **Start image:** all 11 timed clips started on their cast still's promoted loop's start
  image (`source.image_sha256`). The proposal holds.
- **Keying:** keyer, thresholds, decal box and decal version agree for all 11. Two things
  differ: A's three clips (`s1-a`, `s4-a`, `s8-a`) were keyed with **no** eye-protect box,
  where A's loops have one; and six clips' gate floors differ from their loop's
  (`s1-a` 0.7 against 0.8, `s9-b` 0.78 against 0.65, and `s2-b`, `s8-b`, `s5-d`, `s8-d` at
  the default 0.8 where their loops were allowed 0.65 or 0.6). As built, a clip the build
  makes is keyed with the loop's protect boxes and gated at the default 0.8, not at the
  loop's lowered floor (a floor is a judgement of one clip). Held question Q-426-1.

With the r4 story as imported (layered S2V, seeds written by the test, no media read),
the plan resolves every board: the idle dolls of boards 7 (D) and 9 (A, C) play
`layer-d-shocked-v2-green`, `layer-a-green` and `layer-c-suspicious-green`; every one of
the 11 speakers plays her E0 timed clip **when the build's drive track is the one E0's
clip was made from, with E0's seed** (the test writes E0's seeds on the boards and answers
the drive keys with E0's recorded hashes); no S2V clip is asked for; loops play with `N` 121 and their board phase, timed clips with
section 3's trims; the set is the plate (r4 pins no set loop).

## How a build runs it (stories 406 and 428)

```python
from dataclasses import replace
from haynes_studio.cache import ArtifactCache, Toolchain, plan_story
from haynes_studio.cache.build import PictureBuilder
from haynes_studio.layered import COMPOSITOR, LayeredRenderer, LayeredStages, reader
from haynes_studio.layered.pin import pin_story

cache = ArtifactCache(store, production_id=prd, run_id=run, earlier_runs=earlier)
read = reader(store, [prd, "library"])
stages = LayeredStages(cache, source, read=read)  # FakeS2VSource() in tests; story 842's live source in 428
builder = PictureBuilder(cache, LayeredRenderer(), open_input=read,
                         upstream=lambda key: stages(key) if stages.handles(key) else other(key))
tools = replace(Toolchain(), compositor=COMPOSITOR, s2v_profile=..., drive_rate=24_000)
motion = pin_story(story_document, library, store.verify, production_id=prd)
plan = plan_story(story, ..., toolchain=tools, content=builder, motion=motion)
```

- Takes, the board voice track, library clips and stills must be in the store under
  `reader`'s scopes; the voice track is the renderer's envelope.
- The toolchain's `compositor` is `layered.COMPOSITOR`, its `s2v_profile` names the
  model, LoRA, steps, cfg, `size` (576x1024 in E0), `chunk` 77 and `source_fps` 16, its
  `s2v_adapter` `studio.s2v/1`, its `drive_assembler` `studio.s2v.drive/1`. One build
  has one compositor (story 380's `Toolchain`), so story 406 registers this renderer for
  layered boards beside the whole-frame one and gives each method its compositor.
- Story 406 runs `check_board(story, board, motion=pin_board(...), frame_size=(w, h),
  s2v_size=tuple(profile["size"]))` at `queue_run`, so a set loop of another aspect or a
  speaker's loop of another size is refused before any clip is made, and records
  `renderer.reports`, `renderer.checks` and the S2V provenance records with the run.
- Story 428 swaps the fake source for the live one; nothing else changes. A second build
  of an unchanged story renders nothing, keys nothing and asks the source nothing.
  Heavy work (keying, compositing) runs on the `ai/studio-render` worker (AGENTS.md);
  keying holds one clip's frames at a time and the renderer every frame of the set loop
  (as the PoC did), so record memory and time per board. A r4 build will generate new
  S2V clips unless the drive tracks match E0's bytes (observation below).
- Tests: `uv run pytest tests/layered` (synthetic 144x256 dolls on 360x640 boards, a fake
  source, about a minute and a half on two threads); the cache rows in `tests/cache`.

## Proposals and observations

Proposals of story 426 (beyond the contract): the `layered.*` codes; the APNG keyed
artifact and its record; the keyer's build in the keyed key; the gate on every use, over
the frames the board shows; drive tracks at the takes' rate; the S2V clip as the cached
artifact with its provenance stage; a library timed clip only with the board's seed; a
speaker's start image and keying from her loop, and her loop at the S2V size; the
default floor for a clip the build makes; the single framing read from the preset's
values; one camera cue per board; the compositor digest; the photo's inputs and its PNG
form.

Observations for the contract owner are in the PR of story 426.
