"""The chroma key, the tracked decal and the keyed artifact (story 426), on synthetic
dolls drawn in memory: pixel facts, never encoded bytes across builds."""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from haynes_studio.cache.keys import keyed_frames_key
from haynes_studio.layered import keyed, keying
from haynes_studio.layered.errors import CLIP_INVALID, SOURCE_SHORT, UNSUPPORTED, LayeredError
from haynes_studio.render.encode import decode_frames
from tests.layered import media


def key_of(clip: bytes, still: bytes, *, protect=(media.PROTECT,), decal=True, **changes):
    inputs = dict(clip=hashlib.sha256(clip).hexdigest(), still=hashlib.sha256(still).hexdigest(),
                  key_thresholds={"lo": 20, "hi": 70}, protect_boxes=[list(b) for b in protect],
                  decal_box=list(media.DECAL_BOX) if decal else None,
                  decal_version="erase-v2" if decal else None, keyer="legacy:poc/cutout.py key")
    inputs.update(changes)
    return keyed_frames_key(**inputs)


def make(clip: bytes, **kwargs):
    still = media.start_image()
    key = key_of(clip, still, **kwargs)
    data = keyed.make_keyed(key, keyed.check_settings(key.document), clip, still)
    record = keyed.read_record(data)
    return data, record, list(keyed.read_frames(data, record))


def alpha_at(frames, record, x, y, n=0):
    return int(frames[n][y - record["box"][1], x - record["box"][0], 3])


def test_the_key_clears_the_green_and_keeps_the_doll():
    frame = media.doll_frame(0, garble=False)
    rgba = keying.key(frame, 20, 70, [media.PROTECT])
    assert rgba[2, 2, 3] == 0 and rgba[-2, -2, 3] == 0  # the green field is transparent
    assert rgba[140, 50, 3] == 255  # the jacket is opaque
    assert rgba[131, 72, 3] == 255  # the protected green badge stays solid
    assert keying.key(frame, 20, 70)[131, 72, 3] == 0  # without the box it is keyed away


def test_the_decal_follows_a_known_motion_and_scores_a_clean_track():
    data, record, frames = make(media.doll_clip(12, garble=False))
    assert record["decal"]["failed_frames"] == 0 and record["decal"]["min_ecc"] >= 0.99
    assert len(record["decal"]["scores"]) == 11  # frame 0 is the template
    def left(frame):  # the leftmost lettering pixel (red and not blue: yellow, despilled or not)
        letters = (frame[..., 0] > 200) & (frame[..., 2] < 100) & (frame[..., 3] > 200)
        return int(np.nonzero(letters)[1].min())
    for n in (3, 6, 9):
        assert abs(left(frames[n]) - left(frames[0]) - media.sway(n)) <= 1, n


def test_the_engines_own_lettering_is_erased_under_the_decal():
    _, record, frames = make(media.doll_clip(6, garble=True))
    assert record["decal"]["min_ecc"] >= keying.MIN_ECC
    # The garble's solid yellow block (x 46..72, y 152..170 at frame 3) is inpainted:
    # only the still's letters, a few pixels wide, are yellow there.
    block = frames[3][155 - record["box"][1]:168 - record["box"][1], 60 - record["box"][0]:66 - record["box"][0]]
    yellow = (block[..., 0] > 200) & (block[..., 1] > 170) & (block[..., 2] < 100)
    assert yellow.mean() < 0.6


def test_a_weak_track_is_scored_below_the_floor_and_the_gate_says_so():
    _, record, _ = make(media.doll_clip(8, weak=True))
    summary = {k: record["decal"][k] for k in ("frames_tracked", "failed_frames", "min_ecc", "mean_ecc")}
    assert summary["min_ecc"] < keying.MIN_ECC
    assert not keying.gate(summary, keying.MIN_ECC)
    assert keying.gate(summary, summary["min_ecc"])  # a record may allow it
    assert not keying.gate({**summary, "failed_frames": 1}, 0.0)  # a failed frame never passes


def test_summarize_counts_failed_frames_and_never_hides_them():
    assert keying.summarize([0.9, None, 0.8]) == {"frames_tracked": 2, "failed_frames": 1,
                                                  "min_ecc": 0.8, "mean_ecc": 0.85}
    assert keying.summarize([None]) == {"frames_tracked": 0, "failed_frames": 1, "min_ecc": None,
                                        "mean_ecc": None}


def test_the_keyed_artifact_is_one_lossless_png_with_its_record():
    clip = media.doll_clip(5)
    data, record, frames = make(clip)
    assert data.startswith(b"\x89PNG") and record["frames"] == 5 == len(frames)
    assert record["clip_size"] == [media.CLIP_W, media.CLIP_H]
    assert record["tools"] == keyed.tool_builds()
    again, _, _ = make(clip)
    assert again == data  # the same frames give the same bytes in one build
    # Lossless: what is read back is exactly what was keyed and cropped.
    still = keyed.still_rgb(media.start_image(), (media.CLIP_W, media.CLIP_H))
    decoded = list(decode_frames(clip))
    for n, (fixed, _) in enumerate(keying.decal_frames(still, decoded, media.DECAL_BOX)):
        x0, y0, x1, y1 = record["box"]
        assert np.array_equal(frames[n], keying.key(fixed, 20, 70, [media.PROTECT])[y0:y1, x0:x1])


def test_a_damaged_or_short_keyed_artifact_fails():
    data, record, _ = make(media.doll_clip(4))
    with pytest.raises(LayeredError) as short:
        keyed.frame_pngs(data, {**record, "frames": 5})
    assert short.value.code == SOURCE_SHORT
    with pytest.raises(LayeredError) as extra:
        keyed.frame_pngs(data, {**record, "frames": 3})
    assert extra.value.code == CLIP_INVALID
    with pytest.raises(LayeredError) as cut:
        keyed.frame_pngs(data[:len(data) // 2], record)
    assert cut.value.code == CLIP_INVALID
    with pytest.raises(LayeredError) as other:
        keyed.read_record(media.start_image())
    assert other.value.code == CLIP_INVALID


def test_unsupported_key_settings_are_refused_before_anything_is_read():
    still = media.start_image()
    clip = media.doll_clip(2)
    refused = [
        key_of(clip, still, keyer="studio.keyer/9"),
        key_of(clip, still, key_thresholds={"lo": 70, "hi": 20}),
        key_of(clip, still, key_thresholds={"green": 0.4}),
        key_of(clip, still, decal_box=None, decal_version="erase-v2"),
        key_of(clip, still, decal_version="erase-v1"),
        key_of(clip, still, protect=([1, 2, 3],)),
    ]
    for key in refused:
        with pytest.raises(LayeredError) as error:
            keyed.check_settings(key.document)
        assert error.value.code == UNSUPPORTED, key.document


def test_a_decal_box_outside_the_clip_is_refused():
    still = media.start_image()
    clip = media.doll_clip(2)
    key = key_of(clip, still, decal_box=[100, 100, 400, 120])
    with pytest.raises(LayeredError) as error:
        keyed.make_keyed(key, keyed.check_settings(key.document), clip, still)
    assert error.value.code == UNSUPPORTED


def test_a_clip_that_does_not_decode_or_keys_to_nothing_fails():
    still = media.start_image()
    with pytest.raises(LayeredError) as broken:
        make(b"not a clip at all")
    assert broken.value.code == CLIP_INVALID
    green = media.encode([np.full((media.CLIP_H, media.CLIP_W, 3), media.GREEN, np.uint8)] * 2, 24)
    key = key_of(green, still, decal=False)
    with pytest.raises(LayeredError) as empty:
        keyed.make_keyed(key, keyed.check_settings(key.document), green, None)
    assert empty.value.code == CLIP_INVALID


def test_no_decal_box_keys_without_tracking():
    clip = media.doll_clip(3)
    still = media.start_image()
    key = key_of(clip, still, decal=False)
    record = keyed.read_record(keyed.make_keyed(key, keyed.check_settings(key.document), clip, None))
    assert record["decal"] is None and record["frames"] == 3
