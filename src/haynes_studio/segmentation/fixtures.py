"""Deterministic synthetic fixtures for the bounded install smoke."""

from dataclasses import dataclass
from io import BytesIO

import numpy as np
from PIL import Image, ImageDraw

from .pixels import tight_box
from .profile import PROFILE_ID, digest

SIZE = (1080, 1920)
PLANE = [(80, 900), (1000, 900), (1080, 1920), (0, 1920)]
BACKGROUND = (32, 40, 56)


@dataclass(frozen=True)
class Fixture:
    image: Image.Image
    truth: np.ndarray
    kind: str
    label: str | None
    hint: dict | None

    def request(self, name):
        with BytesIO() as buffer:
            self.image.save(buffer, "PNG", compress_level=6)
            data = buffer.getvalue()
        return data, {
            "schema": "studio.segmentation-request/v1", "profile": PROFILE_ID,
            "input": {"sha256": digest(data), "width": self.image.width, "height": self.image.height},
            "target": {"kind": self.kind, "key": name, "label": self.label}, "hint": self.hint,
        }


def _disk(center, rgb):
    x, y = center
    radius = 70
    distances = np.arange(-radius, radius + 1) ** 2
    squared = distances[:, None] + distances[None, :]
    ball = squared <= radius**2
    shade = 0.65 + 0.35 * np.sqrt(np.maximum(0, 1 - squared / radius**2))
    pixels = np.zeros((*ball.shape, 4), dtype=np.uint8)
    pixels[ball, :3] = np.rint(shade[ball, None] * rgb).astype(np.uint8)
    pixels[ball, 3] = 255
    image = Image.new("RGBA", SIZE)
    image.paste(Image.fromarray(pixels), (x - radius, y - radius))
    truth = np.asarray(image.getchannel("A")) != 0
    return image, truth


def fixtures() -> dict[str, Fixture]:
    width, height = SIZE
    shape = Image.new("1", SIZE)
    ImageDraw.Draw(shape).polygon(PLANE, fill=1)
    foreground = np.asarray(shape)
    rows, columns = np.ogrid[:height, :width]
    checker = 168 + (columns // 16 + rows // 16) % 2 * 16
    plate = np.empty((height, width, 3), dtype=np.uint8)
    plate[:] = BACKGROUND
    plate[foreground] = (168, 120, 72)
    plate[..., 0][foreground] = checker[foreground]
    visible, face = _disk((300, 700), (255, 140, 24))
    hidden, prop = _disk((600, 1200), (56, 220, 64))
    return {
        "foreground": Fixture(Image.fromarray(plate), foreground, "foreground", None,
                              {"kind": "box", "xyxy": tight_box(foreground)}),
        "visible_face": Fixture(visible, face, "face", None, {"kind": "box", "xyxy": tight_box(face)}),
        "hidden_prop": Fixture(hidden, prop, "prop", "green ball", {"kind": "box", "xyxy": tight_box(prop)}),
        "point": Fixture(visible, face, "face", None, {"kind": "point", "xy": [300, 700]}),
        "grounded_ball": Fixture(visible, face, "prop", "orange ball", None),
        "absent_gavel": Fixture(Image.new("RGB", SIZE, BACKGROUND), np.zeros((height, width), dtype=bool),
                                "prop", "gavel", None),
    }


def visible_fraction(subject: np.ndarray, foreground: np.ndarray) -> float:
    return float(np.count_nonzero(subject & ~foreground) / np.count_nonzero(subject))
