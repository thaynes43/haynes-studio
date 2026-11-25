"""Local serving, readiness, provisioning identity and bounded install smoke."""

from __future__ import annotations

import argparse
import signal
import sys
from hashlib import sha256
from pathlib import Path
from threading import Event

from haynes_studio.store import canonical_json

from .profile import COMMAND_FAILED, PROFILE_ID, PROVIDER, MatteError, Profile, SessionSettings


def _serve(scratch: Path, weights: Path) -> None:
    from .backend import Engine
    from .service import MatteServer

    stopping = Event()

    def stop(_signal, _frame):
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with Engine(scratch, weights, Profile.installed()) as engine:
        with MatteServer(scratch / "matte.sock", engine) as server:
            server.timeout = 0.25
            while not stopping.is_set():
                server.handle_request()


def main() -> int:
    parser = argparse.ArgumentParser(prog="studio-matting")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve")
    commands.add_parser("ready")
    measure = commands.add_parser("smoke")
    defaults = SessionSettings()
    measure.add_argument("--cpu-arena", action=argparse.BooleanOptionalAction, default=defaults.cpu_arena)
    measure.add_argument("--no-memory-pattern", dest="memory_pattern", action="store_false",
                         default=defaults.memory_pattern)
    measure.add_argument("--graph-optimization", choices=("all", "extended", "basic", "disabled"),
                         default=defaults.graph_optimization)
    measure.add_argument("--arena-growth", choices=("default", "same-as-requested"),
                         default=defaults.arena_growth)
    measure.add_argument("--shrink-cpu-arena", action="store_true", default=defaults.shrink_cpu_arena)
    commands.add_parser("profile")
    args = parser.parse_args()
    scratch, weights = Path("/matting"), Path("/weights")
    try:
        if args.command == "serve":
            _serve(scratch, weights)
        elif args.command == "ready":
            from .service import local_call

            status, ready = local_call(scratch / "matte.sock", "GET", "/v1/ready", timeout=2)
            return int(status != 200 or ready.get("profile_id") != PROFILE_ID
                       or ready.get("provider") != PROVIDER)
        elif args.command == "profile":
            manifest = Profile.installed().manifest()
            print(canonical_json({"manifest": manifest.decode(), "sha256": sha256(manifest).hexdigest()}).decode())
        else:
            from .smoke import smoke

            if not args.cpu_arena and (args.arena_growth != "default" or args.shrink_cpu_arena):
                measure.error("arena growth and shrinkage require the CPU arena")
            settings = SessionSettings(
                cpu_arena=args.cpu_arena, memory_pattern=args.memory_pattern,
                graph_optimization=args.graph_optimization, arena_growth=args.arena_growth,
                shrink_cpu_arena=args.shrink_cpu_arena,
            )
            report = smoke(scratch, weights, settings)
            print(canonical_json(report).decode(), flush=True)
            return 0 if report["passed"] else 1
    except (MatteError, OSError) as error:
        print(canonical_json({"code": getattr(error, "code", COMMAND_FAILED)}).decode(), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
