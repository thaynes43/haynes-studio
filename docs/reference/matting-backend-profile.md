# Matting backend profile

**Proposed 2026-11-25** for [story 459](https://work.haynesnetwork.com/work_packages/459).
Use **BiRefNet Lite FP32 on ONNX Runtime CPU** for single-subject cast and prop
stills. Keep **BRIA RMBG 1.4 FP32 on the same CPU runtime** as the fallback if
the first profile fails the resource or quality smoke. Provisional
[ruling 33](../contracts/studio-contracts-v1.md#ruling-33) selects BiRefNet Lite
for stills. Installation and private quality proof remain open. A fallback
requires a new ruling and its own smoke, input signatures and receipts.
BiRefNet Lite has published object-domain evidence and a pinned CPU-compatible
export. BRIA uses a different saliency architecture with a smaller graph and
published CPU integration evidence. It gives the pilot a second approach.

The PoC green key can punch holes in green eyes. Protect boxes restored the
eyes manually. A still matte should identify the subject from structure and
context, including opaque green inside a face, keep flyaway hair and lashes,
and retain source geometry for scale matching. A Studio still starts as
`opaque_photo`. Its derived RGBA cutout can earn `rgba_cutout`; a separate
grayscale alpha image has `mask`. A timed chroma layer has `keyed_layer`. The
opaque source and its capabilities stay immutable under D15.
[E0 findings](../../titles/the-winter-menu/video-e0/findings.md) ·
[PoC cutout procedure](../process/manual-short-poc.md) ·
[Layered adapter](layered-adapter.md) · [Asset candidates](asset-candidates.md) ·
[Doll format](doll-format.md) · [Studio plan, D15, D18, D22–D24 and E2](../proposals/0003-studio-plan.md)

**Selected by CR-33**, story 459 comment 9934. The source implements
`birefnet-lite-ort-cpu-v1` for stills. BRIA requires a new ruling after a
primary smoke failure. Clips use the existing chroma keyer. The 32-inode
provisioning budget stands without a free-inode reading because this NFS
client does not report one. Installation and the private quality check are
**Expected**.

## Candidate evidence

External sources and publisher metadata below were read **2026-11-25**.
Benchmarks compare different pipelines and hardware. A file size is the weight
file's byte count. Peak process RAM and VRAM include activations and runtime
buffers. All input sizes below are documented operating points or graph shapes.
None establish that larger sources keep more foreground detail.

| Candidate | Input and output | Edge and clip evidence | CPU and one-card evidence |
|---|---|---|---|
| **BiRefNet Lite**, general-use dichotomous segmentation | RGB, batch 1, 1024 × 1024 for this export's documented processor. Sigmoid of the graph logits supplies a continuous foreground score used as alpha. RGB decontamination is external. | The BiRefNet paper shows fine structures in DIS and evaluates camouflaged objects as a separate task. Its general-use Lite checkpoint is trained on object and portrait data. The paper and card give no results for green doll eyes, lashes or the fraction of translucent hair that this export retains. Independent frames have no temporal state. | A first-hand report on the proposed ORT FP32 graph at 1024 × 1024 reports about 6 s per image with preprocessing. CPU model, thread count and RSS are unknown. The authors report 93.8 ms on A100 for lightweight Swin-T ONNX at 1024². Their separate 24 GB RTX 4090 reference is 95.8 ms FP32 and 57.7 ms FP16, with an inference memory table of 4.8/3.5 GB. Those figures are for the reference BiRefNet, and do not establish Lite ONNX peak VRAM or RTX 3090 latency. [Paper](https://arxiv.org/abs/2401.03407) · [Lite card](https://huggingface.co/ZhengPeng7/BiRefNet_lite/blob/aa62cd87eafb9cc43056d08ef3615a14628b831d/README.md) · [Export card](https://huggingface.co/onnx-community/BiRefNet_lite-ONNX/blob/de15b22ba131738a16dff04aab8bdf8dc32e3ac1/README.md) · [CPU report](https://github.com/ZhengPeng7/BiRefNet/issues/259) · [Author timings](https://github.com/ZhengPeng7/BiRefNet/blob/f7079632d681ecf12161fcea8905682934e59e51/README.md#model-efficiency) |
| **BRIA RMBG 1.4**, IS-Net-based saliency | RGB, batch 1, 1024 × 1024 in the publisher's processor. Outputs a continuous saliency mask. Composition uses input RGB. | Card shows a foreground example and describes diverse stock, e-commerce, gaming and advertising subjects. It supplies no controlled hair, low-contrast or green-on-green score. Saliency can drop a low-contrast prop or a thin feature. Frames are independent. | A first-hand CPU-only integration reports a few seconds per 1024² image and about 0.5 GiB peak RAM for the FP32 graph with a Go ONNX Runtime integration that defaults to all CPU cores. Matching two-thread CPU and RTX 3090 speed and peak memory are unknown. The 1.4 package has an openly reachable ONNX graph. The publisher's newer 3.0 card requires login and agreement for weight access. [1.4 card](https://huggingface.co/briaai/RMBG-1.4/raw/da1d078376e6691105a5530a374a010627fc60b5/README.md) · [CPU report](https://pkg.go.dev/m8sh.su/x/rmbgo@v1.1.0) · [3.0 access](https://huggingface.co/briaai/RMBG-3.0) |
| **MODNet photographic**, trimap-free portrait matting | RGB and a fractional alpha matte, with no foreground colour estimate. The Xenova export's processor targets a 512 px short side with dimensions divisible by 32. Its published processor sets no long-side maximum. | The paper's PPM-100 comparisons show portrait hair detail, and its video discussion reports flicker and uses an optional one-frame-delay filter. Those tests cover people. Evidence for props, painted green eyes and similarly coloured doll/background edges is unknown. | The authors measured 67 fps on GTX 1080 Ti at 512² including data loading. A separate MODNet ONNX conversion measured 68.72 ms on a Core Ultra 9 386H with ORT 1.31.1 CPU at default settings. The related LiteRT conversion measured 602.8 ms and 219 MB peak on Raspberry Pi 5 with four XNNPACK threads. Matching CPU latency/RSS and 24 GB GPU latency/VRAM for the Xenova graph are unknown. [Paper](https://arxiv.org/abs/2011.11961) · [Author ONNX notes](https://github.com/ZHKKKe/MODNet/blob/28165a451e4610c9d77cfdf925a94610bb2810fb/onnx/README.md) · [Export processor](https://huggingface.co/Xenova/modnet/blob/fa2fa546052fba4c08921230a26cc69a333fca12/preprocessor_config.json) · [ORT measurement](https://huggingface.co/mlboydaisuke/MODNet-OpenVINO#speed-and-output-check) · [LiteRT measurement](https://huggingface.co/litert-community/MODNet-LiteRT) |
| **Robust Video Matting (RVM) MobileNetV3**, recurrent human matting | Dynamic RGB frames, recurrent state and downsample ratio, opset 12. Published HD 1920 × 1080 at 0.25 and UHD 3840 × 2160 at 0.125. Outputs fractional alpha and estimated foreground RGB, plus state for the next frame. | The authors show better strand detail and temporal coherence on human videos than independent-frame methods. They report difficulty when the target is ambiguous. No doll, prop or green-on-green measurement. A reset belongs at a segment boundary. | The authors tested CPU ONNX compatibility and provide no matching CPU latency or RSS. On one 24 GB RTX 3090 their FP16 TorchScript tensor loop measured 172 fps at HD and 154 fps at 4K with batch and chunk 1. That excludes decode and encode, and peak VRAM and ORT CUDA time are unknown. [Paper, figures 3–4 and §6.6](https://arxiv.org/pdf/2108.11515) · [ONNX interface](https://github.com/PeterL1n/RobustVideoMatting/blob/53d74c6826735f01f4406b5ca9075eee27bec094/documentation/inference.md#onnx) · [Speed and method](https://github.com/PeterL1n/RobustVideoMatting/blob/53d74c6826735f01f4406b5ca9075eee27bec094/README.md#speed) |

BiRefNet-V2 is described in the November preprint. Its linked repository
returned 404 at the check, so this proposal has no pinned runnable CPU
artifact from that release. The earlier Lite graph has an accessible fixed
artifact and object-domain evidence. An alpha model can learn membership even
when colours match. The separation is ambiguous along an edge where the observed
foreground and background are identical. None of the sources establishes a fix
for this Studio fixture. The bounded eye and hair checks below decide whether
to proceed. [BiRefNet-V2 preprint](https://arxiv.org/abs/2611.11272)

| Exact weight artifact | Publisher bytes | Published digest | Licence evidence |
|---|---:|---|---|
| **Primary** `onnx-community/BiRefNet_lite-ONNX` at `de15b22ba131738a16dff04aab8bdf8dc32e3ac1`, [`onnx/model.onnx`](https://huggingface.co/onnx-community/BiRefNet_lite-ONNX/resolve/de15b22ba131738a16dff04aab8bdf8dc32e3ac1/onnx/model.onnx), exported from `ZhengPeng7/BiRefNet_lite`. The official v1 release lists a Swin-T general ONNX with the same size. Byte identity between the two is unverified. | 224,005,088 | SHA-256 `5600024376f572a557870a5eb0afb1e5961636bef4e1e22132025467d0f03333` | Export and upstream cards say `license: mit`. MIT permits dealing “in the Software without restriction” and requires the copyright and permission notices with substantial copies. [Export metadata](https://huggingface.co/api/models/onnx-community/BiRefNet_lite-ONNX/revision/de15b22ba131738a16dff04aab8bdf8dc32e3ac1?blobs=true) · [Author release](https://github.com/ZhengPeng7/BiRefNet/releases/tag/v1) · [Licence](https://github.com/ZhengPeng7/BiRefNet/blob/f7079632d681ecf12161fcea8905682934e59e51/LICENSE) |
| **Fallback** `briaai/RMBG-1.4` at `da1d078376e6691105a5530a374a010627fc60b5`, [`onnx/model.onnx`](https://huggingface.co/briaai/RMBG-1.4/resolve/da1d078376e6691105a5530a374a010627fc60b5/onnx/model.onnx). | 176,153,355 | SHA-256 `8cafcf770b06757c4eaced21b1a88e57fd2b66de01b8045f35f01535ba742e0f` | Publisher card says “Commercial use is subject to a commercial agreement with BRIA.” Weight use is non-commercial under the open offer. The linked agreement returned 404, leaving the precise Creative Commons variant, output terms and attribution unknown. [Weight metadata](https://huggingface.co/api/models/briaai/RMBG-1.4/revision/da1d078376e6691105a5530a374a010627fc60b5?blobs=true) · [Publisher card](https://huggingface.co/briaai/RMBG-1.4/raw/da1d078376e6691105a5530a374a010627fc60b5/README.md) |
| `Xenova/modnet` at `fa2fa546052fba4c08921230a26cc69a333fca12`, `onnx/model.onnx`, community export linked to `ZHKKKe/MODNet`. | 25,888,640 | SHA-256 `07c308cf0fc7e6e8b2065a12ed7fc07e1de8febb7dc7839d7b7f15dd66584df9` | Export card quotes `license: apache-2.0`; upstream Apache-2.0 includes rights to “reproduce, prepare Derivative Works of” the Work, with redistribution conditions. No separate output term found. [Export metadata](https://huggingface.co/api/models/Xenova/modnet/revision/fa2fa546052fba4c08921230a26cc69a333fca12?blobs=true) · [Card](https://huggingface.co/Xenova/modnet/blob/fa2fa546052fba4c08921230a26cc69a333fca12/README.md) · [Licence](https://github.com/ZHKKKe/MODNet/blob/28165a451e4610c9d77cfdf925a94610bb2810fb/LICENSE) |
| `PeterL1n/RobustVideoMatting` v1.0.0, `rvm_mobilenetv3_fp32.onnx` (CPU) and `rvm_mobilenetv3_fp16.onnx` (CUDA comparison). | 14,975,696 and 7,503,483 | Both unknown. Release metadata has null digests. Intel's manifest publishes SHA-384 `d6eeb320496d9a7de7d740806f1edf4c7144d97bffec0f279abd2eb3c6c8f3dd9b311eb48f8e70478a1d4e8c172ea720` for a **different** 14,981,904-byte `robust_video_matting_mobilenetv3.onnx` conversion fixed at 1280 × 720. | Author readme says “Code is re-released under GPL-3.0 license.” The text allows making and running covered works and puts conditions on conveyance. A specific grant for the ONNX weights and separate output terms are unknown. [Release metadata](https://api.github.com/repos/PeterL1n/RobustVideoMatting/releases/tags/v1.0.0) · [Readme](https://github.com/PeterL1n/RobustVideoMatting/blob/53d74c6826735f01f4406b5ca9075eee27bec094/README.md#news) · [Licence](https://github.com/PeterL1n/RobustVideoMatting/blob/53d74c6826735f01f4406b5ca9075eee27bec094/LICENSE) · [Intel model manifest](https://github.com/openvinotoolkit/open_model_zoo/blob/2c9b5c563ab3a202d085a42e2bbfc48f77961f4b/models/public/robust-video-matting-mobilenetv3/model.yml) |

D49 keeps private research and personal development available. For a future
commercial workflow, replace BRIA 1.4 or obtain a separate commercial
agreement. Replace RVM if its weight terms still cannot be established before
commercial use. BiRefNet Lite and MODNet have permissive weight tags and
notice obligations. Separate output terms for both remain unknown, so the
commercial review would still check the inputs, assets and intended use.
[D48/D49](../proposals/0003-studio-plan.md#decisions-so-far) ·
[Proposed licence rows](model-licences.md#proposed-matting-profiles)

## CPU profiles and clip path

| Setting | `birefnet-lite-ort-cpu-v1` (primary) | `bria-rmbg-1.4-ort-cpu-v1` (fallback) |
|---|---|---|
| Input tensor | RGB FP32 NCHW `[1,3,1024,1024]`; bilinear resize, then `(RGB/255 - mean)/std` with mean `[0.485,0.456,0.406]`, std `[0.229,0.224,0.225]`. | Same shape and resize, `RGB/255 - 0.5` per channel. |
| Alpha tensor | `output_image` logits, apply sigmoid. | Primary saliency plane after the graph's sigmoid. Clamp directly. The reference PyTorch example stretches each mask to its min/max. This profile retains the original relative range to avoid turning a nearly constant output into an apparently good cutout. Verify the actual ONNX I/O metadata and bounds before readiness. |
| Memory allocation | Request 2 GiB, limit 6 GiB. | Request 1 GiB, limit 3 GiB. |
| Warm end-to-end planning window | 3–15 s per still. 100 independent frames would take 5–25 min. | 2–12 s per still. 100 independent frames would take about 3–20 min. |

The planning windows and memory limits are engineering budgets for one
talosw01 job, not measurements or service targets. Very slow jobs may exceed
them. Both profiles set a 30 s per-still deadline, including the first run in
a ready process. Measure cold load separately (startup cap 120 s). Use
**ONNX Runtime 1.32.0** with only `CPUExecutionProvider`, sequential execution,
two intra-op threads, one inter-op thread, spinning disabled, and one request
in flight. Keep image library work inside the same two-vCPU allocation.
Neither a checkpoint swap nor a CPU timeout implies a GPU retry.
[BiRefNet processor](https://huggingface.co/onnx-community/BiRefNet_lite-ONNX/blob/de15b22ba131738a16dff04aab8bdf8dc32e3ac1/preprocessor_config.json) ·
[BRIA processor](https://huggingface.co/briaai/RMBG-1.4/blob/da1d078376e6691105a5530a374a010627fc60b5/preprocessor_config.json) ·
[ORT threading](https://onnxruntime.ai/docs/performance/tune-performance/threading.html)

**Clips retain the existing chroma keyer** for decal tracking, eye-protect boxes,
unmixing, despill and the versioned APNG. Add temporal alpha refinement only
after a separate paired clip check. The first proposed refinement uses a
three-frame median only on unprotected boundary pixels (within 2 px of the
alpha-128 contour in all three source frames) where the squared RGB distance
between the middle pixel and each neighbour in time is at most `12²` in 8-bit
values. Skip the first and last frames, shot boundaries and motion outside
that tolerance. Keep the keyer's RGB, protected regions, source clock and fixed
crop. Compare baseline and refined mattes on static and translating edges
before changing any renderer default. It can reduce small static-edge pulses.
It cannot recover green detail lost outside a protect box or align fast
motion. Refuse that quality result when protection or temporal checks fail.
Version the refinement and its parameters in `keyed_frames_key` and APNG
evidence. Preserve the existing decal gate. Story [451](https://work.haynesnetwork.com/work_packages/451)
consumes the still contract below. The clip refinement is a later, separately
owned renderer change. [Layered keying and APNG](layered-adapter.md#keyed-frames-keyed_frames_key)

Budget **30–90 s per 100 delivery-size frames** for CPU key plus refinement,
and at most **300 frames** per source clip at 1080 × 1920 or 1920 × 1080 up to
24 fps for that first clip check. The range extrapolates the existing synthetic
0.09 s/frame at 576 × 1024 by pixel area (~32 s per 100 at delivery size),
with room for decode, encode and the three-frame filter. Real IO, runtime
and motion stability are unmeasured. Recurrent RVM would add a video-specific
model with uncertain doll performance. A leased GPU would also hold up
every Wan, Foley and local-model job for admission, load, processing and verified
release. Even RVM's ~0.6 s tensor-only arithmetic for 100 HD frames leaves
that queue cost unmeasured. No second scheduler or unused-card bypass.
[Studio plan, D18 and D50](../proposals/0003-studio-plan.md#decisions-so-far) ·
[Layered baseline timing](layered-adapter.md#keyed-frames-keyed_frames_key)

## Artifact contract for story 451

Freeze a `studio.matte-request/v1` JSON object. Its `input_signature` is
`sha256:<hex>` over the store's canonical JSON. Digest fields ending in
`sha256` use bare lower-case hex. Use the existing `job_` and `asv_` ID
grammar. Fields are required.

| Field | Value |
|---|---|
| `schema`, `job_id` | `studio.matte-request/v1` and the claim's Studio job ID. |
| `source` | `{asset_version_id, production_id, sha256, bytes, media_type, width, height}`. `production_id` is the source's scope (null for library). Resolve an authorized pinned `opaque_photo` version and verify encoded bytes by length and hash, then decoded media type and size. Accept one opaque, single-frame RGB PNG or JPEG already oriented, with no embedded ICC profile. Each edge must be 64–2048 px, at most 4,194,304 pixels and 20 MiB encoded. |
| `profile_id`, `profile_sha256` | One ID above and the SHA-256 of its installed canonical manifest (profile ID, runtime wheel, weight file and digests, app build/digest, and effective preprocessing, alpha and PNG parameters). The worker's admitted manifest must match exactly. |
| `parameters` | `{chroma_rgb, target_height_px}`. `chroma_rgb` is the known uniform backing colour `[R,G,B]` in sRGB bytes, or null. Use a colour only for input with established sRGB provenance (for example, the generated synthetic smoke). Existing intake can strip ICC without transforming colour. If the stored input's colour space or the backing is unknown, pass null and retain RGB. `target_height_px` is null or an integer 1–2048 from the pinned layout/reference. Record that reference in the caller's asset provenance. |

Scope authorization lives at the existing Studio claim boundary. The adapter
resolves the source through the store. There are no caller-supplied paths,
URLs, weights or graph options. Pass verified bytes to the backend in its
allocated private scratch with the frozen request. The backend verifies the
byte identity again. For the local-process transport, use HTTP over the Unix
socket. `POST /v1/matte` takes JSON `{attempt_id, request}`. The adapter
creates a fresh 32-character lower-case hex attempt ID outside the frozen
signature and stages only `input` under that scratch directory. The backend
exclusively creates `cutout.png` and `mask.png` there and returns the receipt
after closing both files. A repeated dispatch uses a fresh attempt directory.

The backend resizes the continuous matte to source dimensions
with bilinear interpolation. Convert to an 8-bit mask with
`floor(clamp(alpha, 0, 1) * 255 + 0.5)`. For zero alpha use zero RGB. For
nonzero alpha with null `chroma_rgb`, keep source RGB so the preview can show
any fringe. With a known `chroma_rgb`, use these rules in order.

1. Keep source RGB for `alpha8 >= 243` and for foreground interior pixels
   with `alpha8 >= 128` more than 4 px from the nearest pixel below 128.
2. For remaining pixels with `1 <= alpha8 <= 20` and an sRGB byte distance
   of at most 3 from the backing colour, set alpha and RGB to zero. This
   removes faint predictions where the source and backing nearly coincide.
3. Unmix all remaining fractional pixels, including isolated fringe outside
   the alpha-128 contour. In linear sRGB compute
   `F = clamp((C - (1-a) * B) / a, 0, 1)` with
   `a = max(alpha8, 21)/255`. Here `C` is the source RGB and `B` is the
   backing colour. The lower bound stabilizes RGB when alpha is small.
   Convert back to sRGB bytes and keep the original `alpha8`.
   Both distances above are Euclidean.

Use straight alpha and no copied metadata. Neither model estimates
foreground colour. Compute the output mask and shape from the final alpha.

Return a `studio.matte-result/v1` receipt with `schema`, `job_id`,
`input_signature`, `source`, `profile_id`, `profile_sha256`, `parameters`
as frozen, and these fields.

| Field | Value |
|---|---|
| `artifacts` | `{cutout, mask}` with each descriptor `{sha256, bytes, media_type, width, height}`, `media_type: image/png`. Cutout is straight RGBA8 and mask is L8 identical pixel-for-pixel to the alpha channel. Both are in the exact source canvas. Encode with the image's locked Pillow, compression level 6, optimize off, and no ancillary metadata. |
| `shape` | `{bbox_xyxy, bbox_height_px, foreground_area_px, alpha_threshold, scale}`. Half-open pixel box `[left,top,right,bottom]` and area over pixels `alpha8 >= 128`, `alpha_threshold: 128`. `bbox_height_px = bottom - top`. `scale` is a rational pair `{numerator, denominator}`: target height over bbox height, or `{numerator:1,denominator:1}` with no target. The consumer scales isotropically in layout, without repeatedly resampling the stored cutout. A silhouette height is a pixel measure. Different poses or hair volume may need a separately chosen reference. |
| `provenance` | `{model, source_revision, files_sha256, runtime, provider, image_digest, parameters}` with actual graph filename-to-hash map, runtime name/version/wheel hash, CPU provider and the full applied parameter manifest. Copy the input version and hash through `source`. The app attaches the D48 licence and derived origin using the normal asset-version record. |

A usable result requires finite model output before clamping, alpha of the
expected shape, a nonempty foreground box, a background of at least one
pixel below alpha 128, and matching RGBA/mask/geometry/receipt hashes.
These are structural checks. The feature tests and candidate review evaluate
retained detail. Reuse `adapter.request_invalid` for source validation,
`adapter.pin_mismatch` for the profile pin, `adapter.timeout` for the deadline
and `adapter.response_invalid` for invalid output. Use `adapter.command_failed`,
`adapter.not_found` or `adapter.busy` for runtime failure, unavailability or
occupied capacity respectively. Use existing store and claim codes when those
boundaries fail. A failure has no successful result receipt or render-ready version.

Only the fenced Studio adapter publishes. Verify the backend output, then
`Store.publish` the PNGs and canonical receipt as new content-addressed blobs
in the authorized source scope. The store descriptors in the completion
reference carry the derived locators. The backend receipt keeps the hashes
and sizes. Atomically commit the completion reference and derived candidate
version only after every blob is durable. The derived candidate's primary
content is the cutout PNG with `rgba_cutout`. The paired L8 mask stays in
the receipt and the version's matte provenance. An identical completed
request returns the recorded receipt. Reusing a job ID with a
different signature fails with `idempotency.mismatch`. A stale claim cannot
commit a version. Even a crash after a blob write leaves only an unreferenced
blob and the original opaque candidate. Promotion remains explicit.
[Canonical JSON](../../src/haynes_studio/store/records.py) ·
[Existing photo intake](../../src/haynes_studio/photo/validation.py) ·
[Adapter failure codes](legacy-adapters.md) ·
[Store publication](../contracts/studio-contracts-v1.md#atomic-create-only-publication) ·
[Media worker claims](media-jobs.md#claims-and-results)

## Backend source

The [request](matting-examples/request.json) and [result](matting-examples/result.json)
examples use illustrative artifact and image hashes. Both schemas ship with the
package. Compute the signature over the frozen request object, including its
schema tag and excluding the attempt ID. The signature is a receipt field.
Request and failure bodies are JSON. A failure body is `{"code":"adapter.*"}`.

`studio-matting serve` binds `/matting/matte.sock` with mode 0660.
`GET /v1/ready` returns `{profile_id, profile_sha256, provider}` while the
inference process is ready, or 503 during recovery. A startup pin error
exits before binding. Malformed input returns 400, pin mismatch or busy
409, command failure 500, invalid output 502, unavailability 503 and
deadline expiry 504. Requests have a 4 KiB body limit. The worker stages
an attempt directory writable by the shared group and an `input` file
readable by that group. The backend refuses links, non-regular inputs and
nonempty prior attempts. The caller uses a fresh directory after any failed
or ambiguous reply. A killed attempt may leave files in its private scratch.
The store commits only after a verified success receipt.

The enrolled image's build revision is baked into its configuration. The
provisioner writes the canonical `profile.json` and separate `profile.sha256`
with the exact deployable image digest into the immutable weights allocation.
On startup the backend reconstructs the expected manifest from the image
reference, baked revision and effective settings, checks both mounted records,
then reads and hashes the graph it gives to ORT. The local hash check confirmed
224,005,088 bytes and SHA-256 `5600024376f572a557870a5eb0afb1e5961636bef4e1e22132025467d0f03333`.
The graph declares FP32 tensors `input_image` `[1,3,1024,1024]` and
`output_image` `[1,1,1024,1024]`. The process checks the provider and tensor
metadata before readiness and checks the logits before sigmoid. A request
that exceeds 30 s kills and reaps the subprocess before a fresh CPU session
can load. A load has its own 120 s budget.

## Provisioning and GitOps

Read-only check on 2026-11-25 used `kubectl -n ai get deploy studio-render`
with the resource and node columns, and `kubectl -n ai exec deploy/studio-render -c app -- df -Pk /studio`,
`df -Pi /studio` and `stat -f -c '%S %a %c %d' /studio`. The worker on
talosw01 has a 20-vCPU and 32-GiB container limit. D18's original 24-vCPU
render-worker limit differs from this read-back. The later CR-22 rollout
allocated 20 to offline render and 4 to the queue worker, for 24 total.
The Studio share reported
**110,828,267,241,472 free bytes (100.80 TiB)**. Free inodes were unreported
(`df` dash, `stat` -1). The existing `/studio/jobs` directory was present.
[D18](../proposals/0003-studio-plan.md#decisions-so-far) ·
[CR-22 rollout, comment 9872](https://work.haynesnetwork.com/work_packages/956)

- Use the selected immutable download URL above. The primary leaves
  110,828,043,236,384 free bytes before metadata at the measured headroom.
  The fallback by itself leaves 110,828,091,088,117. Retaining both takes
  400,158,443 bytes and leaves 110,827,867,083,029 before metadata.
  Re-read capacity before provisioning. Budget **1 GiB and 32 new inodes**
  on the share for the selected graph, receipt, retained failed attempt or
  fallback, and a small synthetic smoke. Keep **32 GiB** free after the byte budget. Under CR-33 the NFS client
  may omit the free-inode reading. Use one new allocation for each attempt.
- Stream to a unique file under a new profile job directory in the existing
  `/studio/jobs` allocation, with no Hub cache. Enforce the published byte
  count and SHA-256. Finalize create-only on that share and mount the selected
  immutable directory read-only at `/weights`. A failed copy stays private
  and within the same budget. Record hash verification, exact mount and job
  locator privately. Keep installed weights outside the OCI image.
- Build a Linux amd64 matting image from the Studio pin
  `python:3.12-slim-bookworm@sha256:44cf1793efa7c7a476bb0f2cff81443f4a072c90c1cb127e2924933daa3e8c64`.
  Add the reviewed adapter, locked NumPy/Pillow, CPU ONNX Runtime and its
  pinned dependencies and notices. Pin the PyPI CPython 3.12 x86-64 wheel
  `onnxruntime-1.32.0-cp312-cp312-manylinux_2_28_x86_64.whl` (27,780,211 bytes),
  SHA-256 `99e1074c4b2197accd5073052a465361be17b89c093b8ffb6e6bd8f986c52df8`.
  The release was dated 2026-11-13. The public GitHub latest release route
  returned 404 on the check after the November repository disruption. The
  proposal uses the original PyPI release and fixed wheel hash. Verify the
  installed distribution and record the build and deployable image digest.
  Pin that digest in the mounted profile manifest after the image is built.
  Budget at most 1 GiB installed image and 2 GiB additional temporary build
  space on the runner, separately from the NAS reserve. [Studio base pin](../../docker/studio.Dockerfile) ·
  [Microsoft release notes](https://github.com/Microsoft/onnxruntime/releases?raw=true) ·
  [Pinned PyPI wheel metadata](https://pypi.org/project/onnxruntime/1.32.0/#onnxruntime-1.32.0-cp312-cp312-manylinux_2_28_x86_64.whl) ·
  [ONNX project status thread](https://github.com/onnx/onnx/issues/8842)
- In haynes-ops put the workload on talosw01 in the low-priority Studio CPU
  allocation. Run the install smoke as one Job, active deadline 300 s and
  backoff 0. For the consumer, expose the same profile as a single local
  backend process beside the authorized Studio worker. Use a Unix socket and
  per-attempt files in a 256 MiB shared private scratch, and let the existing
  worker hold the API credential and store access. The backend uses UID/GID
  10001, read-only root, no GPU, ingress, network fetching or service account
  token mount, dropped capabilities and RuntimeDefault seccomp. Give the
  backend two vCPUs maximum from the **20-vCPU offline allocation**. For
  the smoke, use a window without an overlapping heavy render. For concurrent
  sustained use, limit offline render to 18 vCPUs with at most `--workers 16`,
  leaving two vCPUs for matting. The separate four-vCPU queue allocation
  remains available to its existing worker. Serialize heavy renders with
  matting until the concurrent limits are in effect.
- Startup verifies graph and profile hashes and creates the CPU session.
  Readiness identifies the expected profile and provider. Keep readiness
  false on a pin or session mismatch. Bound a stuck inference at the process
  boundary and reap the timed-out child before another dispatch. Roll back
  via the GitOps revision and disable new matte
  dispatch until readiness agrees with the requested profile. Retain the
  existing artifacts and all pinned versions.

## Install smoke and bounded private quality check

All are **Expected**. Use tiny synthetic media written at test time under a
new private scratch directory. Measure cold load, each inference wall time and
peak RSS. Check UID, read-only root and weights, CPU provider only, profile and
provenance hash read-back, and created artifacts. The install run should fit
300 s total, with each result inside its 30 s request deadline and the
profile's memory limit. Record measurements even on a refusal or failure.

1. **Shape and fringe.** Generate a single front-facing doll-like bust on a
   384 × 512 canvas using Pillow draw at 4× resolution. Use a head ellipse
   `[100,88,284,296]`, shoulders `[60,272,324,434]` and a contiguous dark wig
   with eight 1–3 px curved strands extending into the backing. Draw two
   eyelash arcs 1–2 px wide at the eye rims. Use different light levels
   across the glossy head and clothing. Save ground-truth alpha from area
   downsampling and composite in linear sRGB with a plain grey backing.
   Compare alpha-128 silhouette IoU (≥0.92), core foreground coverage (≥0.98
   of pixels with true alpha 255 and ≥4 px from the edge have alpha ≥243),
   and fringe MAE (≤0.20 on the annotated strand pixels with true alpha
   0.05–0.9, measured on 0–1 alpha). Score each eyelash separately at
   ≥0.80 of its annotated opaque pixels with alpha ≥243. Report fringe
   false positives using a 4 px outside band (average alpha ≤0.08).
2. **Green eyes.** Use the same subject with two ellipses centred at
   `(154,179)` and `(230,179)`, horizontal radius 9 px and vertical radius
   6 px, and exact RGB `[36,180,60]` for both their interiors and the backing.
   Pass that backing colour and no protect box. For each eroded iris
   interior require ≥95% of pixels at alpha ≥243 and zero RGB change
   at those retained pixels. Require at least 99% of the true remote
   background (≥8 px outside the true silhouette) at alpha ≤8. In the
   fake-matte test, inject alpha 12 on exact backing and require RGBA
   zero. Inject alpha 64 on a partially covered pixel 8 px outside
   the core, built by blending a `[128,128,128]` strand with the backing
   in linear sRGB. Require preserved alpha and recovered strand RGB
   within 3 byte values per channel.
3. **Size match.** Render the same foreground twice, at 1× and 0.75× centred
   on identical 384 × 512 canvases. Give both the first true bbox height as
   the target. Require measured alpha-128 bbox bounds within 3 px each of
   ground truth. Applying the rational scale must recover target height
   within 1 px and the measured scale ratio within 3% of 4/3. Require exact
   alignment of the encoded alpha and mask. Replay a request and compare
   hashes, then substitute a bad source digest and verify no completed
   receipt or render-ready version. Run the synthetic checks first with a
   fixed ground-truth fake to isolate adapter wiring, then run them once
   against the selected installed model. If the model misses the criterion,
   record the actual score and region. Keep the private quality claim pending.

For the later clip refinement, synthesize 12 frames of the same shape. Hold a
static fringe for six frames with alternating ±6 backing-green values, then
translate the subject by 4 px per frame for six frames. Compare the same key,
crop, timing and protected eye regions with and without refinement. On known
static boundary pixels require mean absolute frame-to-frame alpha change
≤0.035 and no increase over baseline. On moving frames require silhouette IoU
≥0.90 against each frame's ground truth and zero changes in the protect boxes
relative to the keyer. Record residual shimmer and any lag. A failure keeps
the existing keyed artifact path.

Story [451](https://work.haynesnetwork.com/work_packages/451) takes **one**
authorized private cast still with visible lashes, flyaways and green eyes
against chroma, if available. Pin its version and hash, create one private
output, composite it over light and dark plates, and inspect at source zoom.
Record source/receipt/output hashes, model/profile, timing, peak RSS, bboxes
and scale. Mark iris interiors and hair/eyelash detail before the run. Require
the per-eye synthetic criterion on those interiors, retain both visible lash
lines, and keep at least 8 of 10 premarked visible flyaways with no
conspicuous green halo on either plate. Report missed details, whether any
manual correction would be needed and how much, and keep the asset unpromoted
if it fails. An unrepresentative or unavailable authorized fixture leaves
private quality pending. Share the numerical evidence and private locators
through the story. Keep Tom's verdict separate.

The CI image smoke uses a generated channel-mean ONNX graph. It verifies
the pinned wheel, CPU session, Unix HTTP, PNG and receipt read-back. The
install Job runs `studio-matting smoke` with the real profile and prints
one JSON report with per-region metrics, verdicts, hashes, cold load,
wall time per request and peak RSS. It reports the sum of supervisor and
worker RSS peaks as a conservative upper bound.

Real profile load, cold-load/latency/RSS, installed health and rollback
read-back, and painted-eye, fringe and clip behaviour remain **Expected**.
