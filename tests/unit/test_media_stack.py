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


def test_the_keying_and_decal_libraries_import_and_work():
    """Story 426 ports the PoC's chroma key (scipy.ndimage) and tracked decal (OpenCV)."""
    import cv2
    import numpy
    from scipy import ndimage

    grid = numpy.zeros((8, 8), numpy.uint8)
    grid[1:3, 1:3] = 1
    grid[5:7, 4:7] = 1
    labels, count = ndimage.label(grid)
    assert count == 2 and labels.shape == grid.shape
    # The calls poc/decal.py makes.
    for name in ("findTransformECC", "warpAffine", "inpaint", "GaussianBlur", "dilate"):
        assert callable(getattr(cv2, name))
    blurred = cv2.GaussianBlur(grid.astype(numpy.float32), (0, 0), 1.0)
    assert blurred.shape == grid.shape
