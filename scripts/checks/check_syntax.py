#!/usr/bin/env python3
"""Compile tracked PoC Python and parse tracked title, graph and contract-example JSON
without running it."""

import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True
        )
    except (OSError, subprocess.CalledProcessError) as error:
        reason = (
            error.stderr.decode(errors="replace")
            if isinstance(error, subprocess.CalledProcessError) else str(error)
        )
        print(f"git ls-files: {(reason or str(error)).splitlines()[0]}")
        return 1

    failed = False
    python_count = json_count = 0
    for name in result.stdout.split(b"\0"):
        path = os.fsdecode(name)
        is_python = path.startswith("poc/") and path.endswith(".py")
        is_json = path.startswith(
            ("titles/", "poc/graphs/", "docs/contracts/examples/")
        ) and path.endswith(".json")
        if not (is_python or is_json):
            continue
        try:
            if is_python:
                python_count += 1
                compile((root / path).read_bytes(), path, "exec")
            else:
                json_count += 1
                with (root / path).open("rb") as source:
                    json.load(source)
        except (SyntaxError, ValueError, OSError) as error:
            print(f"{path}: {str(error).splitlines()[0]}")
            failed = True

    if not failed:
        print(f"Checked {python_count} Python files and {json_count} JSON files.")
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
