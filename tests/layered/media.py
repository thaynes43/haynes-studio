"""Synthetic media for the layered tests, drawn in memory at test time: a doll on green
with a lettered jacket that moves by a known offset, set loops, cutout stills and
takes. Nothing is read from disk; nothing here is committed media.

A doll frame carries its frame number in a strip of bars on the doll's skirt
(:func:`read_number`), so a composited board frame says which source frame each layer
showed, after keying, scaling and H.264 encoding."""

from __future__ import annotations

import io
import math
import wave

import numpy as np
import PIL.Image
import PIL.ImageDraw

from haynes_studio.render.encode import EncoderSettings, encode_segment

GREEN = (40, 200, 60)
JACKET = (40, 60, 160)
YELLOW = (240, 210, 40)
SKIN = (230, 180, 150)
BITS = 7  # frame numbers up to 127 in the skirt strip
CLIP_W, CLIP_H = 144, 256  # a small doll clip (9:16)
DECAL_BOX = (44, 150, 100, 172)  # the lettering, in clip pixels at offset 0
BADGE = (66, 126, 78, 136)  # a green badge deep in the jacket, in clip pixels at offset 0
PROTECT = (60, 120, 84, 142)  # a protect box around the badge
STRIP_Y = 216  # the frame-number bars


def letters(draw: PIL.ImageDraw.ImageDraw, x: int, y: int) -> None:
    """Blocky yellow letters (no font needed): a row of bars and boxes."""
    for i in range(5):
        x0 = x + 2 + i * 11
        draw.rectangle((x0, y + 4, x0 + 7, y + 6), fill=YELLOW)
        draw.rectangle((x0, y + 4, x0 + 2, y + 17), fill=YELLOW)
        draw.rectangle((x0 + 5, y + 4 + (i % 3) * 4, x0 + 7, y + 17), fill=YELLOW)


def doll_frame(number: int, *, dx: int = 0, dy: int = 0, garble: bool = False, tint: int = 0,
               width: int = CLIP_W, height: int = CLIP_H, badge: bool = True) -> np.ndarray:
    """One frame of a doll on green: head, jacket with lettering, a skirt strip with
    ``number`` in bars. ``dx``, ``dy`` move the whole doll; ``garble`` scrambles the
    jacket's own lettering (what the engine does), ``tint`` shifts the jacket colour."""
    image = PIL.Image.new("RGB", (width, height), GREEN)
    draw = PIL.ImageDraw.Draw(image)
    sx, sy = width / CLIP_W, height / CLIP_H
    def box(x0, y0, x1, y1):
        return (round((x0 + dx) * sx), round((y0 + dy) * sy), round((x1 + dx) * sx), round((y1 + dy) * sy))
    draw.ellipse(box(50, 40, 94, 96), fill=SKIN)
    draw.rectangle(box(36, 96, 108, 190), fill=(JACKET[0] + tint, JACKET[1], JACKET[2]))
    if badge:  # a painted green badge: keyed away unless a protect box keeps it
        draw.rectangle(box(*BADGE), fill=GREEN)
    if garble:  # the engine's own lettering: blobs where the letters were
        draw.rectangle(box(46, 152, 72, 170), fill=YELLOW)
        draw.rectangle(box(78, 150, 98, 171), fill=YELLOW)
    else:
        letters(draw, round((DECAL_BOX[0] + dx) * sx), round((DECAL_BOX[1] + dy) * sy))
    draw.rectangle(box(40, 190, 104, 252), fill=(210, 210, 210))
    for bit in range(BITS):  # below the decal's tracked area (the box grown by 40 px)
        on = (number >> (BITS - 1 - bit)) & 1
        x0 = 42 + bit * 9
        draw.rectangle(box(x0, STRIP_Y, x0 + 7, STRIP_Y + 30), fill=(20, 20, 20) if on else (250, 250, 250))
    return np.asarray(image)


def read_number(rgb: np.ndarray, x: float, y: float, cell: float) -> int:
    """The frame number of a doll whose skirt strip starts at (``x``, ``y``) with bars
    ``cell`` pixels apart: dark bars are ones."""
    value = 0
    for bit in range(BITS):
        px, py = round(x + (bit * 9 + 3.5) * cell), round(y)
        dark = rgb[py - 1:py + 2, px - 1:px + 2].mean() < 128
        value = value << 1 | int(dark)
    return value


def encode(frames: list[np.ndarray], fps: int) -> bytes:
    height, width = frames[0].shape[:2]
    return encode_segment(iter(frames), frames_expected=len(frames), width=width, height=height,
                          fps=fps, settings=EncoderSettings())


def sway(n: int) -> int:
    """The doll's known sideways offset at clip frame ``n``."""
    return round(3 * math.sin(n / 3))


def doll_clip(count: int, *, fps: int = 24, moving: bool = True, garble: bool = True,
              weak: bool = False, tint: int = 0) -> bytes:
    """A doll clip of ``count`` frames that sways sideways by :func:`sway`; frame 0 is
    the start image. ``weak`` paints new stripes across the jacket on every frame, so
    the decal track scores below the 0.8 floor (about 0.66)."""
    frames = []
    for n in range(count):
        frame = doll_frame(n, dx=sway(n) if moving else 0, garble=garble and n > 0, tint=tint)
        if weak and n:
            frame = frame.copy()
            rows = np.arange(110, 212)
            frame[rows[(rows + 7 * n) % 12 < 2], 36:108] = (250, 250, 250)
        frames.append(frame)
    return encode(frames, fps)


def start_image(**kwargs) -> bytes:
    """The doll's start image (frame 0, clean lettering), as PNG."""
    return png(doll_frame(0, **kwargs))


def set_frame(number: int, width: int = 180, height: int = 320) -> np.ndarray:
    """A set: a warm gradient and a moving sun whose x is the frame number."""
    frame = np.zeros((height, width, 3), np.uint8)
    frame[..., 0] = np.linspace(120, 200, height, dtype=np.uint8)[:, None]
    frame[..., 1] = 90
    frame[..., 2] = np.linspace(60, 30, width, dtype=np.uint8)[None, :]
    x = 8 + number * 2
    frame[20:36, x:x + 16] = (250, 240, 200)
    return frame


def set_clip(count: int, fps: int = 24) -> bytes:
    return encode([set_frame(n) for n in range(count)], fps)


def sun_x(rgb: np.ndarray, scale: float, row: float = 28) -> float:
    """Where the set's sun is in a board frame (its left edge, in set pixels)."""
    line = rgb[round(row * scale), :, :].astype(int)
    bright = np.nonzero((line[:, 0] > 235) & (line[:, 1] > 225) & (line[:, 2] > 180))[0]
    return float(bright.min()) / scale if bright.size else -1.0


def set_plate() -> bytes:
    return png(set_frame(40))


def cutout(colour=(200, 60, 60), width: int = 120, height: int = 240) -> bytes:
    """A cast still: an RGBA cutout with a transparent border (an ``rgba_cutout``)."""
    image = PIL.Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = PIL.ImageDraw.Draw(image)
    draw.rectangle((20, 20, width - 20, height - 10), fill=(*colour, 255))
    return png_rgba(image)


def png(rgb: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    PIL.Image.fromarray(np.ascontiguousarray(rgb)).save(buffer, format="PNG")
    return buffer.getvalue()


def png_rgba(image: PIL.Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def wav(samples: np.ndarray, rate: int = 24_000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(np.asarray(samples, dtype="<i2").tobytes())
    return buffer.getvalue()


def take(duration_ms: int, *, rate: int = 24_000, pitch: float = 220.0, seed: int = 0) -> bytes:
    """A take of ``duration_ms``: a tone whose loudness pulses at 4 Hz (syllables)."""
    count = duration_ms * rate // 1000
    t = np.arange(count) / rate
    envelope = 0.5 + 0.5 * np.sin(2 * np.pi * 4 * t + seed)
    return wav((8000 * envelope * np.sin(2 * np.pi * pitch * t)).astype(np.int16), rate)
