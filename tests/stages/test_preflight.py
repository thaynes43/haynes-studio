"""Fail-fast checks before any renderer call, on the small fixture: the contract's
nine-board r4 story (public text), its facts, and one synthetic blob per referenced
asset version published into a store under ``tmp_path``."""

from __future__ import annotations

import copy
import time
from collections.abc import Callable

import pytest

from haynes_studio.canonical import NO_FACTS, Story
from haynes_studio.stages import (
    ASSET_UNRESOLVED,
    DEFINITION_ONLY,
    PreflightError,
    ResolvedVersion,
    ensure_buildable,
    preflight,
    references,
)
from haynes_studio.store import BLOB_MISSING, HASH_MISMATCH, LOCATOR_INVALID, LocalStore, blob_locator
from tests.canonical.fixtures import example, example_context
from tests.store.helpers import PRD_OTHER, plant, sha, tree

LIMIT_S = 5.0  # acceptance: under 5 s on the small fixture
SOUND_7 = "asv_01M79V9FC0000000000000000B"  # board 7's sound cue (legacy shot 7)
SOUND_9 = "asv_01M79V9FC00000000000000009"  # board 9's sound cue (legacy shot 9)
BED = "asv_01M79V9FC0000000000000000C"


def _scope_and_media(path: str, production_id: str) -> tuple[str, str]:
    if path.endswith("/voice/current_version_id"):
        return production_id, "audio/wav"  # board voice: board-scoped
    if path.endswith("/photo/current_version_id"):
        return production_id, "image/png"  # board photo: board-scoped
    if "/cues/" in path or path.startswith("/beds/"):
        return "library", "audio/wav"
    if path == "/set/motion_asset_version_id":
        return "library", "video/mp4"
    return "library", "image/png"  # cast stills, the set, photo inputs


class Fixture:
    def __init__(self, root):
        self.root = root
        self.document = example("valid/story-winter-menu-r4.json")
        self.story = Story.from_document(self.document)
        self.facts = example_context().facts
        self.store = LocalStore(root)
        self.resolved: dict[str, ResolvedVersion] = {}
        for path, version_id, needs_bytes in references(self.story):
            if version_id in self.resolved:
                continue
            if not needs_bytes:
                self.resolved[version_id] = DEFINITION_ONLY  # a stock voice has no bytes
                continue
            scope, media = _scope_and_media(path, self.story.production_id)
            blob = self.store.publish(f"synthetic {media} for {version_id}".encode(),
                                      scope=scope, media_type=media)
            self.resolved[version_id] = ResolvedVersion.of(blob.sha256, blob.locator)

    def story_with(self, change: Callable[[dict], None]) -> Story:
        document = copy.deepcopy(self.document)
        change(document)
        return Story.from_document(document)

    def check(self, story: Story | None = None, **kwargs):
        arguments = {"facts": self.facts, "resolved": self.resolved, "store": self.store, **kwargs}
        started = time.perf_counter()
        report = preflight(story or self.story, **arguments)
        assert time.perf_counter() - started < LIMIT_S
        return report


def board(document: dict, number: int) -> dict:
    return next(b for b in document["boards"] if b["number"] == number)


def summary(report) -> list[tuple]:
    return [(p.rule, p.board_number, p.legacy_shot, p.field) for p in report.blocking]


@pytest.fixture
def fx(tmp_path):
    root = tmp_path / "store"
    root.mkdir()
    return Fixture(root)


def test_the_small_fixture_is_buildable_and_the_check_writes_nothing(fx):
    before = tree(fx.root)
    report = fx.check()
    assert report.ok and report.problems == ()
    assert ensure_buildable(fx.story, facts=fx.facts, resolved=fx.resolved, store=fx.store).ok
    assert tree(fx.root) == before


def test_an_invalid_anchor_names_the_board_the_legacy_shot_and_the_field(fx):
    def change(document):
        board(document, 9)["cues"][0]["anchor"]["at_ms"] = 60000  # past the board's end
        vote = board(document, 8)["cues"][1]["anchor"]
        vote["after_line_id"] = "lin_01M79V9FC000000000000000ZZ"  # not a line of the board
    report = fx.check(fx.story_with(change))
    assert summary(report) == [
        ("cue.anchor_line_missing", 8, 8, "/cues/1/anchor/after_line_id"),
        ("cue.out_of_range", 9, 9, "/cues/0/anchor/at_ms"),
    ]
    problem = report.blocking[1]
    assert problem.board_id == "brd_01M79V9FC00000000000000009"
    assert problem.path == "/boards/8/cues/0/anchor/at_ms"
    assert str(problem).startswith(
        "board B09 (brd_01M79V9FC00000000000000009, legacy shot 9) field /cues/0/anchor/at_ms: "
        "cue.out_of_range (invalid): ")


def test_a_missing_cue_sound_fails_whether_unresolved_or_absent_from_the_store(fx):
    absent = sha(b"a sound that was never published")
    resolved = {**fx.resolved,
                SOUND_7: ResolvedVersion.of(absent, blob_locator("library", absent, "audio/wav"))}
    del resolved[SOUND_9]
    report = fx.check(resolved=resolved)
    assert summary(report) == [
        (BLOB_MISSING, 7, 7, "/cues/0/asset_version_id"),
        (ASSET_UNRESOLVED, 9, 9, "/cues/0/asset_version_id"),
    ]
    missing = report.blocking[0]
    assert (missing.asset_version_id, missing.locator, missing.status) == (
        SOUND_7, blob_locator("library", absent, "audio/wav"), "failed")
    assert "legacy shot 7" in str(missing) and "/cues/0/asset_version_id" in str(missing)


def test_a_wrong_hash_fails_on_damaged_bytes_and_on_a_mismatched_locator(fx):
    damaged = fx.resolved[SOUND_9].blobs[0]
    path = fx.root / damaged.locator
    path.chmod(0o644)
    plant(fx.root, damaged.locator, b"damaged bytes")
    other = sha(b"another sound")
    resolved = {**fx.resolved,
                SOUND_7: ResolvedVersion.of(other, fx.resolved[SOUND_7].blobs[0].locator)}
    report = fx.check(resolved=resolved)
    assert summary(report) == [
        (LOCATOR_INVALID, 7, 7, "/cues/0/asset_version_id"),
        (HASH_MISMATCH, 9, 9, "/cues/0/asset_version_id"),
    ]
    assert "names another hash" in report.blocking[0].message


def test_every_problem_is_reported_and_no_renderer_is_called(fx):
    rendered = []
    story = fx.story_with(lambda d: board(d, 9)["cues"][0]["anchor"].update(at_ms=60000))
    resolved = {k: v for k, v in fx.resolved.items() if k not in (SOUND_7, BED)}
    started = time.perf_counter()
    with pytest.raises(PreflightError) as caught:
        ensure_buildable(story, facts=fx.facts, resolved=resolved, store=fx.store, source="r4")
        rendered.append("render")  # a build's first renderer call comes after the check
    assert time.perf_counter() - started < LIMIT_S
    assert rendered == []
    assert summary(caught.value.report) == [
        (ASSET_UNRESOLVED, None, None, "/beds/0/asset_version_id"),
        (ASSET_UNRESOLVED, 7, 7, "/cues/0/asset_version_id"),
        ("cue.out_of_range", 9, 9, "/cues/0/anchor/at_ms"),
    ]
    text = str(caught.value)
    assert "r4: story field /beds/0/asset_version_id: asset.unresolved" in text
    assert "board B07 (brd_01M79V9FC00000000000000007, legacy shot 7) field /cues/0/" in text


def test_the_queue_run_validation_is_called_with_the_facts(fx):
    report = fx.check(facts=NO_FACTS)  # no facts: every voice is absent (fail closed)
    spoken = [b.number for b in fx.story.boards if b.lines]
    assert [(p.rule, p.board_number, p.field) for p in report.blocking] == [
        ("voice.absent", number, "/voice/current_version_id") for number in spoken]


def test_locators_outside_the_layout_or_the_production_are_refused(fx):
    still = fx.resolved["asv_01M79V9FC00000000000000001"].blobs[0]
    photo = fx.resolved[fx.story.boards[0].photo.current_version_id].blobs[0]
    resolved = {
        **fx.resolved,
        "asv_01M79V9FC00000000000000001": ResolvedVersion.of(still.sha256, "../../etc/passwd"),
        fx.story.boards[0].photo.current_version_id: ResolvedVersion.of(
            photo.sha256, photo.locator.replace(fx.story.production_id, PRD_OTHER)),
    }
    report = fx.check(resolved=resolved)
    rules = {(p.rule, p.board_number, p.field) for p in report.blocking}
    assert (LOCATOR_INVALID, 1, "/cast/0/asset_version_id") in rules
    assert (LOCATOR_INVALID, 1, "/photo/current_version_id") in rules
    assert {p.rule for p in report.blocking} == {LOCATOR_INVALID}


def test_bytes_are_needed_except_for_stock_voices(fx):
    resolved = {**fx.resolved, SOUND_7: DEFINITION_ONLY}
    assert summary(fx.check(resolved=resolved)) == [(BLOB_MISSING, 7, 7, "/cues/0/asset_version_id")]
    voices = [member.voice_version_id for member in fx.story.cast]
    assert all(fx.resolved[voice] == DEFINITION_ONLY for voice in voices)


def test_a_story_without_embedded_boards_cannot_be_checked(fx):
    import dataclasses
    report = fx.check(dataclasses.replace(fx.story, boards=None))
    assert ("schema.invalid", "/boards") in {(p.rule, p.field) for p in report.blocking}
