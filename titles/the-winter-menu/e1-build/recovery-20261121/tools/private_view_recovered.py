"""Put the rebuilt quieter-gavel cut on private viewing with the merged route (story 941).

`studio private-view` reads its four files from a store holding a `studio build` run.
That store was lost, so this one-off replaces only that read (`private_view._inputs`).
It feeds the rebuilt master and proxy, after checking both against the committed run
record. The committed record is `run.json`, and `delivery.json` is a recovery record
that says it is not the lost delivery document. Everything else is the merged
`put_private_view` as it stands: preflight, exclusive reserve, create-only copies,
verify, prepare, link, the read-back of the ledger and served bytes, withdrawal on
failure, and the local production.json.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from haynes_studio import private_view as pv
from haynes_studio.adapters.runner import SubprocessRunner
from haynes_studio.canonical.model import Principal
from haynes_studio.store import canonical_json

STORY = "https://work.haynesnetwork.com/work_packages/941"

ap = argparse.ArgumentParser()
ap.add_argument("--run-record", required=True, type=Path)
ap.add_argument("--master", required=True, type=Path)
ap.add_argument("--proxy", required=True, type=Path)
ap.add_argument("--records", required=True, help="repo path and commit of the recovery records")
ap.add_argument("--job", required=True)
ap.add_argument("--out", required=True, type=Path)
ap.add_argument("--empty-store", required=True, type=Path, help="an empty folder; only its path is used")
ap.add_argument("--title", required=True)
ap.add_argument("--check-only", action="store_true")
a = ap.parse_args()

run_bytes = a.run_record.read_bytes()
run = json.loads(run_bytes)
master, proxy = a.master.read_bytes(), a.proxy.read_bytes()


def facts(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


o = run["outputs"]
if run["status"] != "succeeded" or run["progress"]["stage"] != "delivered":
    sys.exit("the run record is not a delivered, succeeded run")
if facts(master)["sha256"] != o["master_sha256"] or facts(proxy)["sha256"] != o["proxy_sha256"]:
    sys.exit("the rebuilt files are not the run's recorded master and proxy")
if not a.empty_store.is_dir() or any(a.empty_store.iterdir()):
    sys.exit("--empty-store must be an existing empty folder")

recovery = {
    "schema": "studio.recovered-delivery/proposal", "is_original_delivery_document": False,
    "note": ("The delivery document of this run was lost with its store. This file records "
             "the rebuild instead: the master and proxy are byte-identical to the run's "
             "recorded outputs."),
    "run_id": run["id"], "delivery_id": run["delivery_id"], "frames": o["frames"],
    "fps": o["fps"], "master": facts(master), "proxy": facts(proxy),
    "story": STORY, "records": a.records, "human_approval": "Pending: Tom; private viewing only.",
}
data = {"final.mp4": master, "proxy.mp4": proxy, "run.json": run_bytes,
        "delivery.json": canonical_json(recovery)}
delivery = SimpleNamespace(id=run["delivery_id"],
                           master=SimpleNamespace(sha256=o["master_sha256"]),
                           proxy=SimpleNamespace(sha256=o["proxy_sha256"]))
pv._inputs = lambda store, production_id, run_id: (delivery, run, data)
pv.STORY = STORY

by = Principal.from_document({"kind": "cli", "command": "recovery-20261121/tools/private_view_recovered.py",
                              "operator": {"kind": "agent_session", "session": "haynes-studio-1121-002318",
                                           "harness": "Claude Code", "model": "claude-opus-5-5"}})
result = pv.put_private_view(store=SimpleNamespace(root=str(a.empty_store)),
                             production_id=run["snapshot"]["locator"].split("/")[1],
                             run_id=run["id"], job=a.job, out=a.out, runner=SubprocessRunner(),
                             title=a.title, check_only=a.check_only, by=by)
json.dump(result, sys.stdout, indent=2)
print()
