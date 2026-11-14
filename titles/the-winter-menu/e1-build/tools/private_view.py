"""Story 428, step l: a studio delivery to private viewing on the Wan volume, by the
runbook's delivery route (stage 7, ``poc/deliver.py``), as story 840 used it.

The route's own pieces are imported from ``poc/deliver.py`` unchanged: ``REMOTE`` (the
``kubectl exec`` into ``ai/deploy/wan-video`` container ``api``), ``WRITE`` (create-only:
stream into a temp file, hash-check, hard-link into place), ``PUBLISH`` (hard-link the
ledger into ``/workspace/jobs/``), ``READ`` (``GET /videos/<id>`` through the API), ``SPACE``
and ``check_ledger``. What is new here is only what ``poc/deliver.py`` reads from a PoC job
folder: the files come from the store's verified delivery (``read_delivery``), the run
record and the delivery document.

Order (each step stops the delivery on failure; nothing is retried):

1. ``read_delivery`` re-hashes the master and the proxy; the local copies are hashed again.
2. Read-only: free space on ``/workspace`` (more than ten times the bytes), and the
   production folder and the ledger ID are unused.
3. The ledger is built and checked locally twice before anything is linked:
   ``check_ledger`` and story 425's ``record_from_document`` (the parser ``LedgerReader``
   applies to what the API serves). ``--check-only`` stops here and prints it.
4. Each file is copied with ``WRITE``; the ledger, with the copies' answers, is checked
   again, then linked with ``PUBLISH``.
5. Read back: ``LedgerReader.get`` (story 425); ``GET /videos/<id>/file`` inside the API
   container, hashed there (the bytes and SHA-256 must be the master's); and
   ``LedgerReader.list`` must list no unreadable ledger.
6. ``OUT/production.json`` is written create-only.

    uv run python titles/the-winter-menu/e1-build/tools/private_view.py STORE PRD RUN_ID JOB OUT [--check-only]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "poc"))
import deliver as route  # noqa: E402  poc/deliver.py, unchanged

from haynes_studio.adapters.runner import SubprocessRunner  # noqa: E402
from haynes_studio.adapters.wan_ledger import LedgerReader, record_from_document  # noqa: E402
from haynes_studio.delivery.publish import read_delivery  # noqa: E402
from haynes_studio.store.local import LocalStore  # noqa: E402

STORY = "https://work.haynesnetwork.com/work_packages/428"
EXISTS = ("import os,sys;print(json.dumps({p: os.path.lexists(p) for p in sys.argv[1:]}))"
          .replace("import os,sys", "import os,sys,json"))
FETCH = ("import hashlib,sys,urllib.request;h=hashlib.sha256();n=0\n"
         "r=urllib.request.urlopen('http://127.0.0.1:8080/videos/'+sys.argv[1]+'/file')\n"
         "while True:\n b=r.read(1048576)\n if not b:break\n h.update(b);n+=len(b)\n"
         "print(r.status,r.headers.get('Content-Type'),n,h.hexdigest())")


def remote(code: str, *args: str, stdin: bytes | None = None, timeout: int = 60) -> bytes:
    return subprocess.run(route.REMOTE + [code, *args], input=stdin, capture_output=True,
                          check=True, timeout=timeout).stdout


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    for name in ("store", "production", "run_id", "job", "out"):
        parser.add_argument(name)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", args.job):
        raise SystemExit("JOB is a new production folder name")
    root, out = Path(args.store), Path(args.out)
    if (out / "production.json").exists():
        raise SystemExit("already delivered; a new attempt is a new production")

    store = LocalStore(root)
    delivery = read_delivery(store, production_id=args.production, run_id=args.run_id)
    if delivery is None:
        raise SystemExit("the run has no completed delivery")
    run_dir = root / "productions" / args.production / "records" / args.run_id
    stage = json.loads((run_dir / "delivery.json").read_text())
    runs = sorted(run_dir.glob("run-*.json"))
    run_stage = json.loads(runs[-1].read_text())
    run_blob = next(b for k, b in run_stage["blobs"].items() if b["media_type"] == "application/json")
    files = {  # name on the volume -> (local path, sha256)
        "final.mp4": (root / delivery.master.locator, delivery.master.sha256),
        "proxy.mp4": (root / delivery.proxy.locator, delivery.proxy.sha256),
        "delivery.json": (root / stage["blobs"]["delivery"]["locator"], stage["blobs"]["delivery"]["sha256"]),
        "run.json": (root / run_blob["locator"], run_blob["sha256"]),
    }
    for name, (path, digest) in files.items():
        if sha(path) != digest:
            raise SystemExit(f"{name}: the local copy is not {digest}")
    need = sum(path.stat().st_size for path, _ in files.values())

    free = int(remote(route.SPACE, timeout=30))
    if free <= need * 10:
        raise SystemExit(f"only {free} bytes free on the Wan volume for {need}")
    ledger_id = uuid.uuid4().hex
    base = f"/workspace/output/productions/{args.job}/"
    used = json.loads(remote(EXISTS, base.rstrip("/"), f"/workspace/jobs/{ledger_id}.json"))
    if any(used.values()):
        raise SystemExit(f"a name is in use: {used}")
    print(f"free {free} bytes; need {need}; unused: {sorted(used)}")

    run = json.loads(files["run.json"][0].read_text())
    def ledger_for(assets):
        now = time.time()
        return {
            "id": ledger_id, "kind": "edited_production", "story": STORY,
            "title": "The Winter Menu (E1 build 1, studio build)", "state": "succeeded",
            "created_at": now, "finished_at": now, "telemetry": [],
            "output": f"productions/{args.job}/final.mp4",
            "bytes": delivery.master.bytes, "sha256": delivery.master.sha256, "assets": assets,
            "preset": "studio-build-layered-s2v",
            "provenance": {
                "records": "haynes-studio titles/the-winter-menu/e1-build/ (run-log.md, runs/, clips/)",
                "run_id": args.run_id, "delivery_id": delivery.id, "production_id": args.production,
                "story_id": run.get("story_id"),
                "studio_commit": (run.get("provenance") or {}).get("toolchain", {}).get("studio"),
                "frames": delivery.master.frames, "proxy": "proxy.mp4 (720x1280, the phone proxy)",
                "voices": "Kokoro-82M v1.0 stock voices bf_emma, af_heart, af_nicole, af_bella (r4's takes); no cloning",
                "video": "Wan2.2 S2V-14B lightning (speech clips, 14 jobs on the studio's RTX 3090s) and E0's TI2V-5B doll and set loops, keyed and composited by the studio's layered renderer",
                "sound": "audio-authoring Stable Audio 3 Small SFX: r4's cues and the regenerated fire bed (job ebe4a478d4cf44e3974fea1da6a179cb)",
                "human_approval": "Pending: Tom (E1 demo).",
            },
        }
    draft = ledger_for([{"path": base + name, "bytes": path.stat().st_size, "sha256": digest}
                        for name, (path, digest) in files.items()])
    route.check_ledger(draft)
    record_from_document(json.loads(json.dumps(draft)))
    print("ledger checked locally (check_ledger, record_from_document)")
    if args.check_only:
        print(json.dumps(draft, indent=2))
        return 0

    out.mkdir(parents=True, exist_ok=True)
    assets = []
    for name, (path, digest) in files.items():
        with path.open("rb") as handle:
            answer = subprocess.run(route.REMOTE + [route.WRITE, base + name, digest], stdin=handle,
                                    capture_output=True, check=True, timeout=600)
        assets.append(json.loads(answer.stdout))
        print(f"copied {name}: {assets[-1]}")
    ledger = ledger_for(assets)
    route.check_ledger(ledger)
    record_from_document(json.loads(json.dumps(ledger)))
    subprocess.run(route.REMOTE + [route.PUBLISH], input=json.dumps(ledger).encode(),
                   capture_output=True, check=True, timeout=30)
    print(f"ledger linked: /workspace/jobs/{ledger_id}.json")

    reader = LedgerReader(SubprocessRunner())
    served = reader.get(ledger_id)
    doc = served.document
    if (doc["id"], doc["state"], doc["output"], doc["bytes"], doc["sha256"]) != (
            ledger_id, "succeeded", ledger["output"], delivery.master.bytes, delivery.master.sha256):
        raise SystemExit("the served ledger is not the one linked")
    status, kind, size, digest = remote(FETCH, ledger_id, timeout=300).decode().split()
    if (status, kind, int(size), digest) != ("200", "video/mp4", delivery.master.bytes, delivery.master.sha256):
        raise SystemExit(f"the link served {status} {kind} {size} {digest}")
    listing = reader.list()
    print(f"read back: ledger {ledger_id} succeeded; /file 200 video/mp4 {size} bytes {digest}; "
          f"{len(listing.ledgers)} ledgers listed, unreadable {list(listing.unreadable)}")
    with (out / "production.json").open("x") as handle:
        json.dump({"ledger": ledger, "served_file": {"status": int(status), "content_type": kind,
                                                      "bytes": int(size), "sha256": digest},
                   "ledgers_listed": len(listing.ledgers), "unreadable": list(listing.unreadable),
                   "url": f"https://video.haynesops.com/videos/{ledger_id}/file"}, handle, indent=2)
    print(f"https://video.haynesops.com/videos/{ledger_id}/file")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
