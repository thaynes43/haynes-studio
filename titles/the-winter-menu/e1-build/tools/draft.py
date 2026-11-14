"""Story 428, step c and d: the new fire bed as a sound version, and the buildable draft.

One-off driver over the package's own functions (no package code is changed):

1. publish the new bed's bytes (audio-authoring job ``ebe4a478...``, D54) into the store,
   create-only, with the job's own SHA-256 as the expected hash;
2. import it as a new ``sound`` version (a new asset, its own source key) into the
   library the private import wrote; the r4 bed's version is not touched;
3. write the draft: the story the legacy import wrote, with the bed pointed at the new
   version, the set's motion pinned to E0's set loop, and ``s2v:<slot>`` seeds for every
   speaker (E0's seed of the clip that board and slot used, so the new clips compare
   with E0's).

Writes ``OUT/story.json`` and ``OUT/library.json`` create-only (``OUT`` must not exist).

    uv run python titles/the-winter-menu/e1-build/tools/draft.py JOB_DIR OUT
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from haynes_studio.canonical.model import Principal
from haynes_studio.library.library import Library, VersionRequest, import_version
from haynes_studio.library.model import Content, Scope
from haynes_studio.library.winter_menu import REGISTER_PATH, load_licence_register
from haynes_studio.store.local import LocalStore

BED_JOB = "ebe4a478d4cf44e3974fea1da6a179cb"
BED_SHA256 = "0b33af45929b8cfb3859bf1511a2738eef22944d431ee44257c33a1de42da72a"  # as the job reported
BED_SERVICE = "audio-authoring (Stable Audio 3 Small SFX, CPU)"  # as r4 recorded the service
BED_PROMPT = ("A small campfire crackling and popping softly outdoors in a quiet forest, steady "
              "gentle crackle, no wind, no music, no voices")
OLD_BED_VERSION = "asv_01M7BVBVSBHA26B6V3F90A35MT"
SET_LOOP_KEY = "legacy:winter-menu-video-e0:set-loop:set-plate.png"
# E0's speech-to-video seeds (titles/the-winter-menu/video-e0/clip-records-s2v.jsonl), by board number and slot.
E0_SEEDS = {1: {"a": 510}, 2: {"b": 501}, 3: {"c": 512}, 4: {"a": 513}, 5: {"d": 514},
            6: {"c": 515}, 8: {"a": 516, "b": 517, "c": 518, "d": 519}, 9: {"b": 520}}
NOW = "2026-11-14T01:45:00Z"
BY = Principal(kind="agent_session", session="haynes-studio-1114-013021", harness="Claude Code",
               model="claude-opus-5-5")


def create(path: Path, document) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    path.chmod(0o444)


def main(job_dir: str, out: str) -> int:
    job, target = Path(job_dir), Path(out)
    target.mkdir()  # a new folder: fails if it exists
    story = json.loads((job / "import" / "story.json").read_text())
    library = Library.from_version_documents(
        json.loads((job / "import-run1" / "library.json").read_text()))
    production = story["production_id"]

    store = LocalStore(job / "store")
    wav = job / "sfx" / f"fire-{BED_JOB[:8]}-s701.wav"
    with wav.open("rb") as handle:
        blob = store.publish(handle, scope=production, media_type="audio/wav",
                             expected_sha256=BED_SHA256)
    print(f"bed published: {blob.locator} ({blob.bytes} bytes)")

    licences = load_licence_register(REGISTER_PATH)
    outcome = import_version(library, VersionRequest(
        kind="sound", name="fire (bed, regenerated for story 428)", scope=Scope(production),
        labels=("the-winter-menu", "bed"), capabilities=("sound_bed",),
        content=Content(sha256=blob.sha256, bytes=blob.bytes, media_type=blob.media_type,
                        locator=blob.locator),
        provenance={"origin": "generated", "external": None,
                    "source_key": f"audio-authoring:job:{BED_JOB}",
                    "generator": {"role": "sound", "engine": BED_SERVICE,
                                  "model": "Stable Audio 3 Small SFX", "seed": 701,
                                  "prompt": BED_PROMPT, "engine_job_id": BED_JOB,
                                  "params": {"seconds": 12, "steps": 8}}},
        licence=licences.licence_for("sound", BED_SERVICE)), by=BY, now=NOW)
    library, bed = outcome.library, outcome.version
    print(f"bed version: {bed.id} (created {outcome.created}); the r4 bed {OLD_BED_VERSION} unchanged")

    loops = [v for v in library.versions.values() if v.kind == "motion"
             and v.provenance.get("source_key") == SET_LOOP_KEY]
    if len(loops) != 1:
        raise SystemExit(f"expected one E0 set loop, found {len(loops)}")
    if story["set"].get("motion_asset_version_id") is not None:
        raise SystemExit("the set already pins a loop")
    story["set"]["motion_asset_version_id"] = loops[0].id
    [entry] = story["beds"]
    if entry["asset_version_id"] != OLD_BED_VERSION:
        raise SystemExit("the bed is not the r4 bed")
    entry["asset_version_id"] = bed.id
    for board in story["boards"]:
        speakers = sorted({line["speaker"] for line in board.get("lines") or []})
        seeds = E0_SEEDS.get(board["number"], {})
        if speakers != sorted(seeds) or board.get("seeds"):
            raise SystemExit(f"board {board['number']}: speakers {speakers}, seeds {board.get('seeds')}")
        board["seeds"] = {f"s2v:{slot}": seed for slot, seed in seeds.items()}
    create(target / "story.json", story)
    create(target / "library.json", library.documents())
    print(f"set loop: {loops[0].id}; seeds written on {sum(1 for b in story['boards'] if b['seeds'])} boards")
    print(f"wrote {target / 'story.json'} and {target / 'library.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
