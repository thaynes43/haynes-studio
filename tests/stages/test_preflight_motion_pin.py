"""The cast entry's motion pin is a reference of the pre-build check (story 406): a
board that pins its still's loop must have that version resolved and its clip in the
store, like every other blob a build reads."""

from __future__ import annotations

from haynes_studio.stages import ResolvedVersion
from haynes_studio.store import blob_locator
from tests.stages.test_preflight import board, fx  # noqa: F401 - the shared fixture

PIN = "asv_01M79V9FC00000000000000099"


def pinned(document: dict) -> None:
    board(document, 1)["cast"][0]["motion_asset_version_id"] = PIN


def test_an_unresolved_motion_pin_is_reported_on_its_board_and_field(fx):  # noqa: F811
    report = fx.check(fx.story_with(pinned))
    problems = [(p.rule, p.board_number, p.field, p.asset_version_id) for p in report.blocking]
    assert problems == [("asset.unresolved", 1, "/cast/0/motion_asset_version_id", PIN)]


def test_a_motion_pin_whose_clip_is_not_in_the_store_is_missing(fx):  # noqa: F811
    blob = fx.store.publish(b"a synthetic loop", scope=fx.story.production_id, media_type="video/mp4")
    missing = blob_locator(fx.story.production_id, "0" * 64, "video/mp4")
    resolved = {**fx.resolved, PIN: ResolvedVersion.of("0" * 64, missing)}
    report = fx.check(fx.story_with(pinned), resolved=resolved)
    assert [(p.rule, p.field) for p in report.blocking] == [
        ("store.blob_missing", "/cast/0/motion_asset_version_id")]
    resolved[PIN] = ResolvedVersion.of(blob.sha256, blob.locator)
    assert fx.check(fx.story_with(pinned), resolved=resolved).ok
