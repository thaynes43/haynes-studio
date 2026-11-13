"""The Winter Menu library from public files only (story 382).

Builds the asset and version records for every asset version the legacy import of
story 404 names (its import map's ``story_records``): the stills, the set, the sounds,
the bed, the stock voices and the board voices, under the same source keys and
version IDs. Hashes come from the public evidence JSON (``evidence-r4/production.json``
and ``timeline.json``), image provenance from ``prompts.json``, sound provenance from
the manifest's ``source`` blocks and takes from ``speech.json``. No media is read or
copied: locators are computed from the hashes, and whether the bytes exist is the
resolver's injected question.

Every version takes its licence object from the model licence register (story 809,
``docs/reference/model-licences.json``): the entry of its role whose recorded name the
version's model or service text contains. A version no entry matches, or more than one,
gets ``commercial_use: unknown`` with the reason. Values the public files do not hold
stay ``null`` and are listed as :class:`Gap` records, as is every licence still
``unknown`` (the register records a conditional term as ``unknown``); nothing is guessed.

Take, input and definition signatures follow the formulas of the contract's examples
(``asset-version-board-voice.json``, ``run-snapshot.json``), with the model name in
place of the unrecorded digest and the server's default speed 1.0. Choices beyond the
contract are proposals: names, labels, the legacy ``path`` of a stock voice (the
manifest), the media type from the file extension, the capabilities (chroma-keyed
cutouts are ``rgba_cutout``, the set an ``opaque_plate``) and the locator in the
production's folder.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from haynes_studio.canonical.ids import Minter
from haynes_studio.canonical.model import Principal
from haynes_studio.errors import ContractError, Violation, pointer
from haynes_studio.jsonio import read_json
from haynes_studio.legacy import load
from haynes_studio.legacy.manifest import LegacyManifest
from haynes_studio.legacy.speech import pair, speech_from_document
from haynes_studio.library.library import EMPTY, Library, Outcome, VersionRequest, import_all
from haynes_studio.library.model import (
    BOARD,
    KOKORO,
    BoardVoice,
    Content,
    Licence,
    Scope,
    Take,
    input_signature,
    locator_for,
    take_offsets,
    take_signature,
)

EVIDENCE_MISMATCH = "legacy.evidence_mismatch"  # proposal: two public records disagree
ASSET_VERSION = "asset_version"
CUTOUT_TOOL = "poc/cutout.py"
MEDIA_TYPES = {".png": "image/png", ".wav": "audio/wav", ".jpg": "image/jpeg",
               ".webp": "image/webp", ".mp4": "video/mp4"}
REGISTER_PATH = "docs/reference/model-licences.json"  # from the repository root (story 809)
TRACK_NOTE = "Legacy kept one WAV per line; no assembled board track exists."
# poc/studio.py synthesize() sent only a voice and text, so the Kokoro server's default
# speed applied; the contract's board voice example signs legacy takes with 1.0.
LEGACY_SPEED = 1.0
_KEY = re.compile(r"^legacy:(?P<job>[^:]+):(?P<kind>still|set|sfx|bed|voice|speech):(?P<rest>.+)$")


@dataclass(frozen=True)
class PublicSources:
    """The public text records of one legacy revision (no media)."""

    manifest: LegacyManifest
    manifest_path: str  # relative to the title folder, for legacy.path
    speech: Mapping[str, Any]
    speech_path: str
    timeline: Mapping[str, Any]
    ledger: Mapping[str, Any]  # the delivery ledger, evidence*/production.json
    prompts: Mapping[str, Any]


def load_public_sources(title_dir: str | Path, manifest: str, evidence: str) -> PublicSources:
    """Read the manifest, ``<evidence>/speech.json``, ``timeline.json`` and
    ``production.json`` and the title's ``prompts.json``: JSON text only."""
    title = Path(title_dir)
    return PublicSources(
        manifest=load(title / manifest), manifest_path=manifest,
        speech=read_json(title / evidence / "speech.json").document,
        speech_path=f"{evidence}/speech.json",
        timeline=read_json(title / evidence / "timeline.json").document,
        ledger=read_json(title / evidence / "production.json").document,
        prompts=read_json(title / "prompts.json").document)


@dataclass(frozen=True)
class RegisteredEngine:
    """One engine of the licence register: its role, the names this repository's records
    use for it, and its licence object (the most restrictive of its files)."""

    key: str
    role: str
    recorded_as: tuple[str, ...]
    licence: Licence


@dataclass(frozen=True)
class LicenceRegister:
    """The model licence register (story 809), as the builder reads it."""

    engines: tuple[RegisteredEngine, ...]

    @classmethod
    def from_document(cls, doc: Mapping[str, Any]) -> LicenceRegister:
        return cls(tuple(
            RegisteredEngine(key=engine["key"], role=engine["role"],
                             recorded_as=tuple(engine["recorded_as"]),
                             licence=Licence.from_document(engine["licence"]))
            for engine in doc["engines"]))

    def licence_for(self, role: str, model: Any) -> Licence:
        """The licence of the one engine of ``role`` whose recorded name ``model``
        contains as a whole name (``Qwen-Image 2.1`` is not in ``Qwen-Image 2.10``);
        ``unknown`` with the reason when none or several match."""
        text = model if isinstance(model, str) else ""
        found = [engine for engine in self.engines if engine.role == role
                 and any(_names(name, text) for name in engine.recorded_as)]
        if len(found) == 1:
            return found[0].licence
        reason = ("no entry" if not found else
                  "several entries (" + ", ".join(engine.key for engine in found) + ")")
        return Licence.unknown(f"The licence register has {reason} for the {role} model "
                               f"{text!r}; terms not recorded.")


def _names(name: str, text: str) -> bool:
    """``name`` occurs in ``text`` with no letter, digit or version continuation (a dot
    and a digit) directly before or after it."""
    if not name:
        return False
    pattern = r"(?<![\w.])" + re.escape(name) + r"(?![\w]|\.\d)"
    return re.search(pattern, text) is not None


def load_licence_register(path: str | Path) -> LicenceRegister:
    """Read the register (``REGISTER_PATH`` in a checkout): JSON text only."""
    return LicenceRegister.from_document(read_json(Path(path)).document)


@dataclass(frozen=True)
class Gap:
    """A value the public files do not hold, left null or unknown on a record."""

    source_key: str
    field: str
    reason: str


@dataclass(frozen=True)
class WinterMenuLibrary:
    library: Library
    outcomes: tuple[Outcome, ...]
    gaps: tuple[Gap, ...] = field(default=())

    @property
    def created(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.created)


def _mismatch(path: str, message: str) -> ContractError:
    return ContractError("<public evidence>", [Violation(EVIDENCE_MISMATCH, path, message)])


class _Evidence:
    """Lookups into the public records, each cross-checked where two records agree."""

    def __init__(self, sources: PublicSources):
        self.sources = sources
        job = sources.manifest.job
        self.ledger = {}
        for item in sources.ledger.get("assets", []):
            marker = f"/{job}/"
            if marker in item["path"]:
                self.ledger[item["path"].split(marker, 1)[1]] = item
        self.renders = {render["name"]: render for render in sources.prompts["renders"]}
        self.cutouts = {item["file"]: item for item in sources.prompts["cutouts"]}
        self.audio = {(item["kind"], item.get("cue")): item for item in sources.timeline["audio"]
                      if item["kind"] in ("sfx", "bed")}

    def file(self, path: str, sha256: str | None) -> tuple[str, int | None]:
        """The hash and byte count the ledger records for a job file; ``sha256`` (from
        another record) must agree with it."""
        entry = self.ledger.get(path)
        if entry is None:
            if sha256 is None:
                raise _mismatch(pointer("assets"), f"no public hash for {path}")
            return sha256, None
        if sha256 is not None and entry["sha256"] != sha256:
            raise _mismatch(pointer("assets"), f"{path}: the ledger and another record disagree")
        return entry["sha256"], entry["bytes"]


def _content(path: str, sha256: str, size: int | None, production_id: str) -> Content:
    media_type = MEDIA_TYPES[Path(path).suffix]
    return Content(sha256=sha256, bytes=size, media_type=media_type,
                   locator=locator_for(sha256, media_type, production_id))


def _image_generator(prompts: Mapping[str, Any], render: Mapping[str, Any]) -> dict[str, Any]:
    params = {name: render.get(name)
              for name in ("mode", "graph", "width", "height", "source", "at")}
    return {"role": "image", "engine": prompts["service"], "model": prompts["models"],
            "workflow_sha256": render["graph_sha256"], "seed": render["seed"],
            "prompt_ref": render["prompt_file"], "engine_job_id": render["prompt_id"],
            "params": params}


def _sound_generator(source: Mapping[str, Any] | None) -> dict[str, Any]:
    source = source or {}
    return {"role": "sound", "engine": source.get("service"), "model": None,
            "seed": source.get("seed"), "prompt": source.get("prompt"),
            "engine_job_id": source.get("job"),
            "params": {"seconds": source.get("seconds"), "steps": source.get("steps")}}


def winter_menu_requests(story: Mapping[str, Any], import_map: Mapping[str, Any],
                         sources: PublicSources, licences: LicenceRegister,
                         ) -> tuple[list[VersionRequest], list[Gap]]:
    """One import request per asset version the import map's ``story_records`` name,
    in that order, with licences from the register, and the gaps the public files
    leave."""
    evidence = _Evidence(sources)
    manifest = sources.manifest
    job, production_id = manifest.job, story["production_id"]
    title = story["origin"]["source_key"].split(":", 1)[1] if story.get("origin") else job
    service = sources.speech.get("service") or ""
    if KOKORO not in service:
        raise _mismatch("/service", f"speech.json does not name {KOKORO}")
    voice_ids = {member.voice for member in manifest.cast}
    takes = pair(manifest, speech_from_document(sources.speech))
    cast_voices = {member["slot"]: member["voice_version_id"] for member in story["cast"]}
    slot_voice = {member.slot: member.voice for member in manifest.cast}
    boards = {board["origin"]["legacy_shot"]: board for board in story.get("boards") or []
              if board.get("origin")}
    requests: list[VersionRequest] = []
    gaps: list[Gap] = []

    image_licence = licences.licence_for("image", sources.prompts.get("models"))
    voice_licence = licences.licence_for("voice", KOKORO)

    def legacy(key: str, path: str) -> dict[str, str]:
        return {"source_key": key, "path": path, "job": job}

    for index, record in enumerate(import_map.get("story_records", [])):
        if record["kind"] != ASSET_VERSION:
            continue
        key, version_id = record["source_key"], record["id"]
        match = _KEY.match(key)
        if match is None or match["job"] != job:
            raise _mismatch(pointer("story_records", index, "source_key"),
                            f"{key!r} is not a legacy asset key of {job}")
        kind, rest = match["kind"], match["rest"]

        if kind == "still":
            name = Path(rest).name
            cutout = evidence.cutouts.get(name)
            if cutout is None:
                raise _mismatch("/cutouts", f"prompts.json has no cutout {name}")
            sha256, size = evidence.file(rest, cutout["sha256"])
            render = evidence.renders[cutout["source"]]
            slot, _, expression = Path(rest).stem.partition("-")
            generator = _image_generator(sources.prompts, render)
            generator["post"] = {"tool": CUTOUT_TOOL, "lo": cutout["lo"], "hi": cutout["hi"],
                                 "protect": cutout["protect"], "resize": cutout["resize"],
                                 "source_sha256": render["sha256"]}
            requests.append(VersionRequest(
                version_id=version_id, legacy=legacy(key, rest), kind="cast",
                name=f"{slot.upper()} · {expression}", scope=Scope(production_id),
                labels=(title, slot.upper()),
                attributes={"character_slot": slot, "expression": expression},
                capabilities=("rgba_cutout",), content=_content(rest, sha256, size, production_id),
                provenance={"origin": "imported", "generator": generator, "external": None,
                            "source_key": key},
                licence=image_licence))
        elif kind == "set":
            chosen = sources.prompts["set"]
            if Path(rest).name != chosen["file"]:
                raise _mismatch("/set",
                                f"prompts.json records {chosen['file']}, the manifest {rest}")
            sha256, size = evidence.file(rest, chosen["sha256"])
            render = evidence.renders[chosen["source"]]
            if render["sha256"] != sha256:
                raise _mismatch("/set", "the set is not its chosen render's bytes")
            requests.append(VersionRequest(
                version_id=version_id, legacy=legacy(key, rest), kind="set", name=f"{title} set",
                scope=Scope(production_id), labels=(title,), capabilities=("opaque_plate",),
                content=_content(rest, sha256, size, production_id),
                provenance={"origin": "imported",
                            "generator": _image_generator(sources.prompts, render),
                            "external": None, "source_key": key},
                licence=image_licence))
        elif kind in ("sfx", "bed"):
            if kind == "sfx":
                sound = manifest.sound(rest)
            else:
                sound = next((bed for bed in manifest.beds if bed.name == rest), None)
                if sound is None:
                    raise _mismatch("/beds", f"the manifest has no bed {rest}")
            heard = evidence.audio.get((kind, rest))
            if heard is None or heard.get("file") != sound.file:
                raise _mismatch("/audio", f"timeline.json has no {kind} {rest} from {sound.file}")
            sha256, size = evidence.file(sound.file, heard["sha256"])
            gaps.append(Gap(key, "provenance.generator.model",
                            "the sound model is named only inside the service text "
                            f"{(sound.source or {}).get('service')!r}"))
            if size is None:
                gaps.append(Gap(key, "content.bytes",
                                f"{sound.file} is in timeline.json with its hash but not in the "
                                "ledger's assets, so no byte count is public"))
            requests.append(VersionRequest(
                version_id=version_id, legacy=legacy(key, sound.file), kind="sound",
                name=f"{rest} ({'sound effect' if kind == 'sfx' else 'bed'})",
                scope=Scope(production_id), labels=(title, kind),
                capabilities=("sound_effect" if kind == "sfx" else "sound_bed",),
                content=_content(sound.file, sha256, size, production_id),
                provenance={"origin": "imported", "generator": _sound_generator(sound.source),
                            "external": None, "source_key": key},
                licence=licences.licence_for("sound", (sound.source or {}).get("service"))))
        elif kind == "voice":
            if rest not in voice_ids:
                raise _mismatch("/cast", f"the manifest's cast has no voice {rest}")
            requests.append(VersionRequest(
                version_id=version_id, legacy=legacy(key, sources.manifest_path), kind="voice",
                name=f"{rest} (Kokoro stock voice)", scope=Scope(None), labels=("stock-voice",),
                attributes={"voice_id": rest, "stock": True}, capabilities=("tts_voice",),
                content=None,
                provenance={"origin": "declared",
                            "generator": {"role": "voice", "engine": service, "model": KOKORO,
                                          "voice_id": rest},
                            "external": None, "source_key": key},
                licence=voice_licence))
            gaps.append(Gap(key, "provenance.generator.files_sha256",
                            "no Kokoro model digest is recorded; the model name stands in "
                            "(VOICE-3)"))
        else:  # speech:shot:<id>
            shot = int(rest.split(":")[-1])
            board = boards.get(shot)
            if board is None:
                raise _mismatch(pointer("story_records", index),
                                f"the story has no board for shot {shot}")
            voice = _board_voice(board, shot, sources, takes, cast_voices, slot_voice, service)
            requests.append(VersionRequest(
                version_id=version_id, legacy=legacy(key, sources.speech_path), kind="board_voice",
                name=f"{board['title']} voice",
                scope=Scope(production_id, story_id=story["id"], board_id=board["id"]),
                state=BOARD, capabilities=("board_voice",), content=None, voice=voice,
                provenance={"origin": "imported",
                            "generator": {"role": "voice", "engine": service, "model": KOKORO},
                            "external": None, "source_key": key},
                licence=voice_licence))
            gaps.append(Gap(key, "voice.takes[].samples, sample_rate",
                            "speech.json records duration_s, not samples or rate; durations are "
                            "legacy_duration_s (TIME-1)"))
    for request in requests:
        if request.licence.commercial_use == "unknown":
            gaps.append(Gap(request.provenance["source_key"], "licence",
                            request.licence.note or "terms not recorded"))
    return requests, gaps


def _board_voice(board: Mapping[str, Any], shot: int, sources: PublicSources,
                 takes: Mapping[tuple[int, int], Any], cast_voices: Mapping[str, str],
                 slot_voice: Mapping[str, str], service: str) -> BoardVoice:
    raw = sources.speech["lines"]
    lines = board["lines"]
    durations = [takes[(shot, k)].duration_ms for k in range(len(lines))]
    gaps_ms = [line["gap_before_ms"] for line in lines[1:]]
    lead = board["timing"]["lead_ms"]
    offsets = take_offsets(lead, gaps_ms, durations)
    out = []
    for k, (line, offset) in enumerate(zip(lines, offsets)):
        take = takes[(shot, k)]
        voice_id = take.voice or slot_voice[line["speaker"]]
        record = raw[take.index]
        out.append(Take(
            line_id=line["id"], speaker=line["speaker"], text=line["text"],
            voice_version_id=cast_voices[line["speaker"]], engine=KOKORO, voice_id=voice_id,
            sha256=take.sha256, sample_rate=None, samples=None, duration_ms=take.duration_ms,
            duration_source="legacy_duration_s", offset_ms=offset, heard=record.get("heard"),
            heard_matches=record.get("heard_matches"),
            signature=take_signature(KOKORO, voice_id, line["text"], LEGACY_SPEED)))
    signed = input_signature([take.signature for take in out], lead, gaps_ms)
    return BoardVoice(input_signature=signed, lead_ms=lead, gaps_ms=tuple(gaps_ms),
                      speech_end_ms=offsets[-1] + durations[-1], track=None, takes=tuple(out),
                      track_note=TRACK_NOTE)


def build_winter_menu_library(story: Mapping[str, Any], import_map: Mapping[str, Any],
                              sources: PublicSources, *, licences: LicenceRegister,
                              by: Principal, now: str, library: Library = EMPTY,
                              minter: Minter | None = None) -> WinterMenuLibrary:
    """Import every record into ``library``, each licence from ``licences``. Run it again
    on its own result and nothing is created: the same source keys and bytes return the
    same versions."""
    requests, gaps = winter_menu_requests(story, import_map, sources, licences)
    library, outcomes = import_all(library, requests, by=by, now=now, minter=minter)
    return WinterMenuLibrary(library=library, outcomes=tuple(outcomes), gaps=tuple(gaps))


__all__ = ["EVIDENCE_MISMATCH", "LEGACY_SPEED", "REGISTER_PATH", "Gap", "LicenceRegister",
           "PublicSources", "RegisteredEngine", "WinterMenuLibrary", "build_winter_menu_library",
           "load_licence_register", "load_public_sources", "winter_menu_requests"]
