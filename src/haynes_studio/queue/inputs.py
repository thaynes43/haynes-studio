"""Freeze build inputs and estimate the shared lane from E0 timing observations."""

from collections import Counter
from dataclasses import asdict

from haynes_studio.build.pipeline import media_format
from haynes_studio.build.prebuild import make_snapshot, prepare
from haynes_studio.cache.plan import Toolchain
from haynes_studio.canonical.derive import board_clock
from haynes_studio.library.model import version_document
from haynes_studio.render.clock import S2V_CHUNK, i2v_clip_lengths, s2v_request_frames
from haynes_studio.voice import Engine

# Deliberately broad heuristic intervals around E0's two-minute TI2V clip and
# the lightning batch's ~250 seconds render + cooldown per chunk.
GPU_SECONDS = {"whole_frame/i2v": (90, 210), "layered/s2v": (140, 360)}
CPU_PER_FILM_SECOND = {"whole_frame": (2, 12), "layered": (5, 22)}
BASIS = ("E0 The Winter Menu: TI2V clips, lightning S2V chunks and CPU compositing. "
         "Cold-cache estimate. Shared GPU load, cooldown, reuse and retries vary.")


def prepare_queue(story, library, *, jobs=()):
    media = media_format(story["media_kind"])
    return prepare(story, library=library, store=None, toolchain=Toolchain(),
                   frame_size=(media.width, media.height), current_engine=Engine().signing_name,
                   jobs=jobs)


def freeze(prepared, *, studio):
    """Canonically pin the eligible timed clips too, so later promotion cannot change a plan."""
    library = prepared.library
    snapshot = make_snapshot(prepared, library, studio=studio)
    pinned = {entry["id"] for entry in snapshot["resolved_asset_versions"]}
    for version in sorted(library.versions.values(), key=lambda v: v.id):
        if version.id not in pinned and version.kind == "motion" and version.content is not None:
            snapshot["resolved_asset_versions"].append(
                {"id": version.id, "kind": version.kind, "sha256": version.content.sha256}
            )
    documents = [version_document(library.version(entry["id"]), library.asset_of(entry["id"]))
                 for entry in snapshot["resolved_asset_versions"]]
    return snapshot, documents


def estimate(prepared):
    """Count chunks with the same clock and split rules used by the build."""
    chunks = Counter()
    frames = Counter()
    unknown = False
    for board in prepared.story.ordered_boards():
        timing = board_clock(board, prepared.facts)
        if timing is None:
            unknown = True
            continue
        layer, motion = board.method.layer, board.method.motion
        frames[layer] += timing.frames
        if (layer, motion) == ("whole_frame", "i2v"):
            chunks[f"{layer}/{motion}"] += len(i2v_clip_lengths(timing.frames))
        elif (layer, motion) == ("layered", "s2v"):
            speakers = {line.speaker for line in board.lines}
            rendered_speakers = speakers.intersection(entry.slot for entry in board.cast)
            if timing.frames and rendered_speakers:
                requested = s2v_request_frames(timing.frames)
                chunks[f"{layer}/{motion}"] += len(rendered_speakers) * ((requested + S2V_CHUNK - 1) // S2V_CHUNK)
        elif (layer, motion) == ("layered", "i2v"):
            chunks[f"{layer}/{motion}"] += 0  # existing loop pins are CPU work
        else:
            unknown = True

    gpu = [sum(count * GPU_SECONDS[method][i] for method, count in chunks.items() if count)
           for i in range(2)]
    cpu = [round(sum(count * CPU_PER_FILM_SECOND[layer][i] / 24 for layer, count in frames.items()))
           for i in range(2)]
    methods = [{"method": method, "chunks": count,
                "gpu_wall_s": [count * bound for bound in GPU_SECONDS.get(method, (0, 0))]}
               for method, count in sorted(chunks.items())]
    return {"estimate": {"gpu_wall_s": None if unknown else gpu,
                         "cpu_wall_s": None if unknown else cpu,
                         "basis": BASIS, "uncertain": True},
            "methods": methods,
            "problems": [asdict(problem) for problem in prepared.report.blocking]}


def queue_wait(ahead):
    lower = upper = count = 0
    bounded = True
    for run in ahead:
        count += 1
        estimate = run["estimate"] or {}
        gpu, cpu = estimate.get("gpu_wall_s"), estimate.get("cpu_wall_s")
        if (gpu is None or cpu is None or run["status"] == "held" or run["wait_reason"]):
            bounded = False
        elif run["status"] in ("queued", "running"):
            lower += gpu[0] + cpu[0] if run["status"] == "queued" else 0
            upper += gpu[1] + cpu[1]
    return {"ahead": count, "wall_s": [lower, upper] if bounded else None,
            "uncertain": True,
            "basis": ("Studio runs ahead, including CPU work on the serial lane. "
                      "Remaining time, outside lease holders and downtime are unknown.")}
