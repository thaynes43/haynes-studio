# Local multimodal model profile proposal

**Proposed 2026-11-24** for [story 442](https://work.haynesnetwork.com/work_packages/442).
Start with **Qwen3.5-9B Q5_K_M**. Use **Ministral 3 8B Instruct 2512 Q5_K_M** as the
fallback if Qwen fails the model-specific vision, tool, or timing checks after a
verified unload. Both use the same pinned llama.cpp backend on one RTX 3090. The
coordinator selected this pilot on 2026-11-24 and kept unload before any Wan
dispatch until fixed S2V placement is proved. The admission runtime is
installed dormant, the sidecar image is published, and the two pilot files
passed size and hash read-back after the provisioning retry. Profile and
sidecar activation and leased smoke remain open. The larger Qwen3.8-27B
candidate is for E10 measurement.
[Install evidence](../contracts/studio-contracts-v1.md#installed-and-published-state).
[Provisional ruling](../contracts/studio-contracts-v1.md#ruling-20).

The model checks whether faces are visible, lettering is readable and wardrobe
matches the costume record. It turns approved material and a format recipe into a
schema-validated production plan. Report doubtful visual evidence as uncertain
for human review. Story [455](https://work.haynesnetwork.com/work_packages/455)
defines the E10 corpus and [421](https://work.haynesnetwork.com/work_packages/421)
compares board drafting with the frontier baseline. Frontier remains the default
until Tom's D46 switch verdict. [Studio plan, D14, D40, D46 and D50](../proposals/0003-studio-plan.md)

## Candidates

Sources in this proposal were read on **2026-11-24**. File sizes are publisher
bytes. All four are estimated to fit one 24 GiB card at 8,192 tokens and one
slot. The planning ranges below include the projector, f16 KV and allowances
for scratch and runtime memory. Qwen3.5 and Ministral are the pilot pair because
their two-file downloads each fit under 7 GiB and leave ample room to measure
vision bursts. They use different tool templates, which makes the fallback
useful if the primary fails template or OCR checks. Gemma has an open tool-grammar
report for the proposed quant. Qwen3.8 would consume about 9 GiB more disk than
either pilot profile. The published readings have their own hardware,
build and request shape. No talosw01 memory or quality measurement exists yet.

| Candidate and pinned files | Memory at 8,192 tokens | Vision and tool behavior |
|---|---|---|
| **Qwen3.5-9B**. `unsloth/Qwen3.5-9B-GGUF`: `Qwen3.5-9B-Q5_K_M.gguf` (6,577,841,376) + `mmproj-BF16.gguf` (921,705,024). [Weights and licence](https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/tree/3885219b6810b007914f3a7950a8d1b469d598a5) | **8–11 GiB** planning range. Published 8K Q5_K_M estimate is 7.65 GiB. A first-principles check budgets 6.98 GiB for both files, 0.25 GiB f16 attention KV, about 0.07 GiB recurrent state and 1–3 GiB for other buffers. [8K estimate](https://huggingface.co/datasets/gpunz/llm-vram-requirements) · [Text config](https://huggingface.co/Qwen/Qwen3.5-9B/blob/c202236235762e1c871ad0ccb60c8ee5ba337b9a/config.json) | Dynamic 32-pixel image grid. Limit to 1,024 visual tokens per input image. Use the Qwen template with thinking disabled and one tool call at a time. Earlier builds reported XML tool calls inside thinking and wrong answers with some visual batch sizes. [Card](https://huggingface.co/Qwen/Qwen3.5-9B/blob/c202236235762e1c871ad0ccb60c8ee5ba337b9a/README.md) · [Image config](https://huggingface.co/Qwen/Qwen3.5-9B/blob/c202236235762e1c871ad0ccb60c8ee5ba337b9a/preprocessor_config.json) · [Tool issue](https://github.com/ggml-org/llama.cpp/issues/20837) · [Vision issue](https://github.com/ggml-org/llama.cpp/issues/19929) |
| **Ministral 3 8B Instruct 2512**. `mistralai/Ministral-3-8B-Instruct-2512-GGUF`: `Ministral-3-8B-Instruct-2512-Q5_K_M.gguf` (6,059,268,512) + `Ministral-3-8B-Instruct-2512-BF16-mmproj.gguf` (858,283,168). [Weights and licence](https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512-GGUF/tree/0102285ad796bd99af90f58de616092e5630e970) | **9–11 GiB** planning range. 6.44 GiB files + 1.06 GiB f16 KV (34 layers × 8 KV heads × 128 × 8,192 tokens × 4 bytes for K and V) + 1–3 GiB for runtime and image encoding. The publisher cites 12 GB for FP8 without naming a context. A different Q4 run measured about 6.41 GiB process VRAM at 32K with q8 KV. [Model config](https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512/blob/d2ff65a33fc5f72d77a65a2bc366feefd44ca320/config.json) · [Publisher card](https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512/blob/d2ff65a33fc5f72d77a65a2bc366feefd44ca320/README.md) · [Q4 measurements](https://deepwakelabs.com/benchmarks/?campaign=original-qb) | Pixtral longest edge 1,540 px, 14-pixel patches with 2× merge. Respect the common token budget including row separators. Use the Instruct variant's embedded Mistral template. The related Reasoning variant has a report of tool calls being lost inside reasoning blocks. Downsampling can hide small lettering, so send a detail crop when needed. [Processor config](https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512/blob/d2ff65a33fc5f72d77a65a2bc366feefd44ca320/processor_config.json) · [Reasoning variant issue](https://github.com/ggml-org/llama.cpp/issues/29248) |
| **Gemma 4 12B Instruct QAT**. `google/gemma-4-12B-it-qat-q4_0-gguf`: `gemma-4-12b-it-qat-q4_0.gguf` (6,975,879,296, QAT Q4_0) + `mmproj-gemma-4-12b-it-qat-q4_0.gguf` (175,115,616, publisher's paired projector). [Weights and licence](https://huggingface.co/google/gemma-4-12B-it-qat-q4_0-gguf/tree/29d097773436b69ff9feafd636ab4cf873786537) | **8–11 GiB** planning range. 6.66 GiB files + up to 0.44 GiB f16 KV assuming a 1,024-token sliding window and conservative separate K/V + 1–3 GiB for other buffers. A different Gemma 12B QAT GGUF with projector reported about 9,380 MB at 32K-class load on a 3060. [Base config](https://huggingface.co/google/gemma-4-12B-it/blob/43c9d014b231474fa7212dbb48a762566c2b255d/config.json) · [3060 measurements](https://github.com/Ajay9o9/runs-on-a-3060/blob/main/models/gemma4-12b.md#b-qat-gemma-4-12b-it-qat-ud-q4_k_xl--no-mtp) | Card lists 70, 140, 280, 560 and 1,120 image tokens. Use its embedded Gemma tool template and cap a first smoke at 560 per image. Reported CUDA vision faults on a different build/platform and tool grammar loops that can exhaust the token budget with quoted values in nested arguments. [Card](https://huggingface.co/google/gemma-4-12B-it/blob/43c9d014b231474fa7212dbb48a762566c2b255d/README.md) · [CUDA issue](https://github.com/ggml-org/llama.cpp/issues/30436) · [Tool issue](https://github.com/ggml-org/llama.cpp/issues/32561) |
| **Qwen3.8-27B**. `unsloth/Qwen3.8-27B-GGUF`: `Qwen3.8-27B-UD-Q4_K_M.gguf` (16,564,259,744) + `mmproj-BF16.gguf` (931,146,432). [Weights and licence](https://huggingface.co/unsloth/Qwen3.8-27B-GGUF/tree/4af51b3542f775b0a8e4b310bfb3f17e01c306c9) | **18–21 GiB** planning range. 16.29 GiB files + 0.50 GiB f16 attention KV + recurrent state and a 1–3 GiB runtime allowance. A different, larger ggml-org Q4_K_M package measured 18.42 GiB at 8K for text on Blackwell, without a projector. [Base config](https://huggingface.co/Qwen/Qwen3.8-27B/blob/37561816e66b5b9153b1b64c10968c18c1e6f4a0/config.json) · [8K measurement](https://huggingface.co/ggml-org/Qwen3.8-27B-GGUF/discussions/6) | Dynamic 32-pixel image grid. Limit to 1,024 tokens per image and use the Qwen template. The developer discussion reports Python values in nested tool arguments. Consider it for a later E10 comparison if there is a measurable quality gap and room for longer loads. [Card](https://huggingface.co/Qwen/Qwen3.8-27B/blob/37561816e66b5b9153b1b64c10968c18c1e6f4a0/README.md) · [Image config](https://huggingface.co/Qwen/Qwen3.8-27B/blob/37561816e66b5b9153b1b64c10968c18c1e6f4a0/preprocessor_config.json) · [Tool discussion](https://github.com/ggml-org/llama.cpp/discussions/32180) |

The four pinned weight cards above say `license: apache-2.0`. Qwen's base repositories
include the Apache grant to “reproduce, prepare Derivative Works of, publicly
display, publicly perform, sublicense, and distribute the Work”. Mistral's card
explicitly says “allowing usage and modification for both commercial and
non-commercial purposes”. Google links the Gemma 4 Apache terms from the QAT card.
These quotes cover the models. The proposed D48 rows leave generated-output
commercial terms and attribution `unknown` where the checked sources do not specify
them. D49 leaves private Studio use available. [Qwen3.5 licence](https://huggingface.co/Qwen/Qwen3.5-9B/blob/c202236235762e1c871ad0ccb60c8ee5ba337b9a/LICENSE) · [Qwen3.8 licence](https://huggingface.co/Qwen/Qwen3.8-27B/blob/37561816e66b5b9153b1b64c10968c18c1e6f4a0/LICENSE) · [Mistral card](https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512/blob/d2ff65a33fc5f72d77a65a2bc366feefd44ca320/README.md#license) · [Gemma terms](https://gemma.ai/resources/apache-2/) · [Licence register](model-licences.md)

## Runtime and lease

| Runtime | Precedent and fit |
|---|---|
| **llama.cpp b12679, CUDA 12** | The household manifest runs `ghcr.io/ggml-org/llama.cpp:server-cuda-b11096@sha256:0192ab2545efcbe79c240645e34abd8fffbe4813aedcef5a0e3a886ef6d6d82f` with UUID pinning, explicit slots and health checks. The proposed build has libmtmd, schema-to-GBNF and Jinja tool parsing. The embedded templates and Qwen, Gemma and Mistral call syntax must pass the chosen build's parser smoke. Reuse the libraries and template/parser logic in the OP441 process so its watchdog also terminates the CUDA owner. The stock HTTP executable is a serving reference. [Household manifest](https://github.com/thaynes43/haynes-ops/blob/1a5d2e08cca998017b84ae28fd90a4be1e28eac1/kubernetes/main/apps/ai/llama-server/app/helmrelease.yaml) · [Release](https://github.com/ggml-org/llama.cpp/releases/tag/b12679) · [Vision](https://github.com/ggml-org/llama.cpp/blob/b12679/docs/multimodal.md) · [Grammar](https://github.com/ggml-org/llama.cpp/blob/b12679/grammars/README.md) · [Tool parsing](https://github.com/ggml-org/llama.cpp/blob/b12679/common/chat.cpp) |
| **Ollama 0.40.18** | The household Prime and Assist02 manifests pin `docker.io/ollama/ollama:0.40.18`. Docker Hub tag index `sha256:1cabd20e1762a7a8444bf4a7110b346d923cd77ab6c97c984434140638c913ec` was read from the registry. Ollama exposes images, structured `format`, tool calls and `keep_alive: 0` for unloading. Its separate runner can outlive the OP441 watchdog. Using Ollama would need a change to the lease and recovery protocol that proves runner termination and fresh idle memory. [Prime manifest](https://github.com/thaynes43/haynes-ops/blob/1a5d2e08cca998017b84ae28fd90a4be1e28eac1/kubernetes/main/apps/ai/ollama/prime/app/helmrelease.yaml) · [Assist02 manifest](https://github.com/thaynes43/haynes-ops/blob/1a5d2e08cca998017b84ae28fd90a4be1e28eac1/kubernetes/main/apps/ai/ollama/assist02/app/helmrelease.yaml) · [Releases](https://github.com/ollama/ollama/releases) · [Chat API](https://docs.ollama.com/api/chat) · [Structured outputs](https://docs.ollama.com/capabilities/structured-outputs) · [Tool calls](https://docs.ollama.com/capabilities/tool-calling) · [Runner lifecycle](https://github.com/ollama/ollama/blob/v0.40.18-rc0/server/sched.go) |

For each candidate, llama.cpp can constrain assistant content by the supported
JSON Schema subset or by GBNF. Tool calls use the embedded chat template and the
runtime parser. Ship small reviewed schemas and validate the parsed result and
tool arguments independently. Use one required, allowlisted function with a
small flat argument object for the tool smoke. Ship the plan schema as a
separate decoding mode. Reject truncation, malformed output and unexpected tool
names before any Studio write. Studio's caller validates and owns any writes.
The runtime receives no shell, file, network, or MCP tools. [Server API](https://github.com/ggml-org/llama.cpp/blob/b12679/tools/server/README.md) · [Tool and grammar handling](https://github.com/ggml-org/llama.cpp/blob/b12679/tools/server/server-common.cpp)

Load, infer and unload pass through Wan's shared `/workspace/compute.lock` and
OP441's unknown-work checks. A verified resident model may sit idle on its reserved
card while a proved single-card S2V job uses the other card. The lease still
serializes inference and S2V. Start with the conservative default: OP441 reserves
both cards for unverified placement and unloads before dispatch. Before enabling
other-card residency, verify fixed S2V placement on Card C and read back both UUIDs,
processes and memory during the authorized smoke. Unload and clear the reservation
before changing the profile or its S2V placement pin. Card A is also Foley's card, so
Foley must unload the model first. [OP441 source proposal](https://github.com/thaynes43/haynes-ops/pull/5024) · [Wan card layout](https://github.com/thaynes43/haynes-ops/blob/1a5d2e08cca998017b84ae28fd90a4be1e28eac1/.agents/runbooks/dual-3090-video.md)

## Exact OP441 admission profiles

Mount **one** of these as `/config/video/local-model.json` for the Wan API and
sidecar. The model string is the client-visible profile key. The backend selects
its immutable model and projector from the matching verified directory. Both
use Card A. Omit `s2v_gpu_uuid` until the fixed placement is proved. The idle
ceiling (512 MiB), 12 GiB peak cap and operation deadlines are proposed budgets.
Record actual idle and resident readings by UUID before enabling the profile.
[OP441 profile loader](https://github.com/thaynes43/haynes-ops/blob/7e77e38fd7176d36ed754d1d5aaa53670440388c/kubernetes/main/apps/ai/wan-video/app/product_local.py)

Primary

```json
{
  "model": "qwen3.5-9b-q5_k_m",
  "gpu_uuid": "GPU-6ff9702a-1b2c-6094-5a85-00aa1924c55a",
  "context_tokens": 8192,
  "max_output_tokens": 2048,
  "load_timeout_seconds": 120,
  "infer_timeout_seconds": 180,
  "unload_timeout_seconds": 15,
  "unloaded_max_mib": 512,
  "resident_min_mib": 5120,
  "resident_max_mib": 12288
}
```

Fallback

```json
{
  "model": "ministral-3-8b-instruct-2512-q5_k_m",
  "gpu_uuid": "GPU-6ff9702a-1b2c-6094-5a85-00aa1924c55a",
  "context_tokens": 8192,
  "max_output_tokens": 2048,
  "load_timeout_seconds": 120,
  "infer_timeout_seconds": 180,
  "unload_timeout_seconds": 15,
  "unloaded_max_mib": 512,
  "resident_min_mib": 5120,
  "resident_max_mib": 12288
}
```

**Frame envelope.** Accept up to four ordered staged PNGs, up to 1080×1920 for
portrait or 1920×1080 for landscape and up to 8 MiB each. CPU-decode and validate
dimensions, preserve aspect ratio, and cap each prepared image at 1,024 visual
tokens plus its template delimiters. Use a bounded, labeled detail crop in an
image slot for small lettering or costume patterns. With four images at the
visual cap and a 2,048-token output allowance, fewer than 2,048 tokens remain
for instructions and delimiters. Count the complete templated input on CPU
before any image encoding or text decode. Use the template's actual image
token accounting, including Pixtral row separators. Return `context_limit`
before inference when the combined budget does not fit. OP441 also caps prompt
text at 4,096 characters. For longer format recipes, the pilot can request one
bounded board or recipe step at a time. A whole long-board-draft workload
remains for the E10 harness to measure.

**Contract gap.** The OP441 source proposal accepts one `image_sha256` and returns
`text` plus token counts. It has no schema or tool selector. Keep existing calls
working and add ordered `image_sha256s` and a server-owned `mode` before claiming
multi-frame/schema/tool usability. Prefer modes `text` (default), `frame_check_v1`,
`plan_v1` and `plan_tool_v1` with versioned schema/tool definitions in source.
Use the existing request fingerprint and private sidecar receipt to bind the
mode, order and digests. Return validated JSON in `result.text` for structured
modes. For `plan_tool_v1`, serialize the one validated tool name and arguments
there. Validate `image_sha256s` and the legacy `image_sha256` as mutually
exclusive. Include the normalized mode and ordered digests in the immutable
request before sending it under the existing lease. Keep caller-supplied schemas,
grammars, tool definitions and image URLs outside the request contract. The profile can be installed for the base lease
smoke with the original contract. The expanded modes need source and private
smoke evidence before they are offered to Studio. [OP441 API and adapter](https://github.com/thaynes43/haynes-ops/pull/5024/files)

## Download plan

Read-only preflight on 2026-11-24, using
`kubectl -n ai exec deploy/wan-video -c api -- df -h /workspace`, returned
79G size, 53G used and 26G available. The `df -Pk /workspace` and
`df -Pi /workspace` variants gave **27,507,707,904 available bytes (25.62 GiB)**
and **5,242,125 free inodes**. Reserve **8 GiB free** and **1,024 free inodes**
throughout the download and after verification. This keeps 3 GiB above the
Wan upload guard's existing 5 GiB floor. Use at most 16 new inodes for the selected
profile's staging, directory and manifest. No volume expansion is needed for
either profile at the observed headroom. If the fresh check fails, stop and put a
PVC size change through haynes-ops if capacity is still needed. [Wan upload guard](https://github.com/thaynes43/haynes-ops/blob/1a5d2e08cca998017b84ae28fd90a4be1e28eac1/kubernetes/main/apps/ai/wan-video/app/product.py)

| File and pinned source | Bytes | Published SHA-256 |
|---|---:|---|
| [Qwen3.5-9B-Q5_K_M.gguf](https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/resolve/3885219b6810b007914f3a7950a8d1b469d598a5/Qwen3.5-9B-Q5_K_M.gguf) | 6,577,841,376 | `dc2a39aef291f91a9116ad214058da0d86eb648743a124bd8c333787c4b9c91c` |
| [mmproj-BF16.gguf](https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/resolve/3885219b6810b007914f3a7950a8d1b469d598a5/mmproj-BF16.gguf) | 921,705,024 | `853698ce7aa6c7ba732478bad280240969ddf7b0fcbf93900046f63903a83383` |
| [Ministral-3-8B-Instruct-2512-Q5_K_M.gguf](https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512-GGUF/resolve/0102285ad796bd99af90f58de616092e5630e970/Ministral-3-8B-Instruct-2512-Q5_K_M.gguf) | 6,059,268,512 | `7a5454127ec772e2389f0e71a77fedb88b83d4366d8a69facd0cfd0898f04d35` |
| [Ministral-3-8B-Instruct-2512-BF16-mmproj.gguf](https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512-GGUF/resolve/0102285ad796bd99af90f58de616092e5630e970/Ministral-3-8B-Instruct-2512-BF16-mmproj.gguf) | 858,283,168 | `e799380f596d152ff4026a72d409ecc89c96cd437676804bc3f2ab3bd6b486ec` |

- Primary totals **7,499,546,400 bytes (6.98 GiB)** and leaves **18.63 GiB** before metadata.
- Fallback totals **6,917,551,680 bytes (6.44 GiB)** and leaves **19.18 GiB** by
  itself, or **12.19 GiB** if the first pair has to be retained for evidence.

Provision the selected pair once into a new directory under
`/workspace/local-model-weights/<model>/<revision>/`. Save a manifest with the
exact sizes and SHA-256s. Re-read the reserve before each file, enforce its byte
cap, and stream to a unique staging name on the same filesystem. Verify both
sizes and hashes before making the directory visible to the adapter with a
create-only rename. Keep a single on-volume copy and bypass the Hub cache. Keep a failed
attempt quarantined and account for its bytes before any retry or fallback.
The weights mount read-only in serving. Auth-free Hub metadata supplied sizes
and LFS SHA-256s. The rollout worker must hash the bytes actually provisioned.
[Qwen file metadata](https://huggingface.co/api/models/unsloth/Qwen3.5-9B-GGUF/revision/3885219b6810b007914f3a7950a8d1b469d598a5?blobs=true) · [Ministral file metadata](https://huggingface.co/api/models/mistralai/Ministral-3-8B-Instruct-2512-GGUF/revision/0102285ad796bd99af90f58de616092e5630e970?blobs=true)

## Sidecar sketch for haynes-ops

- **Base image** `ghcr.io/ggml-org/llama.cpp:server-cuda12-b12679@sha256:fbd1c7239e4a14fdb973aa114add9ab7057f10ff632f6147890ff1843a607f3b`.
  Linux amd64 manifest `sha256:3f825497190fed44861c374495ad662c995c9f3efc375bcfea4f560734b6a6a3`.
  Build the in-process adapter against b12679 commit
  `af5c58347fdbc2cd19e65b278e81c8f528f8a175`. The stock CUDA-12 server image
  provides the CUDA userspace and llama libraries. Add pinned Python and the
  native binding in the derived image and record its own deployable digest
  after build. [Registry version](https://github.com/ggml-org/llama.cpp/pkgs/container/llama.cpp/versions?filters%5Bversion_type%5D=tagged) · [Source](https://github.com/ggml-org/llama.cpp/commit/af5c58347fdbc2cd19e65b278e81c8f528f8a175) · [CUDA Dockerfile](https://github.com/ggml-org/llama.cpp/blob/b12679/.devops/cuda.Dockerfile)
- **Process** `python3 -m studio_local_backend serve --workspace /workspace --profile /config/video/local-model.json --weights-root /workspace/local-model-weights`
  is a proposed entry point. It calls OP441's `local_model_sidecar.serve(root,
  profile, backend_factory)`. Load both GGUFs within the lease, prepare and count
  on CPU, encode and decode in-process under the lease, synchronize before
  returning, and free all model, projector, cache and CUDA allocations on unload.
  The native binding can use `mtmd_tokenize_from_parts` and sum
  `mtmd_input_chunk_get_n_tokens` before calling `mtmd_encode_chunk`.
  Start unloaded. OP441's watchdog terminates this CUDA-owning process on a
  hard deadline. A separately started `llama-server` or `ollama serve` would
  have an independent GPU lifetime. Use only `/workspace/local-model/sidecar.sock`.
  [OP441 sidecar](https://github.com/thaynes43/haynes-ops/blob/7e77e38fd7176d36ed754d1d5aaa53670440388c/kubernetes/main/apps/ai/wan-video/app/local_model_sidecar.py) · [libmtmd API](https://github.com/ggml-org/llama.cpp/blob/b12679/tools/mtmd/mtmd.h)
- **Inference settings** Use the model and projector from the selected manifest.
  Equivalent llama.cpp settings are `--ctx-size 8192 --n-predict 2048 --parallel 1
  --n-gpu-layers 999 --fit off --flash-attn on --batch-size 1024 --ubatch-size
  1024 --cache-type-k f16 --cache-type-v f16 --image-max-tokens 1024
  --mtmd-batch-max-tokens 1024 --threads 2 --threads-batch 2 --jinja
  --reasoning off --spec-type none --no-context-shift --cache-ram 0`.
  Treat these as backend parameters. Start with one image encoding at a time
  under the same request so scratch is bounded. Pass no remote model URLs and
  keep the server's built-in tools and UI disabled. [Runtime argument reference](https://github.com/ggml-org/llama.cpp/blob/b12679/tools/server/README.md)
- **Resources** Use the Wan pod's existing device allocation. Set
  `NVIDIA_VISIBLE_DEVICES` and `CUDA_VISIBLE_DEVICES` to the profile UUID and
  `NVIDIA_DRIVER_CAPABILITIES=compute,utility`. Request `1` CPU and `8Gi`
  host RAM, limit `2` CPUs and `16Gi` RAM. Verify node and pod headroom
  during S2V. Use the existing non-root UID 1000 and read-only root filesystem.
  Mount the shared workspace for the socket, receipts and staged inputs. Add
  no Service, Ingress or second device allocation. [Wan manifest](https://github.com/thaynes43/haynes-ops/blob/1a5d2e08cca998017b84ae28fd90a4be1e28eac1/kubernetes/main/apps/ai/wan-video/app/helmrelease.yaml)
- **Probes** Proposed exec startup and readiness probe
  `python3 -m studio_local_backend ready --workspace /workspace` checks that
  the current process and its bound private listener without adding work to
  the inference queue. Use `periodSeconds: 5`, `timeoutSeconds: 1`,
  `failureThreshold: 12` for startup and a 10 s period, 1 s timeout and
  failure threshold of 3 for readiness. Use the kernel
  watchdog for stuck operations. Avoid a liveness probe that runs inference
  or restarts the sidecar during a normal lease.

## Rollout smoke and stop conditions

1. Roll out the merged OP441 change first with the model profile absent. Verify
   source hashes, `/health`, `/v1/ready`, Wan/Foley profile discovery, a legacy
   read, and `503 local_model_not_installed` on model discovery. Confirm OP410
   readiness, disk reserve, a clear render hold, empty engine queue and known card
   ownership. Use GitOps to revert the dormant rollout if its health gate fails.
   [OP441 rollout plan](https://github.com/thaynes43/haynes-ops/pull/5024) · [OP410](https://work.haynesnetwork.com/work_packages/410)
2. Following the profile ruling, verify the image digest and both file hashes.
   Discover the profile with `GET /v1/local-model/profile`. Use distinct
   32-lowercase-hex IDs for `PUT /v1/local-model/requests/{request_id}` load,
   infer and unload. Read the original ID with GET after an ambiguous response.
   Time a first `load` including the projector. Target **60 s** and stop at
   **120 s**. Record the initial idle, peak and post-load memory reading on the
   exact UUID. A full read of the primary pair within 60 s needs about 125 MB/s,
   before initialization time. Record if the filesystem cache may have been warm.
3. Run one bounded text request asking for a short plan from a synthetic recipe
   and approved brief, with at most 256 output tokens. With the proposed mode,
   require one call to a side-effect-free stub such as `record_plan_v1` with
   a scene ID, shot count and one technical direction. Validate the complete
   arguments against its schema, including additional-property rejection.
   Set temperature to zero for both inference smokes. Record whether the
   pinned template produced the required call. A text-only
   lease smoke on the base API establishes text and lease behavior only.
4. Run one image-plus-text request on four synthesized 1080×1920 frames with
   known differences in face visibility, a printed code and garment color,
   including an obscured example. Stage through `PUT /v1/inputs/{sha256}.png`
   with the actual file hashes. Use `frame_check_v1` and max 512 output tokens.
   Use a costume record calling for green and vary one attribute at a time:
   fully visible face / readable `A17` / green, hidden face / readable `B24` /
   green, visible face / readable `C38` / red, and visible face / obscured code
   and garment. Require one result per image in input order, exact readable
   codes, correct face and wardrobe results and uncertainty for the obscured
   evidence. Validate against the full schema and record output and token counts.
   On the base interface, use one PNG and record that narrower check. Exercise
   invalid IDs, excess images, invalid schemas and context overflow with CPU-only
   fakes before the live window.
5. From load through generation, sample per-UUID memory and process ownership
   (for example one sample per second) and record runtime allocation logs to
   supplement sampled peaks. Both profiles must remain at or below 12,288 MiB,
   within 16 GiB host RAM and within their deadlines. Use one bounded S2V
   handover with the conservative pair assumption and record which card S2V
   actually used. Verify the automatic unload receipt and fresh memory at or
   below 512 MiB **before**
   engine submission, then read the Wan job to completion and require an empty
   queue before the model can reload. Time the reload, label cache warmth and do
   a tracked final unload. Keep the whole leased GPU window within the story's
   30 minutes. Retained residency needs its own authorized S2V test with fixed
   placement. Observe idle model memory on Card A and S2V on Card C, with local
   inference refused until S2V releases the lease.
6. Preserve the request IDs, returned states, image and model hashes, time
   and memory samples, schema verdicts and any refusal in private evidence.
   Unknown ownership, a failed unload or unmet capacity stops the rollout.
   Reconcile the original ID and preserve holds. After activation, quiesce,
   prove unload and clear residency through the lease before disabling the
   profile or reverting through GitOps. Change to the fallback only after
   verified idle state and a new coordinator ruling/window. [OP441 recovery and rollback](https://github.com/thaynes43/haynes-ops/pull/5024#rollout-and-rollback)

Cold load from this PVC, true peak and post-unload memory on Ampere, the
in-process image's digest and build compatibility, other-card S2V placement,
multi-frame OCR near the token cap, and tool/grammar reliability remain unverified.
This proposal does not supply an E10 score or a release verdict.
