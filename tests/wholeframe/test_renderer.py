"""The whole-frame segment renderer (story 427): exact frames from the clip chain, or a
failure; every refusal tested. Decoded frames are compared, never encoded bytes.
"""

from __future__ import annotations

import hashlib
import io

import numpy as np
import pytest

from haynes_studio.cache import ArtifactCache, stage_name
from haynes_studio.cache.build import PictureBuilder
from haynes_studio.render.base import SegmentRequest
from haynes_studio.render.encode import EncoderSettings, decode_frames, encode_segment
from haynes_studio.render.synthetic import read_code
from haynes_studio.stages import completed_stage
from haynes_studio.store import canonical_json
from haynes_studio.wholeframe import WholeFrameClips, WholeFrameRenderer, fit_rule, production_reader
from haynes_studio.wholeframe.errors import (
    CLIP_INVALID,
    METHOD_UNAVAILABLE,
    SOURCE_SHORT,
    UNSUPPORTED,
    WholeFrameError,
)
from haynes_studio.wholeframe.fake import FakeClipSource, draw, marker
from tests.cache.fixtures import PRODUCTION
from tests.wholeframe import helpers as h


@pytest.fixture
def store(tmp_path):
    store = h.new_store(tmp_path / "store")
    h.publish_photos(store)
    return store


def make_clips(store, key, source=None) -> str:
    cache = ArtifactCache(store, production_id=PRODUCTION, run_id=h.RUN1)
    clips = WholeFrameClips(cache, source or FakeClipSource(),
                            read_photo=production_reader(store, "library", ("image/png",)))
    return clips(key)


def request(store, segment) -> SegmentRequest:
    return SegmentRequest(key=segment.value, inputs=segment.document,
                          open_input=production_reader(store, PRODUCTION))


def expected_codes(frames: int, clip: int, seed: int) -> list[tuple[int, int]]:
    """(frame within clip, marker) for board frames 0..F-1 of a chain of ``clip``-frame
    clips at 24 fps, written out independently of the chain module: clip 0 gives
    frames 0..clip-1, every later clip frames 1..clip-1."""
    out, index = [], 0
    while len(out) < frames:
        first = 0 if index == 0 else 1
        out += [(n, marker(index, seed + index)) for n in range(first, clip)]
        index += 1
    return out[:frames]


@pytest.mark.parametrize(("frames", "lengths"), [(20, (25,)), (46, (25, 25)), (73, (25, 25, 25))])
def test_disposable_clips_assemble_to_exactly_the_boards_frames(store, frames, lengths):
    clip_set = make_clips(store, h.clip_key(lengths=lengths))
    renderer = WholeFrameRenderer()
    segment = h.wf_segment(clip_set, frames)
    shown = [read_code(frame) for frame in renderer.render(request(store, segment))]
    assert shown == expected_codes(frames, 25, 31)  # each boundary duplicate dropped
    report = renderer.reports[segment.value]
    assert report.assembly.frames == frames and report.fit is None
    assert report.assembly.trimmed == 1 + 24 * len(lengths) - frames
    assert report.to_document()["assembly"]["clips"][-1]["trimmed"] == report.assembly.trimmed


def test_the_boundary_frame_is_shown_once(store):
    """The fake's clip 1 frame 0 is clip 0's decoded last frame: never shown twice."""
    clip_set = make_clips(store, h.clip_key())
    frames = list(WholeFrameRenderer().render(request(store, h.wf_segment(clip_set, 30))))
    codes = [read_code(frame) for frame in frames]
    assert codes[24] == (24, marker(0, 31)) and codes[25] == (1, marker(1, 32))
    assert all(a != b for a, b in zip(codes, codes[1:]))


def test_through_the_cache_the_segment_decodes_to_the_boards_frames(store):
    clip_set = make_clips(store, h.clip_key())
    cache = ArtifactCache(store, production_id=PRODUCTION, run_id=h.RUN2)
    builder = PictureBuilder(cache, WholeFrameRenderer(), open_input=production_reader(store, PRODUCTION))
    segment = h.wf_segment(clip_set, 46)
    made = builder.segment(segment)
    with store.open(made.blob.locator) as handle:
        decoded = [read_code(frame) for frame in decode_frames(handle.read())]
    assert decoded == expected_codes(46, 25, 31)


def test_a_same_aspect_clip_is_scaled_with_lanczos_and_another_aspect_refused(store):
    clip_set = make_clips(store, h.clip_key(profile={**h.PROFILE, "size": [180, 320]}))
    renderer = WholeFrameRenderer()
    segment = h.wf_segment(clip_set, 30)
    frames = list(renderer.render(request(store, segment)))
    assert len(frames) == 30 and frames[0].shape == (640, 360, 3) and frames[0].dtype == np.uint8
    assert [read_code(f) for f in frames] == expected_codes(30, 25, 31)
    assert renderer.reports[segment.value].fit == "lanczos"
    assert fit_rule((576, 1024), (1080, 1920)) == "lanczos" and fit_rule((360, 640), (360, 640)) is None
    with pytest.raises(WholeFrameError) as error:
        renderer.render(request(store, h.wf_segment(clip_set, 30, width=640, height=360)))
    assert error.value.code == UNSUPPORTED and "neither crops nor pads" in str(error.value)


def test_121_frame_clips_chain_for_a_board_past_one_clip(store):
    """The default policy with real 121-frame clips, small and scaled up 5x."""
    key = h.clip_key(lengths=(121, 121), profile={**h.PROFILE, "size": [72, 128]})
    clip_set = make_clips(store, key)
    shown = [read_code(f) for f in WholeFrameRenderer().render(request(store, h.wf_segment(clip_set, 144)))]
    assert shown == expected_codes(144, 121, 31)


@pytest.mark.parametrize(("override", "code"), [
    ({"method": {"layer": "whole_frame", "motion": "s2v"}}, METHOD_UNAVAILABLE),
    ({"method": {"layer": "layered", "motion": "i2v"}}, UNSUPPORTED),
    ({"cues": [{"type": "camera", "start_ms": 0, "duration_ms": 350, "zoom_from": 1.0,
                "zoom_to": 1.1, "center_px": [180, 320], "easing": "ease_out_cubic"}]}, UNSUPPORTED),
    ({"cues": [{"type": "move", "slot": "a", "start_ms": 0, "duration_ms": 0, "dx_px": 4,
                "dy_px": 0, "angle_deg": 0, "steps": 3}]}, UNSUPPORTED),
    ({"layout": {"height": 420}}, UNSUPPORTED),
    ({"layers": [{"slot": "a", "still": "1" * 64, "clip": None, "keyed": None, "phase": None}]}, UNSUPPORTED),
    ({"set_layer": {"plate": "2" * 64, "loop": None, "phase": None}}, UNSUPPORTED),
    ({"motion_style": {"talk_hop": 34}}, UNSUPPORTED),
    ({"foreground": {"edge_px": [[0, 1]], "feather_px": 2}}, UNSUPPORTED),
    ({"fps": 25}, UNSUPPORTED),
    ({"whole_frame_clip": None}, SOURCE_SHORT),
])
def test_unsupported_input_fails_and_is_never_ignored(store, override, code):
    clip_set = make_clips(store, h.clip_key())
    with pytest.raises(WholeFrameError) as error:
        WholeFrameRenderer().render(request(store, h.wf_segment(clip_set, 30, **override)))
    assert error.value.code == code


def test_an_unknown_segment_input_fails(store):
    clip_set = make_clips(store, h.clip_key())
    segment = h.wf_segment(clip_set, 30)
    inputs = {**segment.document, "sparkle": 1}
    with pytest.raises(WholeFrameError) as error:
        WholeFrameRenderer().render(SegmentRequest(key=segment.value, inputs=inputs,
                                                   open_input=production_reader(store, PRODUCTION)))
    assert error.value.code == UNSUPPORTED and "sparkle" in str(error.value)


def test_the_voice_envelope_and_talk_are_accepted_and_draw_nothing(store):
    clip_set = make_clips(store, h.clip_key())
    plain = h.wf_segment(clip_set, 30)
    spoken = h.wf_segment(clip_set, 30, voice_envelope="3" * 64,
                          talk=[{"speaker": "a", "start_ms": 500, "end_ms": 900}])
    a = list(WholeFrameRenderer().render(request(store, plain)))
    b = list(WholeFrameRenderer().render(request(store, spoken)))
    assert all(np.array_equal(x, y) for x, y in zip(a, b)) and len(a) == len(b) == 30


def test_a_chain_shorter_than_the_board_fails_before_any_frame(store):
    clip_set = make_clips(store, h.clip_key(lengths=(25,)))
    with pytest.raises(WholeFrameError) as error:
        WholeFrameRenderer().render(request(store, h.wf_segment(clip_set, 26)))
    assert error.value.code == SOURCE_SHORT and error.value.status == "failed"


def test_a_missing_clip_fails_the_stage_and_commits_nothing(store, tmp_path):
    clip_set = make_clips(store, h.clip_key())
    document = h.parse(store, clip_set)
    h.blob(store, document["clips"][1]["sha256"]).rename(tmp_path / "gone.mp4")
    cache = ArtifactCache(store, production_id=PRODUCTION, run_id=h.RUN2)
    builder = PictureBuilder(cache, WholeFrameRenderer(), open_input=production_reader(store, PRODUCTION))
    segment = h.wf_segment(clip_set, 46)
    with pytest.raises(WholeFrameError) as error:
        builder.segment(segment)
    assert error.value.code == SOURCE_SHORT and "clip 1 is missing" in str(error.value)
    assert cache.stats.made == [] and builder.rendered == []
    assert completed_stage(store, production_id=PRODUCTION, run_id=h.RUN2, stage=stage_name(segment)) is None


def test_a_clip_that_decodes_short_fails_mid_render_and_commits_nothing(store):
    """A clip set that records more frames than its clip decodes to (made by hand here):
    the render fails at the gap, so the encoder never finishes and nothing commits."""
    honest = make_clips(store, h.clip_key(lengths=(25,)))
    document = h.parse(store, honest)
    # Point the record at a 20-frame clip while it still says 25 were delivered.
    data = encode_segment((draw(0, 31, n, 360, 640) for n in range(20)), frames_expected=20,
                          width=360, height=640, fps=24, settings=EncoderSettings())
    store.publish(data, scope=PRODUCTION, media_type="video/mp4")
    document["clips"][0].update(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
    forged = canonical_json(document)
    blob = store.publish(forged, scope=PRODUCTION, media_type="application/json")
    cache = ArtifactCache(store, production_id=PRODUCTION, run_id=h.RUN2)
    builder = PictureBuilder(cache, WholeFrameRenderer(), open_input=production_reader(store, PRODUCTION))
    with pytest.raises(WholeFrameError) as error:
        builder.segment(h.wf_segment(blob.sha256, 24))
    assert error.value.code == SOURCE_SHORT and "decodes to 20 frames" in str(error.value)
    assert cache.stats.made == [] and builder.rendered == []


def test_a_clip_set_that_is_not_its_hash_fails(store):
    clip_set = make_clips(store, h.clip_key())
    path = h.blob(store, clip_set, "application/json")
    path.chmod(0o644)
    path.write_bytes(path.read_bytes().replace(b'"seed":31', b'"seed":32'))
    with pytest.raises(Exception) as error:
        WholeFrameRenderer().render(request(store, h.wf_segment(clip_set, 30)))
    assert getattr(error.value, "code", None) == "store.hash_mismatch"


def test_a_clip_set_with_clips_of_two_sizes_is_refused(store):
    clip_set = make_clips(store, h.clip_key())
    document = h.parse(store, clip_set)
    document["clips"][1]["width"] = 180
    blob = store.publish(canonical_json(document), scope=PRODUCTION, media_type="application/json")
    with pytest.raises(WholeFrameError) as error:
        WholeFrameRenderer().render(request(store, h.wf_segment(blob.sha256, 30)))
    assert error.value.code == CLIP_INVALID


def test_a_request_without_an_input_reader_cannot_hide_a_missing_clip(store):
    segment = h.wf_segment("4" * 64, 30)
    with pytest.raises(WholeFrameError) as error:
        WholeFrameRenderer().render(SegmentRequest(key=segment.value, inputs=segment.document))
    assert error.value.code == SOURCE_SHORT


def test_io_is_not_needed_for_a_refusal():
    with pytest.raises(WholeFrameError):
        WholeFrameRenderer().render(SegmentRequest(key="k", inputs=h.wf_segment(
            "5" * 64, 30, method={"layer": "layered", "motion": "s2v"}).document,
            open_input=lambda sha: io.BytesIO(b"")))
