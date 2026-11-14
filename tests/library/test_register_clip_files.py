"""Every model file a Wan clip record of story 428 names is a file of its engine in the
licence register, with the register's hash (story 860 item c).

The clip records are the committed text records of the first live build
(``titles/the-winter-menu/e1-build/clips/``); the engine is the one a run's provenance
takes for the clip (``Register.engine_for_model_file`` of the profile's model), and the
files are what a run would record for it (``Register.engine_files``). Nothing is read
from a service.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

import pytest

from haynes_studio.build.provenance import Register
from haynes_studio.jsonio import read_json
from tests.library.fixtures import register_document
from tests.support.policy import REPO_ROOT

CLIPS = REPO_ROOT / "titles" / "the-winter-menu" / "e1-build" / "clips"
RECORDS = sorted(CLIPS.glob("*.s2v-clip-record.json"))
ENCODER = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
UNNAMED = "The engine reported this file; the licence register does not name it."


def _record(path) -> Mapping[str, Any]:
    return read_json(path).document


def not_in_register(document: Mapping[str, Any], record: Mapping[str, Any]) -> dict[str, str]:
    """The files of ``record`` (name to SHA-256) that its engine's register entry does not
    hold with that hash, as a run's provenance would list them."""
    register = Register(document)
    engine = register.engine_for_model_file(record["profile"]["model"])
    assert engine is not None, record["profile"]["model"]
    reported = dict(record["clip"]["files_sha256"])
    listed = {item["name"]: item for item in register.engine_files(engine, reported)}
    return {name: sha for name, sha in reported.items()
            if name not in listed or listed[name]["sha256"] != sha
            or listed[name]["licence"]["note"] == UNNAMED
            or not any(f["engine"] == engine and f["name"] == name and f["sha256"] == sha
                       for f in document["files"])}


def test_the_fixture_holds_story_428s_speech_clip_records():
    assert len(RECORDS) == 14  # every Wan job of story 428, the re-rolled clips included
    for path in RECORDS:
        record = _record(path)
        assert Register(register_document()).engine_for_model_file(
            record["profile"]["model"]) == "wan-s2v", path.name
        assert ENCODER in record["clip"]["files_sha256"], path.name


@pytest.mark.parametrize("path", RECORDS, ids=lambda p: p.name.split(".")[0])
def test_every_file_a_clip_record_names_is_a_file_of_its_engine(path):
    assert not_in_register(register_document(), _record(path)) == {}


def test_the_check_fails_when_the_encoder_is_not_a_file_of_the_engine():
    document = copy.deepcopy(register_document())
    keys = [f["key"] for f in document["files"]
            if f["engine"] == "wan-s2v" and f["name"] == ENCODER]
    assert len(keys) == 1
    document["files"] = [f for f in document["files"] if f["key"] not in keys]
    for engine in document["engines"]:
        engine["files"] = [key for key in engine["files"] if key not in keys]
    record = _record(CLIPS / "94f-seed501.s2v-clip-record.json")
    sha = record["clip"]["files_sha256"][ENCODER]
    assert not_in_register(document, record) == {ENCODER: sha}
    # The text-to-video engine still holds the same file with the same hash.
    assert any(f["engine"] == "wan-ti2v" and f["name"] == ENCODER and f["sha256"] == sha
               for f in document["files"])
