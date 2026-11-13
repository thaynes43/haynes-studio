"""A run's provenance (contract section 7, D44; story 406).

``toolchain`` names the studio commit, the Python version, the encoder build (PyAV with
its bundled FFmpeg and x264) and every adapter, compositor, mixer and pinned service
snippet the run used. ``engines`` lists each engine that made something the film
holds or checks it, from the **model licence register**
(``docs/reference/model-licences.json``, story 809): its files with their hashes (as the
engine reported them when it did, else the register's) and licences, its licence (the
register's entry, the most restrictive of its files), its profile and the hardware it
ran on. ``inputs_externally_generated`` lists every input version with the D42 marker.
``public.credits`` names only the video, voice and sound engines (D44); image,
composite, writer and check engines stay private.

Which engine made what (**proposal**):

- a clip the build made: the register engine whose ``files`` hold the clip profile's
  ``model`` (``wan2.2-s2v-14b-fp8``, ``wan2.2-ti2v-5b``); the clip's own record gives
  the files it loaded and its hardware;
- a library version (stills, loops, timed clips, sounds, voices): the register engine
  of its generator's role whose recorded name its ``model`` holds;
- the transcript check: the register's ``check`` engine (``asr``).

A version whose generator matches no register entry is listed as an unregistered engine
with an ``unknown`` licence and the reason, never guessed. Licences block nothing (D49).
"""

from __future__ import annotations

import copy
import platform
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from haynes_studio.jsonio import thaw
from haynes_studio.library import Library

ROLE_LABEL = {"video": "Video", "voice": "Voices", "sound": "Sound"}
CREDIT_ROLES = tuple(ROLE_LABEL)
CONDITIONAL, UNKNOWN = "conditional", "unknown"


def _unknown(note: str) -> dict[str, Any]:
    return {"name": None, "url": None, "commercial_use": UNKNOWN, "attribution_required": None,
            "checked_at": None, "checked_by": None, "note": note}


def _names(name: str, text: str) -> bool:
    """``name`` occurs in ``text`` as a whole name (the register's own matching rule)."""
    if not name or not text:
        return False
    return re.search(r"(?<![\w.])" + re.escape(name) + r"(?![\w]|\.\d)", text) is not None


@dataclass
class Use:
    """One engine's use in the run: what it made, the files and hardware it reported."""

    role: str
    used_by: list[str] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)  # name -> sha256, as reported
    hardware: str | None = None
    profile: Mapping[str, Any] | None = None


class Register:
    """The model licence register, read as JSON (``model-licences.json``)."""

    def __init__(self, document: Mapping[str, Any]):
        self.engines = {engine["key"]: engine for engine in document.get("engines", [])}
        self.files = [file for file in document.get("files", [])]

    def engine_for_model_file(self, model: str) -> str | None:
        """The engine whose ``files`` hold the profile's model key."""
        found = [key for key, engine in self.engines.items() if model in engine.get("files", [])]
        return found[0] if len(found) == 1 else None

    def engine_for(self, role: str, model: str | None) -> str | None:
        """The one engine of ``role`` whose recorded name ``model`` holds."""
        if not model:
            return None
        found = [key for key, engine in self.engines.items() if engine.get("role") == role
                 and any(_names(name, model) for name in engine.get("recorded_as", []))]
        if len(found) != 1:
            found = [key for key, engine in self.engines.items() if engine.get("role") == role
                     and model in engine.get("files", [])]
        return found[0] if len(found) == 1 else None

    def licence(self, key: str) -> dict[str, Any]:
        """An entry's licence; a conditional term the register writes ``unknown`` is
        ``conditional`` (P-23, as story 849's register lookup reads it)."""
        engine = self.engines[key]
        licence = copy.deepcopy(engine["licence"])
        if engine.get("outputs_commercial_use") == CONDITIONAL and licence["commercial_use"] == UNKNOWN:
            licence["commercial_use"] = CONDITIONAL
        return licence

    def engine_files(self, key: str, reported: Mapping[str, str]) -> list[dict[str, Any]]:
        """The engine's files: the register's, each with the hash the engine reported
        for it (matched by name) or the register's pin; then any reported file the
        register does not name, with an ``unknown`` licence."""
        out, matched = [], set()
        for file in self.files:
            if file.get("engine") != key:
                continue
            names = [file.get("key"), file.get("name"), *file.get("recorded_as", [])]
            sha = next((reported[n] for n in names if n in reported), None)
            matched.update(n for n in names if n in reported)
            out.append({"name": file["name"], "sha256": sha if sha is not None else file.get("sha256"),
                        "licence": copy.deepcopy(file["licence"])})
        for name, sha in sorted(reported.items()):
            if name not in matched:
                out.append({"name": name, "sha256": sha, "licence": _unknown(
                    "The engine reported this file; the licence register does not name it.")})
        return out


RESTRICTION = {"allowed": 0, "conditional": 1, "unknown": 2, "noncommercial": 3}


def most_restrictive(licences: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Section 7: an engine's licence is the most restrictive of its files (proposal:
    ``noncommercial`` over ``unknown`` over ``conditional`` over ``allowed``; the first
    of equals, so the register's own entry wins a tie)."""
    chosen: Mapping[str, Any] | None = None
    for licence in licences:
        if chosen is None or RESTRICTION.get(licence["commercial_use"], 2) > \
                RESTRICTION.get(chosen["commercial_use"], 2):
            chosen = licence
    return copy.deepcopy(dict(chosen)) if chosen is not None else _unknown("No licence recorded.")


def _generator(library: Library, version_id: str) -> Mapping[str, Any]:
    version = library.get(version_id)
    if version is None:
        return {}
    provenance = version.provenance if isinstance(version.provenance, Mapping) else {}
    generator = provenance.get("generator") or {}
    return generator if isinstance(generator, Mapping) else {}


def library_uses(register: Register, library: Library, version_ids: Iterable[str],
                 uses: dict[str, Use], unregistered: dict[str, dict[str, Any]]) -> None:
    """Add the engine of each library version (stills, loops, voices, sounds) to
    ``uses``; a generator the register does not hold goes to ``unregistered``."""
    for version_id in version_ids:
        generator = _generator(library, version_id)
        role, model = generator.get("role"), generator.get("model")
        if role not in ("image", "video", "voice", "sound", "composite"):
            continue
        key = register.engine_for(role, model if isinstance(model, str) else None)
        if key is None:
            name = model if isinstance(model, str) and model else f"unrecorded {role} model"
            slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or role
            key = f"unregistered-{role}-{slug}"
            unregistered.setdefault(key, {"name": name, "role": role})
        use = uses.setdefault(key, Use(role=role))
        use.used_by.append(version_id)
        files = generator.get("files_sha256")
        if isinstance(files, Mapping):
            use.files.update({str(k): str(v) for k, v in files.items()})
        if isinstance(generator.get("hardware"), str) and use.hardware is None:
            use.hardware = generator["hardware"]


def engines(register: Register, uses: Mapping[str, Use],
            unregistered: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for key in sorted(uses):
        use = uses[key]
        if key in register.engines:
            entry = register.engines[key]
            files = register.engine_files(key, use.files)
            out.append({"key": key, "role": entry["role"], "name": entry["name"],
                        "files": files,
                        "licence": most_restrictive([register.licence(key),
                                                     *(file["licence"] for file in files)]),
                        "profile": None if use.profile is None else thaw(use.profile),
                        "hardware": use.hardware or entry.get("where"),
                        "used_by": sorted(set(use.used_by))})
        else:
            info = unregistered[key]
            out.append({"key": key, "role": info["role"], "name": info["name"],
                        "files": [{"name": name, "sha256": sha, "licence": _unknown(
                            "The licence register does not name this engine.")}
                            for name, sha in sorted(use.files.items())],
                        "licence": _unknown(f"The licence register has no entry for the "
                                            f"{info['role']} model {info['name']!r}; terms not recorded."),
                        "profile": None, "hardware": use.hardware,
                        "used_by": sorted(set(use.used_by))})
    return out


def credits(engine_list: Iterable[Mapping[str, Any]],
            reported_hardware: Mapping[str, str | None]) -> list[dict[str, str]]:
    """D44: one credit per video, voice or sound engine, naming it, and the hardware it
    ran on when the engine reported it (**proposal**: ``<Video|Voices|Sound>: <engine
    name>[ on <hardware>]``). The register's ``where`` names cluster deployments and
    nodes; it stays in the private ``engines[].hardware`` and never reaches a credit."""
    out = []
    for engine in engine_list:
        if engine["role"] in CREDIT_ROLES:
            text = f"{ROLE_LABEL[engine['role']]}: {engine['name']}"
            hardware = reported_hardware.get(engine["key"])
            if hardware:
                text += f" on {hardware}"
            out.append({"engine_key": engine["key"], "text": text[:200]})
    return out


def externally_generated(library: Library, version_ids: Iterable[str]) -> list[dict[str, Any]]:
    """Every input version with the D42 marker, for the E9 disclosure check."""
    out = []
    for version_id in sorted(set(version_ids)):
        version = library.get(version_id)
        provenance = version.provenance if version is not None else None
        external = provenance.get("external") if isinstance(provenance, Mapping) else None
        if isinstance(external, Mapping) and external.get("externally_generated") is True:
            out.append({"id": version_id, "kind": version.kind,
                        "agent": thaw(external.get("agent"))})
    return out


def toolchain_record(*, studio: str, tools: Mapping[str, Any], image_digest: str | None = None
                     ) -> dict[str, Any]:
    """The run's toolchain: ``tools`` holds the adapter, compositor, mixer, mux, encoder
    and keyer versions the build used."""
    from haynes_studio.adapters.pinned import PINS
    from haynes_studio.render.encode import encoder_build
    return {"studio": studio, "image_digest": image_digest,
            "python": platform.python_version(), "ffmpeg": encoder_build(),
            "service_snippets": {name: PINS[name].sha256 for name in ("kokoro_tts.py", "whisper_asr.py")},
            **copy.deepcopy(dict(tools))}


def provenance(*, register: Register, uses: Mapping[str, Use],
               unregistered: Mapping[str, Mapping[str, Any]], library: Library,
               inputs: Iterable[str], toolchain: Mapping[str, Any]) -> dict[str, Any]:
    engine_list = engines(register, uses, unregistered)
    return {"toolchain": dict(toolchain), "engines": engine_list,
            "inputs_externally_generated": externally_generated(library, inputs),
            "usage": {"frontier_tokens": None, "basis": "not metered"},
            "public": {"ai_generated": True,
                       "credits": credits(engine_list, {k: u.hardware for k, u in uses.items()}),
                       "derived_from_roles": list(CREDIT_ROLES)}}


__all__ = ["CREDIT_ROLES", "Register", "Use", "credits", "engines", "externally_generated",
           "library_uses", "most_restrictive", "provenance", "toolchain_record"]
