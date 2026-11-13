"""The E0 clips of The Winter Menu as motion records, from public text only (story 457).

Reads ``titles/the-winter-menu/video-e0/`` (the three clip record files, the three
clipmaps, ``decal-scores.json``, ``assembly-wf.json`` and ``keyframes.json``), r4's
manifest and ``timeline.json``, the recovery map of story 425 (the cutouts' and the
set's hashes) and two constants of the PoC code. No media is read, no service called.

Every line of the three clip record files gets one :class:`E0Row`: a recorded motion
version, or the reason it is not one. What no public text records is a :class:`Gap`
and the field is left out, never guessed. Values taken from the PoC code rather than
a clip record are named in :data:`FROM_CODE`.

- **Doll loops:** every clip a layered clipmap names for a cutout. One asset per
  cutout; its clips are its versions in recording order. The clips the delivered
  layered v2 and layered S2V films used (``clipmap-layered-v2.json``) are
  ``promoted`` with that clipmap's keying; the three the sleeves-fixed clips replaced
  are ``candidate`` and record no keying (their only film keyed them with a decal that
  had no version name yet).
- **Set loop:** ``layer-set-loop`` (``set-plate.png``, ``poc/e0_batch.py``),
  ``promoted``. No public record ties ``set-plate.png`` to r4's set, so its still is
  a gap and a story uses it only by pinning it.
- **Timed clips:** the eleven speech-to-video clips of ``clipmap-s2v.json``'s
  ``shots``, ``promoted``, each with its drive track and r4 board length.
- **Not motion clips:** the whole-frame image-to-video clips of ``assembly-wf.json``
  (story 427's whole-frame clips) and the whole-frame speech-to-video test clip.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from haynes_studio.canonical.ids import Minter
from haynes_studio.canonical.model import Principal
from haynes_studio.errors import ContractError, Violation
from haynes_studio.jsonio import parse_strict, read_json
from haynes_studio.library.library import EMPTY, Library, Outcome, VersionRequest, import_all
from haynes_studio.library.model import CANDIDATE, PROMOTED, Content, Scope, locator_for
from haynes_studio.library.winter_menu import EVIDENCE_MISMATCH, LicenceRegister
from haynes_studio.motion.identity import motion_identity
from haynes_studio.motion.record import (
    DOLL,
    LOOP,
    SET,
    SUBJECT_CAPABILITY,
    TIMED,
    MotionRecord,
    playback,
    timed_trim,
)
from haynes_studio.render.clock import s2v_request_frames

E0 = "video-e0"
RECORD_FILES = ("clip-records.jsonl", "clip-records-layers.jsonl", "clip-records-s2v.jsonl")
JOB = "winter-menu-video"  # poc/e0_batch.py: ~/studio-jobs/winter-menu-video
SOURCE_PREFIX = "legacy:winter-menu-video-e0"
MP4 = "video/mp4"

# Settings the clip records do not carry, from the PoC code that made or keyed the clips
# (contract label "Legacy"; each named in the reference's E0 table).
ENGINE = "ComfyUI on ai/deploy/wan-video, through the Wan API's generate() (poc/wan.py)"
TI2V_MODEL = "Wan2.2 TI2V-5B"  # contract section 5; findings.md
TI2V_FPS = 24  # contract section 3: TI2V-5B gives 121 frames at 24 fps
S2V_MODEL = "Wan2.2 S2V-14B fp8 (wan2.2_s2v_14B_fp8_scaled) with wav2vec2"  # findings.md
S2V_STEPS, S2V_CFG, S2V_CHUNK = 4, 1, 77  # poc/s2v.py --lightning; contract section 5
LOOP_ADAPTER = "legacy:poc/wan.py"
S2V_ADAPTER = "legacy:poc/s2v.py"
KEYER = "legacy:poc/cutout.py key"
KEY_THRESHOLDS = {"lo": 20, "hi": 70}  # DollClip.cache_dir 'key': [20, 70]; findings.md
DECAL_VERSION = "erase-v2"  # DollClip.cache_dir 'decal', since commit 8f16830
DECAL_MIN_ECC = 0.8  # poc/decal.py MIN_ECC; a clipmap's decal_min_ecc overrides it

FROM_CODE = {
    "keying.keyer": "poc/cutout.py key (findings.md: keyed with cutout.key)",
    "keying.key_thresholds": "poc/layered_film.py DollClip.cache_dir 'key': [20, 70]",
    "keying.decal_version": "poc/layered_film.py DollClip.cache_dir 'decal': 'erase-v2'",
    "keying.decal_min_ecc": "poc/decal.py MIN_ECC 0.8 unless the clipmap sets decal_min_ecc",
    "source.negative_prompt (timed)": "poc/wan.py NEGATIVE, which poc/s2v.py sends",
    "source.profile.lora (timed)": "poc/s2v.py LORA",
    "source.profile steps and cfg (timed)": "poc/s2v.py --lightning: 4 steps at cfg 1",
    "source.adapter, profile.adapter": "the PoC script that made the clip",
    "fps (loops)": "contract section 3: TI2V-5B gives 24 fps",
}


@dataclass(frozen=True)
class E0Row:
    """One line of a clip record file and what became of it."""

    file: str
    line: int  # 1-based
    name: str
    outcome: str  # "doll loop", "set loop", "timed clip" or "not a motion clip"
    state: str | None = None  # promoted or candidate; None when not recorded
    source_key: str | None = None
    version_id: str | None = None
    still: str | None = None  # the cutout or set it stands in for (path)
    board: int | None = None  # a timed clip's r4 board (shot)
    slot: str | None = None
    note: str = ""


@dataclass(frozen=True)
class Gap:
    """A value no public text records: the field is left out of the clip's record."""

    clip: str  # the clip record's name
    field: str
    reason: str


@dataclass(frozen=True)
class E0Motion:
    library: Library
    rows: tuple[E0Row, ...]
    outcomes: tuple[Outcome, ...]
    gaps: tuple[Gap, ...] = field(default=())

    def row(self, name: str) -> E0Row:
        return next(row for row in self.rows if row.name == name)


@dataclass(frozen=True)
class E0Sources:
    records: tuple[tuple[str, int, Mapping[str, Any]], ...]  # (file, line, record)
    clipmap_v1: Mapping[str, Any]
    clipmap_v2: Mapping[str, Any]
    clipmap_s2v: Mapping[str, Any]
    decal_scores: Mapping[str, Any]
    assembly_wf: Mapping[str, Any]
    keyframes: tuple[Mapping[str, Any], ...]
    manifest: Mapping[str, Any]  # r4
    timeline: Mapping[str, Any]  # r4
    stills: Mapping[str, str]  # recovery map: cutout or set path -> sha256
    negative_prompt: str  # poc/wan.py NEGATIVE
    s2v_lora: str  # poc/s2v.py LORA


def _mismatch(path: str, message: str) -> ContractError:
    return ContractError("<E0 public records>", [Violation(EVIDENCE_MISMATCH, path, message)])


def _poc_constant(path: Path, name: str) -> Any:
    """A module-level literal of a PoC script, read as text (never imported or run)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name
                                                for t in node.targets):
            return ast.literal_eval(node.value)
    raise _mismatch(f"/{path.name}", f"no literal {name} in {path.name}")


def load_e0_sources(repo_root: str | Path) -> E0Sources:
    """Read every public input (text and JSON only) from a checkout."""
    root = Path(repo_root)
    title = root / "titles" / "the-winter-menu"
    e0 = title / E0
    records = []
    for name in RECORD_FILES:
        for i, line in enumerate((e0 / name).read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                records.append((name, i, parse_strict(line)))
    stills: dict[str, str] = {}
    recovery = read_json(root / "docs" / "reference" / "legacy-recovery-map.json").document
    for row in recovery["rows"]:
        if row["role"] in ("still", "set"):
            if stills.setdefault(row["file"], row["sha256"]) != row["sha256"]:
                raise _mismatch("/rows", f"the recovery map gives {row['file']} two hashes")

    def doc(path: Path) -> Any:
        return read_json(path).document

    return E0Sources(
        records=tuple(records), clipmap_v1=doc(e0 / "clipmap-layered.json"),
        clipmap_v2=doc(e0 / "clipmap-layered-v2.json"), clipmap_s2v=doc(e0 / "clipmap-s2v.json"),
        decal_scores=doc(e0 / "decal-scores.json"), assembly_wf=doc(e0 / "assembly-wf.json"),
        keyframes=tuple(doc(e0 / "keyframes.json")), manifest=doc(title / "manifest-r4.json"),
        timeline=doc(title / "evidence-r4" / "timeline.json"), stills=stills,
        negative_prompt=_poc_constant(root / "poc" / "wan.py", "NEGATIVE"),
        s2v_lora=_poc_constant(root / "poc" / "s2v.py", "LORA"))


def _stem(clip_path: str) -> str:
    """``clips/layer-a-green.mp4`` -> ``layer-a-green``."""
    return Path(clip_path).stem


def _keying(entry: Mapping[str, Any]) -> dict[str, Any]:
    out = {"keyer": KEYER, "key_thresholds": dict(KEY_THRESHOLDS),
           "protect_boxes": [list(box) for box in entry.get("protect", [])],
           "decal_box": None, "decal_version": None}
    if entry.get("decal_box"):  # legacy gated the decal track only where it pasted one
        out.update(decal_box=list(entry["decal_box"]), decal_version=DECAL_VERSION,
                   decal_min_ecc=entry.get("decal_min_ecc", DECAL_MIN_ECC))
    return out


def complete_block(block: Mapping[str, Any], clip_sha256: str) -> dict[str, Any]:
    """A block with its ``playback`` (fixed by use and trim) and its ``keys`` (from
    :func:`~haynes_studio.motion.identity.motion_identity`) filled in."""
    out = dict(block)
    out["playback"] = playback(out["use"], out["trim"]["frames"])
    out["keys"] = {"clip": "sha256:" + "0" * 64, "identity": "sha256:" + "0" * 64}
    if out.get("keying") is not None:
        out["keys"]["keyed"] = "sha256:" + "0" * 64
    identity = motion_identity(MotionRecord.from_block(out), clip_sha256)
    out["keys"] = identity.keys_block()
    return out


class _Builder:
    def __init__(self, sources: E0Sources, production_id: str, licences: LicenceRegister):
        self.s = sources
        self.production_id = production_id
        self.licences = licences
        self.by_name: dict[str, tuple[str, int, Mapping[str, Any]]] = {}
        for file, line, record in sources.records:
            if record["name"] in self.by_name:
                raise _mismatch(f"/{file}/{line}", f"clip {record['name']} is recorded twice")
            self.by_name[record["name"]] = (file, line, record)
        self.images = {r["image"]: r["image_sha256"] for _, _, r in sources.records if "image" in r}
        self.requests: list[tuple[str, VersionRequest, E0Row]] = []  # (sort key, request, row)
        self.rows: list[E0Row] = []
        self.gaps: list[Gap] = []

    # Shared pieces ------------------------------------------------------------------

    def still(self, path: str) -> str:
        if path not in self.s.stills:
            raise _mismatch("/stills", f"the recovery map has no hash for {path}")
        return self.s.stills[path]

    def record(self, clip_path: str) -> tuple[str, int, Mapping[str, Any]]:
        name = _stem(clip_path)
        if name not in self.by_name:
            raise _mismatch("/clipmap", f"no clip record for {clip_path}")
        return self.by_name[name]

    def image_sha(self, still_path: str) -> str:
        name = Path(still_path).name
        if name not in self.images:
            raise _mismatch("/clipmap", f"no clip record names the image {still_path}")
        return self.images[name]

    def request(self, *, key: str, name: str, record: Mapping[str, Any], block: dict[str, Any],
                model: str, profile_params: Mapping[str, Any], state: str, attributes: dict,
                labels: tuple[str, ...]) -> VersionRequest:
        sha = record["clip_sha256"]
        block = complete_block(block, sha)
        generator: dict[str, Any] = {
            "role": "video", "engine": ENGINE, "model": model, "seed": record["seed"],
            "prompt": record["prompt"], "engine_job_id": record["job_id"],
            "params": dict(profile_params)}
        if "template_sha256" in record:
            generator["workflow_sha256"] = record["template_sha256"]
        content = Content(sha256=sha, bytes=record.get("bytes"), media_type=MP4,
                          locator=locator_for(sha, MP4, self.production_id),
                          width=record["width"], height=record["height"])
        if record.get("bytes") is None:
            self.gaps.append(Gap(record["name"], "content.bytes",
                                 "the clip record holds no byte count"))
        if "template_sha256" not in record:
            self.gaps.append(Gap(record["name"], "provenance.generator.workflow_sha256",
                                 "the clip record holds no workflow or graph hash"
                                 + (" (poc/s2v.py builds its graph in code)"
                                    if block["use"] == TIMED else
                                    " (the first E0 batch, before poc/wan.py recorded one)")))
        return VersionRequest(
            kind="motion", name=name, scope=Scope(self.production_id),
            capabilities=(SUBJECT_CAPABILITY[block["subject"]],), content=content,
            provenance={"origin": "imported", "generator": generator, "external": None,
                        "source_key": key},
            licence=self.licences.licence_for("video", model), state=state, labels=labels,
            attributes=attributes,
            legacy={"source_key": key, "path": f"clips/{record['name']}.mp4", "job": JOB},
            motion=block)

    # Loops --------------------------------------------------------------------------

    def loop_block(self, record: Mapping[str, Any], *, subject: str, still: str | None,
                   keying: dict[str, Any] | None) -> dict[str, Any]:
        if record["frames"] != record["length"]:
            raise _mismatch(f"/{record['name']}",
                            "a loop record asked for other frames than it got")
        profile = {"model": TI2V_MODEL, "adapter": LOOP_ADAPTER, "width": record["width"],
                   "height": record["height"], "length": record["length"], "fps": TI2V_FPS}
        if "template_sha256" in record:
            profile["template_sha256"] = record["template_sha256"]
        block: dict[str, Any] = {
            "use": LOOP, "subject": subject, "frames": record["frames"], "fps": TI2V_FPS,
            "width": record["width"], "height": record["height"],
            "trim": {"start": 0, "frames": record["frames"]},
            "source": {"image_sha256": record["image_sha256"], "prompt": record["prompt"],
                       "negative_prompt": record.get("negative"), "seed": record["seed"],
                       "profile": profile, "engine_job_id": record["job_id"]}}
        if still is not None:
            block["still_sha256"] = still
        if keying is not None:
            block["keying"] = keying
        return block

    def doll_loops(self) -> None:
        v1, v2 = self.s.clipmap_v1, self.s.clipmap_v2
        if {k: v for k, v in self.s.clipmap_s2v.items() if k != "shots"} != v2:
            raise _mismatch("/clipmap-s2v.json",
                            "its doll loops differ from clipmap-layered-v2.json")
        clips: dict[str, list[tuple[str, Mapping[str, Any], bool]]] = {}  # cutout -> clips
        for cutout, entry in v2.items():
            clips.setdefault(cutout, []).append((entry["clip"], entry, True))
        for cutout, entry in v1.items():
            if all(entry["clip"] != clip for clip, _, _ in clips.get(cutout, [])):
                clips.setdefault(cutout, []).append((entry["clip"], entry, False))
        for cutout in sorted(clips):
            still = self.still(cutout)
            key = f"{SOURCE_PREFIX}:loop:{cutout}"
            ordered = sorted(clips[cutout], key=lambda item: self.record(item[0])[2]["at"])
            for clip_path, entry, current in ordered:
                file, line, record = self.record(clip_path)
                if Path(entry["still"]).name != record["image"]:
                    raise _mismatch(f"/{file}/{line}", f"the clipmap starts {clip_path} from "
                                                       f"{entry['still']}, the record from "
                                                       f"{record['image']}")
                self.check_scores(record["name"], entry)
                note = ""
                if current:
                    keying, state = _keying(entry), PROMOTED
                else:
                    keying, state = None, CANDIDATE
                    replaced = v2[cutout]["clip"]
                    note = f"superseded by {_stem(replaced)} (sleeves-fixed still)"
                    self.gaps.append(Gap(record["name"], "motion.keying",
                                         "the layered v1 film keyed it with the decal of poc at "
                                         "6ea34aa, which had no version name (its box is in "
                                         "clipmap-layered.json)"))
                block = self.loop_block(record, subject=DOLL, still=still, keying=keying)
                request = self.request(
                    key=key, name=f"{Path(cutout).stem} doll loop", record=record, block=block,
                    model=TI2V_MODEL, profile_params=_params(record), state=state,
                    attributes={"still_path": cutout}, labels=("E0", "doll loop"))
                row = E0Row(file=file, line=line, name=record["name"], outcome="doll loop",
                            state=state, source_key=key, still=cutout, note=note)
                self.requests.append((record["at"], request, row))

    def check_scores(self, name: str, entry: Mapping[str, Any]) -> None:
        """decal-scores.json measured some clips' decal tracks: its box must be the
        clipmap's box for that clip (v1 or v2)."""
        score = self.s.decal_scores.get(name)
        if score is None:
            return
        clip = f"clips/{name}.mp4"
        boxes = [list(e["decal_box"]) for m in (self.s.clipmap_v1, self.s.clipmap_v2)
                 for e in m.values() if isinstance(e, Mapping) and e.get("clip") == clip]
        if list(score["box"]) not in boxes:
            raise _mismatch(f"/decal-scores.json/{name}",
                            "its box is no clipmap's box for the clip")

    def set_loop(self) -> None:
        loops = [(f, n, r) for f, n, r in self.s.records if r.get("image") == "set-plate.png"]
        if len(loops) != 1:
            raise _mismatch("/clip-records.jsonl", "expected one set loop (image set-plate.png)")
        file, line, record = loops[0]
        key = f"{SOURCE_PREFIX}:set-loop:set-plate.png"
        block = self.loop_block(record, subject=SET, still=None, keying=None)
        self.gaps.append(Gap(record["name"], "motion.still_sha256",
                             "no public record ties set-plate.png to r4's cutouts/set.png; a "
                             "story uses this loop only by pinning it"))
        request = self.request(key=key, name="frosty campsite set loop", record=record,
                               block=block, model=TI2V_MODEL, profile_params=_params(record),
                               state=PROMOTED, attributes={"still_path": "set-plate.png"},
                               labels=("E0", "set loop"))
        self.requests.append((record["at"], request, E0Row(
            file=file, line=line, name=record["name"], outcome="set loop", state=PROMOTED,
            source_key=key, note="pinned only: its still is a gap")))

    # Timed clips --------------------------------------------------------------------

    def timed(self) -> None:
        frames = {shot["shot"]: shot["frames"] for shot in self.s.timeline["shots"]}
        dolls = {shot["id"]: shot["dolls"] for shot in self.s.manifest["shots"]}
        for shot_key, slots in self.s.clipmap_s2v["shots"].items():
            shot = int(shot_key)
            board_frames = frames[shot]
            for slot, entry in slots.items():
                file, line, record = self.record(entry["clip"])
                where = f"/{file}/{line}"
                if round(board_frames / 24, 3) != record["audio_s"]:
                    raise _mismatch(where, f"the drive track lasts {record['audio_s']} s, not "
                                           f"board {shot}'s {board_frames} frames (TIME-9)")
                if s2v_request_frames(board_frames) != record["length"]:
                    raise _mismatch(where, "the requested length is not TIME-9's")
                if self.image_sha(entry["still"]) != record["image_sha256"]:
                    raise _mismatch(where, "the clipmap's start still is not the record's image")
                if entry["fps"] != record["fps"]:
                    raise _mismatch(where, "the clipmap's fps is not the record's")
                cutout = dolls[shot][slot]
                key = f"{SOURCE_PREFIX}:s2v:shot-{shot}:{slot}"
                profile = {"model": S2V_MODEL, "method": record["method"], "lora": self.s.s2v_lora,
                           "steps": S2V_STEPS, "cfg": S2V_CFG, "width": record["width"],
                           "height": record["height"], "length": record["length"],
                           "chunk": S2V_CHUNK, "chunks": record["chunks"], "fps": record["fps"]}
                block = {
                    "use": TIMED, "subject": DOLL, "still_sha256": self.still(cutout),
                    "frames": record["frames"], "fps": record["fps"], "width": record["width"],
                    "height": record["height"],
                    "trim": {"start": 0, "frames": timed_trim(board_frames, record["fps"])},
                    "source": {"image_sha256": record["image_sha256"], "prompt": record["prompt"],
                               "negative_prompt": self.s.negative_prompt, "seed": record["seed"],
                               "profile": profile, "adapter": S2V_ADAPTER,
                               "engine_job_id": record["job_id"]},
                    "drive_track": {"sha256": record["audio_sha256"], "board_frames": board_frames},
                    "keying": _keying(entry)}
                request = self.request(
                    key=key, name=f"board {shot} {slot} speech-to-video", record=record,
                    block=block, model=S2V_MODEL, profile_params=_params(record), state=PROMOTED,
                    attributes={"character_slot": slot, "shot": shot, "still_path": cutout},
                    labels=("E0", "timed"))
                self.requests.append((record["at"], request, E0Row(
                    file=file, line=line, name=record["name"], outcome="timed clip",
                    state=PROMOTED, source_key=key, still=cutout, board=shot, slot=slot)))

    # Lines that are not motion clips --------------------------------------------------

    def others(self, recorded: set[tuple[str, int]]) -> list[E0Row]:
        whole = {clip for shot in self.s.assembly_wf["shots"] for clip in shot["clips"]}
        keyframes = {frame["sha256"]: frame for frame in self.s.keyframes}
        rows = []
        for file, line, record in self.s.records:
            if (file, line) in recorded:
                continue
            name = record["name"]
            if f"{name}.mp4" in whole:
                note = ("whole-frame image-to-video clip of the 15-clip film (assembly-wf.json); "
                        "story 427's whole-frame clip, not a library motion asset")
            elif str(record.get("method", "")).startswith("s2v") \
                    and record["image_sha256"] in keyframes:
                frame = keyframes[record["image_sha256"]]
                note = (f"whole-frame speech-to-video test from keyframe {frame['file']} "
                        "(method.unavailable, section 5); its drive track is the bare line "
                        f"({record['audio_s']} s), not a board-length track (TIME-9), so it is "
                        "no board's timed clip")
            else:
                raise _mismatch(f"/{file}/{line}", f"clip {name} is not accounted for")
            rows.append(E0Row(file=file, line=line, name=name, outcome="not a motion clip",
                              note=note))
        return rows


def e0_table(motion: E0Motion) -> str:
    """The reference's E0 table: one row per clip record line (generated; a test
    compares it with docs/reference/motion-clips.md)."""
    lines = ["| File | Line | Clip | Outcome | State | Stands in for | Board, slot | Note |",
             "|---|---|---|---|---|---|---|---|"]
    for row in motion.rows:
        place = "" if row.board is None else f"{row.board}, {row.slot}"
        lines.append(f"| `{row.file}` | {row.line} | `{row.name}` | {row.outcome} | "
                     f"{row.state or ''} | {f'`{row.still}`' if row.still else ''} | {place} | "
                     f"{row.note} |")
    return "\n".join(lines) + "\n"


def e0_gaps(motion: E0Motion) -> str:
    """The reference's gap list, generated like :func:`e0_table`."""
    grouped: dict[tuple[str, str], list[str]] = {}
    for gap in motion.gaps:
        grouped.setdefault((gap.field, gap.reason), []).append(gap.clip)
    lines = ["| Field left out | Why | Clips |", "|---|---|---|"]
    for (name, reason), clips in grouped.items():
        lines.append(f"| `{name}` | {reason} | {', '.join(f'`{c}`' for c in sorted(clips))} |")
    return "\n".join(lines) + "\n"


def _params(record: Mapping[str, Any]) -> dict[str, Any]:
    """The run measurements a clip record holds, kept as generator params."""
    names = ("length", "frames", "fps", "method", "chunks", "audio_s", "render_s", "wall_s",
             "cooldown_s", "peak_gpu_mib", "at")
    return {name: record[name] for name in names if name in record}


def build_e0_motion(sources: E0Sources, *, production_id: str, licences: LicenceRegister,
                    by: Principal, now: str, library: Library = EMPTY,
                    minter: Minter | None = None) -> E0Motion:
    """Import every E0 motion record into ``library`` (by source key, so a second build
    returns the same versions) and account for every clip record line."""
    builder = _Builder(sources, production_id, licences)
    builder.doll_loops()
    builder.set_loop()
    builder.timed()
    ordered = sorted(builder.requests, key=lambda item: (item[0], item[2].name))
    library, outcomes = import_all(library, [request for _, request, _ in ordered], by=by,
                                   now=now, minter=minter)
    rows = [replace(row, version_id=outcome.version.id)
            for (_, _, row), outcome in zip(ordered, outcomes)]
    rows += builder.others({(row.file, row.line) for row in rows})
    rows.sort(key=lambda row: (RECORD_FILES.index(row.file), row.line))
    return E0Motion(library=library, rows=tuple(rows), outcomes=tuple(outcomes),
                    gaps=tuple(builder.gaps))


__all__ = ["DECAL_MIN_ECC", "DECAL_VERSION", "E0Motion", "E0Row", "E0Sources", "FROM_CODE", "Gap",
           "KEY_THRESHOLDS", "RECORD_FILES", "build_e0_motion", "complete_block", "e0_gaps",
           "e0_table", "load_e0_sources"]
