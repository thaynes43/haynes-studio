# Cache keys, the segment cache and the splice

`haynes_studio.cache` and `haynes_studio.render` (story
[380](https://work.haynesnetwork.com/work_packages/380), epic
[372](https://work.haynesnetwork.com/work_packages/372)) cover three things: a cache key
for every artifact of [contract v1](../contracts/studio-contracts-v1.md) section 4, the
board clock, and the picture segment cache and its splice. They build on the store and
stage commit of [store-and-stages.md](store-and-stages.md) and on the story model of
[studio-model.md](studio-model.md). Real renderers, GPU and service calls, the mix,
master and proxy files, timings and any deletion are not part of this story. Those are
stories [426](https://work.haynesnetwork.com/work_packages/426),
[427](https://work.haynesnetwork.com/work_packages/427),
[381](https://work.haynesnetwork.com/work_packages/381),
[406](https://work.haynesnetwork.com/work_packages/406) and
[428](https://work.haynesnetwork.com/work_packages/428).

## Modules

| Module | What |
|---|---|
| `cache.keys` | `make_key`, `CacheKey`, one key function per artifact, `INVENTORY` |
| `cache.plan` | `plan_story`: every artifact's key for one story, in dependency order; `diff` of two plans; `Toolchain`, `MediaFormat`, `BoardVoice` |
| `cache.artifacts` | `ArtifactCache`: one completed stage per key; `StageFinder`, `RunSearch` |
| `cache.build` | `PictureBuilder`: segments and the film picture through the cache |
| `render.clock` | the board clock: loop phase, ping-pong, TIME-8 and TIME-9 frame maths, procedural randomness |
| `render.base` | `SegmentRenderer` and `SegmentRequest`, the interface a real renderer implements |
| `render.synthetic` | `SyntheticRenderer`, a deterministic test renderer, and `read_code` |
| `render.encode` | `EncoderSettings`, `encode_segment`, `decode_frames`, `probe_segment` |
| `render.splice` | `splice`: the film picture from ordered segments by stream copy |
| `render.errors` | the codes below (`cache.errors` re-exports them) |

## Keys

`key = "sha256:" + hex(sha256(canonical_json(document)))`. The canonical JSON is the
store's: UTF-8, sorted keys, no whitespace, no NaN or Infinity, and floats in shortest
round-trip form. Before a document is encoded, `make_key` checks and normalizes it:

- An integral float is the integer it equals (`-22.0` is `-22`, as section 2 reads JSON).
- Texts and mapping keys are NFC.
- Times, frames, rates and seeds are integers, and `bool` does not count as one.
- A hash field holds 64 lower-case hex digits.
- No text anywhere in a key document may be a studio identifier (`<prefix>_<ULID>`);
  `make_key` refuses one with `cache.key_input_invalid`.
- Nothing else can enter a key: no bytes, paths, sets or objects.

Every document carries `kind` and `scheme` (`studio.cache-key/v1`, a proposal; changing
how any key is made bumps it). The key's 64 hex digits are also the SHA-256 of
`CacheKey.canonical`. Inputs are content hashes and parameters, never identifiers or
paths. `make_key` enforces this, and a test also checks that no key document in the
fixture plan holds an ID.

### Inventory

One pure function per row of the section 4 table. None of them reads a file, the clock
or the environment, and a test runs each one with `open`, `os.open` and `os.stat`
disabled. A second test changes each input in turn and checks that the key changes.
To add an artifact, add a function and an `ArtifactSpec` row to `INVENTORY`.

| Artifact | `kind` | Clock | Function | Inputs |
|---|---|---|---|---|
| Voice take | `voice_take` | none | `voice_take_key` | `tts_model`, `voice_id` (stock voice name), `text` (NFC), `speed`, `sample_rate` |
| Board voice track | `board_voice_track` | board | `board_voice_track_key` | `takes` (hashes, line order), `lead_ms`, `gaps_ms` (lines 2..n), `mix_rate`, `assembler`; no tail |
| S2V drive track | `s2v_drive_track` | board | `s2v_drive_track_key` | `speaker`, `lines` (the speaker's take hashes with their start in ms), `frames`, `fps`, `rate`, `assembler` (proposal, below) |
| S2V clip | `s2v_clip` | source | `s2v_clip_key` | `drive_track`, `start_still`, `prompt`, `negative_prompt`, `seed`, `profile`, `adapter` |
| Doll clip or set loop | `motion_clip` | source | `motion_clip_key` | `still`, `prompt`, `seed`, `profile` (names the adapter) |
| Whole-frame I2V clip(s) | `whole_frame_clip` | source | `whole_frame_clip_key` | `photo`, `prompt`, `seed`, `profile`, `clip_lengths` |
| Keyed and decal frames | `keyed_frames` | source | `keyed_frames_key` | `clip`, `still`, `key_thresholds`, `protect_boxes`, `decal_box`, `decal_version`, `keyer` |
| Board picture segment | `segment` | board | `segment_key` | `method`, `frames`, `width`, `height`, `fps`, `layout` (preset values), `layers` (per cast slot in draw order: still, clip, keyed, phase), `set_layer`, `whole_frame_clip`, `motion_style`, `voice_envelope`, `talk` (each line's speaker and span), `cues` (move and camera, resolved to ms), `foreground`, `procedural_stream`, `compositor`, `encoder` |
| Film picture | `film_picture` | film | `film_picture_key` | `segments` (ordered hashes with frames), `splicer` |
| Mix | `mix` | film | `mix_key` | `voice_tracks` (hash, `F[k]`, line spans), `sounds` (hash, start sample, trim, level), `beds`, `line_rms_dbfs`, `master_lufs`, `true_peak_dbtp`, `frames`, `rate`, `mixer` |
| Master | `master` | film | `master_key` | `picture`, `mix`, `mux` |
| Proxy | `proxy` | film | `proxy_key` | `master`, `profile` |
| Check result | `check_result` | none | `check_result_key` | `artifact`, `check`, `version`, `thresholds` (a transcript check also gets the story's tolerances and the script's hash) |

### The key plan

`plan_story(story, voices=, blobs=, voice_ids=, toolchain=, media=, content=)` walks the
boards in `board_order` and computes each artifact's key in dependency order. A key
takes the content hash of what it is made from, so the plan asks `content(key)` for
each artifact it needs downstream:

- `PictureBuilder` renders or reuses segments and the film picture, and hands every
  other kind to its `upstream` source: the adapters of stories 426, 427, 381 and 406.
- A key-only test uses a stand-in, a hash of the key.

The plan's inputs are resolved beforehand:

- the story with its boards embedded;
- each spoken board's current voice (`BoardVoice`: take hashes and lengths, and the
  track hash);
- `blobs` (asset version to content hash);
- `voice_ids` (voice version to stock voice name);
- the `Toolchain`, which holds every adapter, profile, prompt and tool digest; its
  defaults are placeholders, and the default mux and proxy profile name the encoder
  build, as segments do;
- the `MediaFormat`: an even frame size, and 24 fps only (both media kinds deliver at
  24 fps and TIME-3 counts board frames at 24, so another fps is refused rather than
  half applied).

Board timing comes from story 404's `board_clock`. An untimed board, an unresolved
asset, a missing seed or an unavailable method is `cache.key_input_invalid`; the
pre-build check refuses these first. Artifact names in the plan (`<board>/segment`,
`<board>/s2v_clip/<slot>`, `film/mix`) contain IDs, but key documents never do.

The plan decides which layers a board has:

- **Layered + S2V:** every cast slot with a line on the board gets an S2V layer (drive
  track, S2V clip, keyed frames). Every other slot gets a doll layer: a doll clip keyed
  by its still, the toolchain's doll prompt and seed, then keyed frames.
- **Layered + I2V:** every slot gets a doll layer.
- **Whole frame + I2V:** one whole-frame clip, from the board's current photo and its
  `i2v:frame` seed.
- **Whole frame + S2V:** refused (`method.unavailable`).

## The board clock

All picture runs on the board clock (P-06). Nothing in `render.clock`, `SegmentRequest`
or `SegmentRenderer.render` takes a film frame or offset, and a test checks every
signature for that.

| Rule | Function | Detail |
|---|---|---|
| Loop phase | `loop_phase(board_id, slot, period)` | `int(sha256(board_id + ":" + slot)[:8], 16) mod period`; the set loop uses slot `set` (proposal); a loop's N is the motion profile's `frames` (121) |
| Ping-pong loops (TIME-8a) | `pingpong`, `loop_frame`, `loop_period` | board frame *n* shows `pingpong(n + phase, N)`, period `2N - 2` |
| Board-specific clips (TIME-8) | `source_frame`, `source_frames_needed` | `floor(n * fs / 24)`; checked against the r4 worked example |
| S2V request (TIME-9) | `s2v_request_frames` | `L = 4 * ceil(F / 6) + 1`, then multiples of 77 |
| Whole-frame clip lengths | `i2v_clip_lengths` | **placeholder** for story 427's chain policy: whole 121-frame clips |
| Procedural randomness | `procedural_random(seed, board_id, index)` | `stream_random(board_stream(seed, board_id), index)`, SHA-256 based with no generator state, so draw order does not matter |

- The segment key carries the phases and `procedural_stream` (a 64-bit number derived
  from the toolchain's `procedural_seed` and the board ID), never the board ID itself.
- Generation seeds are read from the board's `seeds` (`s2v:<slot>`, `i2v:frame`). The
  plan never makes one: a missing seed is an error, because the server writes seeds.
- A build test lengthens board 1, so that boards 2 to 4 start later in the film. Only
  board 1 renders, and every film frame still decodes to its own board's frame *n*.

## The segment cache on the store

A cached artifact is a completed stage named `<kind>-<key hex>`, for example
`segment-<64 hex>`. The stage has two outputs:

- the artifact itself, under its kind's name (`segment`, `video/mp4`);
- `inputs`, the key document as canonical JSON (`application/json`), committed with
  `expected_sha256` equal to the key, so the record shows which inputs made the
  artifact.

| Case | What the cache does |
|---|---|
| Miss | `commit_stage` publishes both blobs, then the record, under the current run |
| Hit | Reads the completed record and re-hashes its blobs (the local ledger does it itself; with a separate ledger, `RunSearch` re-hashes through the store), then checks it: exactly the two outputs, `inputs` hashing to the key, the right media type; else `cache.entry_invalid` |
| Damaged entry | Fails closed: the error stops the build; the cache neither skips nor repairs it (D17), so a person looks at it |
| Never | Deletes, evicts, overwrites, renames or truncates; a test scans the source for such calls |

Lookup order (**proposal**): records live under a run, so `ArtifactCache` searches the
current run first and then the `earlier_runs` it is given, newest first (`RunSearch`).
`StageFinder` is the seam for the product's Postgres ledger (story
[434](https://work.haynesnetwork.com/work_packages/434)), which can find a stage name
in a production with one query. A hit writes nothing in the current run; the build's
film picture key lists every segment hash it used. Cached artifacts are per production,
because a record names blobs in its production's folder.

`PictureBuilder` serves as the plan's `content` for segments and the film picture:

- **Segment:** checks that the key's compositor is the renderer's and its encoder
  settings are the builder's, renders through `SegmentRenderer` from a
  `SegmentRequest` (key, key document, an input reader by hash), encodes, probes the
  frame count (TIME-11) and commits.
- **Film picture:** reads each segment by hash from the production's folder, one at a
  time and only when the splice reaches it, re-hashes the bytes it read
  (`store.hash_mismatch` otherwise), splices them and commits the film. The film
  holds exactly the bytes its key names.

A real renderer implements `SegmentRenderer` (a `compositor` digest and `render`) and
plugs in without touching the cache.

## Encoding and the splice

Segments are H.264 in MP4 with video only and a constant frame rate. Every packet's
decode time equals its presentation time (no B-frames), and the first frame is an IDR.
Settings (a proposal) are the legacy per-shot ones: libx264 `fast` at CRF 18 in
yuv420p on 2 threads, with a 2 s keyframe interval.

x264 runs **sliced threads**. Its default frame threading, which legacy used through
`ffmpeg -threads 2`, gave three different outputs in 25 encodes of one synthetic
segment in a session pod. Sliced threads gave one. The encoder settings, the thread
count and mode, and the encoder build (the PyAV and libavcodec versions) are segment
key inputs. Encoded bytes may still differ between builds and are never compared
across builds; tests compare decoded frames. One test checks that the same frames give
the same bytes within one build. The build string covers the PyAV wheel, which bundles
FFmpeg and x264; a PyAV built from source against another x264 is not supported.

`splice` copies each segment's packets into one MP4, each shifted by the frames before
it. Nothing is decoded or re-encoded, so the film decodes to exactly the segments'
frames. Legacy did the same with ffmpeg's concat demuxer and `-c copy`. The splice
enforces these rules:

- A segment that does not hold its board's frames fails `time.conservation`.
- The written film is probed again; it must hold the sum of the boards' frames.
- Segments of another codec, size, pixel format or parameter set fail
  `splice.incompatible`, as does a segment whose packets are not at frame *i* or whose
  first packet is not a keyframe.

What the build tests show, on the four-board fixture (223 frames at 360x640, 9.3 s):

- A second build of the unchanged story renders and splices nothing: 5 hits, and the
  first run's records are read.
- After one board edit, exactly that board renders. The film spliced from the 3 cached
  segments and the new one decodes frame for frame to the same arrays as a full render
  of the edited story in an empty store.
- A reorder renders nothing, and its film decodes to the same frames as a full render.
- Every decoded frame carries its board's key fingerprint and its board frame number,
  in film order.

## Invalidation matrix as tested

`tests/cache/test_invalidation.py` makes each edit on a four-board story:

- B1: layered S2V, speakers `a`, `b` and `c`, with a move, a camera and a sound cue;
- B2: layered I2V with one spoken line;
- B3: silent whole-frame I2V;
- B4: layered S2V, speakers `b` and `c`.

Each test asserts the exact set of keys that change or appear, and that every other
key stays. `ROWS` in the test maps every contract row to its tests, and one test checks
that `ROWS` and the contract's table list the same rows in the same order.

| Row | Keys that change (all others stay) |
|---|---|
| Line text, line added or removed | the take, the track, the speaker's drive, S2V clip and keyed frames, the segment; plus every speaker with a later line when the length changes; every S2V layer when frames change; film, mix, master, proxy, checks. A removed line drops its take, and a speaker left with no line becomes an idle doll layer |
| Line speaker | that take; old and new speakers' layers; the segment; film and mix. Between two slots of one voice: no take or track, but the segment (`talk`), the S2V layers, and the picture outputs |
| Lead or gap | no take (no TTS); the track; speakers after the edit point (all for a lead); the segment; film and mix |
| Tail | inside the frame: nothing; frames change: every S2V layer of the board, the segment, film and mix |
| Hold (silent board) | frames change: segment, film and mix, with the whole-frame clip kept while its requested lengths stay; past 121 frames: the clip too; inside the frame: nothing |
| Reorder boards | film, mix, master, proxy, checks only |
| Add or remove a board | that board's artifacts appear or go; film and mix |
| Method (layer or motion) | the board's clips and segment; film picture, master, proxy, checks (mix stays) |
| Seed | that clip and its keyed frames (the drive track stays); the segment; picture outputs |
| Cast still version | clips and keyed frames made from that still, on every board using it; those segments; picture outputs |
| Board photo version | whole-frame: clip and segment; layered: nothing (Q-03) |
| Layout preset values | segments of boards using the preset; picture outputs |
| Move or camera cue | the segment; picture outputs |
| Sound cue, bed, level, loudness target | mix, master, proxy and checks only |
| Note or title | nothing |
| Story motion style | every layered segment (B1, B2, B4); not the whole-frame B3 |
| A cast slot's voice | that speaker's takes on every board, tracks, her S2V layers, segments of those boards; film and mix |
| Toolchain or profile digest | what that tool made (compositor or encoder: segments; S2V profile: S2V clips and keyed frames; keyer: keyed frames; TTS: everything spoken; splicer: film picture on; mixer: mix on); every `Toolchain` field is changed in turn and changes only what that tool makes |
| Media kind frame size or fps | short to video: every clip, keyed frame and segment, film picture, master, proxy; same aspect: segments only (proposal); another fps is refused |

"Picture outputs" means the film picture, master, proxy and checks; the mix stays.

Where the keys give something other than the table's wording, the tests assert the
keys and the difference is listed here:

- **Picture-only edits** (method, seed, cast still, board photo, layout, cues, motion
  style, picture tools, frame size): the last column says "rebuilt". The mix has no
  picture input and keeps its key; the film picture, master, proxy and checks rebuild.
- **Hold inside the frame:** a hold edit that keeps the frame count changes no key,
  as the tail row says for tails.
- **Media kind change:** the drive tracks and the mix are audio and keep their keys.
- **Cast still version, pre-build column:** "photo inputs marked changed" is the board
  photo's state (story 404's `photo_state`), not a cache key, so it is not tested
  here. A whole-frame board does not draw cast stills; its clip changes only when its
  photo version does (the "Board photo version" row).

## Codes

All are **proposals** of story 380; TIME-11 names no code.

| Code | Status | When |
|---|---|---|
| `cache.key_input_invalid` | invalid | a key input is not a hash, integer, text or finite JSON value; the plan meets an untimed board, an unresolved asset, a missing seed or an unavailable method |
| `cache.entry_invalid` | failed | a completed stage at a key's name is not that key's entry; a renderer or encoder that differs from the key |
| `render.frame_count` | failed | a renderer gave more or fewer frames than the board has |
| `render.frame_invalid` | failed | a frame is not `uint8` RGB of the board's size |
| `splice.incompatible` | failed | segments that cannot share one stream |
| `time.conservation` | failed | TIME-11: segment, board and film frames disagree |

## Proposals beyond the contract

- **Drive track key:** the speaker's own take hashes and starts. Section 4's input,
  "board voice track", would rebuild every speaker on any line edit.
- **Extra segment key inputs:** `talk` (who speaks when, which the envelope alone does
  not say), `set_layer` (set plate, set loop and its phase), `whole_frame_clip` and
  `procedural_stream`.
- **Transcript check key:** also carries the script's hash and the story's ASR
  tolerances, so a script edit that leaves the audio unchanged is checked again.
- **Film picture key:** carries each segment's frame count, for TIME-11 checks.
- **Mix key:** carries each track's line spans, for per-take levels (VOICE-7).
- **Motion style:** an input of every layered segment, because legacy applies idle
  wobble and talk bounce to every placed doll; whole-frame segments do not read it.
- **The voice envelope:** the board voice track's hash, an input of every spoken
  board's segment.
- **Clip profiles:** carry the media kind's aspect and delivery fps, so a media kind
  change regenerates clips and a same-aspect size change does not.
- **Stages and lookup:** stage names `<kind>-<key hex>` with outputs `<kind>` and
  `inputs`; lookups search the current run, then earlier runs.
- **The encoder:** sliced x264 threads, no B-frames, a 48-frame keyframe interval; the
  encoder build is in the key.
- **The key scheme:** `studio.cache-key/v1`, `make_key`'s normalization and its
  identifier refusal.
- **24 fps only** in `MediaFormat`.
- **The I2V chain policy:** a placeholder of whole 121-frame clips until story 427.
