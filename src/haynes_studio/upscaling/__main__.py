"""Local profile, staged service, install smoke and separate private comparison."""

from __future__ import annotations

import argparse
import signal
from hashlib import sha256
from http.client import HTTPException
from pathlib import Path
from threading import Event

from haynes_studio.store import canonical_json

from .profile import COMMAND_FAILED, NOT_FOUND, PROFILE_ID, PROVIDER, RESOURCES, TARGETS, Profile, UpscaleError


def _serve(scratch, weights):
    from .backend import Engine
    from .service import UpscaleServer

    if RESOURCES["serving"] is None:
        raise UpscaleError(NOT_FOUND)
    stopping = Event()

    def stop(_signal, _frame):
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with Engine(scratch, weights, Profile.installed()) as engine:
        with UpscaleServer(scratch / "upscale.sock", engine) as server:
            server.timeout = 0.25
            while not stopping.is_set():
                server.handle_request()


class _Parser(argparse.ArgumentParser):
    def error(self, _message):
        # argparse can echo an invalid argument, including an input share path.
        self.exit(2, '{"code":"adapter.request_invalid"}\n')


def main() -> int:
    parser = _Parser(prog="studio-upscaling")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve")
    commands.add_parser("ready")
    commands.add_parser("profile")
    measure = commands.add_parser("smoke")
    measure.add_argument("--allocator", choices=("compare", "default"), default="compare")
    trial = commands.add_parser("compare")
    trial.add_argument("--input", required=True, help="Relative path on the read-only Studio share")
    trial.add_argument("--input-sha256", required=True)
    trial.add_argument("--allocation", required=True)
    trial.add_argument("--orientation", choices=("portrait", "landscape"), default="portrait")
    trial.add_argument("--plate", action="store_true", help="Center-crop to the target aspect before scaling")
    for name in ("lettering", "face", "hair"):
        trial.add_argument(f"--{name}-roi", nargs=4, type=int, metavar=("X0", "Y0", "X1", "Y1"))

    args = parser.parse_args()
    scratch, weights = Path("/upscaling"), Path("/weights")
    try:
        if args.command == "serve":
            _serve(scratch, weights)
            return 0
        if args.command == "ready":
            from .service import local_call

            status, ready = local_call(scratch / "upscale.sock", "GET", "/v1/ready", timeout=2)
            return int(status != 200 or ready.get("profile_id") != PROFILE_ID or ready.get("provider") != PROVIDER)
        profile = Profile.installed()
        if args.command == "profile":
            manifest = profile.manifest()
            report = {"manifest": manifest.decode(), "sha256": sha256(manifest).hexdigest()}
        elif args.command == "smoke":
            from .smoke import smoke

            report = smoke(scratch, weights, profile, try_compact=args.allocator == "compare")
        else:
            from .comparison import compare

            rois = {name: box for name in ("lettering", "face", "hair")
                    if (box := getattr(args, name + "_roi")) is not None}
            report = compare(
                scratch, weights, Path("/studio-source"), Path("/jobs"), profile,
                relative=args.input, source_sha256=args.input_sha256, allocation=args.allocation,
                target=TARGETS[0] if args.orientation == "portrait" else TARGETS[1], plate=args.plate, rois=rois,
            )
        print(canonical_json(report).decode(), flush=True)
        return int(args.command == "smoke" and not report["passed"])
    except (UpscaleError, OSError, HTTPException) as error:
        # Logs contain no caller paths, exception text or private pixels.
        print(canonical_json({"code": getattr(error, "code", COMMAND_FAILED)}).decode(), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
