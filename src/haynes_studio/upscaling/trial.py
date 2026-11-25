"""Shared local client for synthetic fixtures and one private still."""

import os
from pathlib import Path
from shutil import rmtree
from uuid import uuid4

from PIL import Image

from .backend import REQUEST_SCHEMA, verify_result
from .files import create_file, open_directory, read_file
from .pixels import describe, encode_png
from .profile import COMMAND_FAILED, MAX_INPUT, MAX_OUTPUT, PROFILE_ID, REQUEST_INVALID, RESPONSE_INVALID, UpscaleError
from .service import local_call


def stage(scratch: Path, data: bytes, size, target, digest: str) -> dict:
    if not 0 < len(data) <= MAX_INPUT:
        raise UpscaleError(REQUEST_INVALID)
    attempt = uuid4().hex
    run = scratch / attempt
    run.mkdir(mode=0o770)
    with open_directory(run) as directory:
        # The dormant sidecar uses a different UID with the same scratch GID.
        os.fchmod(directory, 0o2770)
        create_file(directory, "input.png", data)
    return {"attempt_id": attempt, "request": {
        "schema": REQUEST_SCHEMA, "source": describe(data, size),
        "target": {"width": target[0], "height": target[1]},
        "profile_id": PROFILE_ID, "profile_sha256": digest,
    }}


def frame(root: Path, socket: Path, rgb: Image.Image, size, profile, digest: str):
    value = stage(root, encode_png(rgb), rgb.size, size, digest)
    try:
        status, receipt = local_call(socket, "POST", "/v1/upscale-frame", value)
        if status != 200:
            raise UpscaleError(receipt.get("code", COMMAND_FAILED))
        with open_directory(root / value["attempt_id"] / "result") as directory:
            png = read_file(directory, "output.png", MAX_OUTPUT, RESPONSE_INVALID)
        verify_result(value["request"], receipt, png, profile)
        return png, receipt
    finally:
        # Scratch is specific to this client run. Per-frame cleanup lets the
        # bounded smoke finish without growing scratch with frame count.
        rmtree(root / value["attempt_id"])
