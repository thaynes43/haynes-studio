"""Story 428, step j: the coordinator's decisions of 2026-11-14 04:02Z as a new draft version.

Reads ``SOURCE/story.json`` (a voiced draft) and writes ``OUT/story.json`` create-only
(``OUT`` must not exist) with:

- the story's ``closeup`` layout preset (only board 7 uses it): slot ``d`` ``x`` 0.56 ->
  0.55, so the keyed close-up stays inside the 240 px off-frame margin;
- re-roll seeds: board 1 ``s2v:a`` 510 -> 610, board 9 ``s2v:b`` 520 -> 620 (or the
  values given as ``--seed BOARD:SLOT:SEED``, for a second re-roll);
- the story's ``revision`` and each edited board's ``revision`` raised by one.

Nothing else changes; the old clips stay in the store.

    uv run python titles/the-winter-menu/e1-build/tools/redraft.py SOURCE OUT [--no-layout] [--seed 1:a:610 ...]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("out")
    parser.add_argument("--no-layout", action="store_true", help="leave the closeup preset as it is")
    parser.add_argument("--seed", action="append", default=None)
    args = parser.parse_args()
    seeds = args.seed or ["1:a:610", "9:b:620"]
    story = json.loads((Path(args.source) / "story.json").read_text())
    target = Path(args.out)
    target.mkdir()
    edited = set()
    if not args.no_layout:
        slot = story["layouts"]["closeup"]["slots"]["d"]
        if slot["x"] != 0.56:
            raise SystemExit(f"closeup d x is {slot['x']}, not 0.56")
        slot["x"] = 0.55
        print("closeup d x: 0.56 -> 0.55")
    for item in seeds:
        number, slot_name, seed = item.split(":")
        [board] = [b for b in story["boards"] if b["number"] == int(number)]
        key = f"s2v:{slot_name}"
        print(f"board {number} {key}: {board['seeds'][key]} -> {seed}")
        board["seeds"][key] = int(seed)
        edited.add(board["id"])
    story["revision"] += 1
    for board in story["boards"]:
        if board["id"] in edited:
            board["revision"] += 1
    with (target / "story.json").open("x", encoding="utf-8") as handle:
        json.dump(story, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    (target / "story.json").chmod(0o444)
    print(f"story revision {story['revision']}; wrote {target / 'story.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
