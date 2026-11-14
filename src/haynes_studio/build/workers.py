"""Render a build's missing segments in up to N processes (``studio build --workers N``).

Each worker opens the same local store, makes its own cache for the same run and its
own renderer for the segment's compositor, and renders and commits one segment through
story 380's :class:`~haynes_studio.cache.build.PictureBuilder`. Nothing new guards the
store: a stage commit is create-only, so two writers of the same segment both succeed
with the same record (P-28), and no lock or delete is added. A worker keeps the
two-thread rule (the encoder's two sliced threads, OpenCV's two), so N workers use at
most 2N threads. Processes are started with ``spawn``, never ``fork``, so no thread
pool or open descriptor of the parent is copied into a child.

A worker returns its renderer's report and checks with the segment's hash, or the
error's code and message: exceptions with required arguments do not cross a process
boundary intact, so the parent raises the failure itself, naming the board.
"""

from __future__ import annotations

import multiprocessing
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from typing import Any

from haynes_studio.build.errors import INTERNAL, BuildError
from haynes_studio.cache.keys import SEGMENT, CacheKey


def _render_one(job: Mapping[str, Any]) -> dict[str, Any]:
    """One segment, in a worker process (see the module docstring)."""
    from haynes_studio.cache import ArtifactCache, make_key
    from haynes_studio.cache.build import PictureBuilder
    from haynes_studio.layered import COMPOSITOR as LAYERED
    from haynes_studio.layered import LayeredRenderer, reader
    from haynes_studio.store import LocalStore
    from haynes_studio.wholeframe import COMPOSITOR as WHOLE_FRAME
    from haynes_studio.wholeframe import WholeFrameRenderer

    renderer: Any = None
    try:
        store = LocalStore(job["root"])
        cache = ArtifactCache(store, production_id=job["production_id"], run_id=job["run_id"],
                              earlier_runs=job["earlier_runs"])
        renderer = {LAYERED: LayeredRenderer, WHOLE_FRAME: WholeFrameRenderer}[job["compositor"]]()
        builder = PictureBuilder(cache, renderer, open_input=reader(store, [job["production_id"], "library"]))
        key = make_key(SEGMENT, job["inputs"])
        if key.value != job["key"]:
            raise BuildError("cache.entry_invalid", "the segment key did not survive the process "
                             "boundary unchanged")
        start = time.perf_counter()
        made = builder.segment(key)
        report = renderer.reports.get(key.value)
        return {"ok": True, "key": key.value, "sha256": made.sha256, "made": not made.hit,
                "seconds": round(time.perf_counter() - start, 3),
                "report": None if report is None else report.to_document(),
                "checks": list(getattr(renderer, "checks", {}).get(key.value, []))}
    except Exception as error:  # noqa: BLE001 - sent back as data, raised in the parent
        code = getattr(error, "code", None)
        message = getattr(error, "message", None) or str(error)
        return {"ok": False, "key": job["key"], "code": code if isinstance(code, str) else INTERNAL,
                "message": str(message)[:600],
                "checks": [] if renderer is None else list(getattr(renderer, "checks", {}).get(job["key"], []))}


def render_segments(build: Any, missing: Sequence[tuple[CacheKey, str | None]],
                    workers: int) -> dict[str, dict[str, Any]]:
    """Render ``missing`` (segment keys with their boards) in up to ``workers``
    processes; returns each rendered segment's report and checks by key. The first
    failure in board order raises, naming its board."""
    from haynes_studio.store import LocalStore

    if not missing:
        return {}
    if not isinstance(build.store, LocalStore):
        raise ValueError("--workers needs the local store (each worker opens it by its root)")
    jobs = [{"root": build.store.root, "production_id": build.production_id,
             "run_id": build.run_id, "earlier_runs": list(build.earlier_runs),
             "compositor": key.document["compositor"], "key": key.value,
             "inputs": {k: v for k, v in _plain(key.document).items() if k not in ("kind", "scheme")}}
            for key, _ in missing]
    boards = {key.value: board for key, board in missing}
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=min(workers, len(jobs)), mp_context=context) as pool:
        results = list(pool.map(_render_one, jobs))
    out = {}
    for result in results:
        if not result["ok"]:
            raise BuildError(result["code"], result["message"], board_id=boards.get(result["key"]),
                             stage=SEGMENT)
        out[result["key"]] = result
        build.worker_made.append(result["key"])
    return out


def _plain(value: Any) -> Any:
    """A key document as plain JSON values (no read-only mappings), for pickling."""
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


__all__ = ["render_segments"]
