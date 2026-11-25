"""Measure and place a cast matte using the silhouette rather than its padding."""

from dataclasses import dataclass
from fractions import Fraction

from PIL.Image import Image, Resampling

from haynes_studio.adapters.errors import AdapterError

ENGINE = "studio-matting"
SHAPE_INVALID = "matting.shape_invalid"
SIZE_POLICY = "studio.cast-matte-size/v1"


@dataclass(frozen=True)
class MatteSize:
    box: tuple[int, int, int, int]
    scale: Fraction

    @classmethod
    def measured(cls, shape: dict, canvas: tuple[int, int], target: int) -> "MatteSize":
        """Validate the verified alpha-128 measurement against the cast-size policy."""
        x0, y0, x1, y1 = shape["bbox_xyxy"]
        width, height = x1 - x0, y1 - y0
        area = shape["foreground_area_px"]
        scale = Fraction(target, height)
        if x0 == 0 or y0 == 0 or x1 == canvas[0] or y1 == canvas[1]:
            reason = "The alpha-128 silhouette reaches the input frame edge"
        elif height < 64 or scale > 4:
            reason = "The silhouette is too small for the requested cast height"
        elif width * 4 < height or width > height * 2 or area * 4 < width * height:
            reason = "The silhouette aspect or filled area is implausible for a cast slot"
        else:
            return cls((x0, y0, x1, y1), scale)
        raise AdapterError(SHAPE_INVALID, "matting.size", reason)

    def sprite(self, image: Image) -> tuple[Image, tuple[int, int], tuple[int, int]]:
        """Return the resized sprite, its silhouette size and its inset from the sprite origin."""
        support, size, silhouette, inset = self.geometry(image)
        return image.crop(support).resize(size, Resampling.LANCZOS), silhouette, inset

    def geometry(self, image: Image):
        """Return the source crop, size, silhouette and inset of this sprite."""
        x0, y0, x1, y1 = self.box
        # Trimming transparent padding is lossless. Keep all nonzero alpha,
        # including fractional hair below the measurement threshold.
        support = image.getchannel("A").getbbox()
        left, top, right, bottom = support
        width = max(1, round((x1 - x0) * self.scale))
        height = round((y1 - y0) * self.scale)
        inset_x = round((x0 - left) * self.scale)
        inset_y = round((y0 - top) * self.scale)
        size = (inset_x + width + round((right - x1) * self.scale),
                inset_y + height + round((bottom - y1) * self.scale))
        return support, size, (width, height), (inset_x, inset_y)
