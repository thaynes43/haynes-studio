"""Cache keys (contract section 4, P-07): one pure function per artifact.

``key = "sha256:" + hex(sha256(canonical_json(inputs)))``. Canonical JSON is the
store's (:func:`haynes_studio.store.canonical_json`): UTF-8, keys sorted, no whitespace,
no NaN or Infinity, floats in shortest round-trip form. Before it is encoded, every
key document is checked and normalized here:

- times, frames, samples, rates and seeds are integers (``bool`` is not one);
- an integral float is the integer it equals (``-22.0`` is ``-22``), as contract
  section 2 reads JSON numbers, so a document read back from JSON keys the same;
- a field that holds a content hash is 64 lower-case hex digits (the section 2
  ``sha256`` form); a text is NFC; a mapping's keys are texts;
- nothing else (bytes, paths, sets, objects) can reach a key.

Inputs are content hashes of input bytes and parameters, never identifiers or paths.
Each document also names its artifact ``kind`` and the key ``scheme``; the adapter,
profile or tool version is one of each artifact's inputs (P-07).

Nothing here reads a file, the clock or the environment. Reference:
``docs/reference/cache-and-splice.md``.
"""

from __future__ import annotations

import hashlib
import math
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from haynes_studio.cache.errors import KEY_INPUT_INVALID, CacheError
from haynes_studio.canonical.jsonvalues import too_deep
from haynes_studio.jsonio import freeze, thaw
from haynes_studio.store import canonical_json, is_sha256

# Proposal: the key scheme. Changing how any key is formed bumps it, so no key made
# under an older scheme can match a new one.
SCHEME = "studio.cache-key/v1"

VOICE_TAKE = "voice_take"
BOARD_VOICE_TRACK = "board_voice_track"
S2V_DRIVE_TRACK = "s2v_drive_track"
S2V_CLIP = "s2v_clip"
MOTION_CLIP = "motion_clip"
WHOLE_FRAME_CLIP = "whole_frame_clip"
KEYED_FRAMES = "keyed_frames"
SEGMENT = "segment"
FILM_PICTURE = "film_picture"
MIX = "mix"
MASTER = "master"
PROXY = "proxy"
CHECK_RESULT = "check_result"

BOARD, FILM, SOURCE, NONE = "board", "film", "source", "none"


@dataclass(frozen=True)
class CacheKey:
    """One artifact's key: its kind, its checked key document and the key value."""

    kind: str
    document: Mapping[str, Any] = field(repr=False)
    value: str

    @property
    def hex(self) -> str:
        """The 64 hex digits of the key: also the SHA-256 of :attr:`canonical`."""
        return self.value.removeprefix("sha256:")

    @property
    def canonical(self) -> bytes:
        """The canonical JSON bytes the key hashes."""
        return canonical_json(thaw(self.document))

    def inputs(self) -> dict[str, Any]:
        """A plain, mutable copy of the key document."""
        return thaw(self.document)

    def __str__(self) -> str:
        return self.value


def _bad(path: str, message: str) -> CacheError:
    return CacheError(KEY_INPUT_INVALID, message, where=path or "(root)")


def _canon(value: Any, path: str) -> Any:
    """``value`` as checked, normalized plain JSON (see the module docstring)."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _bad(path, "no NaN or Infinity in a key")
        return int(value) if value.is_integer() else value
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Mapping):
        out = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise _bad(path, f"a mapping key in a key document is text, got {type(key).__name__}")
            out[unicodedata.normalize("NFC", key)] = _canon(item, f"{path}/{key}")
        if len(out) != len(value):
            raise _bad(path, "two mapping keys are the same text after NFC")
        return out
    if isinstance(value, list | tuple):
        return [_canon(item, f"{path}/{i}") for i, item in enumerate(value)]
    raise _bad(path, f"a key input is a JSON value, not a {type(value).__name__}")


def make_key(kind: str, inputs: Mapping[str, Any]) -> CacheKey:
    """The key of ``kind`` over ``inputs`` (a mapping of plain JSON values). The
    document is ``inputs`` plus ``kind`` and ``scheme``."""
    if "kind" in inputs or "scheme" in inputs:
        raise _bad("", "'kind' and 'scheme' are set by the key, not by its inputs")
    if too_deep(inputs):
        raise _bad("", "a key document nests too deep")
    document = _canon({**inputs, "kind": kind, "scheme": SCHEME}, "")
    digest = hashlib.sha256(canonical_json(document)).hexdigest()
    return CacheKey(kind=kind, document=freeze(document), value=f"sha256:{digest}")


# Typed input checks ---------------------------------------------------------------------


def _sha(value: Any, name: str) -> str:
    if not is_sha256(value):
        raise _bad(f"/{name}", f"{name} is a content hash (64 lower-case hex digits), got {value!r}")
    return value


def _opt_sha(value: Any, name: str) -> str | None:
    return None if value is None else _sha(value, name)


def _int(value: Any, name: str, *, minimum: int | None = 0) -> int:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int):
        raise _bad(f"/{name}", f"{name} is an integer, got {type(value).__name__}")
    if minimum is not None and value < minimum:
        raise _bad(f"/{name}", f"{name} is at least {minimum}, got {value}")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise _bad(f"/{name}", f"{name} is a non-empty text, got {value!r}")
    return value


def _number(value: Any, name: str) -> float | int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _bad(f"/{name}", f"{name} is a number, got {type(value).__name__}")
    return value


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _bad(f"/{name}", f"{name} is a mapping, got {type(value).__name__}")
    return value


def _seq(value: Any, name: str) -> Sequence[Any]:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise _bad(f"/{name}", f"{name} is a sequence, got {type(value).__name__}")
    return value


# One key function per artifact of section 4's table ------------------------------------


def voice_take_key(*, tts_model: str, voice_id: str, text: str, speed: float,
                   sample_rate: int) -> CacheKey:
    """Voice take (clock: none): TTS model digest, stock voice ID, NFC text, speed and
    sample rate. ``voice_id`` is the engine's stock voice name (``af_heart``), not a
    studio identifier."""
    return make_key(VOICE_TAKE, {
        "tts_model": _text(tts_model, "tts_model"), "voice_id": _text(voice_id, "voice_id"),
        "text": _text(text, "text"), "speed": _number(speed, "speed"),
        "sample_rate": _int(sample_rate, "sample_rate", minimum=1)})


def board_voice_track_key(*, takes: Sequence[str], lead_ms: int, gaps_ms: Sequence[int],
                          mix_rate: int, assembler: str) -> CacheKey:
    """Board voice track (board clock): the takes' hashes in line order, the lead, the
    gap before each line after the first, the mix rate and the assembler version.
    The tail is not an input: the track ends with the last line."""
    takes = [_sha(take, f"takes/{i}") for i, take in enumerate(_seq(takes, "takes"))]
    gaps = [_int(gap, f"gaps_ms/{i}") for i, gap in enumerate(_seq(gaps_ms, "gaps_ms"))]
    if not takes or len(gaps) != len(takes) - 1:
        raise _bad("/gaps_ms", "a track has at least one take and one gap per later line")
    return make_key(BOARD_VOICE_TRACK, {
        "takes": takes, "lead_ms": _int(lead_ms, "lead_ms"), "gaps_ms": gaps,
        "mix_rate": _int(mix_rate, "mix_rate", minimum=1), "assembler": _text(assembler, "assembler")})


def s2v_drive_track_key(*, speaker: str, lines: Sequence[tuple[str, int]], frames: int,
                        fps: int, rate: int, assembler: str) -> CacheKey:
    """S2V drive track (board clock): one on-screen speaker's lines, each as its take
    hash and start (ms from board start), and the board's frames, so the track lasts
    exactly ``frames / fps`` s (TIME-9).

    **Proposal:** section 4 lists "board voice track, speaker, board frames". Keyed on
    the whole board track, any line edit would change every speaker's drive track, and
    the invalidation table's "the edited line's speaker" could not hold. The speaker's
    own takes at their offsets are what the drive track is made of."""
    spans = []
    for i, line in enumerate(_seq(lines, "lines")):
        take, start_ms = _seq(line, f"lines/{i}")
        spans.append([_sha(take, f"lines/{i}/take"), _int(start_ms, f"lines/{i}/start_ms")])
    if not spans:
        raise _bad("/lines", "a drive track has at least one line")
    return make_key(S2V_DRIVE_TRACK, {
        "speaker": _text(speaker, "speaker"), "lines": spans,
        "frames": _int(frames, "frames", minimum=1), "fps": _int(fps, "fps", minimum=1),
        "rate": _int(rate, "rate", minimum=1), "assembler": _text(assembler, "assembler")})


def s2v_clip_key(*, drive_track: str, start_still: str, prompt: str, negative_prompt: str,
                 seed: int, profile: Mapping[str, Any], adapter: str) -> CacheKey:
    """S2V clip (source clock): drive track, start still, prompt, negative prompt, seed,
    profile (model files, LoRA, steps, cfg, size, chunk) and adapter version."""
    return make_key(S2V_CLIP, {
        "drive_track": _sha(drive_track, "drive_track"),
        "start_still": _sha(start_still, "start_still"),
        "prompt": _text(prompt, "prompt"), "negative_prompt": negative_prompt,
        "seed": _int(seed, "seed", minimum=None), "profile": _mapping(profile, "profile"),
        "adapter": _text(adapter, "adapter")})


def motion_clip_key(*, still: str, prompt: str, seed: int, profile: Mapping[str, Any]) -> CacheKey:
    """Doll clip or set loop, a library ``motion`` asset (source clock): still, prompt,
    seed and profile (which names the adapter version)."""
    return make_key(MOTION_CLIP, {
        "still": _sha(still, "still"), "prompt": _text(prompt, "prompt"),
        "seed": _int(seed, "seed", minimum=None), "profile": _mapping(profile, "profile")})


def whole_frame_clip_key(*, photo: str, prompt: str, seed: int, profile: Mapping[str, Any],
                         clip_lengths: Sequence[int]) -> CacheKey:
    """Whole-frame I2V clip(s) (source clock): the board photo, prompt, seed, profile
    and the requested clip lengths (set by the frames needed and story 427's chain
    policy). A chain of clips is one artifact."""
    lengths = [_int(n, f"clip_lengths/{i}", minimum=1)
               for i, n in enumerate(_seq(clip_lengths, "clip_lengths"))]
    if not lengths:
        raise _bad("/clip_lengths", "at least one clip is requested")
    return make_key(WHOLE_FRAME_CLIP, {
        "photo": _sha(photo, "photo"), "prompt": _text(prompt, "prompt"),
        "seed": _int(seed, "seed", minimum=None), "profile": _mapping(profile, "profile"),
        "clip_lengths": lengths})


def keyed_frames_key(*, clip: str, still: str, key_thresholds: Mapping[str, Any],
                     protect_boxes: Sequence[Any], decal_box: Sequence[Any] | None,
                     decal_version: str | None, keyer: str) -> CacheKey:
    """Keyed and decal frames (source clock): the clip, key thresholds, protect boxes,
    the still, the decal box and decal version (Legacy ``DollClip.cache_dir``), and
    the keyer version."""
    return make_key(KEYED_FRAMES, {
        "clip": _sha(clip, "clip"), "still": _sha(still, "still"),
        "key_thresholds": _mapping(key_thresholds, "key_thresholds"),
        "protect_boxes": list(_seq(protect_boxes, "protect_boxes")),
        "decal_box": None if decal_box is None else list(_seq(decal_box, "decal_box")),
        "decal_version": decal_version, "keyer": _text(keyer, "keyer")})


def segment_key(*, method: Mapping[str, str], frames: int, width: int, height: int, fps: int,
                layout: Mapping[str, Any] | None, layers: Sequence[Mapping[str, Any]],
                set_layer: Mapping[str, Any] | None, whole_frame_clip: str | None,
                motion_style: Mapping[str, Any] | None, voice_envelope: str | None,
                cues: Sequence[Mapping[str, Any]], foreground: Mapping[str, Any] | None,
                procedural_stream: int, compositor: str, encoder: Mapping[str, Any]) -> CacheKey:
    """Board picture segment (board clock): method, layout preset values, the cast
    stills with their clip and keyed hashes and loop phases (``layers``, draw order),
    motion style, the voice envelope when any line is spoken, move and camera cues
    resolved to ms from board start, frames, frame size, fps, foreground edge,
    compositor digest and encoder settings.

    Beyond the table (**proposals**): ``set_layer`` (the set plate's hash, the set
    loop's hash and its phase), ``whole_frame_clip`` (a whole-frame board's clip), and
    ``procedural_stream`` (:func:`haynes_studio.render.clock.board_stream`, so
    procedural randomness is keyed without the board ID). Nothing on the film clock
    is an input."""
    method = _mapping(method, "method")
    checked_layers = []
    for i, layer in enumerate(_seq(layers, "layers")):
        layer = _mapping(layer, f"layers/{i}")
        checked_layers.append({
            **layer, "slot": _text(layer.get("slot"), f"layers/{i}/slot"),
            "still": _sha(layer.get("still"), f"layers/{i}/still"),
            "clip": _opt_sha(layer.get("clip"), f"layers/{i}/clip"),
            "keyed": _opt_sha(layer.get("keyed"), f"layers/{i}/keyed"),
            "phase": None if layer.get("phase") is None else _int(layer["phase"], f"layers/{i}/phase")})
    if set_layer is not None:
        set_layer = _mapping(set_layer, "set_layer")
        set_layer = {**set_layer, "plate": _opt_sha(set_layer.get("plate"), "set_layer/plate"),
                     "loop": _opt_sha(set_layer.get("loop"), "set_layer/loop")}
    return make_key(SEGMENT, {
        "method": {"layer": _text(method.get("layer"), "method/layer"),
                   "motion": _text(method.get("motion"), "method/motion")},
        "frames": _int(frames, "frames", minimum=1), "width": _int(width, "width", minimum=2),
        "height": _int(height, "height", minimum=2), "fps": _int(fps, "fps", minimum=1),
        "layout": None if layout is None else _mapping(layout, "layout"),
        "layers": checked_layers, "set_layer": set_layer,
        "whole_frame_clip": _opt_sha(whole_frame_clip, "whole_frame_clip"),
        "motion_style": None if motion_style is None else _mapping(motion_style, "motion_style"),
        "voice_envelope": _opt_sha(voice_envelope, "voice_envelope"),
        "cues": [_mapping(cue, f"cues/{i}") for i, cue in enumerate(_seq(cues, "cues"))],
        "foreground": None if foreground is None else _mapping(foreground, "foreground"),
        "procedural_stream": _int(procedural_stream, "procedural_stream"),
        "compositor": _text(compositor, "compositor"), "encoder": _mapping(encoder, "encoder")})


def film_picture_key(*, segments: Sequence[tuple[str, int]], splicer: str) -> CacheKey:
    """Film picture (film clock): the ordered segment hashes. Each segment also
    carries its frame count (**proposal**: implied by its hash, so it never changes the
    key on its own; it lets the splice check TIME-11 from the key alone) and the
    splicer version."""
    out = []
    for i, item in enumerate(_seq(segments, "segments")):
        sha, frames = _seq(item, f"segments/{i}")
        out.append({"segment": _sha(sha, f"segments/{i}/segment"),
                    "frames": _int(frames, f"segments/{i}/frames", minimum=1)})
    if not out:
        raise _bad("/segments", "a film has at least one segment")
    return make_key(FILM_PICTURE, {"segments": out, "splicer": _text(splicer, "splicer")})


def mix_key(*, voice_tracks: Sequence[Mapping[str, Any]], sounds: Sequence[Mapping[str, Any]],
            beds: Sequence[Mapping[str, Any]], line_rms_dbfs: float, master_lufs: float,
            true_peak_dbtp: float, frames: int, rate: int, mixer: str) -> CacheKey:
    """Mix (film clock): the ordered voice tracks, each with its board's film start
    frame ``F[k]`` (and its line spans, for per-take levels), sound cues resolved to
    mix samples (sound hash, start sample, trim, level), beds, the line RMS, the
    loudness target, the film's frames (its length, TIME-11) and the mixer digest
    (which includes its fades)."""
    tracks = []
    for i, track in enumerate(_seq(voice_tracks, "voice_tracks")):
        track = _mapping(track, f"voice_tracks/{i}")
        tracks.append({**track, "track": _sha(track.get("track"), f"voice_tracks/{i}/track"),
                       "start_frame": _int(track.get("start_frame"), f"voice_tracks/{i}/start_frame")})
    checked_sounds = []
    for i, sound in enumerate(_seq(sounds, "sounds")):
        sound = _mapping(sound, f"sounds/{i}")
        checked_sounds.append({**sound, "sound": _sha(sound.get("sound"), f"sounds/{i}/sound"),
                               "start_sample": _int(sound.get("start_sample"), f"sounds/{i}/start_sample")})
    checked_beds = []
    for i, bed in enumerate(_seq(beds, "beds")):
        bed = _mapping(bed, f"beds/{i}")
        checked_beds.append({**bed, "sound": _sha(bed.get("sound"), f"beds/{i}/sound")})
    return make_key(MIX, {
        "voice_tracks": tracks, "sounds": checked_sounds, "beds": checked_beds,
        "line_rms_dbfs": _number(line_rms_dbfs, "line_rms_dbfs"),
        "master_lufs": _number(master_lufs, "master_lufs"),
        "true_peak_dbtp": _number(true_peak_dbtp, "true_peak_dbtp"),
        "frames": _int(frames, "frames", minimum=1), "rate": _int(rate, "rate", minimum=1),
        "mixer": _text(mixer, "mixer")})


def master_key(*, picture: str, mix: str, mux: Mapping[str, Any]) -> CacheKey:
    """Master (film clock): the film picture, the mix and the mux settings."""
    return make_key(MASTER, {"picture": _sha(picture, "picture"), "mix": _sha(mix, "mix"),
                             "mux": _mapping(mux, "mux")})


def proxy_key(*, master: str, profile: Mapping[str, Any]) -> CacheKey:
    """Proxy (film clock): the master and the proxy profile."""
    return make_key(PROXY, {"master": _sha(master, "master"), "profile": _mapping(profile, "profile")})


def check_result_key(*, artifact: str, check: str, version: str,
                     thresholds: Mapping[str, Any]) -> CacheKey:
    """Check result (clock: none): the checked artifact's hash, the check and its
    version, and its thresholds."""
    return make_key(CHECK_RESULT, {
        "artifact": _sha(artifact, "artifact"), "check": _text(check, "check"),
        "version": _text(version, "version"), "thresholds": _mapping(thresholds, "thresholds")})


# The inventory -------------------------------------------------------------------------


@dataclass(frozen=True)
class ArtifactSpec:
    """One row of the key inventory: what the contract's table names, its clock, the
    pure key function and the inputs that function takes."""

    kind: str
    artifact: str
    clock: str
    function: Callable[..., CacheKey]
    inputs: tuple[str, ...]
    rendered_here: bool = False  # made by this story (segment, film picture)


INVENTORY: tuple[ArtifactSpec, ...] = (
    ArtifactSpec(VOICE_TAKE, "Voice take", NONE, voice_take_key,
                 ("tts_model", "voice_id", "text", "speed", "sample_rate")),
    ArtifactSpec(BOARD_VOICE_TRACK, "Board voice track", BOARD, board_voice_track_key,
                 ("takes", "lead_ms", "gaps_ms", "mix_rate", "assembler")),
    ArtifactSpec(S2V_DRIVE_TRACK, "S2V drive track", BOARD, s2v_drive_track_key,
                 ("speaker", "lines", "frames", "fps", "rate", "assembler")),
    ArtifactSpec(S2V_CLIP, "S2V clip", SOURCE, s2v_clip_key,
                 ("drive_track", "start_still", "prompt", "negative_prompt", "seed", "profile",
                  "adapter")),
    ArtifactSpec(MOTION_CLIP, "Doll clip or set loop", SOURCE, motion_clip_key,
                 ("still", "prompt", "seed", "profile")),
    ArtifactSpec(WHOLE_FRAME_CLIP, "Whole-frame I2V clip(s)", SOURCE, whole_frame_clip_key,
                 ("photo", "prompt", "seed", "profile", "clip_lengths")),
    ArtifactSpec(KEYED_FRAMES, "Keyed and decal frames", SOURCE, keyed_frames_key,
                 ("clip", "still", "key_thresholds", "protect_boxes", "decal_box",
                  "decal_version", "keyer")),
    ArtifactSpec(SEGMENT, "Board picture segment", BOARD, segment_key,
                 ("method", "frames", "width", "height", "fps", "layout", "layers", "set_layer",
                  "whole_frame_clip", "motion_style", "voice_envelope", "cues", "foreground",
                  "procedural_stream", "compositor", "encoder"), rendered_here=True),
    ArtifactSpec(FILM_PICTURE, "Film picture", FILM, film_picture_key, ("segments", "splicer"),
                 rendered_here=True),
    ArtifactSpec(MIX, "Mix", FILM, mix_key,
                 ("voice_tracks", "sounds", "beds", "line_rms_dbfs", "master_lufs",
                  "true_peak_dbtp", "frames", "rate", "mixer")),
    ArtifactSpec(MASTER, "Master", FILM, master_key, ("picture", "mix", "mux")),
    ArtifactSpec(PROXY, "Proxy", FILM, proxy_key, ("master", "profile")),
    ArtifactSpec(CHECK_RESULT, "Check result", NONE, check_result_key,
                 ("artifact", "check", "version", "thresholds")),
)

KINDS = MappingProxyType({spec.kind: spec for spec in INVENTORY})
