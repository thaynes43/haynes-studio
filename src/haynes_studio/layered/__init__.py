"""The layered method adapter (story 426, contract sections 3 to 6): ``layered`` +
``s2v`` and ``layered`` + ``i2v`` boards.

- :mod:`.keying`: the chroma key and the tracked lettering decal, ported from the PoC.
- :mod:`.keyed`: :class:`~.keyed.KeyedFrames`, keyed frames as one cached APNG per clip.
- :mod:`.drive`: :class:`~.drive.DriveTracks`, one speaker's drive track (TIME-9).
- :mod:`.source`, :mod:`.fake`: the speech-to-video clip source and its fake.
- :mod:`.s2v`: :class:`~.s2v.S2VClips`, speech-to-video clips as cached artifacts.
- :mod:`.compose`: placement, shadow, motion, foreground and camera (the PoC's drawing).
- :mod:`.renderer`: :class:`~.renderer.LayeredRenderer`, the segment renderer.
- :mod:`.photo`: a layered board's photo, the composite of its layers (D51).
- :mod:`.pin`: the motion records a story plays (story 457's resolver), for the plan.
- :mod:`.build`: :class:`~.build.LayeredStages`, the stages as one ``upstream``.
- :mod:`.checks`: :func:`~.checks.check_board`, the pre-build refusals.

Import :mod:`.pin` directly (it uses the library). Reference:
``docs/reference/layered-adapter.md``.
"""

from __future__ import annotations

from haynes_studio.layered.build import LayeredStages, reader
from haynes_studio.layered.checks import check_board
from haynes_studio.layered.drive import DriveTracks
from haynes_studio.layered.errors import LayeredError
from haynes_studio.layered.fake import FakeS2VSource
from haynes_studio.layered.keyed import KeyedFrames
from haynes_studio.layered.photo import PhotoInputs, compose_photo, photo_inputs
from haynes_studio.layered.renderer import COMPOSITOR, LayeredRenderer
from haynes_studio.layered.s2v import S2VClips
from haynes_studio.layered.source import S2VClip, S2VRequest, S2VSource

__all__ = [
    "COMPOSITOR", "DriveTracks", "FakeS2VSource", "KeyedFrames", "LayeredError",
    "LayeredRenderer", "LayeredStages", "PhotoInputs", "S2VClip", "S2VClips", "S2VRequest",
    "S2VSource", "check_board", "compose_photo", "photo_inputs", "reader",
]
