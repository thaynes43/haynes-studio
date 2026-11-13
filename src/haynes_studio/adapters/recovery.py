"""The private-input recovery map for The Winter Menu r1 to r4.

Builds, from the public manifests and evidence JSON only, one row per input file each
revision used: cast stills, the set, sound effects, beds and speech takes; the renders
the stills and set were cut from; and the E0 keyframes composed from r4. Each row has
its expected SHA-256 (or ``missing`` when no public file records one), the private
places the evidence says a copy was written, and status ``unverified``: nobody has
looked, so the map claims no file exists. Private paths stay as recorded (``~`` is
never expanded).

A hash comes from every public record that names the file (the delivery ledger in
``evidence*/production.json``, ``speech.json``, ``timeline.json``, ``prompts.json``,
``keyframes.json``, the E0 clip records); if two records disagree the build fails.

    python -m haynes_studio.adapters.recovery > docs/reference/legacy-recovery-map.json
    python -m haynes_studio.adapters.recovery --check docs/reference/legacy-recovery-map.json

The committed JSON must equal :func:`render` of :func:`build` (a test checks it), and the
Markdown table in ``docs/reference/legacy-recovery-map.md`` must equal
:func:`markdown_rows`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from haynes_studio.jsonio import parse_strict, read_json

TITLE = "titles/the-winter-menu"
REVISIONS = ((1, "manifest.json", "evidence"), (2, "manifest-r2.json", "evidence-r2"),
             (3, "manifest-r3.json", "evidence-r3"), (4, "manifest-r4.json", "evidence-r4"))
PROMPTS = f"{TITLE}/prompts.json"
KEYFRAMES = f"{TITLE}/video-e0/keyframes.json"
CLIP_RECORDS = f"{TITLE}/video-e0/clip-records.jsonl"
MISSING = "missing"
UNVERIFIED = "unverified"
WAN_PRODUCTIONS = "/workspace/output/productions/"
WAN_UPLOADS = "/workspace/input/studio-e0/"
ROLES = ("render", "still", "set", "sfx", "bed", "take", "keyframe")
STATUS_MEANING = ("unverified: no one has checked that a file exists at any locator or that "
                  "its bytes have the expected sha256. This map claims no file exists.")


class RecoveryConflict(ValueError):
    """Two public records give different hashes for one input."""


class _Sources:
    def __init__(self, root: Path):
        self.root = root
        self.read: dict[str, str] = {}

    def json(self, rel: str) -> Any:
        parsed = read_json(self.root / rel)
        self.read[rel] = parsed.sha256
        return parsed.document

    def jsonl(self, rel: str) -> list[Any]:
        data = (self.root / rel).read_bytes()
        self.read[rel] = hashlib.sha256(data).hexdigest()
        return [parse_strict(line) for line in data.decode("utf-8").splitlines() if line.strip()]


def _locator(kind: str, recorded_in: list[str], **fields: Any) -> dict:
    return {"kind": kind, **fields, "recorded_in": recorded_in, "status": UNVERIFIED}


def _row(rows: dict, *, revision: int, job: str | None, role: str, file: str,
         hashes: list[tuple[str, str]], size: int | None, locators: list[dict],
         provenance: dict | None = None, gaps: list[str] | None = None) -> None:
    key = f"r{revision}:{role}:{file}"
    if key in rows:
        raise RecoveryConflict(f"{key}: listed twice")
    distinct = sorted({digest for _, digest in hashes})
    if len(distinct) > 1:
        raise RecoveryConflict(f"{key}: recorded hashes differ: "
                               + ", ".join(f"{src} {digest}" for src, digest in hashes))
    rows[key] = {
        "key": key, "revision": revision, "job": job, "role": role, "file": file,
        "sha256": distinct[0] if distinct else MISSING,
        "bytes": size,
        "hash_recorded_in": sorted({src for src, _ in hashes}),
        "provenance": provenance,
        "locators": locators,
        "locator_gaps": gaps or [],
        "status": UNVERIFIED,
    }


def _revision(rows: dict, src: _Sources, revision: int, manifest_name: str, evidence: str) -> dict:
    manifest_rel = f"{TITLE}/{manifest_name}"
    production_rel = f"{TITLE}/{evidence}/production.json"
    speech_rel = f"{TITLE}/{evidence}/speech.json"
    timeline_rel = f"{TITLE}/{evidence}/timeline.json"
    m = src.json(manifest_rel)
    ledger = src.json(production_rel)
    speech = src.json(speech_rel)
    timeline = src.json(timeline_rel)
    job, job_dir = m["job"], m["job_dir"]
    prefix = f"{WAN_PRODUCTIONS}{job}/"
    assets = {a["path"][len(prefix):]: a for a in ledger["assets"] if a["path"].startswith(prefix)}
    audio = {a["file"]: a for a in timeline["audio"]}

    def add(role, file, hashes, provenance=None, recorded_in=(manifest_rel,)):
        asset = assets.get(file)
        if asset:
            hashes = [*hashes, (production_rel, asset["sha256"])]
        if file in audio:
            hashes = [*hashes, (timeline_rel, audio[file]["sha256"])]
        locators = [_locator("job_dir", list(recorded_in), job_dir=job_dir, path=file)]
        gaps = []
        if asset:
            locators.append(_locator("wan_pvc", [production_rel], pvc="ai/wan-video",
                                     ledger_id=ledger["id"], path=asset["path"]))
        else:
            gaps.append(f"not in the r{revision} delivery ledger, so poc/deliver.py did not "
                        "copy it to the Wan PVC")
        _row(rows, revision=revision, job=job, role=role, file=file, hashes=hashes,
             size=asset["bytes"] if asset else None, locators=locators, provenance=provenance,
             gaps=gaps)

    stills = []
    for shot in m["shots"]:
        for file in shot["dolls"].values():
            if file not in stills:
                stills.append(file)
    for file in stills:
        add("still", file, [])
    add("set", m["set"]["image"], [])
    for role, section in (("sfx", "sfx"), ("bed", "beds")):
        for name, sound in m.get(section, {}).items():
            source = sound.get("source", {})
            add(role, sound["file"], [], {"cue": name, **{k: source[k] for k in
                                                          ("service", "job", "seed") if k in source}})
    for take in speech["lines"]:
        add("take", take["file"], [(speech_rel, take["sha256"])],
            {"shot": take["shot"], "k": take.get("k", 0), "voice": take["voice"]},
            recorded_in=(manifest_rel, speech_rel))
    return m


def _renders(rows: dict, src: _Sources, manifests: dict[str, dict]) -> None:
    prompts = src.json(PROMPTS)
    job = prompts["job"]
    manifest_rel, manifest = manifests[job]
    renders = {r["name"]: r for r in prompts["renders"]}
    used_by: dict[str, list[str]] = {}
    for item in [*prompts["cutouts"], prompts["set"]]:
        name = item["source"]
        used_by.setdefault(name, []).append(item["file"])
        upstream = renders[name].get("source")
        if upstream:
            used_by.setdefault(upstream.removesuffix(".png"), []).append(name)
    for name, render in renders.items():
        if name not in used_by:
            continue  # rejected candidates are not inputs
        provenance = {k: render[k] for k in ("mode", "graph", "graph_sha256", "seed", "width",
                                             "height", "source", "prompt_file", "prompt_id")}
        provenance["used_by"] = sorted(set(used_by[name]))
        locators = [
            _locator("job_dir", [PROMPTS, manifest_rel], job_dir=manifest["job_dir"],
                     path=f"{name}.png",
                     derivation="poc/comfy.py writes <job dir>/<name>.png; prompts.json job is "
                                + job),
            _locator("comfyui_output", [PROMPTS], pod="ai/comfyui-0",
                     filename_prefix=f"studio/{job}/{name}",
                     derivation="graph_sha256 rebuilds with this filename_prefix "
                                "(tests/adapters/test_compat.py); the saved file name is not "
                                "recorded. A CronJob deletes top-level outputs after 30 days; "
                                "whether it reaches studio/ subfolders is not recorded"),
        ]
        _row(rows, revision=1, job=job, role="render", file=f"{name}.png",
             hashes=[(PROMPTS, render["sha256"])], size=None, locators=locators,
             provenance=provenance)
    for item in prompts["cutouts"]:  # the cut stills' hashes, checked against each revision
        for key, row in rows.items():
            if row["role"] == "still" and row["file"] == "cutouts/" + item["file"] \
                    and row["sha256"] != item["sha256"]:
                raise RecoveryConflict(f"{key}: prompts.json records {item['sha256']}")
    for key, row in rows.items():
        if row["role"] == "set" and row["sha256"] != prompts["set"]["sha256"]:
            raise RecoveryConflict(f"{key}: prompts.json records {prompts['set']['sha256']}")


def _keyframes(rows: dict, src: _Sources) -> None:
    keyframes = src.json(KEYFRAMES)
    clips = src.jsonl(CLIP_RECORDS)
    for frame in keyframes:
        uses = [c for c in clips if c.get("image_sha256") == frame["sha256"]
                and c.get("image") == frame["file"]]
        locators = []
        if uses:
            locators.append(_locator(
                "wan_upload", [KEYFRAMES, CLIP_RECORDS], pvc="ai/wan-video",
                path=f"{WAN_UPLOADS}{frame['sha256'][:16]}.png",
                engine_jobs=[c["job_id"] for c in uses],
                derivation="poc/wan.py uploads an image as studio-e0/<first 16 hex digits of its "
                           "sha256>.png under /workspace/input/"))
        _row(rows, revision=4, job=None, role="keyframe", file=frame["file"],
             hashes=[(KEYFRAMES, frame["sha256"])], size=None, locators=locators,
             provenance={"composed_by": "poc/keyframes.py", "manifest": f"{TITLE}/manifest-r4.json",
                         "shot": frame["shot"], "layout": frame["layout"]},
             gaps=["the OUT_DIR poc/keyframes.py wrote to was not recorded"])


def build(root: str | Path) -> dict:
    """The recovery map, built from the public files under ``root`` (a checkout)."""
    src = _Sources(Path(root))
    rows: dict[str, dict] = {}
    manifests = {}
    for revision, manifest_name, evidence in REVISIONS:
        m = _revision(rows, src, revision, manifest_name, evidence)
        manifests[m["job"]] = (f"{TITLE}/{manifest_name}", m)
    _renders(rows, src, manifests)
    _keyframes(rows, src)
    ordered = sorted(rows.values(), key=lambda r: (r["revision"], ROLES.index(r["role"])))
    by_role = {role: sum(r["role"] == role for r in ordered) for role in ROLES}
    by_revision = {f"r{n}": sum(r["revision"] == n for r in ordered) for n, _, _ in REVISIONS}
    return {
        "kind": "legacy-recovery-map",
        "version": 1,
        "title": "The Winter Menu",
        "story": "https://work.haynesnetwork.com/work_packages/425",
        "status_meaning": STATUS_MEANING,
        "built_by": "python -m haynes_studio.adapters.recovery",
        "sources": [{"path": rel, "sha256": digest} for rel, digest in sorted(src.read.items())],
        "summary": {"rows": len(ordered), "missing_sha256": sum(r["sha256"] == MISSING
                                                               for r in ordered),
                    "by_role": by_role, "by_revision": by_revision},
        "rows": ordered,
    }


def render(recovery_map: dict) -> str:
    """The committed JSON text: two-space indent, ASCII, one trailing newline."""
    return json.dumps(recovery_map, indent=2, ensure_ascii=True) + "\n"


def markdown_rows(recovery_map: dict) -> str:
    """The Markdown table of rows that ``docs/reference/legacy-recovery-map.md`` embeds."""
    lines = ["| Row | SHA-256 (first 16) | Bytes | Locators (all unverified) |",
             "|---|---|---|---|"]
    for row in recovery_map["rows"]:
        digest = row["sha256"] if row["sha256"] == MISSING else row["sha256"][:16]
        size = "" if row["bytes"] is None else str(row["bytes"])
        kinds = ", ".join(loc["kind"] for loc in row["locators"]) or "none recorded"
        lines.append(f"| `{row['key']}` | `{digest}` | {size} | {kinds} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys
    parser = argparse.ArgumentParser(prog="python -m haynes_studio.adapters.recovery",
                                     description="Print the Winter Menu recovery map, or check a "
                                                 "committed copy. Reads public files only.")
    parser.add_argument("--root", default=".", help="the checkout to read (default: .)")
    parser.add_argument("--check", metavar="FILE", help="exit 1 if FILE differs from the build")
    args = parser.parse_args(argv)
    text = render(build(args.root))
    if args.check:
        same = Path(args.check).read_text(encoding="utf-8") == text
        print(f"{args.check}: {'matches' if same else 'differs from'} the build")
        return 0 if same else 1
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
