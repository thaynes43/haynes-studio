"""The Winter Menu r4 placements from public text only (story 841, TIME-12).

The r4 story imported by story 404, timed with the library of story 382, is planned
with story 380's ``plan_story``; the mix key's placements (TIME-7, from the key alone,
no audio) are compared with the recorded ``timeline.json``. TIME-12 allows 1 ms for
line, sound and bed times (the record rounds to 3 decimals and takes line ends from the
resampled audio); frames are exact, and shot times exact at the record's 4 decimals.
"""

from __future__ import annotations

import copy
import json
from fractions import Fraction

from haynes_studio.cache import BoardVoice, TakeFacts, plan_story
from haynes_studio.canonical import load_story
from haynes_studio.mix import board_ranges, planned_starts
from tests.cache import fixtures as fx
from tests.library.fixtures import imported, winter_menu
from tests.mix.fixtures import TOOLCHAIN
from tests.support.policy import REPO_ROOT

TIMELINE = REPO_ROOT / "titles" / "the-winter-menu" / "evidence-r4" / "timeline.json"
TOLERANCE = Fraction(1, 1000)  # TIME-12: 1 ms for line, sound and bed times
PLACEHOLDER_TRACK = "0" * 64  # legacy board voices have no assembled track


def r4_plan():
    library = winter_menu(4).library
    document = copy.deepcopy(imported(4).story)
    for board in document["boards"]:  # the server writes seeds; placements do not read them
        if board["method"]["motion"] == "s2v":
            board["seeds"] = {f"s2v:{line['speaker']}": 1 for line in board["lines"]}
    story = load_story(document, context="read", source="r4")
    voices = {}
    for board in story.ordered_boards():
        if board.spoken:
            takes = library.takes(board.voice.current_version_id)
            voices[board.id] = BoardVoice(
                takes={t.line_id: TakeFacts(sha256=t.sha256, duration_ms=t.duration_ms)
                       for t in takes},
                track_sha256=PLACEHOLDER_TRACK)
    blobs = {v.id: v.content.sha256 for v in library.versions.values() if v.content is not None}
    voice_ids = {v.id: library.assets[v.asset_id].attributes["voice_id"]
                 for v in library.versions.values() if v.kind == "voice"}
    plan = plan_story(story, voices=voices, blobs=blobs, voice_ids=voice_ids,
                      toolchain=TOOLCHAIN, media=fx.MEDIA, content=fx.stand_in)
    return story, plan


def seconds(samples: int) -> Fraction:
    return Fraction(samples, 48_000)


def test_r4_placements_match_the_recorded_timeline_within_time12():
    story, plan = r4_plan()
    recorded = json.loads(TIMELINE.read_text())
    document = plan.mix.key.document
    assert document["frames"] == 1087 and recorded["total_s"] == 45.2917

    # Shots: frames exact, starts exact at the record's 4 decimals.
    ranges = board_ranges(story, document)
    assert [r.frames for r in ranges] == [s["frames"] for s in recorded["shots"]]
    starts = [round(r.start_frame / 24, 4) for r in ranges]
    assert starts == [s["start_s"] for s in recorded["shots"]]

    planned = planned_starts(document)
    lines = [a for a in recorded["audio"] if a["kind"] == "line"]
    assert len(planned["lines"]) == len(lines) == 13
    worst = {"start": Fraction(0), "end": Fraction(0)}
    for ours, theirs in zip(planned["lines"], lines):
        for side in ("start", "end"):
            gap = abs(seconds(ours[f"{side}_sample"]) - Fraction(str(theirs[f"{side}_s"])))
            assert gap <= TOLERANCE, (ours, theirs)
            worst[side] = max(worst[side], gap)
    # The record rounds to 3 decimals (starts within 1/3 ms) and takes line ends from
    # the resampled audio (TIME-12: up to 0.667 ms on the Winter Menu).
    assert worst == {"start": Fraction(1, 3000), "end": Fraction(2, 3000)}

    sfx = [a for a in recorded["audio"] if a["kind"] == "sfx"]
    sounds = list(document["sounds"])
    assert [s["sound"] for s in sounds] == [a["sha256"] for a in sfx]
    for ours, cue, theirs in zip(planned["sounds"], sounds, sfx):
        start = seconds(ours["start_sample"])
        assert abs(start - Fraction(str(theirs["start_s"]))) <= Fraction(1, 3000), theirs
        trim = cue["trim_ms"]  # every r4 sound is trimmed and ends inside the film
        end = start + Fraction(trim[1] - trim[0], 1000)
        assert abs(end - Fraction(str(theirs["end_s"]))) <= Fraction(1, 3000), theirs
        assert ours["start_sample"] + (trim[1] - trim[0]) * 48 <= 1087 * 2000

    (bed,) = [a for a in recorded["audio"] if a["kind"] == "bed"]
    (ours_bed,) = document["beds"]
    assert ours_bed["sound"] == bed["sha256"] and ours_bed["level_rms_dbfs"] == bed["rms_dbfs"]
    assert abs(seconds(1087 * 2000) - Fraction(str(bed["end_s"]))) <= TOLERANCE


def test_the_contracts_gavel_example():
    """Section 3: the gavel, 50 ms after "Motion carried." on board 8 (film frame 728),
    is mix sample 728 * 2000 + 7625 * 48 = 1822000, 37.958 s."""
    _, plan = r4_plan()
    gavel = plan.mix.key.document["sounds"][2]
    assert gavel["start_sample"] == 728 * 2000 + 7625 * 48 == 1_822_000
    assert round(gavel["start_sample"] / 48_000, 3) == 37.958
    assert list(gavel["trim_ms"]) == [1300, 1950] and gavel["level_rms_dbfs"] == -20
