"""A synthetic S2V board through the normal build, master and phone delivery."""

from __future__ import annotations

import hashlib
import io
import wave
from fractions import Fraction

import av
import numpy as np
import pytest
from PIL import Image

from haynes_studio.delivery import MASTER_SIZES, read_delivery
from haynes_studio.layered import compose
from haynes_studio.layered.fake import FILES
from haynes_studio.layered.keyed import read_record
from haynes_studio.mix.audio import read_pcm
from haynes_studio.render.delivery_profile import (
    delivery_profile_record,
    resolve_delivery_upscaler,
)
from haynes_studio.store import blob_locator, canonical_json
from tests.build_story import fixtures as f
from tests.layered import media


@pytest.mark.parametrize(("source_size", "kind"), [((36, 64), "short"), ((64, 36), "video")])
def test_delivery_scaling_matches_pillow_lanczos_at_both_master_sizes(source_size, kind):
    pixels = np.arange(source_size[0] * source_size[1], dtype=np.uint8)
    source = Image.frombytes("L", source_size, pixels.tobytes()).convert("RGB")
    size = MASTER_SIZES[kind]
    scaler = resolve_delivery_upscaler(delivery_profile_record()["sha256"])
    assert scaler.scale(source, source.size) is source
    assert scaler.scale(source, size) == source.resize(size, Image.Resampling.LANCZOS)
    with pytest.raises(ValueError, match="different aspects"):
        scaler.scale(source, size[::-1])


def _check_delivered_clocks(path, size, read_mark):
    """Check exact container and decoded clocks, and read the doll's frame numbers."""
    frames, samples = 0, 0
    marks = []
    with av.open(str(path)) as container:
        video, audio = container.streams.video[0], container.streams.audio[0]
        for stream in (video, audio):
            stream.codec_context.thread_count = 2
        assert (video.width, video.height, video.average_rate) == (*size, 24)
        assert video.duration * video.time_base == Fraction(23, 24)
        assert audio.rate == 48_000 and audio.duration * audio.time_base == Fraction(23, 24)
        for packet in container.demux(video, audio):
            for frame in packet.decode():
                if packet.stream is video:
                    assert frame.pts * frame.time_base == Fraction(frames, 24)
                    if frames >= 4:
                        marks.append(read_mark(frame.to_ndarray(format="rgb24")))
                    frames += 1
                else:
                    assert frame.pts * frame.time_base * 48_000 == samples
                    samples += frame.samples
    assert frames == 23
    assert 46_000 <= samples < 47_024  # the decoder may return AAC end padding
    assert marks == [2 * n // 3 for n in range(19)]


def test_s2v_cadence_and_samples_stay_aligned_through_delivery(tmp_path, record_property):
    world = f.make_world(tmp_path / "store")
    document = f.story_document()
    b1, b2 = (f.board_of(document, board) for board in (f.B1, f.B2))
    b2["timing"]["hold_ms"] = 130  # 4 frames, so film and board cadence phases differ
    b1["timing"]["lead_ms"] = 250  # delivery frame 6 and source frame 4 on the board
    b1["layout"]["foreground"] = False
    document.update(boards=[b2, b1], board_order=[f.B2, f.B1],
                    motion_style={key: 0 for key in document["motion_style"]})
    document, library = f.voiced(world, document)
    sources = f.sources()
    result = f.build(world, document, library, source=sources)
    assert result.run["status"] == "succeeded" and result.plan.frames == 23

    profile = result.run["provenance"]["toolchain"]["delivery_profile"]
    digest = profile["sha256"]
    assert profile["version"] == "studio.delivery-conversion/v1"
    payload = {key: value for key, value in profile.items() if key != "sha256"}
    assert hashlib.sha256(canonical_json(payload)).hexdigest() == digest
    assert all(board.segment.key.document["delivery_profile_sha256"] == digest
               for board in result.plan.boards)
    backend = profile["scaling"]["upscaler"]
    with open(Image.core.__file__, "rb") as core:
        assert backend["tool_sha256"] == hashlib.file_digest(core, "sha256").hexdigest()
    assert backend["name"] == "lanczos" and backend["model_sha256"] is None

    (request,) = sources.s2v.calls
    assert request.profile["source_fps"] == 16
    with wave.open(io.BytesIO(request.drive_track), "rb") as track:
        assert (track.getframerate(), track.getnframes()) == (24_000, 19_000)
        drive = np.frombuffer(track.readframes(19_000), dtype="<i2")
    assert not drive[:6000].any() and drive[6000:10_800].all() and not drive[10_800:].any()
    _, stage = result.run["stages"]
    (s2v,) = [clip for clip in stage["clips"] if clip["role"] == "s2v_clip"]
    assert s2v["files_sha256"] == FILES and s2v["trimmed"] == 8
    drive_artifact = next(artifact for artifact in stage["artifacts"] if artifact["name"] == "drive/a")
    assert drive_artifact["sha256"] == request.drive_track_sha256 == f.sha(request.drive_track)
    (line,) = result.run["outputs"]["placement"]["lines"]
    assert line["start_sample"] == 20_000  # 4 * 2000 + 250 * 48
    assert line["end_sample"] == 29_600
    mix_path = world.root / blob_locator(f.PRODUCTION, result.plan.mix.content, "audio/wav")
    pcm = read_pcm(mix_path.read_bytes(), where="synthetic mix")
    assert pcm.rate == 48_000 and pcm.samples.shape == (46_000, 2)
    assert not pcm.samples[:20_000].any() and pcm.samples[20_001:20_240].any()

    keyed = result.plan.artifacts[f"{f.B1}/keyed/a"].content
    x0, y0, x1, y1 = read_record(
        (world.root / blob_locator(f.PRODUCTION, keyed, "image/png")).read_bytes())["box"]
    slot = compose.slot_of(document["layouts"]["pair"], "a")
    scale = slot.height / (y1 - y0)
    size = compose.sprite_size((x1 - x0, y1 - y0), slot)
    place = compose.place(size, slot, 1080, "a")
    delivery = read_delivery(world.store, production_id=f.PRODUCTION, run_id=result.run["id"])
    for asset, size in ((delivery.master, (1080, 1920)), (delivery.proxy, (720, 1280))):
        ratio = Fraction(size[0], 1080)

        def read_mark(frame):
            return media.read_number(frame, (place.x + (42 - x0) * scale) * ratio,
                                     (place.y + (media.STRIP_Y + 15 - y0) * scale) * ratio,
                                     scale * ratio)

        _check_delivered_clocks(world.root / asset.locator, size, read_mark)

    record_property("conversion_sha256", digest)
    record_property("upscaler_tool_sha256", backend["tool_sha256"])
    record_property("frames", 23)
    record_property("mix_samples", 46_000)
    record_property("line_start_sample", line["start_sample"])
