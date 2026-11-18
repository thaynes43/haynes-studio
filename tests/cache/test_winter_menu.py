"""Story 861: recompute story 428's speech clip keys from its committed records."""

import json

import pytest

from haynes_studio.adapters.wan import NEGATIVE
from haynes_studio.cache.keys import s2v_clip_key
from haynes_studio.cache.plan import Toolchain
from tests.support.policy import REPO_ROOT

BUILD = REPO_ROOT / "titles/the-winter-menu/e1-build"
RECORDS = sorted((BUILD / "clips").glob("*.s2v-clip-record.json"))


def test_the_compatibility_fixture_covers_all_fourteen_live_clip_records():
    assert len(RECORDS) == 14


@pytest.mark.parametrize("path", RECORDS, ids=lambda path: path.stem)
def test_the_default_negative_prompt_preserves_story_428s_recorded_clip_key(path):
    record = json.loads(path.read_text())
    tools = Toolchain()
    saved_tools = json.loads((BUILD / "toolchain.json").read_text())
    assert tools.s2v_negative_prompt == saved_tools["s2v_negative_prompt"] == NEGATIVE
    assert record["negative_prompt"] == tools.s2v_negative_prompt
    inputs = dict(drive_track=record["drive_track"]["sha256"],
                  start_still=record["start_image"]["sha256"], prompt=record["prompt"],
                  negative_prompt=tools.s2v_negative_prompt, seed=record["seed"],
                  profile=record["profile"], adapter=record["adapter"])
    assert s2v_clip_key(**inputs).value == record["key"]
    assert s2v_clip_key(**{**inputs, "negative_prompt": ""}).value != record["key"]
