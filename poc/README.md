# poc/

Throwaway helpers for the manual proof of concept
([runbook](../docs/process/manual-short-poc.md)). They make the manual run repeatable
and show what the real tooling must do. They are not the tooling. Expect them to be
replaced.

| File | Stage | What it does |
|---|---|---|
| `comfy.py` | 2 | Submits one Qwen-Image 2.1 text-to-image or edit job to the shared ComfyUI from inside its pod, waits for an idle queue, saves create-only, logs `records.jsonl` |
| `graphs/qwen_image_2_1_t2i_API.json` | 2 | API-format text-to-image graph, hand-converted from haynes-ops' UI template |
| `cutout.py` | 2 | Chroma-keys a doll on #00FF00 into an RGBA cutout (`--resize`, `--protect`) |
| `contact_sheet.py` | 2 | Labelled review grid of candidates |
| `studio.py` | 3 to 7 | Shared helpers: manifest loading, audio I/O, loudness, and the Kokoro (TTS) and Whisper (ASR) Wyoming clients lifted from haynes-ops |
| `speech.py` | 3 | Synthesizes every manifest line with Kokoro and pre-checks each with ASR |
| `edit.py` | 5, 6 | Manifest-driven rigid-puppet editor: `audio`, `preview`, `render`, `validate`, `transcript`, each create-only in `--out` |
| `keyframes.py` | E0 | Composes each shot's first frame from a manifest as a Wan keyframe |
| `wan.py` | E0 | One Wan TI2V image-to-video clip through the Wan API's own `generate()` under its compute lease (OP342 path), cool-idle gate, ledger |
| `e0_batch.py` | E0 | Sequential batch of whole-frame and layer clips for The Winter Menu |
| `s2v.py` | E0 | Wan 2.2 speech-to-video for a talking shot (keyframe plus line audio); by default 20 steps at cfg 6 with a two-GPU CFG split |
| `s2v.py --lightning` | E0 | The current S2V profile for doll talking shots (D24): the template's 4-step lightning LoRA at cfg 1 on one 3090, about 4 min per 4.8 s chunk |
| `layered.py` | E0 | Layered shot: Wan set loop plus a keyed Wan doll-on-green clip, with syllable-synced bounce |
| `layered_film.py` | E0 | Full layered film: every doll in every shot is a keyed Wan doll-on-green clip over a Wan set loop, with the manifest's layouts, talk bounce, moves and camera, muxed with a soundtrack. Shot-specific clips (such as S2V from the shot's voice track) play locked to the shot's clock. Optional decals stop the render on a weak track. `--workers` 1 in a session pod, up to 22 on studio-render |
| `decal.py` | E0 | Tracked lettering decal: follows the jacket through a Wan doll clip (OpenCV ECC, affine), erases Wan's garbled lettering and pastes the still's lettering warped by that motion; writes per-frame tracking scores. Below `MIN_ECC` (0.8) the clip should be re-rolled |
| `assemble_video.py` | E0 | Joins and trims Wan clips per cut, upscales, and muxes a soundtrack |
| `foley.py` | E0 | One ControlFoley take on a Wan clip through the Foley service's HTTP API |
| `deliver.py` | 7 | Copies assets create-only to the Wan PVC, validates and links the ledger, verifies through the API in the pod |

`wan.py`, and the helpers built on it (`s2v.py`, `e0_batch.py`), reach the Wan API by
importing its `api` module inside the Wan pod and swapping `api.make_graph` for a job-local
graph. That is a PoC shortcut and stays as it is here. Typed product Wan operations
(image-to-video, S2V, Foley) belong to [R36 · 458](https://work.haynesnetwork.com/projects/haynes-studio/work_packages/458), a typed job interface on the Wan API (see
[the backlog review](../docs/backlog/review-2026-11-05.md)), not to in-pod monkeypatching.

Everything is driven by a title manifest (`titles/<slug>/manifest.json`); see the
runbook. Run the image and edit tools with the studio venv (`~/.cache/studio-venv/bin/python`, see
runbook stage 0) and `OPENBLAS_NUM_THREADS=2`. `comfy.py`, `speech.py` and `deliver.py`
need only the system `python3` and `kubectl`.
