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

Run the image tools with the studio venv (`~/.cache/studio-venv/bin/python`, see
runbook stage 0) and `OPENBLAS_NUM_THREADS=2`. `comfy.py` needs only the system
`python3` and `kubectl`.
