# Wardrobe and decal checks

[Story 450](https://work.haynesnetwork.com/work_packages/450) provides two checks in
`haynes_studio.checks`. Each returns a `studio.check-result/v1` document with a check
name, version, result, confidence, SHA256 artifact references, thresholds, measurements
and issues. The `pass` and `fail` results report evidence within the stated method.
`uncertain` carries low confidence and an explicit escalation. Confidence describes
the available evidence. It does not estimate a probability or convey creative
approval. `as_run_check` preserves the full document under `actual` and records
uncertain outcomes as a blocking `fail` in the current run schema.

## Decal drift

`check_decal(keyed, clip_id=…, clip_sha256=…, attempt=…, regions=…, shown=…)`
reads the [layered adapter](layered-adapter.md)'s keyed APNG. Use the source clip ID
and SHA256 from the caller's plan. `shown` selects zero-based source frames. Frame 0
is always the comparison template, even when trimmed from a board. The result
records the template and exact shown source indices. The existing
`layered.decal_gate` supplies ECC and counts failed tracks. This check uses its
default `MIN_ECC` of 0.8 for every clip.

`DecalRegions` describes two padded crops in the decoded keyed frame, with separate
RGB ranges for visible jacket cloth and ink. The crops must isolate a jacket panel
and its lettering throughout the clip. Use the keyed record's crop origin to
translate boxes defined in source-video coordinates. The check uses opaque pixels
(alpha at least 224) and requires at least 24 pixels of each color. It measures
the ink centroid and ink area in units of the cloth's bounding box. This cancels
common translation and uniform scaling. The frame with the largest displacement
and the frames with the extreme ink-area ratios are carried with the measurements.
This check uses region geometry directly and runs no second motion tracker.

| `decal.drift` v1 evidence | Result |
| --- | --- |
| Comparable ink offset above 0.035 jacket units or ink area above 1.35 times the template | Fail for offset or excess ink |
| ECC marks any shown frame as lost | Fail for lost track |
| ECC below 0.8 and no measured defect | Uncertain, even when the visible ink holds |
| Missing track or regions, a clipped color region, ink area below 0.65 times the template, or a cloth aspect change above 1.20 times in either direction | Uncertain if there is no other measured defect |
| All shown frames comparable, within the visual bounds and passing the ECC gate | Pass |

Excess ink is a signal for doubling. The method can miss overlapping copies, an
already doubled template, and wrong letters with similar geometry. Shadows, stripes,
turns, occlusion and props in the ink color can invalidate the region hints. Use
an isolated region or escalate if one is unavailable.

With weak or lost ECC, the returned escalation contains the clip ID, check, attempt
and maximum of two re-rolls (CR-02). Invalid visual regions are recorded alongside
that track evidence. Attempt 1 denotes the original clip. Attempts 1
and 2 can return `reroll`. Attempt 3 and later return `stop_with_evidence`. Other
failures and uncertain cases go to `review`. [Story 454](https://work.haynesnetwork.com/work_packages/454)
owns scheduling and persistence. A person's per-artifact override goes through
`record_check_override` with their identity and reason. The check exposes no
threshold override.

## Wardrobe attributes

`check_wardrobe(keyed_still, costume, sleeves=…, observer=…)` reads a single keyed RGBA
still and a mapping of declared attribute names to expected values. The evidence
identifies the still by bytes and the declaration by its canonical JSON hash.
For `sleeves: full_length` or `sleeves: sleeveless`, the caller can supply four
arm-interior windows (upper arm and forearm on each side as viewed by the camera)
and disjoint fabric and bare-arm RGB ranges. The v1 check requires at least 16
opaque pixels and 50% opaque support per window. At least 80% of those opaque
pixels must match a swatch to identify that window. A visible contradiction fails.
A pass requires all four windows to agree with the declaration. Occluded,
ambiguous or unsupported attributes without another observation escalate.
`AttributeObserver` is the injection point for those attributes. A low-confidence
observation or no value leaves an attribute uncertain. The suite uses a fake
observer. There is no hosted observer in this story.

## Winter Menu E0 evidence

Owner labels below come from the recorded verdicts. The crew's visual notes and
historical overrides are listed separately from those labels. The newer S2V
verdict is for the whole film.

On 2026-11-24, the read-only `ai/studio-render` worker replayed story 426's
`keying.decal_frames` and `keying.gate` using OpenCV 4.14.0 and PyAV 18.1.0. All
six input clip and still hashes matched the evidence records. The whole-source
gate evaluated all frames after the template. Exact minima can vary slightly
with the decoder and tracker build. Locators below are relative to
`/studio/jobs/winter-menu-video-v2`. The source hashes are in the evidence linked
on each row.

| Clip under `clips/` | Tom's recorded label | Replayed min ECC, frames tracked / lost | Check evidence and historical override | Source |
| --- | --- | --- | --- | --- |
| `layer-d-shocked-green.mp4` (v1) | Defect. The lettering slid and doubled. | 0.7176, 120 / 0 | Fixed ECC gate fails. No archived v1 keyed pixels in this job to measure the reviewed lettering. Visual assessment uncertain. | [D23](../proposals/0003-studio-plan.md#decisions-so-far), [verdict](../../titles/the-winter-menu/video-e0/findings-layered.md#toms-verdict-2026-11-04-and-the-two-defects), [scores](../../titles/the-winter-menu/video-e0/decal-scores.json), [hash](../../titles/the-winter-menu/video-e0/clip-records-layers.jsonl) |
| `layer-a-staring-green.mp4` (v1) | Unlabelled per clip. Tom did not flag it in the v1 film review. | 0.8459, 120 / 0 | Fixed ECC gate passes. Archive contains the later erase-v2 frames. Those pixels did not yield comparable jacket regions. | [verdict](../../titles/the-winter-menu/video-e0/findings-layered.md#toms-verdict-2026-11-04-and-the-two-defects), [scores](../../titles/the-winter-menu/video-e0/decal-scores.json), [hash](../../titles/the-winter-menu/video-e0/clip-records-layers.jsonl) |
| `layer-b-deadpan-v2-green.mp4` | Unlabelled | 0.7051, 120 / 0 | Uncertain. E0 override 0.65 after visual review found creasing with lettering holding. | [v2 findings](../../titles/the-winter-menu/video-e0/findings-layered.md#layered-v2-2026-11-04-toms-two-fixes-on-the-render-worker), [override](../../titles/the-winter-menu/video-e0/clipmap-layered-v2.json), [hash](../../titles/the-winter-menu/video-e0/clip-records-layers.jsonl) |
| `layer-d-shocked-v2-green.mp4` | Unlabelled | 0.6260, 120 / 0 | Uncertain. E0 override 0.60 after visual review found creasing with lettering holding. | [v2 findings](../../titles/the-winter-menu/video-e0/findings-layered.md#layered-v2-2026-11-04-toms-two-fixes-on-the-render-worker), [override](../../titles/the-winter-menu/video-e0/clipmap-layered-v2.json), [hash](../../titles/the-winter-menu/video-e0/clip-records-layers.jsonl) |
| `s1-a-lightning.mp4` | Unlabelled per clip. S2V film accepted for quality. | 0.7120, 157 / 0 | Uncertain. E0 override 0.70 after visual review found the lettering on the jacket. | [D24](../proposals/0003-studio-plan.md#decisions-so-far), [S2V findings](../../titles/the-winter-menu/video-e0/findings-s2v.md#measurements-clip-records-s2vjsonl), [override](../../titles/the-winter-menu/video-e0/clipmap-s2v.json), [hash](../../titles/the-winter-menu/video-e0/clip-records-s2v.jsonl) |
| `s9-b-lightning.mp4` | Unlabelled per clip. S2V film accepted for quality. | 0.7953, 73 / 0 | Uncertain. E0 override 0.78 after visual review found the lettering on the jacket. | [D24](../proposals/0003-studio-plan.md#decisions-so-far), [S2V findings](../../titles/the-winter-menu/video-e0/findings-s2v.md#measurements-clip-records-s2vjsonl), [override](../../titles/the-winter-menu/video-e0/clipmap-s2v.json), [hash](../../titles/the-winter-menu/video-e0/clip-records-s2v.jsonl) |
| Whole-frame shot 1 with Foley | Jacket continuity defect | No layered track | The frame has no isolated keyed jacket or authored decal. | [D22](../proposals/0003-studio-plan.md#decisions-so-far), [whole-frame findings](../../titles/the-winter-menu/video-e0/findings.md#drift-end-frames-vs-keyframes), [assembly](../../titles/the-winter-menu/video-e0/assembly-wf.json), [clip evidence](../../titles/the-winter-menu/video-e0/clip-records.jsonl) |

The archived erase-v2 pixel trial used cloth box `[0,409,576,1024]`, cloth RGB
`[0,25,70]..[135,180,255]`, ink RGB `[171,131,0]..[255,255,99]` and the archived
decal box expanded by 24 px per edge. No template yielded valid isolated regions,
so there are zero jacket-relative visual measurements on those clips. The archive
digest is SHA256 of the concatenated binary SHA256s of the PNGs in frame order.

| Directory under `keyed/` | Archive digest |
| --- | --- |
| `layer-a-staring-green-d54181d7405a` | `b7b6c2a13beaada58d8e52b51a4474e4c2dde440dd9c6386d87918010d8a8783` |
| `layer-b-deadpan-v2-green-7eb8a6b9fc37` | `4ea14473c11183b1bdcf0b45be05756f63b36dad80756bc5dcac5876a4577705` |
| `layer-d-shocked-v2-green-80b94749ce2e` | `d621c35ae13a69a74aeee6db7cc88b932a017a545916a208de428f87ff6b73c9` |
| `s1-a-lightning-0e82b8b7fa75` | `d7014d897651cab6d62627ed2ac2f1855801fe4adbd012878136db84a6503415` |
| `s9-b-lightning-84e4fcf1d677` | `8bc4d7910f645c894df94100ab89d2efa97788b4978354addb470951e8608f6f` |

The sleeve trial keyed the six archived stills at 576×1024 using story 426's keyer
with `lo=20`, `hi=70` and no protect boxes. Source hashes matched the
[layer clip records](../../titles/the-winter-menu/video-e0/clip-records-layers.jsonl).
The trial compared against the full-length sleeve declaration documented in the
v2 fix. Camera-relative arm windows were chosen from the color distribution and
held constant for each doll across variants. They are fixture hints, so these
results measure those windows and do not establish performance on new poses.

| Still under `layers/` | Tom's recorded label | Result with reported material coverage | Source |
| --- | --- | --- | --- |
| `b-base-s101-green.png` | Sleeve defect | Fail, mixed. Camera-right upper arm 100% bare-color. The other three windows were 82–98% fabric-color. | [D23](../proposals/0003-studio-plan.md#decisions-so-far), [verdict](../../titles/the-winter-menu/video-e0/findings-layered.md#toms-verdict-2026-11-04-and-the-two-defects), [hash](../../titles/the-winter-menu/video-e0/clip-records-layers.jsonl) |
| `d-base-s101-green.png` | Sleeve defect on D | Fail, sleeveless. All four windows were 95–100% bare-color. | [D23](../proposals/0003-studio-plan.md#decisions-so-far), [verdict](../../titles/the-winter-menu/video-e0/findings-layered.md#toms-verdict-2026-11-04-and-the-two-defects), [hash](../../titles/the-winter-menu/video-e0/clip-records-layers.jsonl) |
| `d-shocked-s301-green.png` | Sleeve defect on D | Fail, sleeveless. All four windows were 96–100% bare-color. | [D23](../proposals/0003-studio-plan.md#decisions-so-far), [verdict](../../titles/the-winter-menu/video-e0/findings-layered.md#toms-verdict-2026-11-04-and-the-two-defects), [hash](../../titles/the-winter-menu/video-e0/clip-records-layers.jsonl) |
| `b-base-s101-sleeves-s401-green.png` | Unlabelled | Uncertain. Right upper arm had 59% fabric-color and 0% bare-color. | [v2 fix](../../titles/the-winter-menu/video-e0/findings-layered.md#layered-v2-2026-11-04-toms-two-fixes-on-the-render-worker), [hash](../../titles/the-winter-menu/video-e0/clip-records-layers.jsonl) |
| `d-base-s101-sleeves-s401-green.png` | Unlabelled | Uncertain. Right forearm had 53% fabric-color and under 1% bare-color. | [v2 fix](../../titles/the-winter-menu/video-e0/findings-layered.md#layered-v2-2026-11-04-toms-two-fixes-on-the-render-worker), [hash](../../titles/the-winter-menu/video-e0/clip-records-layers.jsonl) |
| `d-shocked-s301-sleeves-s401-green.png` | Unlabelled | Uncertain. Right forearm had 53% fabric-color and 1% bare-color. | [v2 fix](../../titles/the-winter-menu/video-e0/findings-layered.md#layered-v2-2026-11-04-toms-two-fixes-on-the-render-worker), [hash](../../titles/the-winter-menu/video-e0/clip-records-layers.jsonl) |

Window order is left upper, left forearm, right upper, right forearm. Fabric RGB
was `[0,25,65]..[99,135,190]` for both dolls. Bare RGB was
`[70,25,0]..[130,75,38]` for B and `[100,60,30]..[245,180,156]` for D.

| Doll | Windows as `x0,y0,x1,y1` |
| --- | --- |
| B | `162,650,182,666`, `156,803,178,822`, `411,678,427,698`, `408,803,429,823` |
| D | `159,672,173,690`, `85,750,105,770`, `405,672,424,691`, `454,786,474,806` |

The source suite generates small keyed PNG and APNG fixtures under `tmp_path`.
It checks rigid, sliding, doubled and lost decals, the fixed ECC floor, and
matched, mismatched and uncertain wardrobe attributes. The E0 trial and synthetic
cases are the evidence available for v1.
