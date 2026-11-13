# The film's sound and its master

`haynes_studio.mix` (story [841](https://work.haynesnetwork.com/work_packages/841), split
from story [406](https://work.haynesnetwork.com/work_packages/406), epic
[372](https://work.haynesnetwork.com/work_packages/372)): the mix as a pure function of
its cache key, a placement record, the master (the film picture and the mix in one
MP4), sound checks as data, and both artifacts as completed stages found again by
their keys. Built against [contract v1](../contracts/studio-contracts-v1.md) sections 3
(TIME-7, TIME-10, TIME-11, TIME-12), 4 and 6, and VOICE-7. It is ported from the legacy
mixer in `poc/edit.py` (`audio`, `levels`, `mux`, `validate`).

**State: source and tested with synthetic audio and picture only.** No voice, sound or
service is called. Generating voices and sounds, the transcript check, the proxy and
delivery, and the run itself are other stories (405, 406, 381).

## Modules

| Module | What |
|---|---|
| `mix.mixer` | `mix(document, read)`: the mix of a mix key document; `MixerSettings` and `MIXER`; `planned_starts` |
| `mix.master` | `mux(picture, mix_wav)`: the master, checked with story 381's `inspect`; `MuxSettings` and `MUX` |
| `mix.checks` | the sound checks, their thresholds and `check_result_key` keys |
| `mix.build` | `SoundBuilder` (a `plan_story` content source), `film_sound`, `board_ranges`, `check_cues`, `label_placement`, `store_reader`, `sound_toolchain` |
| `mix.audio` | decoding, libavfilter graphs at two threads, the R128 meter, 24-bit WAV |
| `mix.errors` | `MixError` and the codes below |

## How a run calls it (story 406)

```python
from haynes_studio.cache import ArtifactCache, plan_story
from haynes_studio.cache.build import PictureBuilder
from haynes_studio.mix import SoundBuilder, film_sound, sound_toolchain

cache = ArtifactCache(store, production_id=prd, run_id=run, earlier_runs=earlier)
sound = SoundBuilder(cache, story=story, upstream=adapters)  # takes, clips, proxy, ...
picture = PictureBuilder(cache, renderer, upstream=sound)
plan = plan_story(story, voices=voices, blobs=blobs, voice_ids=voice_ids,
                  toolchain=sound_toolchain(toolchain), media=media, content=picture)
result = film_sound(story, plan, sound)   # mix, master, placement, checks
result.ensure_passed()                    # or record result.checks and decide
```

- `sound_toolchain` puts this mixer's version and these mux settings in the toolchain;
  a key that names another mixer or mux is `cache.entry_invalid`, as story 380's
  builder does for a compositor or encoder.
- The plan asks for the film picture first, then the mix, then the master. Picture
  keys never take a sound input, so a mix-only edit renders and splices nothing.
- With `story` given, every sound cue is checked against its own board before
  anything is mixed: a cue outside its board is `cue.out_of_range` with no mix and no
  master. A missing input is the store's `store.blob_missing`, also before any mix.
- Inputs are read by hash: voice tracks from the production's folder, sounds and beds
  from it or the library (`store_reader`), each re-hashed as read.
- `film_sound` returns `FilmSound`: the cached mix and master, the run's placement
  record with the story's identifiers, and seven `CheckResult`s. It finds everything
  by key, so after the plan it makes nothing new except check results.

## The mixer

`mix(document, read)` takes the document `cache.keys.mix_key` made and nothing else.
Every number is in `MixerSettings`; its `version()` (`studio.mixer/1:<16 hex>`, a
digest of every setting and the filter build) is the key's `mixer` input, so changing
any number is a new mix (section 4: "mixer digest, including its fades").

| Step | What | Numbers (samples at 48 kHz) | Source |
|---|---|---|---|
| 1 | Each board voice track (16-bit mono PCM, VOICE-2) is cut at each line's span on the board clock, `[start_ms * rate div 1000, end_ms * rate div 1000)` | 24 per ms at Kokoro's 24 kHz | VOICE-2, the key's line spans |
| 2 | The line goes to 48 kHz stereo (libswresample; mono is upmixed at -3 dB) and is fitted to exactly `(end_ms - start_ms) * 48` samples | 24 kHz to 48 kHz is exact; another rate is trimmed or padded with silence | legacy `read_audio` |
| 3 | Line level: scaled so its RMS over both channels is `line_rms_dbfs` | -22 dBFS on every r4 story; RMS floor 1e-8 | VOICE-7, legacy `edit.audio` |
| 4 | Line fades, linear, at each edge | 5 ms = 240 | section 6 |
| 5 | Line placed at `F[k] * 2000 + start_ms * 48` | exact integers | TIME-7 |
| 6 | Sound decoded to 48 kHz stereo, trimmed to `[from * 48, to * 48)` | a trim past the sound's end is refused | section 6, legacy `edit.audio` |
| 7 | Sound level: RMS of the trimmed sound to `level_rms_dbfs` | | section 6 |
| 8 | Sound fades, linear | in 10 ms = 480, out 50 ms = 2400 (a sound shorter than 2400 is refused) | section 6 |
| 9 | Sound placed at its `start_sample`; past the film's end it is cut there, not faded, and the cut recorded | | TIME-10 |
| 10 | Bed: RMS to its level, looped under the whole film, each copy crossfading linearly into the one before | crossfade 1 s = 48 000 (a bed of 96 000 or fewer is refused) | section 6, legacy `edit.audio` |
| 11 | Bed fade in, linear | 0.5 s = 24 000 | section 6 |
| 12 | Headroom: if the peak is over 0.5, the whole mix is scaled to a peak of 0.5 | | legacy premaster step |
| 13 | Loudness: integrated loudness measured (libavfilter `ebur128`, BS.1770 gated), then `volume` by `master_lufs - measured` dB | -20 LUFS on every r4 story; a silent programme gets 0 dB | VOICE-7, legacy `levels` |
| 14 | Limiter: `alimiter`, limit `10^((true_peak_dbtp - 1) / 20)` to 4 decimals, attack 2 ms, release 60 ms, no auto-level, delay compensated (`latency=1`) | r4: limit 0.5957 for -3.5 dBTP | VOICE-7, legacy `audio` (latency: proposal) |
| 15 | Output: 48 000 Hz stereo 24-bit PCM WAV of exactly `frames * 2000` samples | | TIME-11, legacy `soundtrack.wav` |

The filters run in one libavfilter graph each, held to two threads. Accumulation is
float32, as legacy; the output is rounded to the nearest 24-bit code. The same key
gives the same bytes within one build.

### Worked example: r4 board 8

Board 8 starts at film frame 728 (section 3's table). Line 5, "Motion carried.", spans
6551 to 7575 ms on the board clock:

- Start: `728 * 2000 + 6551 * 48 = 1 456 000 + 314 448 = 1 770 448` (36.884 s).
- End: `728 * 2000 + 7575 * 48 = 1 819 600` (37.908 s); the line is
  `1024 * 48 = 49 152` samples, its take's 24 576 samples at 24 kHz doubled.
- Fades: samples 1 770 448 to 1 770 687 rise from 0, and 1 819 360 to 1 819 599 fall
  to 0.

The gavel cue is anchored 50 ms after that line: `7575 + 50 = 7625` ms, so
`728 * 2000 + 7625 * 48 = 1 822 000` (37.958 s, the contract's example). Its trim
`[1300, 1950]` ms takes source samples 62 400 to 93 599 (31 200 samples), so it is
placed at 1 822 000 to 1 853 200 (38.608 s), fading in to 1 822 479 and out from
1 850 800. The recorded timeline says 36.884 to 37.908 for the line and 37.958 to
38.608 for the gavel.

### Cross-check against the r4 timeline

`tests/mix/test_r4.py` plans the imported r4 story (story 404) with the library's
facts (story 382) and compares the mix key's placements with
`titles/the-winter-menu/evidence-r4/timeline.json`, from public text only: 9 shots'
frames exact and starts exact at 4 decimals; 13 lines within 0.333 ms at the start and
0.667 ms at the end; 4 sounds within 0.333 ms at both ends; the bed's end within 1 ms
(TIME-12 allows 1 ms).

## The placement record

Each mix has a placement record (`studio.mix-placement/v1`, a proposal), cached with
it as kind `mix_placement` under the mix key's own inputs, so it is found exactly when
the mix is. It holds no identifiers: lines by track and line index, sounds and beds by
index. For each line: its track's hash, `start_frame`, `board_start_ms` and
`board_end_ms`, `start_sample`, `end_sample`, level and the gain applied (dB). For each
sound: hash, start and end sample as placed, its length after trim, the source's
length, the trim, `cut_at_film_end` and `cut_samples`, level and gain. For each bed:
hash, 0 to the film's last sample, the source's length, the copies looped, level and
gain. Then the premaster peak, the headroom step (dB), the measured loudness before
the gain, the master gain and the limiter's settings: what legacy `timeline.json`
recorded as `audio`, `premaster_headroom_db` and `master_gain_db`.

`label_placement(story, document, record)` adds `board_id` and `line_id` to each line,
`board_id` and `cue_id` to each sound, `bed_id` to each bed, and every board's film
range: the run's record, as `film_sound` returns it.

## The master

`mux(picture, mix_wav)`:

- The film picture's H.264 packets are copied as they are (no decode, no re-encode),
  so the master decodes to exactly the film picture's frames.
- The mix is encoded as AAC-LC stereo, 48 000 Hz, 192 kbit/s (legacy `mux`), in
  1024-sample frames from sample 0.
- The MP4 is written with `+faststart` (legacy) and a movie timescale of 48 000
  (proposal), so the audio's recorded length is exactly `frames x 2000`. At the
  muxer's default timescale of 1000 the edit list rounds it down to a whole ms: 32
  samples short at 223 frames, as the PoC's masters were.
- Before the master is returned it is checked with story 381's `inspect` at the
  picture's own size: one video and one audio stream, H.264 `yuv420p`, AAC 48 kHz,
  24 fps, decoded frames equal the picture's, audio within one AAC frame, continuous
  from 0, every packet decodable. A mix whose length is not the picture's frames x
  2000 is refused before muxing (`time.conservation`). A master that fails is never
  cached.

`MuxSettings.key_inputs()` (container, video copy, codec, bit rate, layout, rate,
faststart, movie timescale, threads and the encoder build) is the master key's `mux`.

## Sound checks

Each check is a cached artifact keyed by `check_result_key(artifact, check, version,
thresholds)`. The thresholds carry the story's targets and the film's length, so a
result is a pure function of its key. The version is `1/<filter build>`, because
another meter build can read a programme slightly differently; the tolerances are far
wider than that. Results are `studio.check-result/v1` JSON (a proposal) with
`measured` and `passed`; a failing check is data, and `FilmSound.ensure_passed()`
raises `mix.check_failed` naming each one.

| Check | On | Passes when | Source |
|---|---|---|---|
| `mix.length` | mix | 48 000 Hz, 2 channels, 24-bit, exactly `frames x 2000` samples | TIME-11 |
| `mix.loudness`, `master.loudness` | mix, master (decoded AAC) | integrated loudness within 1.5 LU of `master_lufs` | legacy `validate`: `abs(I - lufs) <= 1.5` |
| `mix.true_peak`, `master.true_peak` | mix, master | true peak at most `true_peak_dbtp + 1` dBTP | legacy `validate`: `-2.5` at r4's `-3.5` (kept relative: proposal) |
| `mix.clipping`, `master.clipping` | mix, master | no sample at full scale | legacy `validate`: `abs(a) >= 1` on the master |

The master's frame count and audio length are checked when the master is made (above),
so a master that exists has passed them. The transcript check is story 406's.

## Through the cache

| Artifact | Stage | Outputs | Made by |
|---|---|---|---|
| Mix | `mix-<key hex>` | `mix` (`audio/wav`), `inputs` | `SoundBuilder.mix` |
| Placement record | `mix_placement-<hex>` | `mix_placement` (`application/json`), `inputs` | with the mix, committed first |
| Master | `master-<key hex>` | `master` (`video/mp4`), `inputs` | `SoundBuilder.master` |
| Check result | `check_result-<key hex>` | `check_result` (`application/json`), `inputs` | `SoundBuilder.checks` |

What the tests show on story 380's four-board fixture (223 frames, 9.3 s) with real
synthetic voice tracks, a sound cue and a bed:

- The first build mixes once and muxes once; the master passes `inspect` at 223
  frames with exactly 446 000 recorded audio samples, and every sound check passes.
- A second build of the unchanged story mixes, muxes, renders, splices and checks
  nothing: every key is a hit.
- An edit of a cue's level or anchor, the bed's level or the loudness target changes
  the mix, master, proxy and check keys and nothing else; no segment renders and the
  film picture is not spliced again.
- A cue outside its board, or a sound not in the store, fails with no mix, placement
  or master stage.

## Codes

| Code | Status | When |
|---|---|---|
| `cue.out_of_range` | invalid | contract TIME-10: a sound starts outside its board (with the story) or the film |
| `time.conservation` | failed | contract TIME-11: a line runs past its board or the film, the story's boards and the mix key disagree, the mix is not the picture's frames x 2000, the master does not hold them |
| `mix.input_invalid` | failed | **proposal**: a track that is not 16-bit mono PCM, a span outside its track, a trim past a sound's end, a sound shorter than its fade out, a bed too short to loop, an undecodable input, a key for another mixer |
| `mix.master_invalid` | failed | **proposal**: the master fails another of story 381's checks, or the mix is not 48 kHz stereo |
| `mix.check_failed` | failed | **proposal**: `ensure_passed` on a failed sound check |

The store's and the cache's own codes pass through: `store.blob_missing`,
`store.hash_mismatch`, `cache.entry_invalid`.

## Proposals beyond the contract

- The limiter's delay is compensated (`latency=1`). Legacy left `alimiter`'s 2 ms
  look-ahead in, which delays the whole soundtrack by 95 samples against the picture
  and loses its last 95 samples; TIME-7 placements hold only without it.
- A sound cut at the film's end is cut exactly there (TIME-10), not 100 ms later.
- Fades shorter than a line are clipped to the line; a sound shorter than its 50 ms
  fade out and a bed of 2 s or less are refused (legacy crashed or asserted).
- A silent programme gets no loudness gain (legacy would divide by nothing).
- The mix is 24-bit PCM with no intermediate 16-bit premaster file.
- Line levels are measured on the line's span, so up to one ms of silence after the
  take counts (under 0.002 dB on a one-second line).
- The placement record, its cache kind and its schema; the check result schema; the
  true-peak margin as `+1 dB` of the target; the movie timescale; the mux settings as
  a key input; `mix.input_invalid`, `mix.master_invalid`, `mix.check_failed`.

## Limits

- Loudness is read by libavfilter's `ebur128` meter, not `loudnorm`'s first pass as
  legacy did; both implement BS.1770, and the checks' tolerances are 1.5 LU.
- Each line is resampled in its own filter graph; the meter and the limiter each run
  once over the whole film. A synthetic mix shaped like r4 (1087 frames, 13 lines in 8
  tracks, 4 sounds, a 12 s bed) took 0.31 s of wall time and 0.31 s of CPU in a session
  pod, with 195 MB peak memory for the process.
