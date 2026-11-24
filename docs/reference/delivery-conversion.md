# Delivery conversion profile

[Story 453](https://work.haynesnetwork.com/work_packages/453) versions the conversion
that runs before board segment encoding. The source and synthetic tests cover the
Pillow Lanczos baseline. The earlier softness finding remains open pending a private
quality comparison with the approved upscaler. [E0 findings](../../titles/the-winter-menu/video-e0/findings.md)

## Picture and audio clocks

- On a timed layer, delivery frame `n` shows source frame
  `trim_start + floor(n * source_fps / 24)`. Canonical S2V uses 16 fps, so the cadence
  from the trim start is `0, 0, 1, 2, 2, 3, …`. Each board starts at `n = 0`.
  A board of `F` frames needs `floor(2 * (F - 1) / 3) + 1` S2V source frames. Extra
  frames are trimmed and recorded. A short source fails with `time.source_short`.
- A 24 kHz S2V drive track holds `1000 * F` samples. The 48 kHz film mix holds 2000
  samples per delivery frame and places a line at
  `film_start_frame * 2000 + line_start_ms * 48`. Picture conversion leaves those
  offsets intact. The master and phone proxy share the 24 fps picture clock and
  48 kHz audio clock, with an MP4 movie timescale of 48 000. The existing AAC decode
  check allows end padding. [Time contract](../contracts/studio-contracts-v1.md#3-the-time-contract)

## Scaling and provenance

Whole-frame clips and layered set loops scale to the segment size with Pillow Lanczos.
The master uses 1080 × 1920 for a short and 1920 × 1080 for a video. Equal sizes pass
through. A different aspect is refused by the renderer. Still set plates keep the
centred Lanczos cover fit. The phone proxy keeps its own area downscale from the master.
[Delivery reference](studio-delivery.md)

`render.delivery_profile` defines `studio.delivery-conversion/v1`. Its canonical JSON
describes the timing and scaling policies, the resize backend version and the Pillow
version. Lanczos records a null `model_sha256`. The normal build writes the profile and
its digest to `provenance.toolchain.delivery_profile`, with a `measured.tool_sha256`
beside them: the SHA-256 of the native Pillow core this process loaded. `measured` is
provenance and is not part of the digest. The separate S2V clip provenance still
records the generation model files.

`DeliveryUpscalerProfile` and `resolve_delivery_upscaler` are the extension point for
an installed scaler with a distinct profile, tool digest and weight digest. Only
Lanczos resolves today. A renderer refuses an unknown profile hash.
[Upscaler installation dependency](https://work.haynesnetwork.com/work_packages/461)

## Cache impact

The board segment key adds `delivery_profile_sha256`. A plan made before story 453
and a new plan use different segment keys for every board. The old segment entries
remain readable by their original keys. New plans can reuse existing takes, voice
tracks, S2V drive tracks and clips, whole-frame clips, library motion, keyed/decal
frames and the mix. The film picture uses the resolved segment **content** hashes.
If rendered segment bytes match, its key can still hit. Otherwise the changes
propagate through film picture, master, proxy and affected checks as the input content
hashes change. The shared key scheme stays `studio.cache-key/v1`.
[Cache contract](../contracts/studio-contracts-v1.md#4-cache-clocks-and-invalidation)

The digest names the scaler by Pillow version, as the keyer's build text does
(`keyer_build`), not by the bytes of its native core. A build runs in two
environments: the session pod (Python 3.11) plans it and runs its service phases, and
the render worker (Python 3.12) renders the segments
([studio-build](studio-build.md)). Both install the same locked Pillow version, from
wheels whose native cores differ byte for byte, so a core digest in the key would give
the two a different key for the same segment. A change of the locked Pillow version
rekeys every segment; a different wheel of the same version does not, and shows only
in `measured.tool_sha256`.

## Synthetic evidence

`tests/delivery/test_delivery_profile.py` builds a 4-frame lead board and a 19-frame
S2V board. It reads the source frame marks and exact video timestamps back from both
delivered MP4s. Each holds 23 frames and records 46 000 audio samples. The S2V drive
track holds 19 000 samples and starts its voice at sample 6000. The corresponding
voice starts at film sample 20 000, the start of film frame 10. The test checks the
mix samples, decoded audio continuity and recorded tool and model hashes. It also
compares the scaler with Pillow Lanczos at both master sizes. All media is generated
by the tests.
