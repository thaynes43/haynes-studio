"""Drive tracks (TIME-9) and speech-to-video clips through the cache (story 426): what
is asked of the source, what is checked, what is committed, and every refusal."""

from __future__ import annotations

import io
import wave
from dataclasses import replace

import numpy as np
import pytest

from haynes_studio.cache import ArtifactCache, stage_name
from haynes_studio.cache.keys import s2v_clip_key, s2v_drive_track_key
from haynes_studio.layered import FakeS2VSource, reader
from haynes_studio.layered.drive import DriveTracks, assemble_drive, drive_samples, track_frames
from haynes_studio.layered.errors import (
    CLIP_INVALID,
    DRIVE_INVALID,
    SOURCE_SHORT,
    UNSUPPORTED,
    LayeredError,
)
from haynes_studio.layered.s2v import S2VClips, read_provenance, record_stage
from haynes_studio.render.clock import s2v_request_frames, source_frames_needed
from haynes_studio.stages import completed_stage
from haynes_studio.store import LocalStore
from tests.cache.fixtures import PRODUCTION
from tests.layered import helpers as h
from tests.layered import media

PROFILE = {**h.S2V_PROFILE, "delivery": {"aspect": "9:16", "fps": 24}}


@pytest.fixture
def store(tmp_path) -> LocalStore:
    path = tmp_path / "store"
    path.mkdir()
    return LocalStore(path)


def publish(store, data, media_type):
    return store.publish(data, scope=PRODUCTION, media_type=media_type).sha256


def samples(data: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(data), "rb") as track:
        assert (track.getnchannels(), track.getsampwidth(), track.getframerate()) == (1, 2, 24_000)
        return np.frombuffer(track.readframes(track.getnframes()), dtype="<i2")


def drive_key(lines, frames=40, rate=24_000, assembler="studio.s2v.drive/1"):
    return s2v_drive_track_key(speaker="b", lines=lines, frames=frames, fps=24, rate=rate,
                               assembler=assembler)


def test_a_drive_track_is_her_takes_at_their_starts_and_exactly_the_board(store):
    first, second = media.take(400), media.take(300, seed=1)
    takes = {publish(store, first, "audio/wav"): first, publish(store, second, "audio/wav"): second}
    shas = list(takes)
    key = drive_key([(shas[0], 100), (shas[1], 900)], frames=40)
    track = samples(assemble_drive(key.document, takes))
    assert track.size == 40 * 1000  # F / 24 s at 24 kHz, exactly (TIME-9)
    assert not track[:100 * 24].any() and track[100 * 24:500 * 24].any()
    assert not track[500 * 24:900 * 24].any() and track[900 * 24:1200 * 24].any()
    assert not track[1200 * 24:].any()  # silence after her last line, to the board's end
    assert track_frames(assemble_drive(key.document, takes)) == (40, 24_000)


def test_a_drive_track_never_resamples_cuts_or_pads(store):
    take = media.take(400)
    sha = publish(store, take, "audio/wav")
    with pytest.raises(LayeredError) as rate:
        drive_samples(40, 24, 16_000)  # 40 / 24 s is not whole samples at 16 kHz
    assert rate.value.code == DRIVE_INVALID
    assert drive_samples(39, 24, 16_000) == 26_000  # it is when 3 divides F
    other = media.take(400, rate=16_000)
    with pytest.raises(LayeredError) as resample:
        assemble_drive(drive_key([(sha, 0)]).document, {sha: other})
    assert resample.value.code == DRIVE_INVALID
    with pytest.raises(LayeredError) as late:
        assemble_drive(drive_key([(sha, 1500)], frames=40).document, {sha: take})
    assert late.value.code == DRIVE_INVALID
    with pytest.raises(LayeredError) as noise:
        assemble_drive(drive_key([(sha, 0)]).document, {sha: b"RIFF nonsense"})
    assert noise.value.code == DRIVE_INVALID


def test_the_drive_stage_commits_once_and_refuses_another_assembler(store):
    take = media.take(400)
    sha = publish(store, take, "audio/wav")
    run1, run2 = h.RUN[1], h.RUN[2]
    read = reader(store, [PRODUCTION])
    stage = DriveTracks(ArtifactCache(store, production_id=PRODUCTION, run_id=run1), read_take=read)
    key = drive_key([(sha, 0)])
    made = stage(key)
    again = DriveTracks(ArtifactCache(store, production_id=PRODUCTION, run_id=run2, earlier_runs=[run1]),
                        read_take=read)
    assert again(key) == made and again.made == [] and stage.made == [key.value]
    with pytest.raises(LayeredError) as other:
        stage(drive_key([(sha, 0)], assembler="studio.s2v.drive/2"))
    assert other.value.code == UNSUPPORTED


def s2v_world(store):
    """A drive track for a 40-frame board and a start image, published."""
    take = media.take(400)
    take_sha = publish(store, take, "audio/wav")
    key = drive_key([(take_sha, 100)])
    drive = publish(store, assemble_drive(key.document, {take_sha: take}), "audio/wav")
    start = publish(store, media.start_image(), "image/png")
    return drive, start


def clip_key(drive, start, *, seed=7, profile=PROFILE, adapter="studio.s2v/1"):
    return s2v_clip_key(drive_track=drive, start_still=start, prompt="a doll talks",
                        negative_prompt="", seed=seed, profile=profile, adapter=adapter)


def clips(store, source, run=h.RUN[1], earlier=()):
    read = reader(store, [PRODUCTION])
    return S2VClips(ArtifactCache(store, production_id=PRODUCTION, run_id=run, earlier_runs=earlier),
                    source, read_drive=read, read_image=read)


def test_the_source_gets_time9s_request_and_the_clip_is_committed_with_its_record(store):
    drive, start = s2v_world(store)
    source = FakeS2VSource(draw=h.s2v_draw, extra=4)
    stage = clips(store, source)
    key = clip_key(drive, start)
    sha = stage(key)
    (request,) = source.calls
    assert request.board_frames == 40 and request.frames == s2v_request_frames(40) == 29
    assert request.frames_needed == source_frames_needed(40, 16) == 27
    assert (request.seed, request.start_image_sha256, request.drive_track_sha256) == (7, start, drive)
    assert request.profile["size"] == [media.CLIP_W, media.CLIP_H]
    record = completed_stage(store, production_id=PRODUCTION, run_id=h.RUN[1], stage=record_stage(sha))
    with store.open(record.blobs["record"].locator) as handle:
        provenance = read_provenance(handle.read())
    assert provenance["key"] == key.value and provenance["clip"]["sha256"] == sha
    assert provenance["clip"]["frames_delivered"] == 33 and provenance["clip"]["trimmed"] == 6
    assert provenance["clip"]["engine_job_id"].startswith("fake-")
    second = clips(store, FakeS2VSource(), run=h.RUN[2], earlier=[h.RUN[1]])
    assert second(key) == sha and second.made == [] and second.source.calls == []


@pytest.mark.parametrize("fault, code", [
    ({"deliver": 26}, SOURCE_SHORT),  # one frame fewer than TIME-8 needs: never held
    ({"seed": 8}, CLIP_INVALID),
    ({"size": (160, 256)}, CLIP_INVALID),
    ({"start_sha256": "1" * 64}, CLIP_INVALID),
    ({"drive_sha256": "2" * 64}, CLIP_INVALID),
    ({"data": b"not a clip"}, CLIP_INVALID),
])
def test_a_bad_answer_fails_and_publishes_nothing(store, fault, code):
    drive, start = s2v_world(store)
    stage = clips(store, FakeS2VSource(**fault))
    key = clip_key(drive, start)
    with pytest.raises(LayeredError) as error:
        stage(key)
    assert error.value.code == code
    assert completed_stage(store, production_id=PRODUCTION, run_id=h.RUN[1],
                           stage=stage_name(key)) is None


def test_a_profile_or_adapter_this_adapter_cannot_serve_is_refused_before_the_source(store):
    drive, start = s2v_world(store)
    source = FakeS2VSource()
    stage = clips(store, source)
    for key in (clip_key(drive, start, profile={**PROFILE, "chunk": 81}),
                clip_key(drive, start, profile={**PROFILE, "size": [256, 144]}),
                clip_key(drive, start, profile={**PROFILE, "source_fps": 0}),
                clip_key(drive, start, adapter="studio.s2v/2")):
        with pytest.raises(LayeredError) as error:
            stage(key)
        assert error.value.code == UNSUPPORTED
    assert source.calls == []


def test_a_missing_input_or_a_hit_without_its_record_fails(store):
    drive, start = s2v_world(store)
    with pytest.raises(LayeredError) as missing:
        clips(store, FakeS2VSource())(clip_key(drive, "3" * 64))
    assert missing.value.code == SOURCE_SHORT
    # A clip committed through the cache alone, with no provenance record: not a clip set.
    key = clip_key(drive, start, seed=9)
    stage = clips(store, FakeS2VSource())
    stage.cache.commit(key, media.doll_clip(30, fps=16), "video/mp4")
    with pytest.raises(LayeredError) as bare:
        clips(store, FakeS2VSource(), run=h.RUN[2], earlier=[h.RUN[1]])(key)
    assert bare.value.code == CLIP_INVALID


def test_a_source_without_engine_facts_fails(store):
    drive, start = s2v_world(store)

    class Anonymous(FakeS2VSource):
        def generate(self, request):
            return replace(super().generate(request), files_sha256={})
    with pytest.raises(LayeredError) as error:
        clips(store, Anonymous())(clip_key(drive, start))
    assert error.value.code == CLIP_INVALID
