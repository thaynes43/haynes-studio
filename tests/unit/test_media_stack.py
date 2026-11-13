"""The media libraries of the stack pin (contract section 13) are locked and usable."""

from __future__ import annotations

import os


def test_the_media_libraries_import_and_can_encode():
    import av
    import imageio_ffmpeg
    import numpy
    import PIL

    assert numpy.__version__ and PIL.__version__ and av.__version__
    # The master and the phone proxy are H.264 with AAC (contract section 8).
    assert "libx264" in av.codecs_available and "aac" in av.codecs_available
    # Session pods have no system ffmpeg; the wheel carries one.
    assert os.path.exists(imageio_ffmpeg.get_ffmpeg_exe())
