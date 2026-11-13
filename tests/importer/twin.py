"""A synthetic twin of The Winter Menu's public records, for the import's tests.

The real records name the SHA-256 of private files, and no test can make bytes with a
given hash. So every media hash ``h`` the records name (the recovery map's rows, the E0
clip records' clips, start images and drive tracks, and the library's content and takes)
gets synthetic bytes ``twin_bytes(h)`` and is replaced everywhere by ``s = sha256(those
bytes)``: in the recovery map (and its upload paths, which carry ``h[:16]``), the E0
lines, and the library's documents (locators carry ``h[:2]/h``). Each motion block's
keys are computed again from its rewritten inputs (``complete_block``), so the twin's
identities are the motion module's own. The structure (rows, roles, sources, versions,
source keys, IDs, the r4 story) is the real one; only the hashes differ.

``twin_volume`` lays the twin's private files out on a :class:`FakeWanVolume`: the four
delivery ledgers with their assets, each E0 motion clip as its Wan job's output, and
each start image and keyframe as its E0 upload. The fire bed is nowhere (it was never
delivered) and no render is (ComfyUI is not read).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import cache
from typing import Any

from haynes_studio.adapters.fakes import FakeWanVolume
from haynes_studio.importer.command import load_inputs
from haynes_studio.importer.plan import E0Line, Plan, plan_import
from haynes_studio.library.library import EMPTY, Library
from haynes_studio.motion.winter_menu import complete_block
from tests.canonical.fixtures import NOW
from tests.library.fixtures import BY, imported
from tests.support.policy import REPO_ROOT

TITLE = REPO_ROOT / "titles" / "the-winter-menu"
LEDGERS = ("evidence", "evidence-r2", "evidence-r3", "evidence-r4")


def twin_bytes(public_sha256: str) -> bytes:
    return b"synthetic twin of " + public_sha256.encode()


@dataclass(frozen=True)
class Public:
    story: dict
    library: Library
    recovery_map: dict
    lines: tuple[E0Line, ...]


@dataclass(frozen=True)
class Twin:
    story: dict
    library: Library
    recovery_map: dict
    lines: tuple[E0Line, ...]
    mapping: dict[str, str]  # public hash -> twin hash
    data: dict[str, bytes]  # twin hash -> its bytes
    ledgers: tuple[dict, ...]

    def plan(self) -> Plan:
        return plan_import(self.recovery_map, self.lines, self.library,
                           production_id=self.story["production_id"])

    def twin_of(self, public_sha256: str) -> str:
        return self.mapping[public_sha256]


@cache
def public() -> Public:
    result = imported(4)
    library, recovery_map, lines, _ = load_inputs(REPO_ROOT, result.story, result.import_map, EMPTY,
                                                  by=BY, now=NOW)
    return Public(result.story, library, recovery_map, tuple(lines))


def _media_hashes(p: Public) -> set[str]:
    hashes = {row["sha256"] for row in p.recovery_map["rows"]}
    for line in p.lines:
        hashes |= {line.record[k] for k in ("clip_sha256", "image_sha256", "audio_sha256")
                   if k in line.record}
    for version in p.library.versions.values():
        if version.content is not None:
            hashes.add(version.content.sha256)
        if version.voice is not None:
            hashes |= {take.sha256 for take in version.voice.takes}
    return hashes


def _rewrite(text: str, mapping: dict[str, str]) -> str:
    for old, new in mapping.items():
        text = text.replace(f"{old[:2]}/{old}", f"{new[:2]}/{new}")
        text = text.replace(f"studio-e0/{old[:16]}", f"studio-e0/{new[:16]}")
        text = text.replace(old, new)
    return text


def _same(document: Any, mapping: dict[str, str]) -> Any:
    return json.loads(_rewrite(json.dumps(document), mapping))


@cache
def twin() -> Twin:
    p = public()
    mapping = {h: hashlib.sha256(twin_bytes(h)).hexdigest() for h in sorted(_media_hashes(p))}
    data = {mapping[h]: twin_bytes(h) for h in mapping}
    docs = _same(p.library.documents(), mapping)
    for doc in docs:
        if doc["content"] is not None and doc["content"]["bytes"] is not None:
            doc["content"]["bytes"] = len(data[doc["content"]["sha256"]])  # the twin's own size
        if doc.get("motion") is not None:
            doc["motion"] = complete_block(doc["motion"], doc["content"]["sha256"])
    library = Library.from_version_documents(docs)
    lines = tuple(E0Line(line.file, line.line, line.outcome, _same(line.record, mapping))
                  for line in p.lines)
    ledgers = tuple(_same(json.loads((TITLE / folder / "production.json").read_text()), mapping)
                    for folder in LEDGERS)
    return Twin(p.story, library, _same(p.recovery_map, mapping), lines, mapping, data, ledgers)


def twin_volume(root, t: Twin | None = None) -> FakeWanVolume:
    """The twin's private files on a fake Wan volume at ``root``."""
    t = t or twin()
    vol = FakeWanVolume(root)
    for ledger in t.ledgers:
        vol.add_ledger(ledger, {a["sha256"]: t.data[a["sha256"]] for a in ledger["assets"]
                                if a["sha256"] in t.data})
    for line in t.lines:
        if line.outcome != "not a motion clip":
            vol.add_job(line.record["job_id"], t.data[line.record["clip_sha256"]])
            image = line.record["image_sha256"]
            vol.add_upload(image[:16] + ".png", t.data[image])
    for row in t.recovery_map["rows"]:
        if row["role"] == "keyframe":
            vol.add_upload(row["sha256"][:16] + ".png", t.data[row["sha256"]])
    return vol
