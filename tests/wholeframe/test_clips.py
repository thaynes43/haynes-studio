"""Whole-frame clips as one cached artifact (story 427): made once, checked, reused.

Clips come from the fake source (25 frames at 360x640, two threads), under tmp_path.
"""

from __future__ import annotations

import hashlib

import pytest

from haynes_studio.cache import ArtifactCache, stage_name
from haynes_studio.cache.keys import WHOLE_FRAME_CLIP
from haynes_studio.jsonio import parse_strict
from haynes_studio.stages import completed_stage
from haynes_studio.store import HASH_MISMATCH, StoreError
from haynes_studio.wholeframe import WholeFrameClips, chain_seed, last_frame_png, production_reader
from haynes_studio.wholeframe.errors import (
    CHAIN_LIMIT,
    CLIP_INVALID,
    SOURCE_SHORT,
    UNSUPPORTED,
    WholeFrameError,
)
from haynes_studio.wholeframe.fake import ENGINE, FILES, FakeClipSource
from tests.cache.fixtures import PHOTO_3, PRODUCTION
from tests.wholeframe import helpers as h


@pytest.fixture
def store(tmp_path):
    store = h.new_store(tmp_path / "store")
    h.publish_photos(store)
    return store


def stage(store, source=None, run_id=h.RUN1, earlier=()):
    cache = ArtifactCache(store, production_id=PRODUCTION, run_id=run_id, earlier_runs=earlier)
    clips = WholeFrameClips(cache, source or FakeClipSource(),
                            read_photo=production_reader(store, "library", ("image/png",)))
    return clips, cache


def clip_set(store, sha256):
    return parse_strict(h.blob(store, sha256, "application/json").read_text())


def test_a_miss_makes_the_chain_once_and_records_each_clips_provenance(store):
    source = FakeClipSource()
    clips, cache = stage(store, source)
    key = h.clip_key()
    made = clips.clips(key)
    assert not made.hit and len(source.calls) == 1 and clips.made == [key.value]
    request = source.calls[0]
    assert request.clip_lengths == (25, 25) and [c.seed for c in request.clips] == [31, 32]
    record = completed_stage(store, production_id=PRODUCTION, run_id=h.RUN1, stage=stage_name(key))
    assert set(record.blobs) == {WHOLE_FRAME_CLIP, "inputs"}
    document = clip_set(store, made.sha256)
    photo = hashlib.sha256(h.PHOTOS[PHOTO_3]).hexdigest()
    assert document["key"] == key.value and document["photo"] == {"sha256": photo}
    assert document["clip_lengths"] == [25, 25] and document["source_fps"] == 24
    first, second = document["clips"]
    clip_bytes = [h.blob(store, c["sha256"]).read_bytes() for c in (first, second)]
    for index, (clip, data) in enumerate(zip((first, second), clip_bytes)):
        assert clip["sha256"] == hashlib.sha256(data).hexdigest() and clip["bytes"] == len(data)
        assert clip["index"] == index and clip["seed"] == chain_seed(31, index)
        assert clip["engine"] == ENGINE and clip["engine_job_id"] and clip["files_sha256"] == FILES
        assert clip["profile"] == h.PROFILE
        assert clip["frames_requested"] == clip["frames_delivered"] == 25
        assert (clip["width"], clip["height"]) == (360, 640)
    assert first["start_image"] == {"role": "photo", "sha256": photo}
    png = last_frame_png(clip_bytes[0])
    assert second["start_image"] == {"role": "previous_last_frame",
                                     "sha256": hashlib.sha256(png).hexdigest(), "media_type": "image/png"}
    assert h.blob(store, second["start_image"]["sha256"], "image/png").read_bytes() == png


def test_a_hit_in_a_later_run_asks_the_source_for_nothing(store):
    first, _ = stage(store)
    made = first.clips(h.clip_key())
    source = FakeClipSource()
    second, cache = stage(store, source, run_id=h.RUN2, earlier=(h.RUN1,))
    found = second.clips(h.clip_key())
    assert found.hit and found.sha256 == made.sha256
    assert source.calls == [] and second.made == [] and cache.stats.made == []


def test_another_seed_or_length_is_another_artifact(store):
    clips, _ = stage(store)
    a = clips.clips(h.clip_key(lengths=(25,)))
    b = clips.clips(h.clip_key(lengths=(25,), seed=32))
    c = clips.clips(h.clip_key(lengths=(25, 25)))
    assert len({a.sha256, b.sha256, c.sha256}) == 3 and len(clips.made) == 3


@pytest.mark.parametrize(("source", "code"), [
    (FakeClipSource(deliver={1: 20}), SOURCE_SHORT),  # a short clip
    (FakeClipSource(omit=frozenset({1})), SOURCE_SHORT),  # a missing clip
    (FakeClipSource(deliver={0: 27}), CLIP_INVALID),  # more frames than asked
    (FakeClipSource(start_sha256={1: "0" * 64}), CLIP_INVALID),  # not chained on the last frame
    (FakeClipSource(start_sha256={0: "1" * 64}), CLIP_INVALID),  # not started on the photo
])
def test_a_bad_answer_fails_and_publishes_nothing(store, source, code):
    clips, cache = stage(store, source)
    key = h.clip_key()
    with pytest.raises(WholeFrameError) as error:
        clips.clips(key)
    assert error.value.code == code
    assert completed_stage(store, production_id=PRODUCTION, run_id=h.RUN1, stage=stage_name(key)) is None
    assert cache.stats.made == []
    assert not list((h.blob(store, "0" * 64).parent.parent).glob("*/*.mp4"))  # no clip published


def test_a_clip_of_another_size_fails(store):
    profile = {**h.PROFILE, "size": [180, 320]}
    source = FakeClipSource()
    clips, _ = stage(store, source)
    original = source.generate

    def generate(request):  # answer the asked request with clips of the default size
        return original(type(request)(**{**request.__dict__, "profile": h.PROFILE}))
    source.generate = generate
    with pytest.raises(WholeFrameError) as error:
        clips.clips(h.clip_key(profile=profile))
    assert error.value.code == CLIP_INVALID and "360x640" in str(error.value)


@pytest.mark.parametrize(("change", "code"), [
    ({"adapter": "studio.i2v/9"}, UNSUPPORTED),
    ({"source_fps": 0}, UNSUPPORTED),
    ({"size": [361, 640]}, UNSUPPORTED),
])
def test_a_profile_the_adapter_cannot_serve_is_refused_before_the_source(store, change, code):
    source = FakeClipSource()
    clips, _ = stage(store, source)
    with pytest.raises(WholeFrameError) as error:
        clips.clips(h.clip_key(profile={**h.PROFILE, **change}))
    assert error.value.code == code and source.calls == []


def test_a_chain_past_the_limit_is_refused_before_the_source(store):
    source = FakeClipSource()
    clips, _ = stage(store, source)
    with pytest.raises(WholeFrameError) as error:
        clips.clips(h.clip_key(lengths=(25,) * 4))
    assert error.value.code == CHAIN_LIMIT and source.calls == []


def test_a_hit_whose_clip_is_missing_fails_closed(store, tmp_path):
    first, _ = stage(store)
    made = first.clips(h.clip_key())
    lost = clip_set(store, made.sha256)["clips"][1]["sha256"]
    path = h.blob(store, lost)
    path.rename(tmp_path / "moved-away.mp4")  # a test removing a blob by hand, outside the store
    second, _ = stage(store, run_id=h.RUN2, earlier=(h.RUN1,))
    with pytest.raises(WholeFrameError) as error:
        second.clips(h.clip_key())
    assert error.value.code == SOURCE_SHORT and "clip 1 is missing" in str(error.value)


def test_a_hit_whose_clip_is_damaged_fails_closed(store):
    first, _ = stage(store)
    made = first.clips(h.clip_key())
    damaged = h.blob(store, clip_set(store, made.sha256)["clips"][0]["sha256"])
    damaged.chmod(0o644)
    damaged.write_bytes(damaged.read_bytes()[:-10])
    second, _ = stage(store, run_id=h.RUN2, earlier=(h.RUN1,))
    with pytest.raises(StoreError) as error:
        second.clips(h.clip_key())
    assert error.value.code == HASH_MISMATCH


def test_a_photo_that_is_not_its_hash_is_never_sent(store, tmp_path):
    source = FakeClipSource()
    clips, _ = stage(store, source)
    with pytest.raises(StoreError):
        clips.clips(h.clip_key(photo=b"a photo the store does not hold"))
    assert source.calls == []
