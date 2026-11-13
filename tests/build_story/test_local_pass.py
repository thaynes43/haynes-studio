"""No clip is asked for until the whole story has passed its local checks (story 406,
review finding 1): drive tracks are made, every speaker's library timed clip resolved,
every seed the plan needs checked and every board planned with clip sources that only
record what they would be asked, before the first clip of any board is requested; then
the mix, which needs no clip, is made and its own checks run (the confirming check's
finding a). A story that cannot be built fails its run with no clip asked; a buildable
one is asked once per missing clip, and its mix is made once across the phases."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest

from haynes_studio.build import offline_sources
from haynes_studio.library.model import locator_for
from haynes_studio.motion.winter_menu import complete_block
from tests.build_story import fixtures as f
from tests.build_story.test_failures import assert_failed
from tests.layered import media
from tests.motion import fixtures as mf

L2 = f.ident("lin", 2)


def two_speakers() -> dict:
    """The fixture draft with ``b`` speaking on B1 too: cast order a then b."""
    document = f.story_document()
    b1 = f.board_of(document, f.B1)
    b1["lines"].append({"id": L2, "speaker": "b", "text": "Two.", "gap_before_ms": 120})
    b1["seeds"]["s2v:b"] = 12
    return document


def damaged_timed_clip(world: f.World, library, *, slot: str, drive: str, board_frames: int,
                       seed: int) -> dict:
    """A promoted library timed clip of ``slot``'s still, made from ``drive`` with
    ``seed``, whose bytes in the store are not the bytes it names (a damaged blob)."""
    clip = b"the timed clip of " + slot.encode()
    clip_sha = hashlib.sha256(clip).hexdigest()
    locator = locator_for(clip_sha, "video/mp4", f.PRODUCTION)
    path = Path(world.store.root) / locator  # a private store: no other test reads it
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"other bytes at that locator")
    needed = (board_frames - 1) * 16 // 24 + 1
    block = mf.timed_block(still_sha256=library.version(f.STILL[slot]).content.sha256,
                           frames=needed + 4, width=144, height=256,
                           trim={"start": 0, "frames": needed},
                           drive_track={"sha256": drive, "board_frames": board_frames},
                           keying={**f.KEYING, "decal_min_ecc": 0.5})
    start = world.publish(media.start_image(tint=f.TINT[slot]), "image/png")  # her loop's
    block["source"] = {**block["source"], "image_sha256": start, "seed": seed}
    doc = mf.version(None, n=1, clip=clip_sha)
    doc["provenance"]["generator"]["seed"] = seed
    doc["motion"] = complete_block(block, clip_sha)
    doc["content"]["bytes"] = len(clip)
    return f._scoped(doc, f.ident("asv", 60), 60)


def test_a_damaged_timed_clip_of_a_later_speaker_stops_the_run_before_any_clip(tmp_path):
    world = f.make_world(tmp_path / "store")
    document, library = f.voiced(world, two_speakers())
    # A first service phase of the new world asks each missing clip once: a's and b's
    # speech-to-video clips and B3's whole-frame clip. The drive tracks are made by the
    # local pass and recorded as made by this run.
    sources = f.sources()
    first = f.build(world, document, library, phase="service", source=sources)
    assert first.run["status"] == "cancelled", first.run["error"]
    assert sorted(r.seed for r in sources.s2v.calls) == [11, 12] and len(sources.i2v.calls) == 1
    b1 = next(s for s in first.run["stages"] if s["board_id"] == f.B1)
    drives = [a for a in b1["artifacts"] if a["kind"] == "s2v_drive_track"]
    assert len(drives) == 2 and all(a["made"] and a["seconds"] is not None for a in drives)
    # a's clip is re-rolled, so a new clip would be asked for her; b has a library timed
    # clip made from her own drive track with her seed, whose bytes are damaged.
    edited = copy.deepcopy(document)
    f.board_of(edited, f.B1)["seeds"]["s2v:a"] = 21
    timed = damaged_timed_clip(world, library, slot="b", seed=12,
                               drive=first.plan.artifacts[f"{f.B1}/drive/b"].content,
                               board_frames=first.plan.boards[0].frames)
    with_timed = f.Library.from_version_documents([*library.documents(), timed])
    sources = f.sources()
    result = f.build(world, edited, with_timed, source=sources)
    assert sources.s2v.calls == [] and sources.i2v.calls == []  # a's clip was never asked
    run = assert_failed(world, result, "store.hash_mismatch", board=f.B1, stage="s2v_clip")
    assert "before any clip was requested" in run["error"]["message"]


def test_a_later_boards_missing_seed_stops_the_run_before_an_earlier_boards_clip(
        world, voiced, first):
    document, library = voiced
    edited = copy.deepcopy(document)
    edited["board_order"] = [f.B3, f.B1, f.B2]  # the whole-frame board first
    f.board_of(edited, f.B3)["seeds"]["i2v:frame"] = 37  # a clip no run made
    del f.board_of(edited, f.B1)["seeds"]["s2v:a"]  # the later layered board has no seed
    sources = f.sources()
    result = f.build(world, edited, library, source=sources)
    assert sources.i2v.calls == [] and sources.s2v.calls == []  # B3's clip was never asked
    run = assert_failed(world, result, "cache.key_input_invalid", board=f.B1, stage="plan")
    assert "s2v:a" in run["error"]["message"]


def unlimitable(document: dict) -> dict:
    """A true-peak target the story schema accepts (a level, at most 0) and the mixer's
    limiter cannot reach (its limit range): refused from that number alone."""
    edited = copy.deepcopy(document)
    edited["mix"]["true_peak_dbtp"] = -30
    return edited


def test_a_mix_the_limiter_refuses_stops_the_service_phase_before_any_clip(world, voiced, first):
    document, library = voiced
    edited = unlimitable(document)
    f.board_of(edited, f.B1)["seeds"]["s2v:a"] = 25  # two clips no run made
    f.board_of(edited, f.B3)["seeds"]["i2v:frame"] = 41
    sources = f.sources()
    result = f.build(world, edited, library, phase="service", source=sources)
    assert sources.s2v.calls == [] and sources.i2v.calls == []
    run = assert_failed(world, result, "mix.input_invalid", stage="mix")
    assert run["error"]["message"].endswith("(found before any clip was requested)")


@pytest.mark.parametrize("workers", [1, 2])
def test_a_mix_the_limiter_refuses_stops_a_full_build_before_any_clip(world, voiced, first, workers):
    document, library = voiced
    edited = unlimitable(document)
    f.board_of(edited, f.B1)["seeds"]["s2v:a"] = 25 + workers  # a clip no run made
    sources = f.sources()
    result = f.build(world, edited, library, source=sources, workers=workers)
    assert sources.s2v.calls == [] and sources.i2v.calls == []
    run = assert_failed(world, result, "mix.input_invalid", stage="mix")
    assert run["error"]["message"].endswith("(found before any clip was requested)")


def test_a_mix_that_fails_its_own_checks_stops_before_any_clip(world, voiced, first):
    # A loudness target the limited speech cannot reach: the mix is made, and its
    # loudness check (a mix-side check, no master needed) fails.
    document, library = voiced
    edited = copy.deepcopy(document)
    edited["mix"]["master_lufs"] = -2
    f.board_of(edited, f.B1)["seeds"]["s2v:a"] = 28  # a clip no run made
    sources = f.sources()
    result = f.build(world, edited, library, source=sources)
    assert sources.s2v.calls == [] and sources.i2v.calls == []
    run = assert_failed(world, result, "build.check_failed", stage="checks")
    assert "mix.loudness" in run["error"]["message"]
    assert run["error"]["message"].endswith("(found before any clip was requested)")
    assert {c["check"] for c in run["checks"]} == {"mix.length", "mix.loudness", "mix.true_peak",
                                                    "mix.clipping"}
    assert next(c for c in run["checks"] if c["check"] == "mix.loudness")["result"] == "fail"


def test_a_buildable_story_asks_each_missing_clip_exactly_once(world, voiced, first):
    document, library = voiced
    edited = copy.deepcopy(document)
    edited["mix"]["line_rms_dbfs"] = -23  # a new mix, which no run made
    f.board_of(edited, f.B1)["seeds"]["s2v:a"] = 22  # a re-roll on the first board
    f.board_of(edited, f.B3)["seeds"]["i2v:frame"] = 39  # and on the last
    sources = f.sources()
    built = f.build(world, edited, library, phase="service", source=sources)
    assert built.run["status"] == "cancelled", built.run["error"]
    assert [r.seed for r in sources.s2v.calls] == [22]
    assert [[c.seed for c in r.clips] for r in sources.i2v.calls] == [[39]]
    assert built.source_calls == 2
    made = {n for n, p in built.plan.artifacts.items() if p.key.value in built.made}
    assert made == {f"{f.B1}/s2v_clip/a", f"{f.B3}/whole_frame_clip", "film/mix"}
    checks = {c["check"]: c["result"] for c in built.run["checks"] or ()}
    assert checks == dict.fromkeys(("mix.length", "mix.loudness", "mix.true_peak",
                                    "mix.clipping"), "pass")
    # The offline phase reuses that mix and those clips: it renders, then stops at the
    # new master's transcript (a service call), and makes no mix.
    offline = f.build(world, edited, library, phase="offline", source=offline_sources())
    assert offline.run["error"]["code"] == "build.offline_missing", offline.run["error"]
    assert offline.run["error"]["stage"] == "check_result" and offline.source_calls == 0
    assert built.plan.artifacts["film/mix"].key.value not in offline.made
