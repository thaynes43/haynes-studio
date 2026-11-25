"""Offline draft parsing and compilation to existing board fields."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace

from haynes_studio.canonical import validate_board
from haynes_studio.canonical.ids import Minter
from haynes_studio.canonical.jsonvalues import normalize, too_deep
from haynes_studio.canonical.occlusion import board_write_document
from haynes_studio.errors import ContractError, Violation, pointer
from haynes_studio.jsonio import freeze, parse_strict
from haynes_studio.schemas import schema_violations

SCHEMA = "studio.agent-draft/v1"
MAX_DOCUMENT_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class Proposal:
    key: str
    index: int
    fields: Mapping
    document: Mapping

    @property
    def path(self) -> str:
        return pointer("boards", self.index, "fields")

    def problems(self, **context) -> list[Violation]:
        found = validate_board(self.document, context="write", **context)
        method = self.fields["method"]
        cues = self.fields["cues"]
        if method["layer"] == "whole_frame" and any(c["type"] in ("move", "camera") for c in cues):
            found.append(Violation("wholeframe.unsupported", "/cues",
                                   "Whole-frame boards cannot use move or camera cues"))
        if sum(c["type"] == "camera" for c in cues) > 1:
            found.append(Violation("layered.unsupported", "/cues", "A board can use one camera cue"))
        return [replace(v, path=self.path + v.path) for v in found
                if v.status != "warning" or v.rule == "method.unavailable"]


@dataclass(frozen=True)
class Draft:
    sha256: str
    production_id: str
    story_id: str
    model: str
    session: str
    set_pins: Mapping | None
    usage: Mapping
    boards: tuple[Proposal, ...]

    def require_valid_boards(self) -> None:
        violations = [violation for board in self.boards for violation in board.problems()]
        if violations:
            raise ContractError("<agent draft>", violations)

    def require_set(self, story_set: Mapping | None) -> None:
        pins = ("asset_version_id", "motion_asset_version_id")
        if any((story_set or {}).get(pin) != (self.set_pins or {}).get(pin) for pin in pins):
            raise _invalid("draft.set_changed", "/set", "The story's pinned set differs from the draft")

    @classmethod
    def parse(cls, data: bytes) -> "Draft":
        if len(data) > MAX_DOCUMENT_BYTES:
            raise _invalid("draft.too_large", "", "Draft exceeds the 4 MiB file limit")
        try:
            raw = parse_strict(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise _invalid("schema.invalid", "", "Expected strict UTF-8 JSON") from None
        if too_deep(raw):
            raise _invalid("schema.invalid", "", "Draft is nested too deeply")
        try:
            json.dumps(raw, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except UnicodeError:
            raise _invalid("schema.invalid", "", "Draft contains an invalid Unicode scalar") from None
        raw = normalize(raw)
        if isinstance(raw, dict) and isinstance(raw.get("boards"), list):
            for item in raw["boards"]:
                if isinstance(item, dict) and "fields" in item:
                    item["fields"] = board_write_document(item["fields"])
        violations = schema_violations("studio.agent-draft.v1.schema.json", raw,
                                       default_rule="schema.invalid")
        if violations:
            raise ContractError("<agent draft>", violations)
        minter = Minter()
        boards = tuple(_compile(item, index, raw["story_id"], minter)
                       for index, item in enumerate(raw["boards"]))
        if len({board.key for board in boards}) != len(boards):
            raise _invalid("ref.duplicate", "/boards", "Draft board keys must be unique")
        usage = {key: raw.get("usage", {}).get(key)
                 for key in ("input_tokens", "output_tokens", "cost_usd")}
        return cls(hashlib.sha256(data).hexdigest(), raw["production_id"], raw["story_id"],
                   raw["model"], raw["session"], freeze(raw["set"]), freeze(usage), boards)


def _invalid(rule: str, path: str, message: str) -> ContractError:
    return ContractError("<agent draft>", [Violation(rule, path, message)])


def _compile(item: dict, index: int, story_id: str, minter: Minter) -> Proposal:
    fields = item["fields"]
    fields.setdefault("seeds", {})
    fields.setdefault("photo", {"prompt": None, "input_asset_version_ids": []})
    fields["photo"]["current_version_id"] = None
    fields["voice"] = {"style": fields["voice"], "current_version_id": None}
    line_ids = {}
    for position, line in enumerate(fields["lines"]):
        key = line.pop("key", None)
        line["id"] = minter.mint("lin")
        if key is not None:
            if key in line_ids:
                raise _invalid("ref.duplicate", pointer("boards", index, "fields", "lines", position, "key"),
                               "Line keys must be unique within a board")
            line_ids[key] = line["id"]
    for position, cue in enumerate(fields["cues"]):
        anchor = cue["anchor"]
        if "after_line" in anchor:
            line_id = line_ids.get(anchor.pop("after_line"))
            if line_id is None:
                raise _invalid("cue.anchor_line_missing",
                               pointer("boards", index, "fields", "cues", position, "anchor", "after_line"),
                               "The cue must name a line key on its board")
            anchor["after_line_id"] = line_id
    document = {
        **fields, "schema": "studio.board/v1", "id": minter.mint("brd"), "story_id": story_id,
        "number": 1, "revision": 1, "origin": None,
        "drafted_by": {"kind": "agent", "key_id": minter.mint("key")},
        "cues": [{**cue, "id": minter.mint("cue")} for cue in fields["cues"]],
        "notes": [{**note, "id": minter.mint("nte")} for note in fields["notes"]],
    }
    return Proposal(item["key"], index, freeze(fields), freeze(document))
