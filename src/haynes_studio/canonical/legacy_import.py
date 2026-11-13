"""The legacy import (contract section 1): one legacy manifest and its ``speech.json``
become one canonical story with boards, lines, cues, notes and layout references, plus
a ``studio.legacy-import/v1`` map with a ``source_key`` per record.

Identifiers come from an existing import map when one is given, so a second import
returns the same IDs (P-01); otherwise they are minted. A map refuses an import whose
manifest or ``speech.json`` bytes differ from the ones it recorded for that revision,
so an ID never names different content (a board voice version, for one, never names
other takes). The returned map records every ID the import used, including the ones
the contract's map does not list (cues, notes, beds and the asset versions the boards
name), so the next import reuses them too.
Nothing here writes a legacy file; the caller decides where the result goes.

Asset versions (cast stills, the set, sounds, stock voices, board voices) belong to the
asset library (story 382). The import names them by ``source_key`` and records the
version ID it used; story 382 must create those versions under the same keys.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from haynes_studio.canonical import validate as rules
from haynes_studio.canonical import with_derived
from haynes_studio.canonical.facts import Facts, VoiceVersionFacts
from haynes_studio.canonical.ids import Minter
from haynes_studio.canonical.jsonvalues import normalize
from haynes_studio.canonical.methods import default_method
from haynes_studio.canonical.model import (
    BOARD_SCHEMA,
    LEGACY_IMPORT_SCHEMA,
    STORY_SCHEMA,
    Board,
    Principal,
    to_document,
)
from haynes_studio.errors import ContractError, Violation, blocking, pointer
from haynes_studio.jsonio import thaw
from haynes_studio.legacy.manifest import LegacyManifest, Shot
from haynes_studio.legacy.speech import LegacySpeech, Take, pair

COMMAND = "studio legacy import"
MAP_MISMATCH = "legacy.import_map_mismatch"  # proposal of story 404
MEDIA_KINDS = {(1080, 1920): "short", (1920, 1080): "video"}
LEGACY_LINE_RMS_DBFS = -22  # edit.audio's per-line level (VOICE-7)
LEGACY_CAMERA_OVER_MS = 400  # edit.py's default push-in time
LEGACY_MOVE_STEPS = 3  # edit.motion's held steps
VOICE_7 = {"master_lufs": -20, "true_peak_dbtp": -3.5}  # used only if a manifest has no master
ASSET_VERSION, BED = "asset_version", "bed"


@dataclass(frozen=True)
class ImportResult:
    story: dict[str, Any]  # studio.story/v1 with boards and derived
    import_map: dict[str, Any]  # studio.legacy-import/v1
    facts: Facts  # the board voice versions' measured takes, from speech.json
    reused: int  # IDs taken from the existing map
    minted: int  # IDs minted by this import
    given: int = 0  # IDs the caller gave without a map (the production)


def story_source_key(manifest: LegacyManifest) -> str:
    """``legacy:<title slug>``: the job name without its ``-r<revision>`` suffix."""
    return "legacy:" + re.sub(rf"-r{manifest.revision}\Z", "", manifest.job)


def media_kind(manifest: LegacyManifest) -> str:
    kind = MEDIA_KINDS.get((manifest.frame.width, manifest.frame.height))
    if kind is None:
        raise ContractError(manifest.source, [Violation(
            MAP_MISMATCH, "/frame",
            f"{manifest.frame.width}x{manifest.frame.height} is not a media kind's profile")])
    return kind


class _Ids:
    """IDs from the existing map, else minted; counts both, and IDs the caller gave."""

    def __init__(self, existing: Mapping[str, Any] | None, revision: int, minter: Minter):
        self.minter, self.reused, self.minted, self.given = minter, 0, 0, 0
        existing = existing or {}
        self.boards = {b["legacy_shot"]: b for b in existing.get(f"boards_from_r{revision}", [])}
        self.records = {(r["kind"], r["source_key"]): r["id"]
                        for r in existing.get("story_records", [])}

    def take(self, prefix: str, known: str | None) -> str:
        if known is not None:
            self.reused += 1
            return known
        self.minted += 1
        return self.minter.mint(prefix)

    def given_or_minted(self, prefix: str, given: str | None) -> str:
        """An ID the caller supplied without a map, else a minted one."""
        if given is not None:
            self.given += 1
            return given
        return self.take(prefix, None)

    def board(self, shot: int) -> str:
        return self.take("brd", self.boards.get(shot, {}).get("board_id"))

    def line(self, shot: int, k: int) -> str:
        lines = {line["legacy_k"]: line["line_id"]
                 for line in self.boards.get(shot, {}).get("lines", [])}
        return self.take("lin", lines.get(k))

    def keyed(self, shot: int, kind: str, field: str, source_key: str, prefix: str) -> str:
        items = {item["source_key"]: item[field] for item in self.boards.get(shot, {}).get(kind, [])}
        return self.take(prefix, items.get(source_key))

    def record(self, kind: str, source_key: str, prefix: str) -> str:
        return self.take(prefix, self.records.get((kind, source_key)))


def _check_existing(existing: Mapping[str, Any], manifest: LegacyManifest,
                    speech: LegacySpeech, production_id: str | None, kind: str,
                    label: str) -> None:
    """Refuse a map made for another title, media kind, draft revision or production,
    or recorded from other manifest or speech.json bytes for this revision."""
    problems = [Violation(v.rule, v.path, v.message) for v in
                blocking(rules.validate_legacy_import(existing))]
    if not problems:
        expect = {"source_key": story_source_key(manifest), "media_kind": kind,
                  "draft_from_revision": manifest.revision}
        if production_id is not None:
            expect["production_id"] = production_id
        for field, value in expect.items():
            if existing[field] != value:
                problems.append(Violation(MAP_MISMATCH, pointer(field),
                                          f"the map has {existing[field]!r}; this import "
                                          f"needs {value!r}"))
        for i, entry in enumerate(existing["revisions"]):
            if entry["legacy_revision"] != manifest.revision:
                continue
            if manifest.sha256 and entry["manifest_sha256"] != manifest.sha256:
                problems.append(Violation(MAP_MISMATCH, pointer("revisions", i, "manifest_sha256"),
                                          "the manifest's bytes differ from the mapped revision"))
            recorded = entry.get("speech_sha256")
            if recorded and speech.sha256 and recorded != speech.sha256:
                problems.append(Violation(
                    MAP_MISMATCH, pointer("revisions", i, "speech_sha256"),
                    "the speech.json bytes differ from the ones this revision was imported "
                    "with; its voice version IDs name those takes"))
    if problems:
        raise ContractError(label, problems)


def import_manifest(manifest: LegacyManifest, speech: LegacySpeech, *, manifest_label: str,
                    operator: Principal, now: str, existing: Mapping[str, Any] | None = None,
                    production_id: str | None = None, minter: Minter | None = None,
                    map_label: str = "<import map>") -> ImportResult:
    """Import one legacy manifest. ``manifest_label`` is the path recorded in
    ``origin.manifest`` (repository-relative); ``operator`` is the human running the
    CLI; ``now`` is the ISO time stamped on created records. Raises
    :class:`ContractError` for a speech mismatch, a map that does not fit, or a result
    that breaks a canonical rule."""
    if operator.kind != "human":
        raise ValueError("the operator is a human principal (contract section 2)")
    if manifest.sha256 is None:
        raise ValueError("the manifest must be loaded from its file: the map records the "
                         "SHA-256 of its bytes (haynes_studio.legacy.load)")
    takes = pair(manifest, speech)
    kind = media_kind(manifest)
    if existing is not None:
        existing = normalize(existing)
        _check_existing(existing, manifest, speech, production_id, kind, map_label)
    ids = _Ids(existing, manifest.revision, minter or Minter())
    job = manifest.job
    by = to_document(Principal(kind="cli", command=COMMAND, operator=operator))

    prd = (ids.take("prd", existing["production_id"]) if existing is not None
           else ids.given_or_minted("prd", production_id))
    sty = ids.take("sty", existing["story_id"] if existing is not None else None)
    board_ids = {shot.id: ids.board(shot.id) for shot in manifest.shots}
    line_ids = {(shot.id, line.k): ids.line(shot.id, line.k)
                for shot in manifest.shots for line in shot.lines}

    # Asset versions the story and boards name (story 382 creates them).
    assets: dict[str, str] = {}

    def asset(source_key: str) -> str:
        if source_key not in assets:
            assets[source_key] = ids.record(ASSET_VERSION, source_key, "asv")
        return assets[source_key]

    stills = sorted({path for shot in manifest.shots for _, path in shot.dolls})
    for path in stills:
        asset(f"legacy:{job}:still:{path}")
    set_image = (manifest.set or {}).get("image")
    if set_image:
        asset(f"legacy:{job}:set:{set_image}")
    for sound in sorted(manifest.sfx, key=lambda s: s.name):
        asset(f"legacy:{job}:sfx:{sound.name}")
    for bed in sorted(manifest.beds, key=lambda b: b.name):
        asset(f"legacy:{job}:bed:{bed.name}")
    for member in manifest.cast:
        asset(f"legacy:{job}:voice:{member.voice}")

    boards, voices, map_boards = [], [], []
    for number, shot in enumerate(manifest.shots, start=1):
        board, voice, entry = _board(shot, number, manifest, sty, board_ids[shot.id], line_ids,
                                     takes, ids, asset, by, manifest_label, now)
        boards.append(board)
        map_boards.append(entry)
        if voice:
            voices.append(voice)

    beds = []
    for bed in manifest.beds:
        key = f"legacy:{job}:bed:{bed.name}"
        beds.append({"id": ids.record(BED, key, "cue"), "type": "bed",
                     "asset_version_id": asset(key), "level_rms_dbfs": bed.level_rms_dbfs,
                     "clock": "film"})
    story = _story(manifest, sty, prd, kind, boards, beds, asset, by, manifest_label, now)
    facts = Facts.build(voices=voices)
    story = with_derived(story, facts=facts, source=manifest.source)

    records = [{"source_key": key, "kind": ASSET_VERSION, "id": value}
               for key, value in assets.items()]
    records += [{"source_key": f"legacy:{job}:bed:{bed.name}", "kind": BED, "id": made["id"]}
                for bed, made in zip(manifest.beds, beds)]
    import_map = _map(existing, manifest, speech, manifest_label, story, kind, map_boards, records)
    problems = blocking(rules.validate_legacy_import(import_map))
    if problems:
        raise ContractError("<import map>", problems)
    return ImportResult(story=story, import_map=import_map, facts=facts,
                        reused=ids.reused, minted=ids.minted, given=ids.given)


def _anchor(anchor, shot: Shot, line_ids: Mapping[tuple[int, int], str]) -> dict[str, Any]:
    if anchor.after_line is None:
        return {"at_ms": anchor.at_ms}
    return {"after_line_id": line_ids[(shot.id, anchor.after_line)], "offset_ms": anchor.offset_ms}


def _board(shot: Shot, number: int, manifest: LegacyManifest, sty: str, brd: str,
           line_ids: Mapping[tuple[int, int], str], takes: Mapping[tuple[int, int], Take],
           ids: _Ids, asset, by: dict, manifest_label: str, now: str):
    job = manifest.job
    base = f"legacy:{job}:shot:{shot.id}"
    lines = [{"id": line_ids[(shot.id, line.k)], "speaker": line.doll, "text": line.text,
              "gap_before_ms": line.gap_ms} for line in shot.lines]
    cues, cue_keys = [], []

    def cue(key: str, body: dict[str, Any]) -> None:
        cue_id = ids.keyed(shot.id, "cues", "cue_id", key, "cue")
        cues.append({"id": cue_id, **body})
        cue_keys.append({"source_key": key, "cue_id": cue_id})

    for item in shot.sfx:
        sound = manifest.sound(item.cue)
        cue(f"{base}:sfx:{item.index}", {
            "type": "sound", "asset_version_id": asset(f"legacy:{job}:sfx:{sound.name}"),
            "anchor": _anchor(item.anchor, shot, line_ids),
            "trim_ms": None if sound.trim_ms is None else list(sound.trim_ms),
            "level_rms_dbfs": sound.level_rms_dbfs})
    for move in shot.moves:
        cue(f"{base}:move:{move.index}", {
            "type": "move", "slot": move.doll, "anchor": _anchor(move.anchor, shot, line_ids),
            "duration_ms": move.dur_ms or 0, "dx_px": move.dx or 0, "dy_px": move.dy or 0,
            "angle_deg": move.angle or 0, "steps": LEGACY_MOVE_STEPS})
    if shot.camera is not None:
        camera = shot.camera
        cue(f"{base}:camera", {
            "type": "camera", "anchor": {"at_ms": 0},
            "duration_ms": LEGACY_CAMERA_OVER_MS if camera.over_ms is None else camera.over_ms,
            "zoom_from": camera.zoom[0], "zoom_to": camera.zoom[1],
            "center_px": list(camera.center), "easing": "ease_out_cubic"})
    notes, note_keys = [], []
    if shot.note:
        key = f"{base}:note"
        note_id = ids.keyed(shot.id, "notes", "note_id", key, "nte")
        notes.append({"id": note_id, "text": shot.note})
        note_keys.append({"source_key": key, "note_id": note_id})

    cast = [{"slot": slot, "asset_version_id": asset(f"legacy:{job}:still:{path}")}
            for slot, path in shot.dolls]
    inputs = sorted({entry["asset_version_id"] for entry in cast} |
                    ({asset(f"legacy:{job}:set:{manifest.set['image']}")}
                     if (manifest.set or {}).get("image") else set()))
    layer, motion = default_method(shot.spoken)
    voice_id = asset(f"legacy:{job}:speech:shot:{shot.id}") if shot.spoken else None
    board = {
        "schema": BOARD_SCHEMA, "id": brd, "story_id": sty, "number": number, "revision": 1,
        "title": f"Shot {shot.id}", "lines": lines,
        "timing": {"lead_ms": shot.lead_ms, "tail_ms": shot.tail_ms,
                   "hold_ms": None if shot.spoken else shot.duration_ms},
        "voice": {"style": "cast" if shot.spoken else None, "current_version_id": voice_id},
        "photo": {"current_version_id": None, "prompt": None, "input_asset_version_ids": inputs},
        "cast": cast,
        "layout": {"preset": shot.layout,
                   "foreground": True if shot.foreground is None else shot.foreground},
        "method": {"layer": layer, "motion": motion}, "seeds": {},
        "cues": cues, "notes": notes, "drafted_by": by,
        "origin": {"source_key": base, "legacy_revision": manifest.revision,
                   "legacy_shot": shot.id, "manifest": manifest_label},
        "created_at": now, "updated_at": now,
    }
    voice = None
    if shot.spoken:
        voice = VoiceVersionFacts(id=voice_id, takes_ms={
            line_ids[(shot.id, line.k)]: takes[(shot.id, line.k)].duration_ms
            for line in shot.lines})
    entry = {"legacy_shot": shot.id, "board_id": brd, "source_key": base,
             "lines": [{"legacy_k": line.k, "line_id": line_ids[(shot.id, line.k)],
                        "source_key": f"{base}:line:{line.k}"} for line in shot.lines],
             "cues": cue_keys, "notes": note_keys}
    return board, voice, entry


def _story(manifest: LegacyManifest, sty: str, prd: str, kind: str, boards: list,
           beds: list, asset, by: dict, manifest_label: str, now: str) -> dict[str, Any]:
    raw_set = thaw(manifest.set) if manifest.set is not None else None
    story_set = None if raw_set is None else {
        "asset_version_id": asset(f"legacy:{manifest.job}:set:{raw_set['image']}")
        if raw_set.get("image") else None,
        "motion_asset_version_id": None,
        "foreground_edge_px": raw_set.get("foreground_edge"),
        "foreground_feather_px": raw_set.get("foreground_feather"),
        "legacy_fire": raw_set.get("fire"),
        "note": raw_set.get("note"),
    }
    master = thaw(manifest.master) if manifest.master is not None else {}
    return {
        "schema": STORY_SCHEMA, "id": sty, "production_id": prd, "media_kind": kind,
        "title": manifest.title, "revision": 1, "format_version_id": None,
        "cast": [{"slot": member.slot, "name": member.name,
                  "voice_version_id": asset(f"legacy:{manifest.job}:voice:{member.voice}")}
                 for member in manifest.cast],
        "narrator_voice_version_id": None, "set": story_set,
        "layouts": thaw(manifest.layouts) if manifest.layouts is not None else {},
        "motion_style": thaw(manifest.motion) if manifest.motion is not None else None,
        "mix": {"line_rms_dbfs": LEGACY_LINE_RMS_DBFS,
                "master_lufs": master.get("lufs", VOICE_7["master_lufs"]),
                "true_peak_dbtp": master.get("true_peak", VOICE_7["true_peak_dbtp"])},
        "checks": {"asr_tolerances": thaw(manifest.asr_tolerances)
                   if manifest.asr_tolerances is not None else None,
                   "asr_tolerances_note": manifest.asr_tolerances_note},
        "beds": beds, "board_order": [board["id"] for board in boards], "boards": boards,
        "origin": {"source_key": story_source_key(manifest), "legacy_revision": manifest.revision,
                   "tracker": manifest.story, "manifest": manifest_label},
        "created_at": now, "updated_at": now, "created_by": by,
    }


def _map(existing: Mapping[str, Any] | None, manifest: LegacyManifest, speech: LegacySpeech,
         manifest_label: str, story: dict[str, Any], kind: str, boards: list[dict],
         records: list[dict]) -> dict[str, Any]:
    out = dict(existing) if existing else {
        "schema": LEGACY_IMPORT_SCHEMA, "source_key": story_source_key(manifest),
        "production_id": story["production_id"], "media_kind": kind,
        "story_id": story["id"], "draft_from_revision": manifest.revision,
        "writes_legacy": False, "revisions": [],
        "not_imported": ["job_dir (private, non-portable locator; story 425 recovery map)"],
    }
    revisions = [dict(r) for r in out["revisions"]]
    current = next((r for r in revisions if r["legacy_revision"] == manifest.revision), None)
    if current is None:
        current = {"legacy_revision": manifest.revision}
        revisions.append(current)
    current.update({
        "revision_field_present": manifest.revision_field_present,
        "manifest": current.get("manifest", manifest_label),
        "job": manifest.job, "tracker": manifest.story,
        "frames": story["derived"]["frames"], "shots": len(manifest.shots),
    })
    if manifest.sha256:
        current["manifest_sha256"] = manifest.sha256
    if speech.sha256:
        current["speech_sha256"] = speech.sha256
    out["revisions"] = sorted(revisions, key=lambda r: r["legacy_revision"])
    out[f"boards_from_r{manifest.revision}"] = boards
    out["story_records"] = records
    return out


def voice_facts(boards: Sequence[Board], manifest: LegacyManifest,
                speech: LegacySpeech) -> Facts:
    """Voice facts for imported boards: each board's current voice version holds the
    legacy takes of its shot (``origin.legacy_shot``), line *i* to take ``k = i``."""
    takes = pair(manifest, speech)
    voices = []
    for board in boards:
        if board.origin is None or not board.spoken or board.voice.current_version_id is None:
            continue
        voices.append(VoiceVersionFacts(id=board.voice.current_version_id, takes_ms={
            line.id: takes[(board.origin.legacy_shot, k)].duration_ms
            for k, line in enumerate(board.lines)}))
    return Facts.build(voices=voices)
