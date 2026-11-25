# Segmentation and detection backend profile

**Selected 2026-11-25 under CR-34** for [story 460](https://work.haynesnetwork.com/work_packages/460).
Use **Grounding DINO Tiny + SAM 2.1 Hiera Tiny** on CPU. Keep **OWLv2 Base
Patch16 Ensemble + the same SAM 2.1** as a fallback if grounding is the part
that fails the bounded quality check, on a new ruling. Provisional
[ruling 34](../contracts/studio-contracts-v1.md#ruling-34) selects the primary
without a separate face detector. Installation and private quality proof
remain open. Both profiles leave the Wan queue available for builds.

The layered doll format puts cutouts behind parts of a set photograph. E0
showed why the foreground edge, the doll faces and the focal prop need checks
before cutting a video. The existing compositor draws the set, dolls in order,
foreground and then camera. The backend extracts pixel masks and boxes in the
source image for that order. Story 452 projects them through the chosen layout
and measures visibility. Story 442's local multimodal model can offer a second
opinion on apparent visibility in a preview. Its answer does not supply mask
pixels or replace measured occlusion. The layout and creative verdict stay with
their existing owners. [Studio plan, D15, D22–D24 and E0](../proposals/0003-studio-plan.md)
· [Doll format](doll-format.md) · [Layered compositor](layered-adapter.md)
· [Wardrobe and decal evidence](wardrobe-decal-checks.md)
· [Story 452](https://work.haynesnetwork.com/work_packages/452)
· [Studio occlusion adapter and layout check](occlusion-masks.md)
· [Local model](local-model-profile.md)

## Candidates

All linked publisher, release and measurement sources were read on **2026-11-25**.
No matching end-to-end measurement at a 1080×1920 **source** on the Studio CPU or
one 24 GB card was found for any row. Model tensors are resized as described
below. The measurements are original reports on their stated inputs and
hardware. They establish neither Studio latency nor a quality threshold.

| Candidate | Prompts, outputs and evidence on small subjects | CPU and single-card evidence |
|---|---|---|
| **SAM 2.1 Hiera Tiny**, Meta `facebookresearch/sam2`, weights `facebook/sam2.1-hiera-tiny` | Points (positive/negative) or boxes yield masks and predicted IoU scores. The image processor uses a 1024×1024 tensor and upsamples 256×256 mask logits. Predicting a full-size mask does not restore fine edges lost there. The paper and card benchmark common objects and video tracks. They do not report doll-face or miniature-prop results. [Publisher code and model table](https://github.com/facebookresearch/sam2) · [Paper](https://arxiv.org/abs/2408.00714) · [Image processor](https://github.com/huggingface/transformers/blob/v5.24.1/src/transformers/models/sam2/image_processing_sam2.py) | Meta reports 91.2 fps in its A100 video benchmark. A Rust port reports **463 ms** on Ryzen 7950X BF16 and **21 ms** on a 24 GB RTX 4090 FP16 with FlashAttention, using a single point on its test still. An independent FP32 video test of the original Hiera-Tiny teacher reports **4.95 s/frame** on two i7-13620H threads. Peak RAM/VRAM and timings for this profile remain unknown. [Meta benchmark](https://github.com/facebookresearch/sam2#sam-21-checkpoints) · [Rust port timings](https://github.com/apiplant/sam-rs#sam-2--21) · [Teacher CPU timings](https://huggingface.co/Pablopigue/sam2-lite#results) |
| **Grounding DINO Tiny**, `IDEA-Research/GroundingDINO`, weights `IDEA-Research/grounding-dino-tiny` | Text labels or short referring phrases yield scored boxes and matching text. The default resize targets a short edge of 800 and caps the long edge at 1333. COCO, LVIS and referring-expression benchmarks show general object and phrase grounding. They give no gavel/menu or doll-face accuracy at Studio sizes. [Publisher repo](https://github.com/IDEA-Research/GroundingDINO) · [Paper](https://arxiv.org/abs/2303.05499) · [Processor config](https://huggingface.co/IDEA-Research/grounding-dino-tiny/blob/a2bb814dd30d776dcf7e30523b00659f4f141c71/preprocessor_config.json) | Independent FP32 timings using the pinned weight SHA report **5.50 s / 3.1 GiB peak RAM** on i7-10700K with eight threads and **119 ms / 2.9 GiB peak VRAM** on a 24 GB RTX 4090, batch one at 1199×800. [Measurements](https://modelsthatrun.dev/models/grounding-dino/) |
| **Grounded SAM 2**, `IDEA-Research/Grounded-SAM-2` | The local pipeline feeds text-grounded boxes into SAM for masks. Points and person-supplied boxes go directly to SAM. It yields masks, boxes and scores from the component models. The project's demos and slice-inference example for small objects use different versions/settings. Neither measures a doll face or a miniature on the proposed stack. Use the local composition pattern with the two pinned weights above. [Publisher demo at b7a9c29](https://github.com/IDEA-Research/Grounded-SAM-2/blob/b7a9c29f196edff0eb54dbe14588d7ae5e3dde28/grounded_sam2_hf_model_demo.py) · [Small-object example](https://github.com/IDEA-Research/Grounded-SAM-2#grounded-sam-2-with-sahi-for-high-resolution-image-inference) | No combined CPU or single-24-GB time or peak-memory result for these two pins was found. Detector-only figures omit SAM encoding, post-processing and store I/O. Plan and measure the whole request at install. |
| **OWLv2 Base Patch16 Ensemble**, `google-research/scenic`, weights `google/owlv2-base-patch16-ensemble` | Text labels or image exemplars yield scored boxes. This profile uses text. The processor pads to a square and resizes to 960×960. The publisher reports LVIS base ensemble AP 43.9 and rare-category AP 40.5. Those categories and a published eyewear study do not establish small prop or doll-face recall. [Model card](https://huggingface.co/google/owlv2-base-patch16-ensemble/blob/cfd3195ba4ea9592eec887ded089f4c08eff231d/README.md) · [Publisher evaluation](https://github.com/google-research/scenic/tree/main/scenic/projects/owl_vit) · [Paper](https://arxiv.org/abs/2306.09683) | Independent FP32 measurements using the pinned weight SHA report **2.72 s / 1.6 GiB peak RAM** on i7-10700K with eight threads and **110 ms / 1.3 GiB peak VRAM** on a 24 GB RTX 4090 at 960×960. An eyewear study reports 267 ms per batch-one inference on a 4090 in its own setup. [Measurements](https://modelsthatrun.dev/models/owlv2/) · [Eyewear study, table 1](https://gs.elaba.lt/object/elaba%3A214959943/214959943.pdf) |
| **YuNet**, `opencv/opencv_zoo`, `face_detection_yunet_2023mar.onnx` | Closed-set face boxes, five landmarks and a score, without prompts or masks. The publisher describes faces around 10×10 to 300×300 pixels and reports on WIDER Face, a human-face dataset. There is no doll-face validation in the checked evidence. Use the 2023 export for comparison with OpenCV 4.x. The Zoo's newer 2026 May export makes its spatial input dimensions dynamic for OpenCV 5.x ONNX Runtime. YuNet cannot ground the prop or segment a set. [Pinned Zoo card](https://github.com/opencv/opencv_zoo/blob/eb9f4f2d4b79b58e5513b5d25d5f0243a8357bf4/models/face_detection_yunet/README.md) · [Paper](https://doi.org/10.1007/s11633-023-1423-y) | The Zoo reports 0.69 ms CPU (i7-12700K) and 5.23 ms CUDA FP32 on Jetson Nano Orin, both at 160×120. No comparable 1080×1920 result or CPU/24-GB peak-memory reading was found. [Zoo benchmark](https://github.com/opencv/opencv_zoo/blob/main/benchmark/README.md) |

### Files and terms

The Hugging Face file pages and API supply the publisher byte counts and
SHA-256s. For YuNet, the pinned Git LFS pointer supplies them. The two pipeline
profiles have no extra pipeline checkpoint.

| Publisher file and metadata | Bytes | Published SHA-256 |
|---|---:|---|
| [SAM 2.1 `model.safetensors`](https://huggingface.co/facebook/sam2.1-hiera-tiny/blob/de431c4043854a71d8101e17995dfe596bf101a5/model.safetensors) | 155,908,064 | `48c14467e5cf9e51870511feb72c89688e82dd74523142c0538b663e193ac2a7` |
| [Grounding DINO `model.safetensors`](https://huggingface.co/IDEA-Research/grounding-dino-tiny/blob/a2bb814dd30d776dcf7e30523b00659f4f141c71/model.safetensors) | 689,359,096 | `1a2412ef99bd74bcd3c2a246fa1e48581f8889a1300c9051974741314fc042f3` |
| [OWLv2 `model.safetensors`](https://huggingface.co/google/owlv2-base-patch16-ensemble/blob/cfd3195ba4ea9592eec887ded089f4c08eff231d/model.safetensors) | 619,918,824 | `e1e130b9e404cf91a75ad45644c1da9d7fa5284085eecc864266a6923efb99e7` |
| [YuNet `face_detection_yunet_2023mar.onnx`](https://github.com/opencv/opencv_zoo/blob/eb9f4f2d4b79b58e5513b5d25d5f0243a8357bf4/models/face_detection_yunet/face_detection_yunet_2023mar.onnx) | 232,589 | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` |

SAM 2.1, Grounding DINO and OWLv2 publisher cards state `license: apache-2.0`.
The Apache grant includes “reproduce, prepare Derivative Works of, publicly
display, publicly perform, sublicense, and distribute the Work”. Preserve
licence and applicable notices when distributing the licensed works. Grounded
SAM 2's demo code also uses Apache-2.0. The YuNet publisher says “All files in
this directory are licensed under MIT License.” Its MIT notice and copyright
conditions apply. [SAM 2.1 card](https://huggingface.co/facebook/sam2.1-hiera-tiny/blob/de431c4043854a71d8101e17995dfe596bf101a5/README.md)
· [Grounding DINO card](https://huggingface.co/IDEA-Research/grounding-dino-tiny/blob/a2bb814dd30d776dcf7e30523b00659f4f141c71/README.md)
· [OWLv2 card](https://huggingface.co/google/owlv2-base-patch16-ensemble/blob/cfd3195ba4ea9592eec887ded089f4c08eff231d/README.md)
· [Apache terms](https://www.apache.org/licenses/LICENSE-2.0)
· [Grounded SAM 2 licence](https://github.com/IDEA-Research/Grounded-SAM-2/blob/b7a9c29f196edff0eb54dbe14588d7ae5e3dde28/LICENSE)
· [YuNet terms](https://github.com/opencv/opencv_zoo/blob/eb9f4f2d4b79b58e5513b5d25d5f0243a8357bf4/models/face_detection_yunet/LICENSE)

None of the four compared packages or the local composition requires
replacement for commercial model use based on these named terms. Separate
output-use and attribution terms remain `unknown` in D48's register. The
Studio would recheck them if commercial use is planned. SAM 3.1 is a newer
reference point with video-tracking gains, a custom Meta licence and gated
access requiring account information. It is outside the candidate set. D49
permits the private research pilot with terms recorded. [Register](model-licences.md)
· [SAM 3.1 release](https://github.com/facebookresearch/sam3/blob/main/RELEASE_SAM3p1.md)
· [Gated checkpoint](https://huggingface.co/facebook/sam3.1)
· [Meta licence](https://github.com/facebookresearch/sam3/blob/main/LICENSE)

## Proposed profiles

| Profile ID | Execution | Warm per maximum-size source and one target |
|---|---|---|
| `grounding-dino-tiny-sam2.1-tiny-cpu-v1` | Grounding DINO Tiny followed by SAM 2.1 Hiera Tiny. Pass a person-supplied point or box straight to SAM. | **8–35 s** for text and mask, **1–10 s** for SAM alone. Planning estimates. |
| `owlv2-base-sam2.1-tiny-cpu-v1` | Substitute OWLv2 Base Patch16 Ensemble for Grounding DINO. Same SAM, CPU, artifact contract and hint path. Activate one profile at a time following the coordinator's ruling. | **5–25 s** for text and mask, **1–10 s** for SAM alone. Planning estimates. |

Use FP32, eager inference, batch one, one request in flight, `nice -n 10`,
two CPU threads (PyTorch intra-op and OMP two, inter-op and BLAS one,
tokenizer parallelism off). The original 2 GiB request and 8 GiB limit were
planning estimates. The first smoke is staged with a 16 GiB request
and limit as a measuring allowance. The smoke checks the image's minimum
allowance and reports the actual cgroup limit. Raise the measuring allowance
in the Ops release when node headroom permits. Set exact serving memory in
a follow-up from the measured run. Allow 60 s for cold readiness and 60 s per
target.
Warm estimates use the detector-only measurements as a starting point with
headroom for fewer CPU threads, SAM and I/O. Measure wall time and peak
cgroup memory in the one install smoke. The fallback shares the same
segmentation failure modes. If its masks or the hinted masks fail, require
person-drawn geometry and stop automatic layout certification. D18 supplies CPU
placement. If a future profile requires CUDA, load, infer and unload under the
one Wan API compute lease and its unknown-work checks. That full window
serializes against Wan, Foley and the local model, even for a short inference.
[Studio plan, D18 and D50](../proposals/0003-studio-plan.md)
· [Wan and render worker](services.md)

Use CPython 3.12 on Linux amd64 from the pinned base below. The current
Transformers release was checked on 2026-11-25. PyTorch 2.14.1 and TorchVision
0.29.1 are the proposed pair because both matching Linux CPython 3.12 CPU
wheels and their declared compatibility were verified. Grounding DINO uses
the stock PyTorch path with custom kernels disabled. The pinned DINO text
position encoder converts position IDs to floating point before encoding,
which avoids the integer truncation in v5.20.2. The SAM image processor
and model are selected explicitly because the checkpoint also advertises
a video processor. Disable remote code and external model access. Lock the
transitive runtime with hashes in the install PR and verify the offline load.
[Transformers release](https://github.com/huggingface/transformers/releases/tag/v5.24.1)
· [PyTorch release](https://github.com/pytorch/pytorch/releases/tag/v2.14.1)
· [TorchVision release](https://github.com/pytorch/vision/releases/tag/v0.29.1)
· [SAM image processor](https://github.com/huggingface/transformers/blob/v5.24.1/src/transformers/models/sam2/processing_sam2.py)
· [DINO config](https://github.com/huggingface/transformers/blob/v5.24.1/src/transformers/models/grounding_dino/configuration_grounding_dino.py)
· [DINO text positions](https://github.com/huggingface/transformers/blob/v5.24.1/src/transformers/models/grounding_dino/modeling_grounding_dino.py#L1049-L1063)

| Runtime wheel for Linux amd64 and CPython 3.12 | Publisher SHA-256 |
|---|---|
| [torch 2.14.1+cpu](https://download.pytorch.org/whl/cpu/torch/) | `5a6363570c753812540a05eb82380e329469cbe668643e88111414c12627711f` |
| [torchvision 0.29.1+cpu](https://download.pytorch.org/whl/cpu/torchvision/) | `ef220d4b21878c58947851beb7337382897159105f012f0c9c07bf7e84174d7e` |
| [transformers 5.24.1](https://pypi.org/project/transformers/5.24.1/#files) | `505b39d3e45a3715f3acb81b858eb245ce1a462373b7f99e26f0dcd41ed4cd0f` |
| [safetensors 0.8.0](https://pypi.org/project/safetensors/0.8.0/#files) | `fd6f3f93c9a0a7cc2788ee63fb763353d4bd2e89b0751bc78fcf7dda00bea774` |
| [Pillow 13.0.0](https://pypi.org/project/Pillow/13.0.0/#files) | `42d63be3af4f9b951b199b0a9d23365d37ab14687e6d77b74940432c8515c4ca` |

## Artifact contract for story 452

One request observes one subject on one upright, decoded still. Normalize the
set plate as `opaque_plate` and the individual cast stills as keyed
`rgba_cutout` versions before submission. Use the prop's unobscured pixels in
the source plate or its own component still. If the source itself hides a
subject, fetch an unobscured reference or ask a person for geometry. A miss on
a composited preview cannot establish that a target was hidden.

`studio.segmentation-request/v1` is a closed JSON object of at most 4 KiB:

| Field | Meaning |
|---|---|
| `schema`, `profile` | Schema literal and one exact profile ID from this page. An inactive profile fails. |
| `input` | `{sha256, width, height}`. Digest is 64 lowercase hex of the stored bytes. The owning Studio run or asset operation supplies production/library scope outside this document. Resolve only an authorized pin in that scope using the existing store. Validate hash, decoded dimensions and format before inference. One PNG, JPEG or WebP still, at most 8 MiB and 2,073,600 pixels, each side at least 32, short side ≤1080 and long side ≤1920. Apply orientation during source normalization. Reject an animation or non-upright orientation. Composite cutout RGB on neutral gray for inference and intersect the resulting mask with the pinned cutout's nonzero alpha. |
| `target` | `{kind, key, label}`. Kind is `foreground`, `prop` or `face`. Key is the foreground role, focal-prop key or cast slot and matches `[a-z0-9][a-z0-9_-]{0,63}`. Label is a short noun phrase for a prop, defaults to `doll face` for a face, and may be null for foreground. Use one request per named prop or slot. Multiple foreground parts may be requested separately and unioned by the caller. |
| `hint` | Null or exactly one of `{kind:"point", xy:[x,y]}`, `{kind:"box", xyxy:[x0,y0,x1,y1]}`, `{kind:"text", text:"..."}`. Point is positive. A text hint replaces the detector query. Label and hint text are NFC, trimmed and at most 80 characters each, with tokenizer length checked before inference. Coordinates are integer source pixels with top-left origin, x to the right, y down. Boxes are half-open, in bounds and nonempty. |

The default foreground query is the fixed list `table. lectern. chair back.`
(or separate OWLv2 query labels). On a plate alone allow a mask only when one
unambiguous target meets a foreground prior. Require its mask to cover at
least 10% of the bottom row in the source. When depth or identity is doubtful,
return `needs_hint`. A hint identifies the foreground part and does not
automatically clear mask quality checks. For groundings use provisional
score floors 0.35 for DINO (text token floor 0.25) and 0.15 for OWLv2. Do NMS
at box IoU 0.50 per target, then require a top score lead of 0.10 for DINO
or 0.05 for OWLv2 over any other qualifying box. Undo each model's own resize
and padding before applying box checks. Discard padding-only hits. Treat a
selected detector region smaller than 16 model-input pixels on either axis as
uncertain. For SAM, use the highest finite predicted IoU (record as reported),
with a provisional floor of 0.80. If another mask within 0.05 of its score
disagrees (mask IoU <0.85), require a hint. Binarize resampled logits at zero
and return source-size pixels. Empty or all-foreground masks and masks
missing the hinted point are uncertain. These checks are heuristics and the
scores are model-specific. Use fewer hints or relax thresholds only with
versioned fixture evidence. [DINO processor](https://github.com/huggingface/transformers/blob/v5.24.1/src/transformers/models/grounding_dino/processing_grounding_dino.py)
· [OWLv2 inverse scaling](https://github.com/huggingface/transformers/blob/v5.24.1/src/transformers/models/owlv2/image_processing_owlv2.py)
· [SAM mask post-processing](https://github.com/huggingface/transformers/blob/v5.24.1/src/transformers/models/sam2/image_processing_sam2.py)

`studio.segmentation-result/v1` is a closed JSON object:

| Field | Meaning |
|---|---|
| `schema`, `request_sha256`, `input`, `target` | Result schema literal, digest of normalized request bytes (Studio canonical JSON), and exact input and target echoes. |
| `status`, `reason` | `ready` with null reason, `needs_hint` with `no_match`, `ambiguous_match`, `foreground_depth_ambiguous`, `too_small` or `mask_uncertain`, or `failed` with `invalid_input`, `input_unavailable`, `profile_unavailable`, `timeout`, `inference_failed`, `invalid_output` or `store_failed`. `needs_hint` asks for a point or box on the identified source. A failed operation may only produce diagnostics. |
| `box_xyxy`, `detector_box_xyxy`, `scores` | Tight half-open source box around nonzero mask pixels, optional separate detector box and `{detector, mask_iou}` with each a finite raw number or null. Detector boxes are clipped to the image and rounded outward. Non-ready results have null `box_xyxy`; the optional detector box and scores are diagnostic only. A point/box hint bypasses the detector and leaves its fields null. |
| `mask` | `{sha256, bytes, width, height, media_type:"image/png"}` on `ready`, null otherwise. Single-channel unsigned 8-bit grayscale PNG, exactly the source dimensions, pixels 0 (background) or 255 (subject), with no metadata. For `foreground`, 255 means draw that pixel of the set in front. |
| `provenance` | `{profile, models, runtime, device, image_digest, parameters}`. Each executed model entry names its repository, revision, file, weight SHA-256 and a manifest SHA-256 over its configs/tokenizer. Runtime records library versions and the hashed runtime lock. Parameters record actual prompt, resize/padding, thresholds, dtype and threads. Give a failed operation a diagnostic receipt if the request was valid and storage is available. |

Return a content hash for the result JSON and publish the output blobs
create-only using Studio's store. Link the mask first, then publish result
JSON, then commit a fenced completion record with both hashes. Only a current,
completed `ready` is usable. A timeout, malformed mask (including one pixel
of dimension mismatch), storage failure or stale completion cannot promote a
mask. An orphaned blob can stay under the existing retention rule. Within the
authorized scope, look up an existing completed `ready` by request SHA-256
and the frozen profile-manifest SHA-256. The manifest pins models, configs,
runtime lock, worker image and preprocessing/scoring parameters. Recheck
output dimensions and hashes at consumption. A changed pin or parameter set
gets a new profile ID.
[Store and atomic publication](../contracts/studio-contracts-v1.md#8-runs-deliveries-and-the-store)
· [Immutable asset versions](../contracts/studio-contracts-v1.md#9-the-library-and-version-ids)

Story 452 measures visibility from the **unoccluded** subject mask transformed
using the layout's crop origin, scale, placement and framing. Use the same
coordinate mapping for the plate and its foreground mask. Count subject
pixels before the slot and frame clips in the denominator. Subtract clipped
pixels and coverage from layers strictly above the subject's own layer.
For the pilot treat a higher layer's rendered alpha of 128 or more as
covering a pixel, with shadows excluded. Record target key, tested
pose/framing, input evidence hashes, visible and total pixel counts and
status. Proposed floors are `visible` at ≥85%, `hidden`
at ≤50% and `uncertain` in between or for missing/invalid geometry. Reject
`hidden` before build. Give `uncertain` the existing human-review path.
A background prop lies behind the dolls and a separate prop follows its
declared layer order. For a prop baked into the foreground, require its
support to lie inside the foreground mask, and exclude that layer and the
dolls below it from its occluders. If its depth is unspecified or its mask
straddles depth layers, require a hint or corrected layer assignment. Keep the old
edge/feather input for legacy boards. A still
measurement covers the supplied pose. A moving plate, cast move or camera
change needs evidence at any additional check pose the layout policy requires.
The proposed thresholds are technical defaults pending the private quality check.

## Backend source

The [request schema](../../src/haynes_studio/schemas/studio.segmentation-request.v1.schema.json)
and [result schema](../../src/haynes_studio/schemas/studio.segmentation-result.v1.schema.json)
ship in the Python package with a synthetic [point-hint request](../../src/haynes_studio/schemas/studio.segmentation-request.v1.example.json)
and [ready result](../../src/haynes_studio/schemas/studio.segmentation-result.v1.example.json).
Send `POST /v1/segment` to
`/segmentation/segment.sock` with JSON `{attempt_id, request}` and media
type `application/json`. The caller makes a private scratch directory under
`/segmentation` named by a fresh 32-character lowercase hex ID and places
the verified bytes in `input`. In the staged sidecar Pod the scratch volume
uses group 1000. The render caller creates a group-writable setgid attempt
directory (mode `2770`) and a group-readable `input` (mode `0640`).
The sidecar's socket and outputs are accessible to that group. The 4 KiB
body cap includes the envelope.
The attempt ID is excluded from the canonical request hash. A direct point or
box uses only SAM. For a text request, the DINO processor maps normalized boxes
onto its resized content, which is unpadded at batch one. Clip before NMS and
round outwards only when projecting back to source pixels. Apply the
foreground bottom-row prior when grounding. An explicit point or box
supplies foreground identity while the mask still has to pass every SAM guard.

The backend closes a create-only `mask.png` on `ready`, checks its bytes and
dimensions, and then creates canonical `result.json`. The HTTP reply is
`{result, result_sha256}`, with the hash over those canonical result bytes.
A new attempt can repeat the same frozen request and produce the same result.
On an ambiguous reply use a fresh attempt. The caller uses the receipt hash,
file read-back and its own claim fence before publishing. The backend writes
a closed failed result when the request is valid and the attempt can receive
one. Malformed envelopes and busy capacity return a short code. A timed-out
child is killed and reaped before a replacement loads. A timeout can leave an
unreferenced mask or late staged receipt. The caller requires a matching
successful reply before using either file. A `needs_hint` result returns HTTP 200 with its
stable reason, null mask and null tight box. Only successful current replies
can lead to a ready completion.

Startup verifies the profile image and build identity, the runtime lock and
the exact file allowlist and hashes before loading either model. The runtime
uses the explicit DINO and SAM image classes, local files, safetensors and
FP32 eager CPU inference. `GET /v1/ready` returns
`{profile_id, profile_sha256, device}` when the inference process is live.
The image records the built Python wheel hashes and embeds its Python
dependency SBOM. A resource contract ships in [the package](../../src/haynes_studio/segmentation/resources.json)
and the image's `io.haynes-studio.segmentation.resources` OCI label. The
measuring image refuses serving pending a measured serving contract.
Workload setup is staged in the [Ops runbook](https://github.com/thaynes43/haynes-ops/blob/main/docs/reference/studio-segmentation-deployment.md).

## Provisioning and GitOps

After selection, fetch only the chosen pair using the same pinned repository,
revision and path as the metadata table, with `/resolve/` in place of
`/blob/`. For each allowlisted config/tokenizer file use the same revision.
The [packaged register](../../src/haynes_studio/model_licences.json) lists all
filenames, byte counts and hashes in `proposals.segmentation`. Hashes
for the small config/tokenizer files were computed from their public bytes.
The payload is **846,220,082 bytes primary** or **777,420,069 bytes fallback**,
including these files. Neither install includes the YuNet comparison file.
Use one verified immutable profile directory under a new private install job
in the existing `/studio/jobs` tree. Mount that directory read-only at
`/opt/studio-models`. No new NAS export, credentials or model-weight
redistribution. Stream to exclusive staging files and verify each byte count
and hash before create-only publication. Publish the manifest last and verify
all pins at startup. Keep runtime offline and the previous verified pin
available for rollback.

**Read only, 2026-11-25 04:38 UTC.** In `ai/deploy/studio-render` on
`talosw01`, `df -Pk /studio` reported 110,935,591,092,224 available bytes
(about 100.9 TiB). `df -Pi /studio` reported no free-inode count and
`stat -f` returned `free-files=-1`. Budget a maximum **2 GiB and 64
new entries** for staging and one installed profile. That would leave
110,933,443,608,576 bytes at the observed baseline. Require a freshly
confirmed reserve of **32 GiB and 1,024 creatable entries** before and after
staging. The storage owner needs to confirm the NAS file quota or equivalent
capacity where NFS cannot report free inodes. The worker's node-backed
`/tmp` reported about 432 GiB free and 265,724,127 free inodes at the same
read. It is suitable for the bounded temporary work with a fresh check.
These observations reserve no resources. [Render worker and share](services.md#studio-render-cpu-work)

Propose a CPU-only companion container in `ai/studio-render`, pinned by image
digest in haynes-ops. Build for amd64 from
`docker.io/library/python:3.12-slim-bookworm@sha256:44cf1793efa7c7a476bb0f2cff81443f4a072c90c1cb127e2924933daa3e8c64`,
the current render-worker pin read on 2026-11-25. Add the hashed runtime lock,
Studio adapter and private-job runner, and model manifest schema. Build budget
**4 GiB scratch and 20,000 entries** with **8 GiB and 100,000 entries free**
on the build filesystem throughout. Recheck that filesystem before the build.
Publish the runtime image digest and its SBOM in the install handoff.

Run the smoke and sidecar as UID/GID 10001 with a read-only root, dropped
capabilities, `RuntimeDefault` seccomp and privilege escalation disabled.
Leave the model mount read-only and limit dedicated scratch to 256 MiB. The
provisioner runs as 1000 and leaves its published weights readable by 10001.
Use the approved
low-priority render placement and a local Unix socket plus bounded scratch for
one request at a time. The trusted render caller stages authorized bytes and
owns the store writes and job fence. Give the companion only the selected
weights and per-request scratch. A socket call supplies the fixed request with
a caller-owned staging handle, never an arbitrary file path. Give it no
network listener, token, GPU device or runtime download.

The live offline render limit was 20 vCPUs and 32 GiB on 2026-11-25,
within D18's 24-vCPU allocation shared with the 4-vCPU queue worker.
The staged serving overlay allocates 18 CPUs to render and two to the
companion, and subtracts the companion's measured limit from 32 GiB. Cap
render `--workers` at 16 in this split, leaving two vCPUs for encoder and
coordination overhead. Account for any other active companion before
changing the allocation. Check existing render health and headroom before
and after the change. Ready means the pinned runtime, manifest, files and
socket verify and both models
load within the startup deadline. Use the current probe pattern without
inference during health polls. Revert the pin or disable the companion via
GitOps if readiness, the bounded smoke, or existing render health fails.
Keep prior assets and run evidence.

## Expected smoke and private quality check

1. Generate deterministic PNG inputs outside the checkout with Pillow.
   At 1080×1920 draw an RGB `(32,40,56)` background and a trapezoid with
   vertices `(80,900),(1000,900),(1080,1920),(0,1920)` as the near plane.
   Fill its pixels with `(168+(x//16+y//16)%2*16,120,72)`. Rasterize the
   same polygon as ground truth with the same boundary convention.
   In separate unoccluded RGBA cutouts draw opaque disks of radius 70
   on transparent backgrounds, one orange face marker centered at
   `(300,700)` and one green focal-prop marker at `(600,1200)`. Render
   both as shaded balls. For each disk pixel with center-relative
   `dx,dy`, multiply RGB `(255,140,24)` or `(56,220,64)` by
   `0.65+0.35*sqrt(1-(dx²+dy²)/70²)`, rounding each channel. Build the
   preview with both behind the plane. The first disk is wholly visible and
   the second wholly hidden. Bind the three source hashes to distinct
   targets. Supply one tight valid box hint per object. A stub returning
   truth masks first verifies the exact counts and the source-to-layout
   transforms independently of inference.
2. The install smoke runs these three hinted observations once through the
   selected worker. Require each output mask IoU ≥0.90 against its truth,
   each tight box IoU ≥0.85, full source-size binary output, and valid
   input/profile/image/weight/parameter provenance. Require the rendered
   visible fractions ≥0.95 and ≤0.05 respectively and the hidden prop to
   fail the pre-build check. Run two more calls with no hint. For `orange
   ball` on the visible marker's source, require a detector box IoU ≥0.70
   and a final mask IoU ≥0.85. For an absent `gavel` in a uniform plate,
   require `needs_hint` without usable geometry. These are checks on the
   pinned pipeline. Quality evidence for doll faces and props comes from
   the private fixture. The measuring smoke also exercises a positive point
   on the visible marker. It repeats the observations with memory-mapped
   and buffered weight loading, each in a fresh inference process, and
   compares output PNG bytes and canonical receipts apart from the recorded
   experimental loading field. The measuring Job allows 900 s for both
   passes together.
3. Inject a correctly hashed mask one pixel narrower into the fake-backend
   fixture and verify `invalid_output` with no usable completion. Repeat
   the same completed request and verify the same references and no
   overwrite. For each real call record elapsed time, peak cgroup memory,
   model and image digests and stage outcome. Stop on any timeout (60 s),
   the actual measuring memory limit, invalid output or unexpected visible/hidden verdict.
   Read back readiness and render-worker health. Keep media and exact
   private artifact locators in the private job record.
4. For story 452, take **one authorized private miniature set** with one
   near table/lectern/chair part, one named visible prop and at least one
   doll cutout. Freeze pinned hashes and a person's traced foreground and
   subject masks first. Test one baseline arrangement and one variant with
   the same inputs deliberately hiding a face or prop. Try the first
   request without a hint, then permit at most one human point or box per
   unresolved target. Require foreground IoU ≥0.85 and face/prop mask IoU
   ≥0.75 against the traces. Require agreement with the human's
   visible/hidden labels and zero false-visible verdicts on the hidden
   variant. Record misses, all uncertain outcomes, elapsed time and hand
   work in minutes. A remaining uncertain target or failure leaves quality
   open and informs the coordinator's profile decision. Stop after that
   fixture. [Story 452](https://work.haynesnetwork.com/work_packages/452)

**Evidence state.** The source tests use deterministic fake models and the
CI image smoke uses tiny synthetic Torch modules with the pinned processors
to check fixture geometry, byte verification, wheel identities and local
service. A separate offline built-image step saves tiny random Grounding
DINO and SAM 2 models, runs the production loader in both load modes and
runs a forward pass with each class. Publisher checkpoint compatibility,
measured portrait latency and memory, doll and prop accuracy, installed image
digest, rollout health, rollback and usability require the corresponding
install and private fixture runs. Free inodes are unreported over NFS. The coordinator accepted the
small file-count budget in story 460, comment 9946. Story 452 owns adapter
pickup and private quality evidence after the install. Installation smoke and private quality acceptance
require their own evidence.
