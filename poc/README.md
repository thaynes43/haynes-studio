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
| `s2v.py` | E0 | Wan 2.2 speech-to-video for a talking shot (keyframe plus line audio), two-GPU CFG split |
| `layered.py` | E0 | Layered shot: Wan set loop plus a keyed Wan doll-on-green clip, with syllable-synced bounce |
| `assemble_video.py` | E0 | Joins and trims Wan clips per cut, upscales, and muxes a soundtrack |
| `foley.py` | E0 | One ControlFoley take on a Wan clip through the Foley service's HTTP API |
| `deliver.py` | 7 | Copies assets create-only to the Wan PVC, validates and links the ledger, verifies through the API in the pod |

Everything is driven by a title manifest (`titles/<slug>/manifest.json`); see the
runbook. Run the image and edit tools with the studio venv (`~/.cache/studio-venv/bin/python`, see
runbook stage 0) and `OPENBLAS_NUM_THREADS=2`. `comfy.py`, `speech.py` and `deliver.py`
need only the system `python3` and `kubectl`.
