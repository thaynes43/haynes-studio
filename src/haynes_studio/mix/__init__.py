"""The film's sound and its master (story 841, contract v1 sections 3, 4 and 6).

- :mod:`.mixer`: the mix as a pure function of the mix key's inputs, and its placement
  record (ported from the legacy ``poc/edit.py`` ``audio``).
- :mod:`.master`: the film picture and the mix muxed into one checked MP4.
- :mod:`.checks`: loudness, true peak, clipping and mix length as check results.
- :mod:`.build`: :class:`~.build.SoundBuilder`, the mix and the master through the
  cache, and :func:`~.build.film_sound` for a run.
- :mod:`.audio`: decoding, filters (two threads), the R128 meter and 24-bit WAV.

Reference: ``docs/reference/studio-mix.md``.
"""

from __future__ import annotations

from haynes_studio.mix.build import (
    CheckResult,
    FilmSound,
    SoundBuilder,
    board_ranges,
    check_cues,
    film_sound,
    label_placement,
    placement_key,
    sound_toolchain,
    store_reader,
)
from haynes_studio.mix.errors import MixError
from haynes_studio.mix.master import MUX, MasterResult, MuxSettings, mux
from haynes_studio.mix.mixer import MIXER, MixerSettings, MixResult, mix, planned_starts

__all__ = [
    "CheckResult", "FilmSound", "MIXER", "MUX", "MasterResult", "MixError", "MixResult",
    "MixerSettings", "MuxSettings", "SoundBuilder", "board_ranges", "check_cues", "film_sound",
    "label_placement", "mix", "mux", "placement_key", "planned_starts", "sound_toolchain",
    "store_reader",
]
