"""Picture on the board clock (story 380): the renderer interface, segment encoding and
the splice.

- :mod:`.clock`: the board clock (P-06, TIME-8, TIME-8a, TIME-9): loop phases,
  ping-pong loops, source frame mapping and procedural randomness.
- :mod:`.base`: :class:`~.base.SegmentRenderer` and :class:`~.base.SegmentRequest`.
- :mod:`.synthetic`: :class:`~.synthetic.SyntheticRenderer`, a deterministic test
  renderer.
- :mod:`.encode`: H.264 segment encoding and decoding at two threads.
- :mod:`.splice`: the film picture from ordered segments by stream copy (TIME-11).
- :mod:`.errors`: the codes of stories 380's cache, render and splice.

Nothing here imports the cache; real renderers (stories 426 and 427) implement
:class:`~.base.SegmentRenderer`.
"""

from __future__ import annotations
