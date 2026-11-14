"""Story 428, step g: one read-only probe of the Wan service (legacy-adapters.md, "Before
the first live job", items 3 and 5). Submits nothing, uploads nothing, writes nothing: the
client loads the store's journal (a missing file is a first use and creates nothing) and
``probe()`` reads the API's health, the GPU sample and the engine queue.

    uv run python titles/the-winter-menu/e1-build/tools/probe.py STORE_ROOT
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

from haynes_studio.adapters.runner import SubprocessRunner
from haynes_studio.adapters.wan import FileJournal, WanClipClient
from haynes_studio.build.live import journal_path


def plain(value):
    if dataclasses.is_dataclass(value):
        return {f.name: plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    return value


def main(store_root: str) -> int:
    path = journal_path(Path(store_root))
    existed = path.exists(), path.with_name(path.name + ".lock").exists()
    journal = FileJournal(path)
    client = WanClipClient(SubprocessRunner(), journal=journal)
    probe = client.probe()
    report = {"journal": str(path), "journal_existed": existed[0], "lock_existed": existed[1],
              "in_flight": plain(WanClipClient.in_flight()), "halted": plain(WanClipClient.halted()),
              "journal_state": plain(journal.read_state()) if existed[0] else None,
              "probe": plain(probe)}
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
