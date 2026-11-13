"""Motion clip records (story 457): the ``motion`` block of a library ``motion`` asset
version, its identity, its checks, and the resolver that gives a board its pinned
clips.

- :mod:`.record`: the block as an immutable :class:`~.record.MotionRecord`; loops
  (TIME-8a) and timed clips (TIME-8) and how each plays.
- :mod:`.identity`: one pure function from the record's inputs, built on the cache
  keys of story 380.
- :mod:`.check`: the block's code rules (the schema holds the rest).
- :mod:`.resolve`: a board's doll loops and the set loop, pinned or the one promoted
  loop of a still, each problem with its own code; a timed clip for its drive track.
- :mod:`.winter_menu`: the E0 clips of The Winter Menu from the public records.

Import :mod:`.resolve` and :mod:`.winter_menu` directly: they use the library, which
imports this package's checks, so this module stays free of them. Nothing here reads
media, writes files or calls a service.
"""

from __future__ import annotations

from haynes_studio.motion.record import (
    DOLL,
    LOOP,
    SET,
    TIMED,
    DriveTrack,
    Keying,
    Keys,
    MotionRecord,
    Source,
)

__all__ = ["DOLL", "LOOP", "SET", "TIMED", "DriveTrack", "Keying", "Keys", "MotionRecord",
           "Source"]
