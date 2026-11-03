"""Lay out candidate images in a labelled grid for review (runbook stage 2).

    ~/.cache/studio-venv/bin/python poc/contact_sheet.py OUT.jpg A.png B.png ... [--cols 4]

Cutouts with transparency are shown over a mid-gray checker so their edges are visible.
"""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS', '2')  # CPU rule in AGENTS.md; set before numpy loads
import argparse
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

CELL_W, CELL_H, LABEL = 420, 560, 34


def checker(size, n=16):
    im = Image.new('RGB', size, (128, 128, 128))
    d = ImageDraw.Draw(im)
    for y in range(0, size[1], n):
        for x in range((y // n % 2) * n, size[0], 2 * n):
            d.rectangle([x, y, x + n - 1, y + n - 1], fill=(150, 150, 150))
    return im


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out'); ap.add_argument('images', nargs='+'); ap.add_argument('--cols', type=int, default=4)
    a = ap.parse_args()
    cols = min(a.cols, len(a.images)); rows = -(-len(a.images) // cols)
    sheet = Image.new('RGB', (cols * CELL_W, rows * (CELL_H + LABEL)), (20, 20, 20))
    font = ImageFont.load_default(size=22)
    for i, path in enumerate(a.images):
        im = Image.open(path)
        im.thumbnail((CELL_W - 10, CELL_H - 10), Image.Resampling.LANCZOS)
        x, y = (i % cols) * CELL_W, (i // cols) * (CELL_H + LABEL)
        if im.mode == 'RGBA':
            bg = checker(im.size); bg.paste(im, mask=im.getchannel('A')); im = bg
        sheet.paste(im.convert('RGB'), (x + (CELL_W - im.width) // 2, y + (CELL_H - im.height) // 2))
        ImageDraw.Draw(sheet).text((x + 8, y + CELL_H + 4), f'{i + 1}. {Path(path).stem}', fill=(240, 240, 240), font=font)
    sheet.save(a.out, quality=88)
    print(a.out, sheet.size)


if __name__ == '__main__':
    main()
