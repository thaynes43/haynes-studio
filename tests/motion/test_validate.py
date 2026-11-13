"""The motion block on ``studio.asset-version/v1`` (story 457): the schema and the code
checks, each rule with its code, status and path; the block is additive, so every
document that was valid stays valid; a malformed block never raises."""

from __future__ import annotations

import copy

import pytest

from haynes_studio.errors import WARNING
from haynes_studio.library import validate_asset_version
from haynes_studio.library.validate import ASSET_VERSION_FILE
from haynes_studio.schemas import validator_for
from tests.canonical.fixtures import example
from tests.motion.fixtures import DRIVE, loop_block, set_block, sha, timed_block, version

CLIP = sha("c")


def check(document, context="write"):
    return {(v.rule, v.path, v.status) for v in validate_asset_version(document, context=context)
            if v.status != WARNING}


def doc(block, **kwargs):
    return version(block, n=10, clip=CLIP, **kwargs)


def edited(block, change, **kwargs):
    out = doc(block, **kwargs)
    change(out)
    return out


@pytest.mark.parametrize("context", ["read", "write", "queue_run"])
@pytest.mark.parametrize("block", [loop_block, set_block, timed_block])
def test_the_fixtures_are_valid_in_every_context(block, context):
    assert check(doc(block()), context) == set()


def test_a_motion_version_without_a_block_stays_valid():
    assert check(doc(None)) == set()


@pytest.mark.parametrize("name", ["valid/asset-version-cast.json",
                                  "valid/asset-version-photo-external.json",
                                  "valid/asset-version-board-voice.json"])
def test_the_contract_examples_stay_valid(name):
    assert check(example(name)) == set()


def _delete(*path):
    def change(document):
        target = document
        for name in path[:-1]:
            target = target[name]
        del target[path[-1]]
    return change


def _set(value, *path):
    def change(document):
        target = document
        for name in path[:-1]:
            target = target[name]
        target[path[-1]] = value
    return change


def _keyless(block):
    return doc(block, keys=False)


def _no_adapter():
    block = timed_block()
    del block["source"]["adapter"]
    return block


def _loop_adapter():
    block = loop_block()
    block["source"]["adapter"] = "studio.motion/1"
    return block


def _keying(**changes):
    block = loop_block()
    block["keying"].update(changes)
    return block


def _set_keyed():
    block = set_block()
    block["keying"] = loop_block()["keying"]
    return block


S, F = "invalid", "failed"
CASES = {
    # Schema: what one field, or a use or subject, fixes.
    "only a motion version has a block": (
        lambda: {**example("valid/asset-version-cast.json"), "motion": doc(loop_block())["motion"]},
        {("schema.invalid", "/motion", S)}),
    "a block on another kind": (lambda: edited(loop_block(), _set("set", "kind")),
                                {("schema.invalid", "/motion", S)}),
    "an unknown field": (lambda: edited(loop_block(), _set(1, "motion", "extra")),
                         {("schema.unknown_field", "/motion/extra", S)}),
    "a loop at 16 fps": (lambda: doc(loop_block(fps=16)), {("schema.invalid", "/motion/fps", S)}),
    "a loop with a drive track": (
        lambda: doc(loop_block(drive_track={"sha256": DRIVE, "board_frames": 10})),
        {("schema.invalid", "/motion/drive_track", S)}),
    "a timed clip without a drive track": (
        lambda: edited(timed_block(), _delete("motion", "drive_track")),
        {("schema.invalid", "/motion/drive_track", S)}),
    "a timed clip not starting at frame 0": (
        lambda: doc(timed_block(trim={"start": 1, "frames": 102})),
        {("schema.invalid", "/motion/trim/start", S)}),
    "a keyed set loop": (lambda: doc(_set_keyed()), {("schema.invalid", "/motion/keying", S)}),
    "a keyed key without keying": (lambda: edited(loop_block(), _delete("motion", "keying")),
                                   {("schema.invalid", "/motion/keys/keyed", S)}),
    "a loop that fails a longer board": (
        lambda: edited(loop_block(), _set("fail", "motion", "playback", "board_longer")),
        {("schema.invalid", "/motion/playback/board_longer", S)}),
    "an empty negative prompt": (
        lambda: edited(loop_block(), _set("", "motion", "source", "negative_prompt")),
        {("schema.invalid", "/motion/source/negative_prompt", S)}),
    # Code: arithmetic, agreement and keys.
    "a loop period other than 2N - 2": (
        lambda: edited(loop_block(), _set(242, "motion", "playback", "period")),
        {("schema.invalid", "/motion/playback/period", S)}),
    "a trim past the clip": (lambda: doc(loop_block(trim={"start": 1, "frames": 121})),
                             {("schema.invalid", "/motion/trim", S)}),
    "a timed trim other than TIME-8's": (
        lambda: doc(timed_block(trim={"start": 0, "frames": 101})),
        {("schema.invalid", "/motion/trim/frames", S)}),
    "a timed clip shorter than its board": (
        lambda: doc(timed_block(frames=90)),
        {("time.source_short", "/motion/frames", F), ("schema.invalid", "/motion/trim", S)}),
    "a timed clip without its adapter": (lambda: _keyless(_no_adapter()),
                                         {("schema.invalid", "/motion/source/adapter", S)}),
    "a loop naming an adapter outside its profile": (
        lambda: doc(_loop_adapter()), {("schema.invalid", "/motion/source/adapter", S)}),
    "a protect box outside the frame": (
        lambda: doc(_keying(protect_boxes=[[0, 0, 600, 10]])),
        {("schema.invalid", "/motion/keying/protect_boxes/0", S)}),
    "an inverted decal box": (lambda: doc(_keying(decal_box=[453, 699, 266, 779])),
                              {("schema.invalid", "/motion/keying/decal_box", S)}),
    "a decal version without a box": (lambda: doc(_keying(decal_box=None)),
                                      {("schema.invalid", "/motion/keying/decal_version", S)}),
    "a doll clip as a set loop": (lambda: doc(loop_block(), capabilities=["set_loop"]),
                                  {("asset.capability_mismatch", "/capabilities", S)}),
    "a set loop as a doll clip": (lambda: doc(set_block(), capabilities=["motion_clip"]),
                                  {("asset.capability_mismatch", "/capabilities", S)}),
    "content of another size": (lambda: edited(loop_block(), _set(1080, "content", "width")),
                                {("schema.invalid", "/content/width", S)}),
    "a generator seed other than the block's": (
        lambda: edited(loop_block(), _set(1, "provenance", "generator", "seed")),
        {("schema.invalid", "/provenance/generator/seed", S)}),
    "a corrupt identity": (
        lambda: edited(loop_block(), _set("sha256:" + "1" * 64, "motion", "keys", "identity")),
        {("motion.identity_mismatch", "/motion/keys/identity", S)}),
    "a corrupt keyed key": (
        lambda: edited(loop_block(), _set("sha256:" + "1" * 64, "motion", "keys", "keyed")),
        {("motion.identity_mismatch", "/motion/keys/keyed", S)}),
    "a corrupt clip key": (
        lambda: edited(timed_block(), _set("sha256:" + "1" * 64, "motion", "keys", "clip")),
        {("motion.identity_mismatch", "/motion/keys/clip", S)}),
    "an identifier in a key input": (
        lambda: edited(loop_block(), _set("doll asv_01M79V9FC00000000000000001",
                                          "motion", "source", "prompt")),
        {("schema.invalid", "/motion/source", S)}),
}


@pytest.mark.parametrize("case", CASES)
def test_each_rule_has_its_code_status_and_path(case):
    make, expected = CASES[case]
    assert check(make()) == expected


def test_a_set_loop_is_never_timed():
    found = check(edited(set_block(), _set("timed", "motion", "use")))
    assert ("schema.invalid", "/motion/use", S) in found


SCHEMA_CASES = ["only a motion version has a block", "a block on another kind", "an unknown field",
                "a loop at 16 fps", "a loop with a drive track",
                "a timed clip without a drive track", "a timed clip not starting at frame 0",
                "a keyed set loop", "a keyed key without keying",
                "a loop that fails a longer board", "an empty negative prompt"]


@pytest.mark.parametrize("case", SCHEMA_CASES)
def test_a_plain_json_schema_validator_refuses_the_schema_cases(case):
    """The schema file alone carries these rules (as story 404's files do)."""
    make, _ = CASES[case]
    assert list(validator_for(ASSET_VERSION_FILE).iter_errors(make()))


@pytest.mark.parametrize("bad", [{"frames": "x"}, {"keying": []}, {"trim": None}, {"source": {}},
                                 {"keys": 3}, {"use": None}, {"playback": []}, {"drive_track": 7}])
def test_a_malformed_block_returns_violations_and_never_raises(bad):
    document = doc(loop_block())
    document["motion"].update(copy.deepcopy(bad))
    assert check(document)
