# Deliveries and the phone proxy

`haynes_studio.delivery` (story [381](https://work.haynesnetwork.com/work_packages/381),
epic [372](https://work.haynesnetwork.com/work_packages/372)): the `studio.delivery/v1`
type, delivering a finished master through the store with its phone proxy, and legacy
deliveries mapped read-only from the Wan ledger. Built against
[contract v1](../contracts/studio-contracts-v1.md) section 8 ("Deliveries", the store
layout and publication), with TIME-11 from section 3, on the store and stages of
[store-and-stages.md](store-and-stages.md). Only the `local` store adapter exists; the
NFS adapter and its database ledger are stories
[434](https://work.haynesnetwork.com/work_packages/434) and
[428](https://work.haynesnetwork.com/work_packages/428). Nothing here is installed.

## Modules

| Module | What |
|---|---|
| `delivery.model` | `Delivery` (read-only), media profiles, `proxy_byte_limit` |
| `delivery.validate` | `validate_delivery(document, context=...)` |
| `delivery.media` | `inspect` (the checks below), `make_proxy` |
| `delivery.publish` | `deliver`, `read_delivery` |
| `delivery.legacy` | `legacy_delivery` |
| `delivery.errors` | `DeliveryError` and its codes |

Schema: `src/haynes_studio/schemas/studio.delivery.v1.schema.json`, registered with the
other `$id` schemas and with the contract-example harness (`delivery` is no longer
pending).

## Delivering a master

```python
from pathlib import Path
from haynes_studio.delivery import deliver
from haynes_studio.store import LocalStore

delivery = deliver(Path("job/edit/final.mp4"), store=LocalStore(root),
                   production_id=prd, run_id=run, expected_frames=1087)  # media_kind="short"
```

`expected_frames` is the sum of the run's board frames (TIME-11). The caller needs no
store detail beyond the store object. In order:

1. Arguments are checked (IDs, media kind, frame count, `delivery_id`, `now`); then
   the master is opened once, read-only, and must be a regular file. It is hashed
   through that descriptor.
2. If the run already has a completed delivery, it is returned when it holds this
   master at this frame count and kind, and nothing is written; any other master is
   `store.collision`.
3. The master is checked by decoding it through the same descriptor
   (`/proc/self/fd/<fd>`). Any failure is `delivery.master_invalid`, listing every
   problem, and **nothing is written**.
4. The proxy is encoded into a scratch folder outside the store (`workdir`, else the
   system temporary folder; removed afterwards) and checked the same way, with the
   byte limit. A failure is `delivery.proxy_invalid`; nothing is written.
5. If the master's inode, size or times changed since it was hashed:
   `delivery.master_changed`; nothing is written.
6. The master and the proxy are published (create-only, by content hash, with the
   expected hash), then re-hashed in place (`store.verify`), which is what
   `sha256_verified: true` records.
7. The delivery document is validated, published as a canonical-JSON blob, and the
   stage `delivery` of the run is completed with one record listing `master`, `proxy`
   and `delivery`. The store re-hashes all three before it links the record.

`read_delivery(store, production_id=, run_id=)` returns the completed delivery or
`None`. It re-hashes every file the record lists and refuses
(`delivery.record_invalid`) a stage that is not exactly a master, a proxy and a valid
delivery document naming those two files.

### Checks

Every video and audio frame is decoded; nothing is taken from the header alone.

| Check | Master | Proxy | Source |
|---|---|---|---|
| `container` | MP4 (`ftyp` first, not QuickTime) | same | contract section 8 |
| `streams` | one video, one audio, nothing else | same | proposal |
| `video_codec`, `pixel_format` | H.264, `yuv420p` | same | section 8; `yuv420p` proposal |
| `frame_size` | 1080x1920 (`short`), 1920x1080 (`video`) | 720x1280, 1280x720 | section 3, P-10, P-20; the `video` proxy is a proposal |
| `frame_rate` | 24 fps; frame *i* at *i*/24 s within half a frame | same | section 3; the per-frame check is a proposal |
| `frame_count` | decoded = expected | same | TIME-11 |
| `duration` | video stream = expected/24 s, within half a frame | same | TIME-11 |
| `audio_codec`, `audio_rate` | AAC, 48 000 Hz | same | section 8, section 3 |
| `audio_duration` | expected x 2000 samples, within 1024 | exactly expected x 2000 | TIME-11; the tolerance is a proposal |
| `decode` | every packet decodes | same | section 8 |
| `bytes` | none | under `proxy_byte_limit(frames)` | P-10 |

The audio tolerance: AAC in MP4 records a stream's length at the encoder's
granularity, and the PoC cut its masters with `-t` at 4 decimals; a master made the
PoC's way is a few samples off (`tests/delivery/test_media.py`). One AAC frame (1024
samples, 21 ms) covers it.

### The proxy

libx264 `veryfast`, CRF 23 capped at 2 500 kbit/s with a 5 000 kbit buffer, High
profile, a key frame every 48 frames, `yuv420p`; AAC-LC stereo 128 kbit/s at
48 000 Hz, trimmed or padded to exactly `frames x 2000` samples; `+faststart`.

The cap makes the size rule hold for any picture: video is at most
`(2 500 000 x s + 5 000 000) / 8` bytes, so a 60 s proxy is at most about 20.3 MB with
its audio, under P-10's 25 000 000. `proxy_byte_limit(frames)` is 25 000 000 up to
1440 frames and grows at the same rate per frame beyond (proposal), and the check is
strict (`bytes < limit`). Tests: a 60 s 1080x1920 fixture delivers once per run, and
4 s of noise (which x264 cannot compress) stays inside the bound for 4 s.

## Idempotence, interruption and races

- Same master again: the completed delivery, unchanged; no store call at all.
- Interrupted at any of the 28 store steps (three blobs, then the record): no
  delivery until the record's `link()`, then a complete one. Leftovers are orphan
  blobs and `.part` files, which no reader trusts and `store doctor` lists; nothing
  removes them (D17). Delivering again converges on one complete delivery.
- Two deliveries of one run at once: both may publish blobs; one record wins the
  create-only link. The other returns the winner if it holds the same master, else
  `store.collision`. The record is never changed.

Tests: `tests/delivery/test_deliver.py` (a failure after each step, and two threads in
lockstep at every store check).

## Legacy deliveries

`legacy_delivery(ledger, validation, delivery_id=, run_id=, assets_ref=,
verification_ref=)` maps a recorded `edited_production` ledger (a
`titles/<slug>/evidence*/production.json`, or `LedgerReader.get(...).document`) and its
`validation.json` to a delivery with adapter `legacy_wan_ledger`, `writable: false`, no
proxy and a `legacy_path` instead of a locator. It takes documents only: no runner, no
store, no file access, no write path (a test checks the module's imports and calls).
IDs come from the import map (`delivery_id`, `imported_run_id`).

| Field | From |
|---|---|
| `created_at` | ledger `created_at`, ISO time rounded down to the second |
| `master.sha256`, `bytes`, `legacy_path` | ledger `sha256`, `bytes`, `output` |
| `master.width`, `height`, `fps`, `frames` | validation `width`, `height`, `fps`, `decoded_frames` |
| codecs | Legacy: `poc/edit.py` encodes libx264 and AAC (the file is on the Wan volume, not decoded here) |
| `verification` | validation frames; `sha256_verified` because its hash and size are the ledger's; `source` |
| `legacy` | ledger `id`, `kind`, `preset`, `provenance` verbatim; `assets_ref`; `url` as `poc/deliver.py` printed it |

The ledger is checked as story 425's reader checks an answer
(`adapter.response_invalid`). Evidence for another file, a failed or incomplete
validation, or a frame size that is no media kind is `delivery.legacy_mismatch`. The
four Winter Menu ledgers map; r4 is the contract's
[example](../contracts/examples/valid/delivery-legacy-r4.json) exactly.

## Codes

| Code | Status | Source |
|---|---|---|
| `store.collision` | failed | contract section 8: the run is delivered with another master, frame count or kind |
| `delivery.master_invalid` | invalid | **proposal**: the master failed a check; nothing written |
| `delivery.proxy_invalid` | failed | **proposal**: the proxy failed a check |
| `delivery.master_changed` | failed | **proposal**: the master changed while it was checked |
| `delivery.not_verified` | failed | **proposal**: a published file did not re-hash |
| `delivery.record_invalid` | invalid | **proposal**: a `delivery` stage that is not a delivery |
| `delivery.legacy_mismatch` | invalid | **proposal**: a ledger and its evidence disagree |

The validator uses the contract's codes: `schema.*`, `id.*`, `store.locator_invalid`.

## Proposals beyond the contract

- The delivery document is a JSON blob in the production's folder, listed with the
  master and proxy in one record of stage `delivery`; one delivery per run.
- Schema shape per adapter: a studio delivery is writable, has a proxy, locators only
  and `verification.proxy_under_bytes`; a legacy one is read-only, no proxy, a
  `legacy_path` and `verification.source`. `sha256_verified` is always `true`.
- Locators of one delivery are in one production's folder, never the library.
- `media_type` is `video/mp4`; master and proxy carry `width`, `height` and `fps`.
- `created_at` to the second; the `video` proxy 1280x720; the limit beyond 60 s;
  the encoder settings; `yuv420p`; one video and one audio stream; the per-frame and
  audio tolerances; the scratch folder for the proxy.
- `store.adapter` for another store comes from its `adapter` attribute (`nfs` for
  story 434).

## Limits

- The master is checked and published through one descriptor; a change in place that
  keeps its size and times between the hash and the publication is caught by the
  store's expected-hash check, not before.
- The proxy needs a few seconds of CPU per minute of video at 2 threads (about 11 s for
  60 s of the synthetic fixture in a session pod; real pictures cost more).
- A legacy delivery's codecs come from the PoC's encoder settings, not a decode.
