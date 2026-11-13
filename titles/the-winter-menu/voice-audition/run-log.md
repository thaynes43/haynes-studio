# The Winter Menu: voice audition 1

Story [840](https://work.haynesnetwork.com/work_packages/840) (E1.16), epic
[372](https://work.haynesnetwork.com/work_packages/372). Tom ruled on 2026-11-13 that the
Winter Menu's voices "were not very good" and asked for better ones: other Kokoro stock
voices and settings, and other local TTS models (comment 7995 on
[372](https://work.haynesnetwork.com/work_packages/372)). This run is the first half (Kokoro)
and the desk review for the second half ([desk-review.md](desk-review.md)).

- **Run:** 2026-11-13, 19:11 to 19:30 UTC for the audition and delivery, by the dev-env
  agent session `haynes-studio-1113-190947` (Claude Code, `claude-opus-5-5`), a worker for
  the E1 coordinator.
- **State:** delivered privately and tested. **Tom's verdict: pending** (recorded below
  when he gives it).
- **Job directory:** `~/studio-jobs/the-winter-menu-voice-audition-1` (new, on the session
  volume; every take and reel is also on the Wan PVC through the deliveries).

## The reels

One reel per cast slot. Each opens on a card naming the doll and the six candidates; then,
for each candidate, an announcer (`am_michael`, a male voice no doll uses) says its number
and name, and the candidate speaks that doll's r4 lines. Candidate 1 is always the r4 voice.
The card on screen names the voice ID. Answer per slot with a voice ID, for example
"B: af_sarah". Links open on the home network only.

| Slot | Doll | Link | Ledger ID | Length | Candidates (1 = current) |
|---|---|---|---|---|---|
| A | the captain | <https://video.haynesops.com/videos/f44c2341ede047438a94064151c576d0/file> | `f44c2341ede047438a94064151c576d0` | 77.4 s | bf_emma, bf_isabella, bf_lily, bf_alice, af_kore, af_aoede |
| B | the chair | <https://video.haynesops.com/videos/a5cabedce555430bac13ee30a5265a81/file> | `a5cabedce555430bac13ee30a5265a81` | 53.9 s | af_heart, af_nova, af_alloy, af_sarah, af_river, af_kore |
| C | the grudge holder | <https://video.haynesops.com/videos/453e297a30754b10878afd97489e76a2/file> | `453e297a30754b10878afd97489e76a2` | 73.6 s | af_nicole, af_sarah, af_jessica, af_aoede, af_alloy, af_river |
| D | the cheerful one | <https://video.haynesops.com/videos/0937643ac4524b3a836ba56b91015b98/file> | `0937643ac4524b3a836ba56b91015b98` | 44.6 s | af_bella, af_sky, af_jessica, af_kore, bf_lily, af_heart |

Lines per slot (r4 script, [`manifest-r4.json`](../manifest-r4.json), verbatim): A lines 1
and 4; B line 2, "Motion carried." (8) and "Needs salt." (9); C lines 3 and 6; D line 5 and
"Nay!" (8). Records: [`takes.json`](takes.json) (every take), [`reels.json`](reels.json)
(every reel, its order, checks and delivery), [`voices.json`](voices.json) (the service's
voice list). Scripts: [`tools/`](tools/).

## Steps

Times are UTC on 2026-11-13.

### 0. Set up: **Proven**

- 19:11:55 claimed story 840. `UV_PYTHON_DOWNLOADS=never uv sync --locked --python 3.11` in
  the worktree: 8.5 s. `mkdir ~/studio-jobs/the-winter-menu-voice-audition-1` (new).
- Service check: `kubectl get deploy -n ai kokoro whisper wan-video`, all 1/1. Kokoro runs on
  `talosm01` (not the studio's 3090s), image
  `ghcr.io/flight777/kokoro-wyoming-ml@sha256:46418df6...`, 4 GiB memory limit.

### 1. Voice list: **Proven**

19:15:12, the runbook's stage 3 `Describe` snippet, changed only to print the whole `Info`
event. **54 voices**, the same count as 2026-11-03: 20 American English (11 female), 8
British English (4 female) and 26 in other languages. The list as reported is in
[`voices.json`](voices.json).

### 2. What settings the service offers: **Changed**

The plan allowed the default speed and up to two other settings. Reading the server
(`/app/main.py` in the pod, read-only) showed there are none per request:

- speed is one server-wide value, `KOKORO_SPEED=1.0`, read at start;
- the server uses only the voice name from a request (language and speaker are ignored;
  the accent follows the voice ID's first letter);
- an unknown voice name silently falls back to `af_heart`;
- no voice blending.

So every take is at speed 1.0, and the audition covers voices only. A speed or style
setting needs a haynes-ops change (held question Q-840-02 in the PR).

### 3. First live use of the story 425 clients: **Proven**

19:19:10, `KokoroClient(SubprocessRunner())` and `WhisperClient(SubprocessRunner())`, their
first run against the live services. One take, `af_heart` with "Winter's coming. We need to
discuss the menu.": 0.44 s TTS, 0.33 s transcript, and **byte-identical to the r4 take**
(SHA-256 `7d5d2d89...` in [`evidence-r4/speech.json`](../evidence-r4/speech.json)). Kokoro
is deterministic: the same voice and text give the same bytes. Neither client needed a
change.

### 4. Shortlist and plan

`python tools/plan.py $JOB titles/the-winter-menu/manifest-r4.json` wrote 82 takes: 54 lines
(6 voices per slot, the r4 voice first) and 28 labels (an intro per slot, one label per
candidate). The shortlists use all 11 female English voices not cast in r4, plus one
cross-cast (`af_heart` for D). Grades are from Kokoro's
[VOICES.md](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md), read 2026-11-13.

### 5. Takes: **Proven**

`OPENBLAS_NUM_THREADS=2 .venv/bin/python tools/take.py $JOB run`, 19:19:16 to 19:20:25, one
request at a time: each take is one TTS call, the WAV written create-only, a decode check
(header, a full PyAV decode, level), its duration, then one transcript call. TTS took 0.27
to 0.49 s and the transcript 0.23 to 0.37 s per take; about 0.85 s per take with
`kubectl exec`. No service error.

### 6. Checks, failures and retries: **Changed**

| What happened | What was done |
|---|---|
| 8 line takes failed the transcript check: `af_nova` line 2 ("Winter is coming") and "Needs salt." ("Nades Salt"); `af_alloy` "Needs salt." ("Nades salt."); `af_river` "Motion carried." ("Motion carried a") and "Needs salt." ("Nade Salter."); `af_jessica` line 5 ("limited editions") and "Nay!" ("Nairo."); `bf_lily` "Nay!" ("Yeah."). | Left out of the reels, named on the candidate's card, listed in `takes.json`. One retry (`af_nova` "Needs salt.") gave the same bytes, so retrying a deterministic take is pointless; no other line was retried. |
| The label "Six." was heard as "Zix" or "Zexo" four times out of four. | Each six-label got its one retry, re-worded "Number six. <name>."; all four then read as "Number 6". |
| Two takes stopped at a clip rule the worker added (peak at full scale): `bf_isabella` line 1 (2 samples) and `af_jessica` line 3 (1 sample). | The story's checks are decode, duration and transcript; a 1 to 2 sample peak is a level fact. Each was transcribed once (passed) and is kept with a `full_scale_samples_warning`. The reel mix lowers both takes to -22 dBFS RMS. |
| "Needs salt." heard as "Need salt." for `af_heart`, `af_sarah`, `af_kore`. | Declared as a recognizer spelling: the same `af_heart` bytes were heard that way in r2, r3 and r4. |
| Label names heard as other words: Isabella "Is Abella", Kore "Core"/"Corn", Aoede "AULED"/"Ayuled"/"Ayulid", Doll "Dahl"/"Dal". | Declared as recognizer spellings for labels only; each is listed with its reason in `takes.json`. |
| The worker's first duration bound (words per second) counted "can't" as two words and failed three good takes. | Replaced before any reel: a line must last 0.5 to 2 times the r4 take of the same line. No take fails it. |

Final: **74 of 82 takes passed**, 8 failed (all transcript, all voices graded C or lower).
Requests: **87 TTS and 96 transcript** (87 for takes, 9 for reels) of 150 each.

### 7. Reels: **Changed**

`OPENBLAS_NUM_THREADS=2 nice -n 10 .venv/bin/python tools/reel.py $JOB $JOB/takes-2.json <slot> . titles/the-winter-menu/voice-audition/reel-<slot>.manifest.json <build>`,
about 7 s per reel. Each take at -22 dBFS RMS with 5 ms edges, then -20 LUFS and a limiter
1 dB under -3.5 dBTP (the r4 mix), 48 kHz; one still card per candidate at 720x1280, 12
fps, H.264 CRF 18 and AAC 192 kbit/s, 2 threads.

Nine builds for four reels; only the last build of each was delivered:

1. `reel-a` (19:25): valid, but the whole-reel transcript heard "Kore" as "Corn", so the
   gate refused it.
2. `reel-a2`, `reel-b`, `reel-c`, `reel-d` (19:26): pictures from ffmpeg's concat demuxer
   came out 7 to 17 frames short of the timeline in B to D, and the whole-reel transcript
   kept spelling names a new way.
3. `reel-a3`, `reel-b2`, `reel-c2`, `reel-d2` (19:28): frames piped to x264 as `poc/edit.py`
   renders (exact frame count), a check that each card sits in its own interval, and one
   rule for the whole-reel transcript: word for word, except where a label says a voice name
   or "Doll". All four passed every check.

Reel D: `af_jessica` has no passing take, so her card shows silently for 3.5 s and her label
is not played.

### 8. Delivery: **Proven**

`cd poc && ../.venv/bin/python deliver.py ../titles/the-winter-menu/voice-audition/reel-<slot>.manifest.json --out reel`,
19:29:13 to 19:29:56, about 7.5 s each. Before that, read-only: 25.9 GiB free on the Wan PVC,
and none of the four production names in use; and a local dry run of `deliver.py`'s asset
list and `check_ledger`. After each: `LedgerReader.get` (story 425) read the ledger back,
and a GET of `127.0.0.1:8080/videos/<id>/file` inside the API container answered 200
`video/mp4` with the ledger's bytes and SHA-256. `LedgerReader.list` then found no unreadable
ledger among the 78 files in `/workspace/jobs`. New production folders:
`productions/the-winter-menu-voices-1-{a,b,c,d}/`; nothing existing was touched.

Two things the route writes that do not fit a reel: the ledger's `preset` is
`rigid-doll-dialogue-manifest`, and its `provenance.records` reads `haynes-studio
titles/voice-audition/` (the script takes the manifest's folder name). The reel manifests
carry `provenance.takes` with the right path.

### 9. Desk review: **done**

[desk-review.md](desk-review.md): 21 local models that pass the stock-voice rule and 12 that do
not, with needs, voices, licence facts and how each would be reached. It recommends **Phonon
31m English** (CPU, Apache-2.0, 13 English female presets, ranked above Kokoro in an
independent arena) and **Qwen3-TTS 1.7B VoiceDesign** (GPU, Apache-2.0, per-line delivery
instructions and per-request speed, voices from descriptions that may drift), with what a
haynes-ops change for each would add. Researched by a subagent; the worker re-read the
primary pages for both picks and the ranking.

## Hand work

- Reading the Kokoro server source to learn what a request can set (about 5 minutes).
- Choosing the shortlists from the model card's grades and the brief; no listening.
- Five decisions on failed checks (table in step 6), each recorded with its reason.
- Two rebuilds of the reels to fix the picture timing and the whole-reel transcript rule.

## Shortlist (worker's notes, not Tom's verdict)

From the model card's grade, the accent, and measured median pitch and pace (per take in
`takes.json`); the worker did not listen. "Pace" compares a take's length with the r4 take
of the same line.

- **Overall.** The four r4 voices are Kokoro's highest-graded female English voices (A to
  B-). Every other is graded C+ or lower; the eight failures all came from C or D voices, and
  in reels B and D `af_nova`, `af_alloy`, `af_river`, `af_sky` and `bf_lily` take 1.2 to 1.6
  times as long as the r4 voice on the same lines, which the server's single speed cannot
  correct. So Kokoro can change casting, not raise
  quality; a better engine is the second half of this work ([desk-review.md](desk-review.md)).
  The voices that passed every take at about r4 pace are `af_kore` (7 of 7), `af_sarah` (5
  of 5) and `af_aoede` (4 of 4).
- **A, the captain:** `bf_emma` (B-, British, 185 Hz) is the reference. `bf_isabella` (C)
  keeps the British accent at a higher pitch (216 Hz). `bf_lily` and `bf_alice` (D) are the
  other British voices, higher (210, 235 Hz) and 10 to 19% slower. `af_kore` (C+) is the
  lowest here (157 to 168 Hz) at Emma's pace, a steadier leader. `af_aoede` (C+) is 5 to 7%
  quicker than Emma.
- **B, the chair:** `af_heart` (flagship) is the reference. `af_kore` and `af_sarah` (C+)
  keep Heart's pace, Kore about 30 to 40 Hz lower, and passed all three lines. `af_alloy` (C) is
  the lowest female voice heard (152 Hz) and slow, the flattest option; its "Needs salt."
  failed. `af_nova` and `af_river` (C, D) each failed two lines and play one.
- **C, the grudge holder:** `af_nicole` (B-) is the slowest and lowest here (154 to 162 Hz).
  `af_alloy` (C) is as low (148 to 150 Hz) with Nicole's pace on line 3, a cool option.
  `af_sarah` and `af_aoede` (C+) take 28 to 38% less time than Nicole, a sharper accusation.
  `af_jessica` and `af_river` (D) are quicker, low-grade options.
- **D, the cheerful one:** `af_bella` (A-) is the reference. `af_heart` (flagship) is the
  only top-grade alternative, near Bella's pace; casting her here needs a new voice for B.
  `af_kore` (C+) matches Bella's pace, lower (189 Hz). `af_sky` (C-) and `bf_lily` (D) are
  1.4 to 1.6 times slower; Lily's "Nay!" failed. `af_jessica` failed both lines.

## For the stock-voice list (story 405)

The recorded list (`STOCK_VOICES` in `src/haynes_studio/library/model.py`, not edited here)
holds `af_bella`, `af_heart`, `af_nicole`, `am_puck` and `bf_emma`. A voice Tom picks from
this audition must be added before the library or a voice job accepts it
(`voice.not_stock`). Candidates auditioned and not yet recorded: `af_alloy`, `af_aoede`,
`af_jessica`, `af_kore`, `af_nova`, `af_river`, `af_sarah`, `af_sky`, `bf_alice`,
`bf_isabella`, `bf_lily`. All 54 voices in `voices.json` are the server's stock voices.

## Tooling notes

- The Kokoro server cannot take a speed per request, and it hides an unknown voice by
  falling back to `af_heart`. A voice job should check the answer's voice, or the server
  should refuse unknown names.
- Kokoro is deterministic, so a retry after a transcript mismatch is wasted; the job should
  retry only transport errors.
- The transcript check cannot judge proper names (voice names); labels need a name-position
  rule like the reels'.
- `poc/deliver.py` assumes a doll short (its `preset`, its `records` path and its fixed
  asset names); a delivery for other media needs its own fields.
- ffmpeg's concat demuxer drops frames on still cards; piping exact frames is reliable.

## Budget

18 minutes from claim to the last delivery, inside the 3 h cap; the desk review ran alongside
(about 16 minutes) and was checked afterwards. 87 TTS and 96 transcript
requests of 150 each, one at a time. Session CPU at 2 threads (`OPENBLAS_NUM_THREADS=2`,
ffmpeg and x264 at 2 threads, `nice -n 10`). No 3090 time, no ComfyUI, no paid inference.
The job directory holds 293 MB.

## Tom's verdict

Pending. To be recorded here word for word, separately from the checks above.
