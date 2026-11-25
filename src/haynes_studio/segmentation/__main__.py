"""Local serving, readiness, release identity, and offline install smoke."""

from __future__ import annotations

import argparse
import os
import signal
from threading import Event

from haynes_studio.store import canonical_json

from .profile import SCRATCH, SERVING_PROFILE_ID, WEIGHT_LOAD, WEIGHTS, Profile, SegmentationError, digest


def _serve():
    from .backend import Engine
    from .service import Server

    stopping = Event()

    def stop(_signal, _frame):
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    os.nice(10)
    with Engine(SCRATCH, WEIGHTS, Profile.installed()) as engine:
        with Server(SCRATCH / "segment.sock", engine) as server:
            server.timeout = 0.25
            while not stopping.is_set():
                server.handle_request()


def main() -> int:
    parser = argparse.ArgumentParser(prog="studio-segmentation")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("serve", "ready", "profile"):
        commands.add_parser(name)
    smoke_command = commands.add_parser("smoke")
    smoke_command.add_argument("--load-strategy", choices=("mmap", "buffered"),
                               help="measure an explicit load strategy instead of serving")
    smoke_command.add_argument("--compare-load-strategy", choices=("mmap", "buffered"),
                               help="measure this strategy in a second worker and compare outputs")
    args = parser.parse_args()
    try:
        if args.command == "serve":
            _serve()
        elif args.command == "ready":
            from .service import local_call

            status, report = local_call(SCRATCH / "segment.sock", "GET", "/v1/ready", timeout=2)
            return int(
                status != 200 or report.get("profile_id") != SERVING_PROFILE_ID or report.get("device") != "cpu"
            )
        elif args.command == "profile":
            manifest = Profile.installed().manifest()
            print(canonical_json({"manifest": manifest.decode(), "sha256": digest(manifest)}).decode())
        else:
            from .smoke import smoke

            strategies = (args.load_strategy or WEIGHT_LOAD,)
            if args.compare_load_strategy:
                if args.compare_load_strategy == strategies[0]:
                    smoke_command.error("compare-load-strategy must differ from load-strategy")
                strategies += (args.compare_load_strategy,)
            measuring = bool(args.load_strategy or args.compare_load_strategy)
            os.nice(10)
            report = smoke(SCRATCH, WEIGHTS, strategies if measuring else ())
            print(canonical_json(report).decode(), flush=True)
            return int(not report["passed"])
    except (OSError, SegmentationError, ValueError) as error:
        print(canonical_json({"code": getattr(error, "reason", "profile_unavailable")}).decode(), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
