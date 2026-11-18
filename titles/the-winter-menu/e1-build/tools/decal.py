"""Story 428: the decal scores of every keyed-frames artifact in the store, read-only.

For each ``keyed_frames-<hex>`` stage under ``STORE/productions/<prd>/records/<run>/``,
reads the APNG's ``studio.keyed-frames/v1`` record (``layered.keyed.read_record``) and
prints one JSON line: the keyed key, the stage's run, frames, the decal box, min and mean
ECC over every tracked frame, failed frames, and the five lowest-scoring source frames.
The gate itself is applied over the frames a board shows (``layered.renderer``); this
lists the whole clip, so a person can judge a weak track by eye.

    uv run python titles/the-winter-menu/e1-build/tools/decal.py STORE
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from haynes_studio.layered.keyed import read_record


def main(store: str) -> int:
    root, seen = Path(store), set()
    for stage_path in sorted(root.glob("productions/*/records/*/keyed_frames-*.json")):
        stage = json.loads(stage_path.read_text())
        blob = stage["blobs"]["keyed_frames"]
        if blob["sha256"] in seen:
            continue
        seen.add(blob["sha256"])
        record = read_record((root / blob["locator"]).read_bytes())
        decal = record.get("decal") or {}
        scores = decal.get("scores") or []
        lowest = sorted(range(len(scores)), key=lambda i: (scores[i] is None, scores[i]))[:5]
        print(json.dumps({
            "keyed_key": record["key"], "run_id": stage_path.parent.name,
            "keyed_sha256": blob["sha256"], "frames": record["frames"], "clip_size": record["clip_size"],
            "decal_box": decal.get("box"), "min_ecc": decal.get("min_ecc"), "mean_ecc": decal.get("mean_ecc"),
            "failed_frames": decal.get("failed_frames"), "frames_tracked": decal.get("frames_tracked"),
            "lowest": [[i, scores[i]] for i in lowest]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
