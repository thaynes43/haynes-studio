"""Cache keys (contract section 4, P-07): canonical JSON, and one pure key function per
artifact in which every input matters."""

from __future__ import annotations

import builtins
import hashlib
import inspect
import json
import os
import unicodedata

import pytest

from haynes_studio.cache import keys
from haynes_studio.cache.errors import KEY_INPUT_INVALID, CacheError
from haynes_studio.cache.keys import INVENTORY, SCHEME, make_key


def h(n: int) -> str:
    return hashlib.sha256(str(n).encode()).hexdigest()


# One valid call per artifact, and for every input another valid value.
SAMPLES = {
    keys.VOICE_TAKE: (
        {"tts_model": "kokoro-82m-v1.0", "voice_id": "af_heart", "text": "Day one.", "speed": 1.0,
         "sample_rate": 24000},
        {"tts_model": "sha256:" + h(1), "voice_id": "am_adam", "text": "Day two.", "speed": 1.1,
         "sample_rate": 22050}),
    keys.BOARD_VOICE_TRACK: (
        {"takes": [h(1), h(2)], "lead_ms": 500, "gaps_ms": [300], "mix_rate": 48000,
         "assembler": "studio.voice.track/1"},
        {"takes": [h(1), h(3)], "lead_ms": 400, "gaps_ms": [310], "mix_rate": 44100,
         "assembler": "studio.voice.track/2"}),
    keys.S2V_DRIVE_TRACK: (
        {"speaker": "a", "lines": [(h(1), 500)], "frames": 78, "fps": 24, "rate": 16000,
         "assembler": "studio.s2v.drive/1"},
        {"speaker": "b", "lines": [(h(1), 510)], "frames": 79, "fps": 25, "rate": 16001,
         "assembler": "studio.s2v.drive/2"}),
    keys.S2V_CLIP: (
        {"drive_track": h(1), "start_still": h(2), "prompt": "talking", "negative_prompt": "",
         "seed": 1, "profile": {"steps": 4}, "adapter": "studio.s2v/1"},
        {"drive_track": h(3), "start_still": h(4), "prompt": "talking doll",
         "negative_prompt": "blur", "seed": 2, "profile": {"steps": 6}, "adapter": "studio.s2v/2"}),
    keys.MOTION_CLIP: (
        {"still": h(1), "prompt": "idle", "seed": 0, "profile": {"frames": 121}},
        {"still": h(2), "prompt": "idle doll", "seed": 1, "profile": {"frames": 81}}),
    keys.WHOLE_FRAME_CLIP: (
        {"photo": h(1), "prompt": "gentle", "seed": 3, "profile": {"fps": 24}, "clip_lengths": [121]},
        {"photo": h(2), "prompt": "gentle motion", "seed": 4, "profile": {"fps": 16},
         "clip_lengths": [121, 121]}),
    keys.KEYED_FRAMES: (
        {"clip": h(1), "still": h(2), "key_thresholds": {"green": 0.4}, "protect_boxes": [],
         "decal_box": None, "decal_version": None, "keyer": "studio.keyer/1"},
        {"clip": h(3), "still": h(4), "key_thresholds": {"green": 0.5},
         "protect_boxes": [[0, 0, 10, 10]], "decal_box": [1, 2, 3, 4], "decal_version": "v2",
         "keyer": "studio.keyer/2"}),
    keys.SEGMENT: (
        {"method": {"layer": "layered", "motion": "s2v"}, "frames": 78, "width": 360,
         "height": 640, "fps": 24, "layout": {"x": 0.5},
         "layers": [{"slot": "a", "still": h(1), "clip": h(2), "keyed": h(3), "phase": None}],
         "set_layer": {"plate": h(4), "loop": None, "phase": None}, "whole_frame_clip": None,
         "motion_style": {"talk_hop": 34}, "voice_envelope": h(5), "cues": [],
         "foreground": None, "procedural_stream": 1, "compositor": "c/1", "encoder": {"crf": 18}},
        {"method": {"layer": "layered", "motion": "i2v"}, "frames": 79, "width": 720,
         "height": 1280, "fps": 25, "layout": {"x": 0.6},
         "layers": [{"slot": "a", "still": h(1), "clip": h(2), "keyed": h(3), "phase": 7}],
         "set_layer": {"plate": h(6), "loop": None, "phase": None}, "whole_frame_clip": h(7),
         "motion_style": {"talk_hop": 40}, "voice_envelope": None,
         "cues": [{"type": "camera", "start_ms": 0}], "foreground": {"edge_px": [[0, 1]]},
         "procedural_stream": 2, "compositor": "c/2", "encoder": {"crf": 20}}),
    keys.FILM_PICTURE: (
        {"segments": [(h(1), 78), (h(2), 42)], "splicer": "studio.splice/1"},
        {"segments": [(h(2), 42), (h(1), 78)], "splicer": "studio.splice/2"}),
    keys.MIX: (
        {"voice_tracks": [{"track": h(1), "start_frame": 0}], "sounds": [], "beds": [],
         "line_rms_dbfs": -22, "master_lufs": -20, "true_peak_dbtp": -3.5, "frames": 223,
         "rate": 48000, "mixer": "studio.mixer/1"},
        {"voice_tracks": [{"track": h(1), "start_frame": 1}],
         "sounds": [{"sound": h(2), "start_sample": 0}],
         "beds": [{"sound": h(3), "level_rms_dbfs": -40}], "line_rms_dbfs": -21,
         "master_lufs": -16, "true_peak_dbtp": -1, "frames": 224, "rate": 44100,
         "mixer": "studio.mixer/2"}),
    keys.MASTER: ({"picture": h(1), "mix": h(2), "mux": {"audio": "aac"}},
                  {"picture": h(3), "mix": h(4), "mux": {"audio": "opus"}}),
    keys.PROXY: ({"master": h(1), "profile": {"size": [720, 1280]}},
                 {"master": h(2), "profile": {"size": [540, 960]}}),
    keys.CHECK_RESULT: (
        {"artifact": h(1), "check": "master.decode", "version": "1", "thresholds": {}},
        {"artifact": h(2), "check": "master.transcript", "version": "2", "thresholds": {"x": 1}}),
}


def test_the_inventory_has_one_function_per_row_of_the_contracts_table():
    assert [spec.kind for spec in INVENTORY] == list(SAMPLES)
    assert len({spec.function for spec in INVENTORY}) == len(INVENTORY) == 13


@pytest.mark.parametrize("spec", INVENTORY, ids=lambda spec: spec.kind)
def test_every_input_of_every_key_changes_the_key(spec):
    base, other = SAMPLES[spec.kind]
    assert tuple(inspect.signature(spec.function).parameters) == spec.inputs == tuple(base)
    key = spec.function(**base)
    assert key.kind == spec.kind and key.value == spec.function(**dict(base)).value
    for name in spec.inputs:
        assert spec.function(**{**base, name: other[name]}).value != key.value, name


@pytest.mark.parametrize("spec", INVENTORY, ids=lambda spec: spec.kind)
def test_keys_read_no_file(spec, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a key function opened a file")

    monkeypatch.setattr(builtins, "open", refuse)
    monkeypatch.setattr(os, "open", refuse)
    monkeypatch.setattr(os, "stat", refuse)
    spec.function(**SAMPLES[spec.kind][0])


def test_a_key_is_sha256_of_the_canonical_json_of_its_document():
    key = make_key("mix", {"b": [1, 2.5], "a": "é"})
    text = '{"a":"é","b":[1,2.5],"kind":"mix","scheme":"' + SCHEME + '"}'
    assert key.canonical == text.encode("utf-8")
    assert key.value == "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert key.hex == hashlib.sha256(key.canonical).hexdigest()
    assert json.loads(key.canonical) == key.inputs()


def test_canonical_form_ignores_key_order_integral_floats_and_unicode_form():
    composed, decomposed = "Café", unicodedata.normalize("NFD", "Café")
    assert composed != decomposed
    one = make_key("x", {"level": -22.0, "text": composed, "z": 1, "a": {"q": 1.0, "p": 0.25}})
    two = make_key("x", {"a": {"p": 0.25, "q": 1}, "z": 1, "text": decomposed, "level": -22})
    assert one.value == two.value
    assert make_key("x", {"v": 0.1}).canonical == b'{"kind":"x","scheme":"' + SCHEME.encode() + b'","v":0.1}'


@pytest.mark.parametrize("inputs", [
    {"v": float("nan")}, {"v": float("inf")}, {"v": b"bytes"}, {"v": {1, 2}}, {1: "a"},
    {"kind": "other"}, {"v": object()}])
def test_a_key_document_is_plain_finite_json(inputs):
    with pytest.raises(CacheError) as caught:
        make_key("x", inputs)
    assert caught.value.code == KEY_INPUT_INVALID


@pytest.mark.parametrize(("field", "value"), [
    ("still", "a" * 63), ("still", "A" * 64), ("still", "brd_01JCACHE000000000000000001"),
    ("seed", True), ("seed", 1.5), ("prompt", ""), ("profile", [])])
def test_typed_inputs_are_checked(field, value):
    with pytest.raises(CacheError) as caught:
        keys.motion_clip_key(**{**SAMPLES[keys.MOTION_CLIP][0], field: value})
    assert caught.value.code == KEY_INPUT_INVALID


def test_a_track_needs_one_gap_per_later_line():
    with pytest.raises(CacheError):
        keys.board_voice_track_key(**{**SAMPLES[keys.BOARD_VOICE_TRACK][0], "gaps_ms": []})


def test_segment_keys_take_no_film_clock_input():
    """P-06: neither the segment's inputs nor its function name a film frame or offset."""
    spec = keys.KINDS[keys.SEGMENT]
    assert not [name for name in spec.inputs if "film" in name or "offset" in name or "start" in name]
