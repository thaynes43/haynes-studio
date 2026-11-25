# Upscaling backend profile

**Comparison profile, 2026-11-25** for [story 461](https://work.haynesnetwork.com/work_packages/461).
Pilot **FSRCNN ×2 FP32 on OpenCV DNN CPU**. Keep **Pillow Lanczos** as the
explicit fallback and current delivery default. Provisional
[ruling 35](../contracts/studio-contracts-v1.md#ruling-35) chooses FSRCNN for
comparison only. Selection stays gated by the install smoke and Tom's
review of a private comparison. Both choices use zero GPU lease time.

The E0 assembly scaled 576 × 1024 clips to 1080 × 1920 (1.875×) and reported
soft hair and lettering. The other master orientation is 1920 × 1080. D22–D24
favor layered speech-to-video for dolls and identify slipping lettering and
wardrobe changes as defects. The scaler must preserve visible strokes, face
features and stable motion. It cannot reliably reconstruct lettering already
damaged by the generator. Keep the pinned source clips, plate and checks under
D15, and leave the advisory format length under D45 separate from resource
admission for an individual scaler request. [E0 findings](../../titles/the-winter-menu/video-e0/findings.md#what-e0-means-for-the-plan) ·
[Layered follow-up](../../titles/the-winter-menu/video-e0/findings-layered.md) ·
[S2V follow-up](../../titles/the-winter-menu/video-e0/findings-s2v.md) ·
[Studio plan](../proposals/0003-studio-plan.md#decisions-so-far) ·
[Delivery conversion](delivery-conversion.md) · [Delivery sizes and clock](studio-delivery.md)

## Candidate evidence

Publisher sources, release notes and artifact metadata were read on
**2026-11-25**. Sizes are bytes on disk. Peak process RAM and GPU memory need
their own measurements. Matching speed and memory for a 576 × 1024 input on
the two-thread render CPU and a single 24 GB RTX 3090 are unknown for all four
weights. The measurements below specify the workload they apply to.

| Candidate | Scale and quality evidence | Motion, determinism and cost |
|---|---|---|
| **FSRCNN** compact CNN, `Saafke/FSRCNN_Tensorflow` | Publisher offers ×2, ×3 and ×4, trained on T91 and fine-tuned on General100. Use ×2 then downsample from 1152 × 2048 with Lanczos. The network runs on luma and leaves chroma reconstruction to linear interpolation. OpenCV's ×2 General100 test reports 32.889 dB PSNR and 0.9301 SSIM, against Lanczos at 32.469 dB and 0.9327. This is a small mixed result on synthetic downscales of fine-tuning images. Thin character edges may improve in luma. Equal-luma lettering, doll identity and hair retention are unmeasured. | One fixed feed-forward graph per frame with no random state. Subpixel motion can still modulate the predicted edges. OpenCV reports 6.325 ms on CPU for the butterfly with 256² reference output (128² input) and 21.741 ms average on General100, with no CPU model, thread count or RSS reported. The pinned headless wheel is CPU-only. Single-card GPU measurements and VRAM for these weights are unknown. [Publisher](https://github.com/Saafke/FSRCNN_Tensorflow/tree/6a4812c4ef1c4f5947d79beafa32a05a6eb4a94d) · [OpenCV benchmark and method](https://docs.opencv.org/5.0/tutorials_contrib/dnn_superres/benchmark/sr_benchmark.html) · [Color pipeline](https://github.com/opencv/opencv_contrib/blob/4.14.0/modules/dnn_superres/src/dnn_superres.cpp) · [Wheel capabilities](https://pypi.org/project/opencv-contrib-python-headless/4.14.0.94/) |
| **Swin2SR Lightweight ×2**, shifted-window transformer from `mv-lab/swin2sr` | This checkpoint is for ×2 lightweight image SR. Use the same ×2 then Lanczos reduction. The paper evaluates classical, lightweight and compressed restoration with separate tasks and weights. The lightweight ×2 model scores 32.85 dB on Urban100 and 39.32 dB on Manga109, evidence of reconstruction on synthetic stills with line structure. Published evidence for matching a doll's eyes or lettering strokes on compressed S2V is unknown. | Inference has no sampling or clip state. Window padding and tiling affect predictions, and edges can change as objects cross attention windows. Fixed graph, padding, runtime and hardware would need a byte-repeat smoke. A research comparison reports 166.97 ms mean on Urban100 for its Swin2SR ×4 configuration on an RTX 3080. This is a different scale, device and input distribution. Comparable ×2 CPU latency/RSS and 24 GB GPU latency/VRAM are unknown. [Paper](https://arxiv.org/abs/2209.11345) · [Author repository](https://github.com/mv-lab/swin2sr/tree/6f25d7689813f7dd12c5a212b638066fa71bc9e6) · [Publisher checkpoint](https://huggingface.co/caidas/swin2SR-lightweight-x2-64/tree/07e8e61492ce6daf4f34c651622960faf110c17f) · [Research comparison, Table 6](https://ojs.bonviewpress.com/index.php/AIA/article/download/1930/772/12360) |
| **BasicVSR++ REDS4 BI ×4**, bidirectional video restoration from `ckkelvinchan/BasicVSR_PlusPlus` with OpenMMLab weights | ×4 on the selected checkpoint, then a 0.46875× Lanczos reduction for the 1.875× delivery target. The authors show recovery of wheel spokes, stairs and detail through partial occlusion using aligned neighbor frames. The paper has no controlled printed-text or doll-face result. Applying it to one still would give up the evidence from temporal context. | Second-order propagation and flow-guided deformable alignment use frames on both sides. Cut boundaries and chunking affect output and can create discontinuities. Fixed clips and a pinned PyTorch/MMCV build would need a repeat test covering deformable ops, device and chunk boundaries. The paper reports 77 ms at 180 × 320 LR with ×4 reconstruction and does not name the timing device in Table 1. The upstream training listing names V100s. A separate comparative experiment reports 60.2 ms on an RTX 3090 without giving comparable target-size peak VRAM. CPU operation and latency/RSS and single-card latency/VRAM at the target size are unverified. [Paper, Table 1 and figures 4–6](https://openaccess.thecvf.com/content/CVPR2022/papers/Chan_BasicVSR_Improving_Video_Super-Resolution_With_Enhanced_Propagation_and_Alignment_CVPR_2022_paper.pdf) · [OpenMMLab model and config](https://github.com/open-mmlab/mmagic/tree/0a560bba9b79ebe78574e1d4cbbdd0e798e63568/configs/basicvsr_pp) · [RTX 3090 timing, Table 6](https://www.aas.net.cn/article/doi/10.16383/j.aas.c240235) · [PyTorch reproducibility](https://docs.pytorch.org/docs/stable/notes/randomness.html) |
| **Stable Diffusion ×4 Upscaler**, `stabilityai/stable-diffusion-x4-upscaler` | Image-conditioned, text-guided latent diffusion with optional source noise. ×4 followed by reduction to 1.875× would still retain invented detail. The publisher card says “The model cannot render legible text” and warns that it may generate faces incorrectly. No quantitative evidence for preserving input decal strokes or doll identity. | Image-only pipeline with no motion constraints. Reusing a seed can reproduce randomness under a fixed build, but gives no guarantee that adjacent source frames yield stable textures. Diffusers documents 75 denoise steps by default and its example uses FP16 CUDA for a 128² input. Comparable target CPU latency/RSS and single 24 GB card latency/VRAM are unknown. The letter and motion requirements rule it out for this pilot. [Model card](https://huggingface.co/stabilityai/stable-diffusion-x4-upscaler/blob/572c99286543a273bfd17fac263db5a77be12c4c/README.md) · [Pipeline](https://huggingface.co/docs/diffusers/main/en/api/pipelines/stable_diffusion/upscale) · [Diffusers reproducibility](https://huggingface.co/docs/diffusers/en/using-diffusers/reusing_seeds) · [Diffusers 0.43.0 release](https://pypi.org/project/diffusers/0.43.0/) |

BasicVSR++ has the strongest reason to help motion. Its ×4 cost and adjoining
frames make it a different delivery integration. As a queue-sizing sensitivity
check only, extrapolating 77 ms by the pixel ratio of 10.24 gives about 0.79
s per frame or 4 minutes of inference for 300 frames, before load, transfer,
blocking, chunk overhead and verified release. This arithmetic is neither a
3090 measurement nor an upper bound. A future GPU proposal could batch a
bounded clip after Wan generation and share one model load within its job. It
would hold the entire Wan/Foley/local-model lease from admission through
release and delay the next queued job accordingly. Whole-run batching would
extend that wait. This proposal uses CPU on the Studio render worker under
D18 and D50. [Studio plan](../proposals/0003-studio-plan.md#decisions-so-far)

### Artifact identities and licence terms

| Exact weight file | Bytes and publisher digest | Licence evidence |
|---|---|---|
| **Primary** `Saafke/FSRCNN_Tensorflow` at `6a4812c4ef1c4f5947d79beafa32a05a6eb4a94d`, `models/FSRCNN_x2.pb` | **38,973**. Git blob SHA-1 `2509b0e19b8a45ebce2ba50128e2fcb43ce8589c`. The raw response supplies an ETag, and the publisher supplies no documented file SHA-256. The install must verify the Git object digest and record the actual raw-file SHA-256. [Publisher tree metadata](https://api.github.com/repos/Saafke/FSRCNN_Tensorflow/git/trees/6a4812c4ef1c4f5947d79beafa32a05a6eb4a94d?recursive=1) | Repository Apache-2.0 grants a licence to “reproduce, prepare Derivative Works of” the Work and specifies redistribution notices. The graph is in the licensed repository. Applying the repository licence to the graph is plausible. A specific weight grant and separate output terms are unknown. [Publisher licence](https://github.com/Saafke/FSRCNN_Tensorflow/blob/6a4812c4ef1c4f5947d79beafa32a05a6eb4a94d/LICENSE) |
| `caidas/swin2SR-lightweight-x2-64` at `07e8e61492ce6daf4f34c651622960faf110c17f`, `model.safetensors`. CPU-oriented export `Xenova/swin2SR-lightweight-x2-64` at `92a21aca5713f20faf9a87590cdfbdce2e34112c`, `onnx/model.onnx`. | **4,082,952**, SHA-256 `1b7a135af7de4287289c59939bf735de5afa9927a943bd946920acdcf4dd6365`. Export **8,078,888**, SHA-256 `c2abbfe0cc8e685b5e11964970f8ebe3d24072e904fd5545a30ac31ec1e110db`. [Checkpoint metadata](https://huggingface.co/api/models/caidas/swin2SR-lightweight-x2-64/revision/07e8e61492ce6daf4f34c651622960faf110c17f?blobs=true) · [Export metadata](https://huggingface.co/api/models/Xenova/swin2SR-lightweight-x2-64/revision/92a21aca5713f20faf9a87590cdfbdce2e34112c?blobs=true) | Base card says `license: apache-2.0`. The author's code uses “Apache License, Version 2.0”. The exporter points to the base checkpoint and states no separate licence. Export-specific and output terms are unknown. [Code licence](https://github.com/mv-lab/swin2sr/blob/6f25d7689813f7dd12c5a212b638066fa71bc9e6/LICENSE) · [Base card](https://huggingface.co/caidas/swin2SR-lightweight-x2-64/blob/07e8e61492ce6daf4f34c651622960faf110c17f/README.md) · [Export card](https://huggingface.co/Xenova/swin2SR-lightweight-x2-64/blob/92a21aca5713f20faf9a87590cdfbdce2e34112c/README.md) |
| `basicvsr_plusplus_c64n7_8x1_600k_reds4_20210217-db622b2f.pth`. Training config also names `spynet_20210409-c6c1bd09.pth`. Weight completeness without the separately fetched SPyNet has not been checked. | Main **29,349,005**, SPyNet **5,770,988** from HTTP HEAD. Publisher `Content-MD5` headers `hc7u/ZkaxNDMmZlYNvNpRQ==` and `UYXQZ3ZFQWrNGJKLHbnB4A==` respectively (base64). The filenames give 8-character suffixes of undocumented meaning. Full SHA-256s are unknown. [Main artifact](https://download.openmmlab.com/mmediting/restorers/basicvsr_plusplus/basicvsr_plusplus_c64n7_8x1_600k_reds4_20210217-db622b2f.pth) · [SPyNet artifact](https://download.openmmlab.com/mmediting/restorers/basicvsr/spynet_20210409-c6c1bd09.pth) · [Config](https://github.com/open-mmlab/mmagic/blob/0a560bba9b79ebe78574e1d4cbbdd0e798e63568/configs/basicvsr_pp/basicvsr-pp_c64n7_8xb1-600k_reds4.py) | Author and MMagic **code** are “Apache License” version 2.0. Separate grants for both hosted weight files and outputs are unknown. [Author licence](https://github.com/ckkelvinchan/BasicVSR_PlusPlus/blob/master/LICENSE) · [MMagic licence](https://github.com/open-mmlab/mmagic/blob/0a560bba9b79ebe78574e1d4cbbdd0e798e63568/LICENSE) |
| `stabilityai/stable-diffusion-x4-upscaler` at `572c99286543a273bfd17fac263db5a77be12c4c`, `x4-upscaler-ema.safetensors` monolith. Diffusers FP16 distribution uses separate text encoder, UNet and VAE files. | Monolith **3,531,269,371**, SHA-256 `35c01d6160bdfe6644b0aee52ac2667da2f40a33a5d1ef12bbd011d059057bc6`. Component pins below. [Publisher LFS metadata](https://huggingface.co/api/models/stabilityai/stable-diffusion-x4-upscaler/revision/572c99286543a273bfd17fac263db5a77be12c4c?blobs=true) | The model card names “CreativeML Open RAIL++-M License”, a use-restricted licence family. The linked licence returned `401 Unauthorized`. Exact restrictions, attribution and terms for commercial use of these weights and their outputs stay unknown. [Publisher card](https://huggingface.co/stabilityai/stable-diffusion-x4-upscaler/blob/572c99286543a273bfd17fac263db5a77be12c4c/README.md) · [Linked licence](https://huggingface.co/stabilityai/stable-diffusion-2/blob/main/LICENSE-MODEL) |

| Diffusers FP16 component at the same revision | Bytes | Published SHA-256 |
|---|---:|---|
| `text_encoder/model.fp16.safetensors` | 680,821,096 | `681c555376658c81dc273f2d737a2aeb23ddb6d1d8e5b3a7064636d359a22668` |
| `unet/diffusion_pytorch_model.fp16.safetensors` | 946,878,752 | `473c61882010d657c0c3aa27f62ee85d4b8cd3b40a4877b19a05d05bb4df20bb` |
| `vae/diffusion_pytorch_model.fp16.safetensors` | 110,674,374 | `68e6ec66e1d85ad6f5d017b1489626b36677522cdb568191ef9d5a2ee1df308d` |

D48 records terms and D49 keeps research and personal use available. Before
commercial use, replace BasicVSR++ or the diffusion upscaler if the missing
weight or output terms remain unresolved, and use the publisher's Swin2SR
checkpoint or confirm the export's terms before adopting it. For FSRCNN,
obtain confirmation of the weight grant and output terms before commercial
use or replace it with a profile whose terms are established. The
publisher's Swin2SR checkpoint has a permissive weight tag with notice terms.
Check separate output terms and the full input chain for commercial use.
Record wheel redistribution terms if an image is distributed. [D48 and D49](../proposals/0003-studio-plan.md#decisions-so-far) ·
[Proposed upscaling licence rows](model-licences.md#proposed-upscaling-profiles)

## Profile settings

| Setting | `fsrcnn-x2-opencv-cpu-v1` | `lanczos` (existing v1 profile) |
|---|---|---|
| Runtime | `opencv-contrib-python-headless==4.14.0.94` on CPython 3.12 Linux amd64. `DNN_BACKEND_OPENCV`, `DNN_TARGET_CPU`, FP32, OpenCL off, `cv2.setNumThreads(2)`, one inference in flight. Keep other math pools at one thread. Pin the effective OpenCV CPU features reported by `getCPUFeaturesLine()` and the exact CPU model on talosw01. Admit that runtime configuration only after repeatability is verified. | Pillow 13.0.0 from the Studio lock. One frame at a time on CPU, one worker, no separate accelerator or model file. |
| Resize | Opaque RGB8 to BGR8, `DnnSuperResImpl` with `setModel("fsrcnn", 2)`, verify BGR8 ×2 shape, back to RGB8, then Pillow 13.0.0 `Resampling.LANCZOS` to the exact target. A ×2 target needs no second resize. | Same-aspect clip calls Pillow `Resampling.LANCZOS` once. Plates use the existing centred Lanczos cover fit. |
| Tile and overlap | Whole frame, e.g. one 576 × 1024 tile, 0 px overlap. Maximum graph input 720 × 1280 or 1280 × 720. No tile seams or padding policy. Larger graph inputs require a different profile. | Whole frame, 0 px overlap. |
| CPU and memory budget | Two vCPUs maximum, one job. 2 GiB quality target. Serving request and limit await measurement. 30 s ready-process startup cap, 5 s per-frame hard deadline from verified input staging through output validation, 300 s from first frame dispatch to clip completion. | Same offline CPU allocation, reserve 512 MiB for one work item. |
| Warm planning range for 100 input frames (576 × 1024 → 1080 × 1920) | **30–80 s**, including local RGB PNG I/O, graph, fit and encode. 300 input frames cost about 90–240 s before startup or unexpected NFS stalls. | **10–30 s** including the same local RGB PNG I/O and encode, excluding ordinary video decode and mux. |

The ranges are estimates. OpenCV's butterfly area extrapolation
(`6.325 ms × 36 ≈ 228 ms`) is a rough compute anchor for FSRCNN. Hardware and
thread settings differ, and at delivery size PNG I/O can dominate either
profile. Measure it in the bounded smoke. The CPU choice avoids both ComfyUI
and Wan contention. OpenCV 5.1.0 was current at the check. This profile pins
4.14.0 to match the package's current OpenCV core line and uses the contrib
wheel for the published source API. [Upstream 4.14.0 release](https://github.com/opencv/opencv/releases/tag/4.14.0) ·
[Upstream change log](https://github.com/opencv/opencv/wiki/OpenCV-Change-Logs) ·
[OpenCV runtime configuration](https://docs.opencv.org/4.14.0/d6/dea/tutorial_env_reference.html) ·
[Pillow release](https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html) ·
[Studio lock](../../uv.lock)

## Artifact contract for delivery conversion

The worker contract and two one-shot workloads are staged. The delivery
consumer, cache grouping and profile selection described here are future
integration, gated by CR-35.

The existing renderer resolves `DeliveryUpscalerProfile` by
`delivery_profile_sha256`. Add the learned backend's manifest SHA-256 to the
canonical conversion profile so a changed weight, worker image, setting or
resize implementation rekeys board segments. Both the planner and renderer
read the same frozen manifest. The baseline, including resolution of old keys
without a profile, keeps its existing digest and semantics. Backend selection
does not change shot timing, proxy downscale, or the established inputs of
voice, video generation and keying. Request each distinct shown source frame
once per target and repeat the result on the current board clock
(`0, 0, 1, 2, 2, 3, …` for 16 → 24 fps). The actual frame clock stays outside
this image operator. [Current conversion profile](delivery-conversion.md) ·
[Extension point](../../src/haynes_studio/render/delivery_profile.py) ·
[Cache and splice](cache-and-splice.md)

Use this profile at the opaque whole-frame clip and set-loop resize points and
at still plate fit when the fitted image needs supported upscaling. For a
learned plate crop, fit the largest exact-aspect integer box before scaling,
using target ratio 9:16 or 16:9 in lowest terms. Center the crop, rounding the
left and top origins down. Equal-size clip frames pass through, and a
mismatched clip aspect fails. Existing direct Lanczos downscale and plate
cover apply when the operation is downscale-only or an equal-size fit. Keep
keyed RGBA sprites on the existing compositor path. The current layered
renderer calls the extension for its background loop. It resizes its doll
sprites separately after keying and decal tracking. An opaque S2V original
can exercise this profile in the comparison. Replacing the RGBA foreground
path needs a separate decision backed by alpha-edge and decal evidence.
[Layered adapter](layered-adapter.md) ·
[Layered renderer](../../src/haynes_studio/layered/renderer.py) ·
[Decal gate](wardrobe-decal-checks.md#decal-drift)

For each source frame sent to the learned worker, freeze one
`studio.upscale-frame-request/v1`. The existing local Lanczos path resolves
from its conversion digest and does not need a worker request. All fields are
required. Refuse unknown or duplicate fields. The input signature is
`sha256:<hex>` over store-canonical JSON of the request. Fields ending in
`sha256` are bare lowercase 64-hex digests.

| Field | Value |
|---|---|
| `schema` | `studio.upscale-frame-request/v1` |
| `source` | `{sha256,bytes,media_type,width,height}`. Single lossless opaque RGB8 PNG, no ICC profile, alpha, animation or orientation metadata. The caller decodes and normalizes an authorized source frame to RGB8 and records the original clip/plate hash, source index and crop with the delivery record. Encode normalized input PNG using the same fixed PNG settings as output. Refuse invalid PNG dimensions before decoding. |
| `target` | `{width,height}` of exactly 1080 × 1920 or 1920 × 1080. Source is already cropped for a plate and must match aspect exactly. Require scale in `(1,2]`, 1280 px max long edge, 921,600 input pixels max and 4 MiB encoded input max for the learned path. |
| `profile_id`, `profile_sha256` | The selected ID and SHA-256 of its canonical manifest. The learned manifest pins upstream repository/revision, graph filename and raw-file SHA-256, image digest, wheel names and SHA-256s, adapter and native tool SHA-256s, CPU/provider/feature mask and all fixed crop, tensor, resize and PNG parameters. |

The authorized delivery runner reads or produces the source by hash within its
existing run claim. It stages verified PNG bytes under a fresh 32-hex attempt
directory. The worker receives `{attempt_id,request}` via `POST /v1/upscale-frame`
over a Unix socket and rehashes `input.png` before using it. The worker owns a
separate output subdirectory and exclusively creates `output.png` there (RGB8,
Pillow fixed PNG `compress_level=1`, `optimize=False`, no timestamps or
ancillary metadata, 8 MiB max). Confine reads and writes to regular files in
the preallocated scratch, refuse symlinks, and accept only the fixed
filenames. There are no caller URLs, paths, model files or graph options.

The worker closes and hash-verifies the output, then returns canonical
`studio.upscale-frame-result/v1` with `schema`, `request_sha256` (the bare
hex of the input signature), `source`, `target`, `output` (same fields as
`source`), and `provenance` (the full admitted manifest and
`profile_sha256`). Put timing, RSS and attempt IDs in a separate run
observation to keep the stable result reproducible. The runner rehashes and
decodes the output from the verified descriptor, publishes both PNGs to the
production's create-only content paths, and re-verifies before completing a
stage. A part or uncompleted stage has no consumer. Group up to 100 requests
in first-use order. The stage name is `upscale-<hex>`, with hex computed from
the SHA-256 of the canonical JSON array of those ordered request digests.
List the source and output blobs as `input.000` and `frame.000` and so on,
plus `receipt`, a JSON array of their results in that order. Each stage holds
at most 201 entries, under the 256-output limit. The consuming segment waits
for all the groups it expects. Exact frame and request hash matches can reuse
a verified receipt and artifact within the authorized production.
A mismatch fails with evidence. Existing artifacts are immutable and no
automatic purge runs. [Stage and store contract](../contracts/studio-contracts-v1.md#atomic-create-only-publication) ·
[Store output limit](../../src/haynes_studio/store/records.py)

Run one request at a time, at most 300 distinct source frames per clip. Bad
input, unknown or unready profile, output mismatch, exhausted time or resource
budget and incomplete groups refuse the consuming build. On timeout, reap
the in-flight child before dispatching another job. Selecting Lanczos is an
explicit new build plan with its own conversion digest. A backend failure
does not rewrite the plan or use a different filter for individual frames.

## Download, image and workload

Read-only on **2026-11-25**, `kubectl -n ai get deploy studio-render` reported one
ready replica on talosw01, limited to **20 vCPUs and 32 GiB**. Read-only
`df -kP /studio`, `df -iP /studio` and
`stat -f -c '%S %a %c %d' /studio` in that container showed
**110,936,790,663,168 bytes free (100.90 TiB)**. Free inodes were unreported
(dash in `df`, `-1` in `stat`). The later queue-worker rollout reduced D18's
original 24-vCPU render allocation by four. The pilot uses the observed
20-vCPU limit and the queue worker's separate four-vCPU allocation. [Rollout evidence, comment 9872](https://work.haynesnetwork.com/work_packages/956) ·
[Render service](services.md#studio-render-cpu-work) · [Repository rules](../../AGENTS.md)

- One primary download totals **38,973 weight bytes**, leaving
  **110,936,790,624,195 bytes** before metadata at the read-back. Lanczos has
  zero weight bytes. Stream the immutable source to one unique staging file in
  a fresh job directory under existing `/studio/jobs`. Check length and the Git blob SHA-1 (the hash of the Git blob header and
  bytes). A bounded in-memory read from the immutable publisher URL
  verified that blob and gave raw SHA-256
  `366b33f0084c7b3f2bf6724f0a2c77bca94fcec9d7b6d72389d330073b380d5c`.
  The private provisioner independently verifies both hashes after
  flushing and dropping its write cache. Provision on talosw01 to capture
  the exact CPU model and OpenCV CPU features in the immutable manifest. Finalize
  create-only and mount that job's immutable weight directory read-only at
  `/weights`. The allocation carries `FSRCNN-NOTICE` from the pinned Studio
  image. It records the publisher's Apache-2.0 repository licence and the
  unconfirmed weight and output terms. Recheck the provisioned file at startup
  and keep weights out of build layers and public git.
  [Pinned weight URL](https://raw.githubusercontent.com/Saafke/FSRCNN_Tensorflow/6a4812c4ef1c4f5947d79beafa32a05a6eb4a94d/models/FSRCNN_x2.pb)
- Reserve **8 GiB and at most 1,024 new filesystem entries** for one install,
  smoke and one bounded comparison or up-to-300-frame clip. Allow up to 600
  new frame blobs, up to 256 additional hash-prefix directories within the
  production, and up to 168 other entries for manifests, receipts, staging,
  fixture and failed-attempt accounting. For a clip, 300 × (4 + 8) MiB is
  3,600 MiB of bounded PNGs before diagnostics. Keep at least **32 GiB**
  available after reservation. This reserve leaves **110,928,200,728,576 bytes**
  at the observation. Re-read before provisioning. Have the existing storage
  owner establish a reserve of at least 1,024 further free entries if NFS
  still omits the count. Track output entries and stop at budget; count retained
  failed attempts before a retry.
- Build the Linux amd64 worker from the Studio digest-pinned CPython 3.12
  slim Bookworm base. Install only one OpenCV flavor in its isolated
  environment. Pin the contrib wheel
  `opencv_contrib_python_headless-4.14.0.94-cp37-abi3-manylinux_2_28_x86_64.whl`
  (**68,184,831 bytes**, SHA-256
  `3ee9718fc1eb2d4439c72ec6ad65831ff6d0802ff6eacab834905d67686f2a38`)
  and Pillow
  `pillow-13.0.0-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl`
  (**7,144,542 bytes**, SHA-256
  `42d63be3af4f9b951b199b0a9d23365d37ab14687e6d77b74940432c8515c4ca`).
  Those two wheels total **75,329,373 bytes** before base and dependencies.
  Pin the Linux amd64 NumPy 2.4.6 wheel from the lock (**16,645,538 bytes**,
  SHA-256 `90f9849678c75fe7afa2d348ac842c168b0a4d3d61919687216dfc547976d853`).
  The image build verifies the three exact wheel hashes against the
  Studio lock. It keeps their installed licence and bundled-library notices.
  Keep the contrib wheel out of the main package's `cv2` environment. Include
  OpenCV, Pillow and bundled-library notices and applicable redistribution
  obligations. Cap at 1 GiB installed image and 2 GiB temporary build space
  separately from the share budget. The build checks the temporary
  package and source footprint and the workflow checks image size.
  [Studio base](../../docker/studio.Dockerfile) ·
  [OpenCV wheel metadata](https://pypi.org/pypi/opencv-contrib-python-headless/4.14.0.94/json) ·
  [Studio lock](../../uv.lock) · [Wheel licensing](https://pypi.org/project/opencv-contrib-python-headless/4.14.0.94/#licensing)
- In haynes-ops, pin the approved image by registry digest and use a
  serial install smoke Job on talosw01 with `backoffLimit: 0` and
  `activeDeadlineSeconds: 300`. Use the render worker's low-priority CPU
  allocation and a window without other heavy renders. The first smoke
  requests 2 GiB and has an 8 GiB measuring allowance. The 2 GiB quality
  target is reported from measured cgroup peak. Set serving memory in a
  separate change from the phase evidence. For continued use,
  place one local worker beside `studio-render` and carve two vCPUs from
  its 20-vCPU allowance for inference (18 for render, 2 for the scaler).
  Count the scaler within the 32 GiB allocation and coordinate concurrent
  matting or render workloads under the same caps. Run as UID/GID 10001,
  dropped capabilities, RuntimeDefault seccomp, read-only root and weights,
  no service-account token, ingress, GPU request or runtime download. Share
  only the Unix socket and bounded scratch (256 MiB `emptyDir`). The
  caller and backend share GID 10001 and use setgid, group-writable attempt
  and result directories with group-readable PNGs. The caller holds store
  credentials and production access. Readiness checks
  decoded graph metadata and admitted manifest/image/tool identity. Roll
  back by withdrawing the policy stage in Git and retaining the private
  files. After future activation, withdraw profile admission from new
  builds, then revert the worker and offline CPU split. The coordinator
  records the image digest, measured peaks and health at installation.
  [Ops runbook](https://github.com/thaynes43/haynes-ops/blob/main/docs/reference/studio-upscaling-deployment.md)

## Install smoke and private comparison

Cluster steps are **Expected**. The built-image check uses a generated CPU
graph and an isolated read-only container with networking disabled. The
coordinator runs the following using the verified weights and fresh scratch.
Run both profiles on identical source PNGs. Use Lanczos as the reference for
the FSRCNN quality and resource gates. Record input, output and profile
hashes, cold start, warm mean/p95 and maximum wall time, peak RSS and cgroup
memory, staged bytes and frame count. A repeated frame after a fresh worker
process must give identical PNG and stable receipt bytes. Check both
orientation shapes, unknown profile, wrong input hash, oversized request and
a forced mid-request failure. Confirm the latter publishes no completion
record and a retry uses a new attempt without disturbing verified files.
Measure luma as `0.2126R + 0.7152G + 0.0722B` on the encoded RGB samples.

1. Draw a 1080 × 1920 RGB reference with integer rectangles and lines. Use
   5 × 7 bitmap glyphs spelling `R8H2` in a printed strip with 2, 3 and 4 px
   cells (14, 21 and 28 px cap heights). Include dark on light, light on
   dark, and a colored label. Draw a slightly slanted edge between neutral
   levels 32 and 224, a 128-gray rectangle and a doll-like face with asymmetric
   lashes and two different eye highlights. Store ground-truth ROI coordinates
   with the fixture. Downsample with Pillow BOX to 576 × 1024. Exercise a
   landscape still from the transposed target and a plate with an off-aspect
   border that has a known centered crop.
2. For both profiles, measure 10–90% luma edge spread by aligning scanlines
   to the analytic edge and interpolating the two crossings. Require FSRCNN
   median spread **≤ 0.90× Lanczos**. On the 21 and 28 px text, classify each fixed
   glyph cell by minimum mean squared error to the ground-truth bitmap
   templates of the four glyphs at that size. Require all glyphs correct and
   mean text-ROI luma absolute error no worse than Lanczos, including the
   14 px band. Inspect lashes and highlights in the synthetic face for changed
   geometry. Require each eye highlight and lash endpoint to stay within
   1 output pixel of the ground-truth feature on the synthetic still. Report
   each band's scores, including any ambiguous small text.
3. On each side of the slanted edge, measure overshoot beyond 32/224 within
   8 output pixels of the edge (gray levels). Require peak **≤ 12/255** and
   **≤ Lanczos peak + 2/255**. In the interior of the gray rectangle, at
   least 32 output pixels from any boundary, require luma standard deviation
   **≤ 1/255** and absolute mean shift **≤ 2/255**. Metrics expressed as
   fractions of 255 use normalized luma. Check neutral RGB channels stay within
   2 levels of one another in the flat ROI.
4. Generate **16** consecutive reference frames as in step 1 with the printed
   strip and a fine bar pattern moving horizontally by 1 delivery pixel per
   source frame (8/15 input pixel). Downsample every reference separately.
   Invert that motion by integer output shifts and use the common interior ROI
   across all frames. Compare consecutive motion-aligned luma residuals
   (output minus matching ground truth). Require the worst pair's mean
   absolute residual change **≤ 2/255** and **≤ Lanczos + 0.5/255**. Require
   the worst pair's p95 absolute residual change **≤ Lanczos + 2/255**.
   Also verify the identical background ROI and exact reference cadence if
   replaying these frames at 24 fps. Check mean warm time **≤ 0.80 s/frame**,
   p95 **≤ 2 s**, each frame under its 5 s deadline and measured job memory
   at or below the 2 GiB quality target. Extrapolate cost to 100 frames
   from the observed mean.

5. Measure both the default and `compact-allocator` processes in the first
   cluster smoke with `--allocator compare`. Use `--allocator default` for
   a baseline-only diagnostic. The compact setting uses glibc arena
   maximum 1 and fixed 128 KiB trim and mmap thresholds. Freeze these settings in separate smoke
   profile digests. Compare every generated PNG byte for byte between the
   two settings, and each setting's PNG and canonical receipt against its
   fresh-worker replay. Record worker phase high-water and post-phase RSS,
   sampled cgroup memory by phase and the kernel's whole-job cgroup peak.
   Report the running container's cgroup memory limit from `memory.max`.
   The serving profile has no allocator override. The generated
   maximum-size graph input adds a 19th evaluated frame per setting.

The Studio coordinator owns the graph provisioning and cluster smoke.
Under provisional CR-49, the staged one-shot comparison Job accepts an
authorized opaque PNG/JPEG still or one frame of a stored MP4 delivery proxy.
Both arms start with the same decoded RGB8 image. For frames, the
baseline calls the delivery profile's exact-aspect Lanczos scaler. For plates,
it calls `fit_set_plate`, which combines a centered, fractional cover crop with
Lanczos in one operation. The FSRCNN arm processes the same full RGB8 image
through ×2 inference immediately before that same final delivery function.
For a plate the cover box scales with the ×2 image, so both arms use the same
field of view. The cover-fit request is internal to the one-shot command.

For video, pass the canonical store locator via `--proxy` and choose exactly
one selector. `--frame-index` is zero-based. `--timestamp` is nonnegative
decimal seconds from the first frame, with up to nine decimal places. It
selects the frame displayed at that time (`floor(seconds × 24)`). The pinned
OpenCV wheel's FFmpeg backend decodes the selected frame directly from the
hashed, read-only file descriptor with one decoder thread. The files must
follow the zero-based 24 fps delivery clock and the selected frame must exist
on that clock. The reader checks the first presentation timestamp against the
sample and edit tables in an unfragmented MP4 with a single video track,
before OpenCV can round or rebase it. A nonzero
origin is refused with `adapter.nonzero_start_timestamp`. The decoder also
checks the selected frame in delivery frame ticks.
Each MP4 has a 256 MiB bound. Proxy frames must meet the 1280 px long
edge and 921,600 pixel limits, match the target aspect and scale by more than
1× and at most 2×. An optional `--master` supplies the same frame index, at
the exact target size and with the same frame count. The caller verifies
the pairing against the delivery record and supplies its `--delivery-id`.
A master without that ID is refused with `adapter.delivery_id_required`.
The report records the ID beside both hashes and credits the caller with
verifying the pairing.
The Job refuses invalid locators, file types, sizes, frame geometry and
decode failures with `adapter.request_invalid`, a wrong content hash with
`adapter.pin_mismatch`, and a selector beyond the file with
`adapter.frame_out_of_range`.
[Delivery clock and format](studio-delivery.md#checks) ·
[OpenCV FFmpeg capture](https://github.com/opencv/opencv/blob/4.14.0/modules/videoio/src/cap_ffmpeg_impl.hpp)

Run `studio-upscaling compare --probe` with the same video locators,
delivery ID when paired, orientation and frame selector before the idle
gate. The probe hashes and decodes the inputs without loading the model or
running a scaler. It prints one JSON line with the frame count, dimensions,
first timestamp in seconds and selector result for the inputs it reads.
Refusals exit nonzero and include a code and any available frame facts.

An init container reserves one new group-writable private jobs directory. The
comparison writes `lanczos.png`, `fsrcnn.png`, and `report.json` there, plus
`proxy.png` and, when supplied, `master.png` for video inputs. All files are
create-only. The Job mounts the input hash shards and pinned weights read-only.
The report and logs keep store paths and private names out. They record
hashes, sizes, frame selection, timing, memory and objective measurements.
Report luma differences at output and source scale, edge energy and fixed
lettering, face or hair ROI scores where supplied. Plate source-scale scores
use the cover-fitted half-delivery grid.

With a master, also report normalized luma MAE, luma PSNR in dB and luma SSIM
for each arm against the decoded master, plus reference MAE for each supplied
ROI. PSNR is recorded as `null` on an exact luma match. SSIM averages 11 × 11
Gaussian windows (σ = 1.5) wholly inside the frame. The report and printed JSON
carry `ground_truth_scope` alongside the metrics. The proxy is an encoded
downscale of the master. These measures reward undoing that specific encode
and do not establish quality on real low-resolution sources. The analytic
glyph, edge and cadence checks above apply to the generated smoke fixtures.
Inspect glyphs, face geometry and halos at 1:1 using the private pair.
**Comparison pending.**

For delivery story [453](https://work.haynesnetwork.com/work_packages/453),
use one authorized excerpt of up to **64 contiguous source frames** from the
archived build's pinned *One More Meeting* 576 × 1024 S2V clip.
Resolve and verify the authorized private clip by the build's source hash.
If that source is unavailable, record the comparison as pending. Use the same
trims, take, decal evidence and clock for both profiles. Choose the
start index and fixed face/hair/lettering ROIs from the original before
rendering. Keep both private outputs in a new comparison job. Review matching
crops at 1:1 and both cuts at playback speed, check existing jacket-relative
drift evidence against the source track, and compare glyph fidelity, eye
geometry and motion-aligned changes within the chosen ROIs. The source's
lettering and decal evidence are distinct. If the excerpt lacks readable
source lettering or an independently pinned decal, record that case as
unresolved. The comparison must show clearer source detail with no new edge
halos, broken strokes, eye changes or visible shimmer. Otherwise retain
Lanczos. An opaque-clip win does not certify layered sprite processing or
close E0 softness for every format. Record the input and profile hashes,
ranges, time, checks and review verdict separately.
[Archived build evidence](../../titles/one-more-meeting/run-log.md) ·
[Decal drift measurement](wardrobe-decal-checks.md#decal-drift)

**Evidence limits.** Source pins include the verified publisher Git blob,
raw file SHA-256 and runtime wheels. The local fake-graph checks exercise
the CPU code, profile, Unix socket and artifact handling. Real graph
execution, measured RAM and timing, installed health, authoritative free
inodes, actual lettering and doll identity, private comparison and Tom's
acceptance await separate evidence. Lanczos remains the delivery scaler.
