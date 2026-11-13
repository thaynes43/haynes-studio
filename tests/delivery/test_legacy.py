"""Legacy deliveries (contract sections 1 and 8): the four recorded Winter Menu ledgers
map to read-only deliveries with adapter ``legacy_wan_ledger``; r4 is the contract's
example exactly. Nothing calls or writes the ledger."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path

import pytest

from haynes_studio.adapters.errors import RESPONSE_INVALID, AdapterError
from haynes_studio.adapters.fakes import FakeRunner, FakeWanLedger
from haynes_studio.adapters.wan_ledger import LedgerReader
from haynes_studio.canonical.model import to_document
from haynes_studio.delivery import (
    LEGACY_MISMATCH,
    DeliveryError,
    legacy_delivery,
    validate_delivery,
)

REPO = Path(__file__).resolve().parents[2]
TITLE = Path("titles/the-winter-menu")
EVIDENCE = ["evidence", "evidence-r2", "evidence-r3", "evidence-r4"]
EXAMPLES = REPO / "docs" / "contracts" / "examples" / "valid"
IMPORT_MAP = json.loads((EXAMPLES / "legacy-import-map.json").read_text())
REVISIONS = {r["ledger_id"]: r for r in IMPORT_MAP["revisions"]}
R4_EXAMPLE = json.loads((EXAMPLES / "delivery-legacy-r4.json").read_text())


def _read(folder: str, name: str) -> dict:
    return json.loads((REPO / TITLE / folder / name).read_text())


def _map(folder: str, ledger: dict | None = None, validation: dict | None = None):
    ledger = _read(folder, "production.json") if ledger is None else ledger
    revision = REVISIONS[ledger["id"]]
    return legacy_delivery(
        ledger, _read(folder, "validation.json") if validation is None else validation,
        delivery_id=revision["delivery_id"], run_id=revision["imported_run_id"],
        assets_ref=(TITLE / folder / "production.json").as_posix(),
        verification_ref=(TITLE / folder / "validation.json").as_posix())


@pytest.mark.parametrize("folder", EVIDENCE)
def test_each_recorded_ledger_maps_to_a_read_only_delivery(folder):
    ledger = _read(folder, "production.json")
    revision = REVISIONS[ledger["id"]]
    delivery = _map(folder)
    assert validate_delivery(to_document(delivery), context="read") == []
    assert (delivery.store.adapter, delivery.store.writable) == ("legacy_wan_ledger", False)
    assert delivery.proxy is None and delivery.master.locator is None
    assert delivery.master.legacy_path == ledger["output"]
    assert delivery.master.sha256 == ledger["sha256"] == revision["master_sha256"]
    assert delivery.master.bytes == ledger["bytes"]
    assert delivery.master.frames == revision["frames"]
    assert delivery.verification.decoded_frames == delivery.verification.expected_frames
    assert delivery.verification.source == f"{TITLE.as_posix()}/{folder}/validation.json"
    assert delivery.legacy.ledger_id == ledger["id"]
    assert delivery.legacy.provenance == ledger["provenance"]
    assert (delivery.id, delivery.run_id) == (revision["delivery_id"], revision["imported_run_id"])


def test_the_r4_ledger_maps_to_the_contract_example_exactly():
    assert to_document(_map("evidence-r4")) == R4_EXAMPLE


def test_the_mapping_reads_a_ledger_through_the_wan_api_and_makes_no_other_call():
    ledgers = [_read(folder, "production.json") for folder in EVIDENCE]
    runner = FakeRunner(FakeWanLedger(ledgers))
    record = LedgerReader(runner).get(R4_EXAMPLE["legacy"]["ledger_id"])
    assert [command.label for command in runner.calls] == ["wan_ledger.get"]
    delivery = legacy_delivery(record.document, _read("evidence-r4", "validation.json"),
                               delivery_id=R4_EXAMPLE["id"], run_id=R4_EXAMPLE["run_id"],
                               assets_ref=R4_EXAMPLE["legacy"]["assets_ref"],
                               verification_ref=R4_EXAMPLE["verification"]["source"])
    assert len(runner.calls) == 1  # the mapping itself called nothing
    assert to_document(delivery) == R4_EXAMPLE


def test_the_inputs_and_the_evidence_files_are_unchanged():
    paths = [REPO / TITLE / folder / name for folder in EVIDENCE
             for name in ("production.json", "validation.json")]
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    for folder in EVIDENCE:
        ledger, validation = _read(folder, "production.json"), _read(folder, "validation.json")
        kept = copy.deepcopy((ledger, validation))
        delivery = _map(folder, ledger, validation)
        assert (ledger, validation) == kept
        with pytest.raises(TypeError):  # the provenance is a read-only view
            delivery.legacy.provenance["images"] = "changed"
    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths} == before


def test_the_legacy_module_has_no_write_path():
    """The mapping imports no store, runner, file or OS module and calls nothing that
    opens a file: it can only read the documents it is given."""
    source = (REPO / "src/haynes_studio/delivery/legacy.py").read_text()
    tree = ast.parse(source)
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    imported |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not {name for name in imported
                if name.split(".")[0] in {"os", "io", "pathlib", "shutil", "tempfile", "subprocess"}
                or name.startswith(("haynes_studio.store", "haynes_studio.stages",
                                    "haynes_studio.adapters.runner"))}
    called = {node.func.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert not called & {"open", "exec", "eval", "__import__"}
    from haynes_studio.adapters import wan_ledger
    used = {node.names[0].name for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == wan_ledger.__name__}
    assert "LedgerReader" not in used


@pytest.mark.parametrize("change, message", [
    ({"sha256": "0" * 64}, "another file"),
    ({"bytes": 1}, "another file"),
    ({"passed": False}, "did not pass"),
    ({"decoded_frames": 1086}, "TIME-11"),
    ({"fps": 25}, "24 fps"),
    ({"width": 720, "height": 1280}, "frame size"),
    ({"width": 1080.5}, "positive integer"),
    ({"expected_frames": None}, "positive integer"),
])
def test_evidence_that_disagrees_with_its_ledger_is_refused(change, message):
    validation = {**_read("evidence-r4", "validation.json"), **change}
    with pytest.raises(DeliveryError) as caught:
        _map("evidence-r4", validation=validation)
    assert caught.value.code == LEGACY_MISMATCH and message in str(caught.value)


def test_evidence_missing_a_field_is_refused():
    validation = _read("evidence-r4", "validation.json")
    del validation["decoded_frames"]
    with pytest.raises(DeliveryError) as caught:
        _map("evidence-r4", validation=validation)
    assert caught.value.code == LEGACY_MISMATCH
    with pytest.raises(DeliveryError):
        _map("evidence-r4", validation=["not", "an", "object"])


@pytest.mark.parametrize("change", [{"kind": "video"}, {"state": "running"},
                                    {"output": "/workspace/output/x.mp4"}, {"id": "nope"}])
def test_a_malformed_ledger_is_refused_as_the_reader_refuses_it(change):
    ledger = {**_read("evidence-r4", "production.json"), **change}
    with pytest.raises(AdapterError) as caught:
        legacy_delivery(ledger, _read("evidence-r4", "validation.json"),
                        delivery_id=R4_EXAMPLE["id"], run_id=R4_EXAMPLE["run_id"],
                        assets_ref="a.json", verification_ref="b.json")
    assert caught.value.code == RESPONSE_INVALID


def test_bad_identifiers_are_refused():
    with pytest.raises(DeliveryError) as caught:
        legacy_delivery(_read("evidence-r4", "production.json"),
                        _read("evidence-r4", "validation.json"),
                        delivery_id="run_01M79V9FC00000000000000002",
                        run_id=R4_EXAMPLE["run_id"], assets_ref="../production.json",
                        verification_ref="b.json")
    assert caught.value.code == LEGACY_MISMATCH
    assert "id.type_mismatch" in str(caught.value) and "/legacy/assets_ref" in str(caught.value)
