"""The legacy timeline reproduces the recorded timeline.json of The Winter Menu r1 to r4
(contract rules TIME-1 to TIME-4, TIME-7, TIME-10 and TIME-12)."""

from __future__ import annotations

import copy
import json
from fractions import Fraction

import pytest

from haynes_studio.errors import ContractError
from haynes_studio.jsonio import read_json
from haynes_studio.legacy import manifest as lm
from haynes_studio.legacy.speech import load_speech, speech_from_document
from haynes_studio.legacy.timeline import compare, compute, load_recorded
from tests.support.policy import REPO_ROOT

TITLE = REPO_ROOT / "titles" / "the-winter-menu"
# revision: (manifest, evidence folder, total frames, lines, sound cues, beds)
FIXTURES = {
    1: ("manifest.json", "evidence", 662, 5, 1, 0),
    2: ("manifest-r2.json", "evidence-r2", 823, 7, 2, 1),
    3: ("manifest-r3.json", "evidence-r3", 1094, 13, 4, 1),
    4: ("manifest-r4.json", "evidence-r4", 1087, 13, 4, 1),
}


def paths(revision):
    name, evidence, *_ = FIXTURES[revision]
    return TITLE / name, TITLE / evidence / "speech.json", TITLE / evidence / "timeline.json"


def timeline_of(revision):
    manifest, speech, _ = paths(revision)
    return compute(lm.load(manifest), load_speech(speech))


def recorded_of(revision):
    return read_json(paths(revision)[2]).document


@pytest.mark.parametrize("revision", FIXTURES)
def test_computed_timeline_matches_the_recorded_one(revision):
    _, _, frames, lines, sounds, beds = FIXTURES[revision]
    timeline = timeline_of(revision)
    recorded = recorded_of(revision)
    assert timeline.frames == frames
    assert [shot.frames for shot in timeline.shots] == [s["frames"] for s in recorded["shots"]]
    assert [shot.shot_id for shot in timeline.shots] == [s["shot"] for s in recorded["shots"]]
    label, document = load_recorded(paths(revision)[2])
    comparison = compare(timeline, document, source=label)
    assert comparison.mismatches == ()
    assert comparison.ok and comparison.violations() == []
    checked = {check.item for check in comparison.checks}
    assert sum(item.split()[2:3] == ["line"] for item in checked if item.startswith("shot")) \
        == lines
    assert sum(" sfx " in item for item in checked) == sounds
    assert sum(item.startswith("bed ") for item in checked) == beds


@pytest.mark.parametrize("revision", FIXTURES)
def test_allowances_are_exact_for_frames_and_1_ms_only_for_audio(revision):
    comparison = compare(timeline_of(revision), recorded_of(revision))
    for check in comparison.checks:
        if check.field in ("frames", "id", "cue") or "count" in check.field:
            assert check.allowance == "exact", check
        elif check.item.startswith("shot") and check.field in ("start", "end") \
                and len(check.item.split()) == 2:
            assert check.allowance == "4 decimals", check
        elif check.item == "film":
            assert check.allowance in ("exact", "4 decimals"), check
        else:
            assert check.allowance == "1 ms", check
            assert abs(check.diff_ms) <= 1
    audio = [abs(c.diff_ms) for c in comparison.checks if c.allowance == "1 ms"]
    assert audio and max(audio) <= Fraction(2, 3)  # observed worst case, under TIME-12's 1 ms


def test_r4_matches_the_contract_worked_example():
    timeline = timeline_of(4)
    assert [s.content_ms for s in timeline.shots] == [
        6363, 3888, 6064, 3475, 3432, 5059, 1900, 10427, 4481]
    assert [s.frames for s in timeline.shots] == [153, 94, 146, 84, 83, 122, 46, 251, 108]
    assert [s.start_frame for s in timeline.shots] == [0, 153, 247, 393, 477, 560, 682, 728, 979]
    vote = timeline.shots[7]
    assert [(line.doll, line.start_ms, line.end_ms) for line in vote.lines] == [
        ("b", 1900, 2903), ("a", 3203, 4014), ("c", 4214, 5089), ("d", 5339, 5851),
        ("b", 6551, 7575), ("b", 8475, 9627)]
    crow, gavel = vote.sfx
    assert (crow.cue, crow.start_ms) == ("crow", 750)
    assert (gavel.cue, gavel.start_ms, gavel.start_sample) == ("gavel", 7625, 1_822_000)
    assert gavel.end_sample == 1_822_000 + 650 * 48  # trim 1.3 to 1.95 s
    assert [(bed.name, bed.start_sample, bed.end_sample) for bed in timeline.beds] == [
        ("fire", 0, 1087 * 2000)]


def test_r1_speech_without_k_reads_as_the_first_line():
    speech = load_speech(paths(1)[1])
    assert all(not take.k_present and take.k == 0 for take in speech.takes)
    assert load_speech(paths(4)[1]).takes[0].k_present


# Mismatches -------------------------------------------------------------------------


def test_a_frame_off_by_one_is_a_mismatch():
    recorded = copy.deepcopy(recorded_of(4))
    recorded["shots"][7]["frames"] += 1
    comparison = compare(timeline_of(4), recorded, source="t.json")
    assert not comparison.ok
    found = {(c.item, c.field) for c in comparison.mismatches}
    assert found == {("shot 8", "frames"), ("film", "frames")}
    assert comparison.violations()[0].rule == "legacy.timeline_mismatch"


@pytest.mark.parametrize(("shift", "ok"), [(0.0003, True), (-0.0003, True), (0.002, False)])
def test_line_placement_allowance_is_1_ms(shift, ok):
    recorded = copy.deepcopy(recorded_of(4))
    line = next(a for a in recorded["audio"] if a["kind"] == "line" and a["shot"] == 8
                and a["k"] == 4)
    line["start_s"] = round(line["start_s"] + shift, 4)
    comparison = compare(timeline_of(4), recorded)
    assert comparison.ok is ok
    if not ok:
        assert [(c.item, c.field) for c in comparison.mismatches] == [("shot 8 line 4", "start")]


def test_a_missing_or_reordered_sound_is_a_mismatch():
    recorded = copy.deepcopy(recorded_of(4))
    sounds = [i for i, a in enumerate(recorded["audio"]) if a["kind"] == "sfx"]
    recorded["audio"][sounds[1]], recorded["audio"][sounds[2]] = \
        recorded["audio"][sounds[2]], recorded["audio"][sounds[1]]
    assert ("shot 8 sfx crow", "cue") in {(c.item, c.field) for c in
                                          compare(timeline_of(4), recorded).mismatches}
    del recorded["audio"][sounds[0]]
    assert ("film", "sfx count") in {(c.item, c.field) for c in
                                     compare(timeline_of(4), recorded).mismatches}


def test_a_malformed_record_is_refused():
    with pytest.raises(ContractError) as caught:
        compare(timeline_of(4), {"shots": [], "audio": []}, source="t.json")
    assert [(v.rule, v.path) for v in caught.value.violations] == [("legacy.invalid", "/total_s")]


# Speech pairing ---------------------------------------------------------------------


def speech_document(revision):
    return copy.deepcopy(read_json(paths(revision)[1]).document)


def test_a_line_without_a_take_is_refused():
    document = speech_document(4)
    del document["lines"][7]  # shot 8, k 1
    with pytest.raises(ContractError) as caught:
        compute(lm.load(paths(4)[0]), speech_from_document(document, source="s.json"))
    assert [(v.rule, v.path) for v in caught.value.violations] == [
        ("legacy.speech_mismatch", "/lines")]
    assert "shot 8 line 1" in str(caught.value)


def test_a_take_with_other_text_or_doll_is_refused():
    document = speech_document(4)
    document["lines"][0]["text"] = "Something else."
    document["lines"][1]["doll"] = "c"
    with pytest.raises(ContractError) as caught:
        compute(lm.load(paths(4)[0]), speech_from_document(document, source="s.json"))
    assert {(v.rule, v.path) for v in caught.value.violations} == {
        ("legacy.speech_mismatch", "/lines/0/text"), ("legacy.speech_mismatch", "/lines/1/doll")}


def test_a_take_without_k_on_a_multi_line_shot_is_refused():
    document = speech_document(4)
    del document["lines"][6]["k"]  # shot 8, k 0
    with pytest.raises(ContractError) as caught:
        compute(lm.load(paths(4)[0]), speech_from_document(document))
    assert ("legacy.speech_mismatch", "/lines/6") in {
        (v.rule, v.path) for v in caught.value.violations}


@pytest.mark.parametrize(("mutate", "expected"), [
    (lambda d: d["lines"][0].update(duration_s=5.1635), ("time.not_integer_ms", "/lines/0/duration_s")),
    (lambda d: d["lines"][0].update(extra=1), ("schema.unknown_field", "/lines/0/extra")),
    (lambda d: d["lines"][0].pop("sha256"), ("legacy.invalid", "/lines/0")),
    (lambda d: d["lines"].append(dict(d["lines"][0])), ("legacy.invalid", "/lines/13")),
])
def test_speech_shape_rules(mutate, expected):
    document = speech_document(4)
    mutate(document)
    with pytest.raises(ContractError) as caught:
        speech_from_document(document)
    assert expected in {(v.rule, v.path) for v in caught.value.violations}


# Synthetic manifests ----------------------------------------------------------------


def synthetic(shots, sfx=None, beds=None):
    document = {"title": "Example", "job": "example-r1",
                "frame": {"width": 1080, "height": 1920, "fps": 24}, "shots": shots}
    if sfx is not None:
        document["sfx"] = sfx
    if beds is not None:
        document["beds"] = beds
    return lm.from_document(document)


def takes(*records):
    return speech_from_document({"lines": [
        {"shot": shot, "k": k, "doll": "a", "text": text, "file": f"voices/{shot}-{k}.wav",
         "duration_s": seconds, "sha256": "0" * 64}
        for shot, k, text, seconds in records]})


def test_default_gap_spaces_lines_300_ms():
    manifest = synthetic([{"id": 1, "layout": "single", "dolls": {"a": "a.png"}, "tail": 0.7,
                           "lines": [{"doll": "a", "text": "One.", "start": 0.5},
                                     {"doll": "a", "text": "Two."}]}])
    shot = compute(manifest, takes((1, 0, "One.", 1.0), (1, 1, "Two.", 0.5))).shots[0]
    assert [(line.start_ms, line.end_ms) for line in shot.lines] == [(500, 1500), (1800, 2300)]
    assert shot.content_ms == 3000 and shot.frames == 72


def test_a_sound_past_the_last_cut_is_cut_at_film_end():
    manifest = synthetic(
        [{"id": 1, "layout": "single", "dolls": {"a": "a.png"}, "duration": 1.0,
          "sfx": [{"cue": "boom", "at": 0.5}, {"cue": "hiss", "at": 0.0}]}],
        sfx={"boom": {"file": "boom.wav", "trim": [0.0, 2.0], "gain_db": -20},
             "hiss": {"file": "hiss.wav", "gain_db": -30}})
    boom, hiss = compute(manifest, takes()).shots[0].sfx
    assert boom.cut_at_film_end and boom.end_sample == 24 * 2000
    assert hiss.end_sample is None and not hiss.cut_at_film_end  # untrimmed: length unknown


def test_a_sound_outside_its_shot_is_refused():
    manifest = synthetic(
        [{"id": 1, "layout": "single", "dolls": {"a": "a.png"}, "duration": 1.0,
          "sfx": [{"cue": "boom", "at": 1.0}]}],
        sfx={"boom": {"file": "boom.wav", "trim": [0.0, 0.5], "gain_db": -20}})
    with pytest.raises(ContractError) as caught:
        compute(manifest, takes())
    assert [(v.rule, v.path) for v in caught.value.violations] == [
        ("cue.out_of_range", "/shots/0/sfx/0")]


def test_timeline_is_json_serializable_through_the_cli_shape():
    from haynes_studio.cli import _timeline_json

    result = _timeline_json(timeline_of(4), compare(timeline_of(4), recorded_of(4)))
    assert json.loads(json.dumps(result))["frames"] == 1087
    assert result["comparison"]["match"] is True
