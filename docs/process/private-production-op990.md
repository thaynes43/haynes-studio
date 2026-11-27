# Private production workflow evidence

[Production story](https://work.haynesnetwork.com/work_packages/990) records a
15.542-second, four-board short across two scenes, with three speaking characters
and a silent reaction. Source used Studio commit
`01ae709dc5ce86c6963f706ac2e0119f9af151b9`. The session and the installed
`studio-render` worker matched the lock and toolchain fingerprints.

## Proven

The production checks and archive readback are recorded in the
[technical evidence](https://work.haynesnetwork.com/work_packages/990/activity#comment-10682).

- The private brief matched its recorded SHA-256. Nineteen reusable inputs
  matched their recorded sizes and hashes and decoded through their expected
  formats. The two source archives matched all 15 files in their receipts.
- Three stock voice takes and four serial Wan submissions completed. One
  replacement clip passed the existing lettering gate after the first take fell
  short. The engine ran for 25.8 minutes and cooldown took 4.2 minutes. The
  interpreter fell back to local Python 3.11 while the render worker used 3.12.16.
- The private build reused the existing renderer and a stock sound bed. All
  lettering checks, mix and master checks, exact normalized transcript and
  frame-count verification passed. The master measured −20.074 LUFS and
  −4.466 dBTP, with zero clipped samples.
- An independent read of the create-only archive verified 15 files, their
  identities and hashes, and a full decode of both H.264/AAC videos. The
  1080×1920 master and 720×1280 phone proxy each held 373 frames at 24 fps.
- The coordinator independently rehashed the archived phone proxy, verified
  the upload size and owner-only permissions, and sent the playback link to
  Tom's phone thread.
  [Phone-copy handoff evidence](https://work.haynesnetwork.com/work_packages/990/activity#comment-10685)

## Expected

Signed-in, off-VPN playback on Tom's phone, his listening check and his
creative verdict remain unverified.
