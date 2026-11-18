"""Story 428: read each speech-to-video clip this store's runs made, with its Wan job's
ledger, read-only, and write one summary per clip.

For every ``s2v_clip_record-<sha>`` stage under ``STORE/productions/<prd>/records/`` (or
only those of the run IDs given), the record blob is read from the store, and the job's
ledger with ``GET /videos/<job>`` inside the Wan API container (the read the client's
``wan_ledger_read.py`` makes; nothing is written there). Writes ``OUT/<board>-<slot>.
s2v-clip-record.json``, ``OUT/<board>-<slot>.wan-ledger.json`` (create-only, an existing
file is skipped) and prints one JSON summary line per clip.

    uv run python titles/the-winter-menu/e1-build/tools/clips.py STORE OUT [RUN_ID ...]
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

READ = ("import sys,urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8080/videos/'"
        "+sys.argv[1]).read().decode())")


def ledger(job_id: str) -> dict:
    out = subprocess.run(["kubectl", "exec", "-n", "ai", "deploy/wan-video", "-c", "api", "--",
                          "python3", "-c", READ, job_id], capture_output=True, check=True,
                         timeout=60).stdout
    return json.loads(out)


def save(path: Path, document) -> None:
    if path.exists():
        return
    with path.open("x", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main(store: str, out: str, *runs: str) -> int:
    root, target = Path(store), Path(out)
    target.mkdir(parents=True, exist_ok=True)
    for stage_path in sorted(root.glob("productions/*/records/*/s2v_clip_record-*.json")):
        run_id = stage_path.parent.name
        if runs and run_id not in runs:
            continue
        stage = json.loads(stage_path.read_text())
        record = json.loads((root / stage["blobs"]["record"]["locator"]).read_text())
        clip, wan = record["clip"], record["clip"]["extra"]["wan"]
        job = ledger(wan["job_id"])
        peaks = {}
        for sample in job.get("telemetry") or []:
            for gpu in sample["gpus"]:
                peaks[gpu["uuid"]] = max(peaks.get(gpu["uuid"], 0), gpu["temperature_c"])
        board = record.get("board_id") or "board"
        name = f"{wan['board_frames']}f-seed{wan['seed']}"
        save(target / f"{name}.s2v-clip-record.json", record)
        save(target / f"{name}.wan-ledger.json", job)
        print(json.dumps({
            "run_id": run_id, "file": name, "job_id": wan["job_id"], "seed": wan["seed"],
            "board_frames": wan["board_frames"], "chunks": wan.get("chunks"),
            "frames_requested": wan["frames_requested"], "frames_delivered": wan["frames_delivered"],
            "fps": wan["measured"]["fps"], "size": [wan["measured"]["width"], wan["measured"]["height"]],
            "clip_sha256": wan["clip_sha256"], "clip_bytes": wan["clip_bytes"],
            "render_s": wan["render_s"], "fetch_s": wan["fetch_s"], "wall_s": wan["wall_s"],
            "cooldown_s": wan["cooldown_s"], "start_temps": wan["start_temps"],
            "cool_before_upload": wan["cool_before_upload"],
            "engine_read_retries": wan["engine_read_retries"], "poll_misses": wan["poll_misses"],
            "unexpected_work_seen": wan["unexpected_work_seen"], "peak_gpu_mib": wan["peak_gpu_mib"],
            "recovered": wan["recovered"], "peak_temp_c": peaks,
            "ledger": {"state": job.get("state"), "bytes": job.get("bytes"),
                       "graph_sha256_matches": job.get("graph_sha256") == wan["graph_sha256"],
                       "bytes_match": job.get("bytes") == wan["clip_bytes"],
                       "created_at": job.get("created_at"), "finished_at": job.get("finished_at")},
            "trimmed": clip.get("trimmed"), "frames_needed": clip.get("frames_needed")},
            sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
