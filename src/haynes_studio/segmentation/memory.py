"""Process peaks and resident memory at the boundaries of the install smoke."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from time import monotonic

CGROUP = Path("/sys/fs/cgroup")


def cgroup_bytes(name: str) -> int | None:
    try:
        return int((CGROUP / f"memory.{name}").read_text().strip())
    except (OSError, ValueError):
        return None


class Phases:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.samples: dict[str, dict] = {}

    @contextmanager
    def __call__(self, name: str):
        if not self.enabled:
            yield
            return
        start = monotonic()
        try:
            Path("/proc/self/clear_refs").write_text("5")
            reset = True
        except OSError:
            reset = False
        try:
            yield
        finally:
            sample = {
                "elapsed_ms": round((monotonic() - start) * 1000),
                "phase_rss_peak_reset": reset,
                "cgroup_resident_bytes": cgroup_bytes("current"),
                "cgroup_peak_since_start_bytes": cgroup_bytes("peak"),
            }
            try:
                for line in Path("/proc/self/status").read_text().splitlines():
                    name_in_proc, _, value = line.partition(":")
                    if name_in_proc == "VmHWM":
                        sample["peak_rss_bytes"] = int(value.split()[0]) * 1024
                    elif name_in_proc == "VmRSS":
                        sample["resident_rss_bytes"] = int(value.split()[0]) * 1024
            except (OSError, ValueError, IndexError):
                pass
            self.samples[name] = sample
