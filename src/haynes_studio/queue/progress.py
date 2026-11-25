"""Optional main-thread progress marker for worker liveness probes."""

import math
import os
import stat
from pathlib import Path
from time import time


class ProgressFile:
    """Touch only at synchronous worker boundaries, never from a lease heartbeat."""

    def __init__(self, path=None, *, clock=time):
        self.path = None if path is None else Path(path)
        self.clock = clock

    def __call__(self):
        self._write()

    def write_status(self, message):
        self._write((message + "\n").encode())

    def _write(self, status=None):
        if self.path is None:
            return
        # The containing directory belongs to the deployment. A bad marker mount
        # must fail visibly instead of silently disabling its liveness probe.
        descriptor = os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            if status is not None:
                os.write(descriptor, status)
                os.ftruncate(descriptor, len(status))
            now = self.clock()
            os.utime(descriptor, (now, now))
        finally:
            os.close(descriptor)

    def fresh(self, seconds):
        """Missing/unreadable markers and invalid probe ages fail closed."""
        if self.path is None or not math.isfinite(seconds) or seconds <= 0:
            return False
        try:
            marker = self.path.stat()
        except OSError:
            return False
        return stat.S_ISREG(marker.st_mode) and self.clock() - marker.st_mtime <= seconds
