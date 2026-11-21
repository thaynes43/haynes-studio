# One More Meeting workflow proof

[Studio work order](https://work.haynesnetwork.com/work_packages/942) ·
[Winter Menu recovery evidence](../the-winter-menu/e1-build/recovery-20261121/README.md)

Source was `a01d0eeb6dcf78a072f66794e61beb310921a66a`. Studio `0.1.0.dev0` used the
locked packages with Python 3.11 in the session and Python 3.12.16 on the render
worker. The lock bytes and the measured keyer and toolchain digests matched across
both environments. The worker used its installed dependencies and the pinned Studio
source, with one worker at low priority and two threads. The new store and Wan
journal started on the session's local filesystem.

## Winter Menu archive — Proven

Copied the approved quieter-gavel master and proxy, the historical run, the original
recovery delivery record and the exact recovery ledger from the existing Wan production.
The committed recovery receipt supplied the expected sizes and full hashes for all five
files before the copy. An independent process reopened every file on the canonical NFS
share and matched all five SHA-256 hashes and sizes, 73,638,915 bytes in total. Its JSON
read-back matched the original run, delivery and recovery ledger. The preserved delivery
record is the recovery record described in story 941.

The archive used an exclusive new directory and fsynced each file before making its
final name with an exclusive hard link. The production location, identities and
read-back are recorded in [story 942](https://work.haynesnetwork.com/work_packages/942).
This was a storage copy of the cut Tom had already approved.

## Inputs, voice and gate — Proven

Imported five blobs read-only using Studio's ledger and volume readers. The package
published and re-hashed them in the new production scope. The inputs were the chair
cutout, the campsite plate, the decal-ready chair loop, the campsite loop, and the
chair's green-screen start image. Their source hashes and sizes are in the run evidence.
Studio's package minted new production, story and board identities and validated the
[manifest](manifest.json). The stock voice was present in the installed Kokoro service.

`studio voice` made two sequential takes in 1.33 seconds, measured at 2,432 ms and
2,816 ms. An early service dry run stopped locally because the reference draft had an
empty seed map. We set the proven chair seed 501, then adjusted the tail from 1,000 ms
to 1,250 ms to put the measured cut over eight seconds. The existing takes remained
current. The final service dry run passed four mix checks and planned 196 output frames
and exactly one 576×1024 S2V clip, requesting 154 source frames in two chunks.

The live probe showed an accepting API, no active or queued work, and both pinned GPUs
idle at 51 °C and 49 °C. The journal and its lock were unused. The deployed API matched
the current GitOps source, including its stricter check for unknown queue work. Story
942 records the checkpoint before the service phase.

## Build and delivery — Proven

The Studio service phase submitted and collected one clip through the Wan lease.
It took 481.90 seconds wall, including 478.9 seconds of engine render and a
0.4-second cool-idle gate. The original Wan job record matched the clip record's
graph hash and byte count on a separate read. The clip held 158 frames at 16 fps.
The composite used 131 source frames for the final 196 frames at 24 fps.

A hash-checked cache transfer put the clip and inputs onto the render worker.
The first offline run assembled the master in 106.46 seconds and reached the
expected `build.offline_missing` at the transcript check. Keying took 22.66 seconds
and the composite and encode took 81.45 seconds. The decal track passed with a
minimum correlation of 0.986 against a floor of 0.8, with zero failed frames.

After transferring the new cache files back, a fresh Studio dry run showed zero Wan
requests. The service phase made one ASR request, matched the normalized script
exactly and left the Wan journal byte-identical. The transcript result went back to
the render worker. The second offline run succeeded and verified the delivery in
3.66 seconds. The master measured −20.033 LUFS and −4.524 dBTP with zero clipped
samples. Both the 1080×1920 master and 720×1280 proxy decoded to exactly 196 frames
at 24 fps (8.167 seconds).

## New archive — Proven

The package's delivery reader re-hashed the master, proxy and delivery document
before export. A new canonical NFS directory received those files and the exact
build run, delivery stage, snapshot, asset versions, Wan clip and service phase
records. A fresh reader opened all ten files on the share and matched their sizes
and hashes, 10,102,482 bytes in total. It also checked the linked run and delivery
IDs. The [run evidence](run-evidence.json) lists both archives' full file hashes.
The [tracker](https://work.haynesnetwork.com/work_packages/942) holds the private
locations and service identities.

## Authenticated phone playback — Blocked

The live route inventory showed one LAN Wan video route. Its route and entry point
had no authentication middleware, and the video origin served completed files without
an application login check. An existing authenticated path to the exact new proxy
could not be verified. Signed-out denial and signed-in phone playback and seek
remain open. The new cut is in the canonical archive and has no Wan playback link.

Tom approved the quieter-gavel Winter Menu cut before this story. His creative
verdict for One More Meeting is pending.

## Usage

One Wan S2V job, two sequential Kokoro synthesis requests and one ASR request.
Kokoro's read-only Describe confirmed the voice before synthesis. No paid inference
or other model jobs. Archive files newly written to NFS totaled 83,741,397 bytes.

## Source validation

The focused contract, private-input importer and live-build adapter suite passed
252 tests. Four existing contract examples remain pending validators. One test
invocation used a restrictive umask that changed expected fixture modes. Another
overlapped a documentation edit and tripped the checkout guard. The final test
run used the standard umask and a stable checkout. The staged files passed the
repository syntax, links and no-media checks.
