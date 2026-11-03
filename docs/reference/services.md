# In-cluster services

The services a doll short uses today. All run in Tom's `main` Kubernetes cluster and
are deployed from [haynes-ops](https://github.com/thaynes43/haynes-ops). Nothing here
is exposed to the internet. Agents reach the services from a dev-env session pod
through `kubectl exec` into the service's own pod. That is the established route:
do not add ingress, port-forwards, proxies or new identities to get around a denial.

Facts below were read from haynes-ops on 2026-11-03 (handoff commit `1401a2ee`, main
at `7c7b2cf6`). Live state changes, so check the pod and its queue before relying on
any of it.

## Summary

| Stage | Service | Where | Route from an agent | Status for the doll format |
|---|---|---|---|---|
| Cast and set images | ComfyUI with Qwen-Image 2.1 and Qwen-Image-Edit | `ai/comfyui-0` (StatefulSet), RTX 2000 Ada 16 GB on `talosm03` | `kubectl exec -n ai comfyui-0 -c app --` to `127.0.0.1:8188` | **Expected**, not used for a doll short yet |
| Voices | Kokoro-82M v1.0 (Wyoming TTS) | `ai/deploy/kokoro`, container `app` | `kubectl exec -i -n ai deploy/kokoro -c app -- python -c ...` to Wyoming `127.0.0.1:10210` | **Proven** (OP341, OP345) |
| Transcript check | Whisper service, configured `nemo-parakeet-tdt-0.6b-v2` (Wyoming ASR) | `ai/deploy/whisper`, container `app` | `kubectl exec -i -n ai deploy/whisper -c app -- python -c ...` to Wyoming `127.0.0.1:10300` | **Proven** (OP345) |
| Sound effects from text | `audio-authoring`, Stable Audio 3 Small-SFX on CPU | namespace `dev` | MCP `http://audio-authoring.dev.svc.cluster.local:8000/mcp` (`generate_sound`, `get_generation`) | **Proven** (OP343) |
| Video-conditioned Foley | ControlFoley sidecar | `ai/deploy/wan-video`, container `foley`, port 8189 | scripts only; shares the Wan compute lease | Proven once (OP344); listening verdict still open |
| Generated video | Wan2.2 TI2V-5B on ComfyUI, two RTX 3090s | `ai/deploy/wan-video` on `talosw01` | `https://video.haynesops.com/videos` | Not used by the doll format |
| Private delivery | Wan API job ledger and file route | `ai/deploy/wan-video`, container `api`, PVC `ai/wan-video` (80 Gi) | `https://video.haynesops.com/videos/<id>/file` | **Proven** (OP345) |

## ComfyUI (images)

- Image `ghcr.io/thaynes43/comfyui`, ComfyUI 0.39.0, no custom nodes (only what
  ComfyUI ships). Source and image notes: haynes-ops `scripts/comfyui/README.md`.
  Deployment: `kubernetes/main/apps/ai/stable-diffusion/comfyui/`.
- One GPU, pinned by UUID: the 16 GB RTX 2000 Ada on `talosm03`. Inside the
  container it is `gpu:0`.
- **Shared.** Home Assistant (AppDaemon camera renders) and Open WebUI chat renders
  use the same server and the same loaded models. Check `GET /queue` first, keep one
  prompt in flight, and do not unload models that others are using.
- Stored workflows (haynes-ops `.../comfyui/resources/`):
  - UI format: `image_qwen_image_2_1_t2i.json`, `image_qwen_image_2_1_image_edit.json`,
    `image_qwen_Image_2512.json`, `02_qwen_Image_edit_subgraphed.json`.
  - API format (what you POST to `/prompt`): `image_qwen_Image_2512_API.json`,
    `qwen_image_2_1_edit_API.json`, `qwen_image_2_1_edit_3frame_API.json`,
    `qwen_image_edit_2509_single_image_API.json`,
    `02_qwen_Image_edit_subgraphed_API.json`,
    `02_qwen_Image_edit_subgraphed_three_images_API.json`.
- Models include Qwen-Image 2.1 (int8 and bf16), Qwen-Image 2512 (fp8),
  Qwen-Image-Edit 2509 (fp8), and the Qwen-Image-Edit-2509 Lightning 4-step LoRA.
  There is no API-format text-to-image graph for Qwen-Image 2.1 yet, only the UI one.
- Timing from the deployment notes: warm Qwen-Image 2.1 edit render 80 to 86 s, cold
  first render about 306 s while models load off NFS.
- **Output retention: 30 days.** A CronJob deletes top-level output images older
  than 30 days. Copy anything you need into the job directory straight away.
- The UI is at `https://comfyui.haynesops.com` for people on the LAN. Agents use the
  in-pod HTTP API (`/prompt`, `/history/<id>`, `/view?filename=...`).
- No alpha output: Qwen renders an opaque image. Doll cutouts need a background
  removal step (see the runbook).

## Kokoro (voices)

- Kokoro-82M v1.0, image `flight777/kokoro-wyoming-ml` pinned by digest
  (`46418df6...`). Stock voices only, no cloning.
- Voices used so far: `af_heart`, `am_puck` (OP341); `bf_emma`, `af_bella` (OP345).
  Ask the server with a Wyoming `Describe` to list the voices installed now; do not
  assume.
- The Wyoming client code is in haynes-ops `scripts/wan-video/butter_speech.py`
  (`CODE`), sent through `kubectl exec -i`. It returns a WAV (24 kHz mono in OP345).

## Whisper (transcript check)

- Image `ghcr.io/thaynes43/wyoming-whisper-gpu:3.8.1-3`, configured model
  `nemo-parakeet-tdt-0.6b-v2`. Despite the deployment's name, the model is not
  Whisper.
- The Wyoming client code is in haynes-ops `scripts/wan-video/check_butter_dialogue.py`
  (`CODE`). Feed it 16 kHz mono PCM of the finished movie and compare a normalized
  transcript with the script.
- A matching transcript shows the words are intelligible. It says nothing about voice
  quality or comic timing.

## audio-authoring (sound effects)

- Stable Audio 3 Small-SFX, CPU, in namespace `dev`. One generation runs at a time
  and four may wait. Results come from `/artifacts/<job-id>/output.wav`; check the
  checksum. Runbook: haynes-ops `.agents/runbooks/audio-authoring.md`.
- Text-only sound effects were judged harsh or out of sync in the butter ASMR work
  (OP343). Short single cues (a crow caw, a twig snap) are a better fit than beds.
- Commercial licensing for this model has not been checked. Settle that in the
  release story, before anything is published.

## Wan API (storage and delivery)

- `ai/deploy/wan-video` has containers `api` (port 8080), `app` (ComfyUI with Wan,
  port 8188) and `foley` (port 8189). The two RTX 3090s are on `talosw01`.
- Video presets: `preview` 832x480, 49 frames, 24 fps; `720p` 1280x704, 81 frames.
  One active compute lease, `409` when busy, 20 minute timeout. Do not resubmit
  blindly after a lost response; read the job first.
- Edited (CPU-made) productions are saved create-only under
  `/workspace/output/productions/<id>/` on PVC `ai/wan-video`, with a ledger JSON in
  `/workspace/jobs/`. The API then serves them at
  `https://video.haynesops.com/videos/<ledger-id>/file`, the same as GPU outputs.
  Reference: haynes-ops `scripts/wan-video/preserve_doll_short.py`.
- The PVC is 80 Gi with no backup or retention policy. Check free space before a
  batch.
- Links on `video.haynesops.com` may not open off the home network.
- Runbook: haynes-ops `.agents/runbooks/dual-3090-video.md`.

## What an agent pod needs

- `kubectl` with the dev-env agent identity (it allows `pods/exec` into these pods).
- A user-local Python venv for editing. The versions known to work:
  Python 3.11, `av==18.1.0`, `numpy==2.4.6`, `Pillow==13.0.0`,
  `imageio-ffmpeg==0.7.0`. The OP345 venv lived in the old session's home and is not
  in fresh pods.
- No GPU in the agent pod, and none is needed: every GPU step runs in a service pod.
