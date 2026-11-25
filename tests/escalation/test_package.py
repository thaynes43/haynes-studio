"""The shipped escalation document has a closed, offline format."""

import ast
import json
import socket
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import ValidationError

from haynes_studio.api.app import schema_app
from haynes_studio.canonical.ids import Minter
from haynes_studio.escalation import package
from haynes_studio.escalation.settings import Settings
from haynes_studio.schemas import validator_for


@pytest.fixture
def document(monkeypatch):
    def no_connection(*args, **kwargs):
        pytest.fail("An escalation package must never open a network connection")

    monkeypatch.setattr(socket, "create_connection", no_connection)
    minter = Minter(clock=lambda: 100, random_bits=lambda: 10)
    board = minter.mint("brd")
    run = {
        "id": minter.mint("run"), "production_id": minter.mint("prd"), "story_id": minter.mint("sty"),
        "document": {"snapshot": {"sha256": "a" * 64, "locator": "/private/source.mov"}},
    }
    failure = package.deduplication_id(run["id"], "layered.decal_gate", board, "b" * 64, "c" * 64)
    return package.make_package(run, failure, board, "layered.decal_gate", "b" * 64,
                                "c" * 64, ["d" * 64, "e" * 64], datetime(2026, 11, 25, tzinfo=UTC))


def test_canonical_immutable_document_uses_closed_actions_and_public_identifiers(document):
    doc, encoded, expected = document
    assert encoded == json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
    assert sha256(encoded).hexdigest() == expected
    assert b"/private/source.mov" not in encoded
    assert doc["callback"]["operation"] == "report_escalation"
    assert doc["responder_key"]["id"].startswith("key_0000000000")
    assert doc["usage_cap"] == {"seconds": 900, "queued_runs": 1}
    assert set(doc["allowed_actions"]) == {
        "get_escalation_check", "get_media", "studio_get_story_summary", "studio_get_board",
        "studio_patch_board", "studio_queue_run",
    }
    assert doc["responder_key"]["scopes"] == ["read", "draft:write", "runs:queue"]


def test_run_wide_package_only_carries_read_scope(document):
    original, _, _ = document
    run = {**original, "id": original["run_id"], "document": {"snapshot": {"sha256": "a" * 64}}}
    result, _, _ = package.make_package(
        run, "b" * 64, None, "mix.length", "c" * 64, "d" * 64, ["e" * 64, "f" * 64],
        datetime(2026, 11, 25, tzinfo=UTC),
    )
    assert result["board_ids"] == []
    assert result["patch_fields"] == []
    assert result["responder_key"]["scopes"] == ["read"]
    assert result["usage_cap"]["queued_runs"] == 0
    assert "studio_patch_board" not in result["allowed_actions"]
    assert "studio_queue_run" not in result["allowed_actions"]


@pytest.mark.parametrize(("field", "value"), [
    ("allowed_actions", ["send_to_unknown_destination", "get_media", "get_escalation_check"]),
    ("snapshot_sha256", "fixture-secret-" + "A" * 35),
    ("artifacts", [{"operation": "get_media", "sha256": "a" * 64, "locator": "/private/cut.mov"}]),
    ("artifacts", [{"operation": "https://user:password@example.invalid/", "sha256": "a" * 64}]),
    ("artifacts", [{"operation": "get_media", "sha256": b"synthetic media bytes"}]),
    ("artifacts", [{"operation": "get_media", "sha256": "a" * 64 + "\n"}]),
    ("responder_key", {"id": "fixture-token-" + "A" * 35, "scopes": ["read"]}),
])
def test_schema_rejects_unknown_actions_paths_credentials_and_payloads(document, field, value):
    doc, _, _ = document
    changed = deepcopy(doc)
    changed[field] = value
    with pytest.raises(ValidationError):
        validator_for(package.SCHEMA_FILE).validate(changed)


def test_escalation_has_no_network_implementation_and_only_http_lifecycle_operations():
    root = Path(package.__file__).parent
    allowed_imports = {
        "datetime", "functools", "hashlib", "json", "os", "re", "dataclasses", "sqlalchemy",
        "haynes_studio", "typing",
    }
    for file in root.glob("*.py"):
        imports = set()
        for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.level == 0:
                imports.add(node.module.split(".")[0])
        assert imports <= allowed_imports, file.name
    from haynes_studio.mcp.tools import OPERATIONS

    assert all("escalation" not in name for name in OPERATIONS)
    document = schema_app().openapi()
    routes = document["paths"]
    base = "/v1/productions/{production_id}/escalations/{package_id}"
    assert routes[base + "/authorize"]["post"]["security"] == [{"StudioSession": []}]
    assert routes[base + "/callback"]["post"]["security"] == [{"StudioBearer": []}]
    assert routes[base + "/callback"]["post"]["x-studio-key"] == "package responder"
    assert "/internal/v1/work/escalation-check-failure" not in routes


def test_unknown_authorization_setting_fails_closed(monkeypatch):
    monkeypatch.setenv("STUDIO_ESCALATION_AUTHORIZATION", "typo")
    assert Settings.from_environment().authorization == "person"
