"""Process RSS and cgroup memory measurements with explicit phase boundaries."""

from contextlib import contextmanager
from pathlib import Path
from threading import Event, Thread
from time import monotonic

from .backend import reset_worker_peak, worker_rss

CGROUP = Path("/sys/fs/cgroup")


def _read(name):
    try:
        return int((CGROUP / name).read_text())
    except (OSError, ValueError):
        return None


def cgroup_peak() -> int | None:
    return _read("memory.peak")


def cgroup_limit() -> int | None:
    return _read("memory.max")


@contextmanager
def phase(report: dict, name: str):
    """Worker peaks use VmHWM. Cgroup phase peaks are sampled every 20 ms."""
    done = Event()
    samples = []

    # Phase calls are sequential. This reset applies to the measuring process,
    # not the supervised inference process, which resets its own high-water mark.
    parent_peak_reset = reset_worker_peak()

    def sample():
        while not done.is_set():
            if (usage := _read("memory.current")) is not None:
                samples.append(usage)
            done.wait(0.02)

    started = monotonic()
    thread = Thread(target=sample, name="upscaling-memory-sampler")
    thread.start()
    try:
        yield
    finally:
        done.set()
        thread.join()
        after = _read("memory.current")
        if after is not None:
            samples.append(after)
        report[name] = {
            "wall_seconds": round(monotonic() - started, 6),
            "cgroup_sampled_peak_bytes": max(samples, default=None), "cgroup_after_bytes": after,
            "parent": worker_rss() if parent_peak_reset else None,
        }
