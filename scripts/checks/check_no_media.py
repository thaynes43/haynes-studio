#!/usr/bin/env python3
"""Fail if any tracked file has a media or model-weight extension.

The extension list is the video, audio, image, subtitle and model-weight
groups in .gitignore. Comparison is case-insensitive. Text formats such as
.json, .md, .py and .html are not media.
"""

import subprocess
import sys
from pathlib import Path

# Source: .gitignore (video, audio, image, subtitle and model-weight groups).
MEDIA_EXTENSIONS = (
    '.aac',
    '.aif',
    '.aiff',
    '.ass',
    '.avi',
    '.avif',
    '.bin',
    '.bmp',
    '.ckpt',
    '.exr',
    '.flac',
    '.gguf',
    '.gif',
    '.heic',
    '.heif',
    '.jpeg',
    '.jpg',
    '.m4a',
    '.m4v',
    '.mkv',
    '.mov',
    '.mp3',
    '.mp4',
    '.mpeg',
    '.mpg',
    '.ogg',
    '.onnx',
    '.opus',
    '.png',
    '.psd',
    '.pt',
    '.pth',
    '.safetensors',
    '.srt',
    '.ssa',
    '.sub',
    '.tif',
    '.tiff',
    '.vtt',
    '.wav',
    '.webm',
    '.webp',
    '.y4m',
)


def main(argv=None):
    if argv is None:
        argv = sys.argv
    root = argv[1] if len(argv) > 1 else '.'
    listed = subprocess.run(
        ['git', '-C', root, 'ls-files', '-z'],
        capture_output=True,
    )
    if listed.returncode != 0:
        sys.stderr.buffer.write(listed.stderr)
        return 1
    failed = False
    for raw in listed.stdout.split(b'\0'):
        if not raw:
            continue
        rel = raw.decode('utf-8', 'surrogateescape')
        ext = Path(rel).suffix.lower()
        if ext in MEDIA_EXTENSIONS:
            print(f'{rel}: tracked file has media or model-weight extension {ext}')
            failed = True
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
