"""Source checks require no external credentials, database, or media."""

import sys
from contextlib import nullcontext
from pathlib import Path
from threading import Event, current_thread
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError, ProgrammingError

from haynes_studio.api import app as app_module
from haynes_studio.api.app import create_app, schema_app
from haynes_studio.api.config import store_freshness_from_environment
from haynes_studio.api.errors import APIError
from haynes_studio.api.media import byte_range
from haynes_studio.api.models import ExternalPhotoDeclaration
from haynes_studio.db.migrate import main as migrate_main
from haynes_studio.errors import ContractError, Violation


def test_openapi_has_resolved_canonical_shapes_errors_and_security():
    document = schema_app().openapi()
    schemas = document["components"]["schemas"]
    assert "boards" not in schemas["Story"]["properties"]
    assert "derived" in schemas["Board"]["properties"]
    for name in ("BoardCreate", "BoardPatch"):
        assert "derived" not in schemas[name]["properties"]
    create = document["paths"]["/v1/stories/{id}/boards"]["post"]
    update = document["paths"]["/v1/boards/{id}"]["patch"]
    assert create["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("/BoardCreate")
    assert update["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("/BoardPatch")
    create_fields = schemas["BoardCreate"]["properties"]
    update_fields = schemas["BoardPatch"]["properties"]
    assert set(create_fields["draft_application"]["required"]) == {
        "board_key", "draft_sha256", "model", "session",
    }
    assert set(update_fields["draft_application"]["required"]) == {
        "board_key", "draft_sha256", "model", "session", "previous_draft_sha256", "story_revision",
    }
    assert "acknowledge_person_edit" not in create_fields
    assert "acknowledge_person_edit" in update_fields
    assert schemas["StoryCreate"]["required"] == ["title"]
    assert "id" not in schemas["NoteInput"]["required"]
    assert "/internal/v1/work/claim" not in document["paths"]
    upload = document["paths"]["/v1/boards/{id}/photo-versions"]["post"]
    assert set(upload["requestBody"]["content"]) == {"image/png", "image/jpeg", "image/webp"}
    assert upload["security"] == [{"StudioBearer": []}]
    assert upload["x-studio-scope"] == "assets:upload"
    assert upload["responses"]["408"]["content"]["application/json"]["schema"]["$ref"].endswith("/ErrorEnvelope")
    assert {header["name"] for header in upload["parameters"] if header["in"] == "header"} == {
        "If-Match", "X-Studio-Photo-Provenance",
    }
    assert document["paths"]["/v1/jobs/{id}/result"]["get"]["security"] == [{"StudioSession": []}]
    assert document["paths"]["/v1/jobs/{id}/media/{sha256}"]["head"]["x-studio-scope"] == "human"
    for path, method in (("/v1/queue/lanes", "get"), ("/v1/queue/lanes/{lane}", "put")):
        assert document["paths"][path][method]["security"] == [{"StudioSession": []}]
        assert document["paths"][path][method]["x-studio-scope"] == "human"
    generation = document["paths"]["/v1/boards/{id}/photo-jobs"]["post"]
    assert generation["x-studio-scope"] == "assets:generate"
    assert "Location" in generation["responses"]["202"]["headers"]
    assert schemas["RunView"]["properties"]["queue_wait"]["anyOf"][0]["$ref"].endswith("/QueueWait")
    assert document["paths"]["/v1/stories/{id}/runs"]["post"]["x-studio-scope"] == "runs:queue"
    assert document["paths"]["/v1/runs/{id}"]["get"]["x-studio-scope"] == "read"
    snapshot = document["paths"]["/v1/runs/{id}/snapshot"]["get"]
    assert snapshot["security"] == document["paths"]["/v1/runs/{id}"]["get"]["security"]
    assert snapshot["x-studio-scope"] == "read"
    assert snapshot["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/RunSnapshot")
    assert "ETag" in snapshot["responses"]["200"]["headers"]
    overrides = document["paths"]["/v1/runs/{id}/checks/{check}/overrides"]["post"]
    assert overrides["x-studio-scope"] == "runs:queue"
    assert overrides["security"] == [{"StudioSession": []}]
    patch = document["paths"]["/v1/stories/{id}"]["patch"]
    assert patch["x-studio-scope"] == "draft:write"
    assert document["paths"]["/v1/me/selections"]["put"]["security"] == [{"StudioSession": []}]
    assert patch["security"] == [{"StudioBearer": []}, {"StudioSession": []}]
    assert patch["responses"]["409"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorEnvelope",
    }
    error = schemas["ErrorDetail"]
    assert "request_id" in error["required"]
    assert {"unavailable", "service_unavailable", "internal"} <= set(error["properties"]["status"]["enum"])
    for status in ("422", "500", "503"):
        response = patch["responses"][status]
        assert "X-Request-ID" in response["headers"]
        assert response["content"]["application/json"]["schema"]["$ref"].endswith("/ErrorEnvelope")
    assert {(header["name"], header["required"]) for header in patch["parameters"]
            if header["in"] == "header"} == {("If-Match", True), ("X-Studio-CSRF", False)}
    media = document["paths"]["/v1/media/{sha256}"]
    assert set(media["get"]["responses"]["206"]["headers"]) == {
        "Accept-Ranges", "Content-Range", "X-Request-ID",
    }
    assert "content" not in media["head"]["responses"]["206"]
    assert "content" not in media["head"]["responses"]["401"]
    stack = [document]
    while stack:
        value = stack.pop()
        if isinstance(value, list):
            stack.extend(value)
        elif isinstance(value, dict):
            stack.extend(value.values())
            if ref := value.get("$ref"):
                target = document
                for part in ref.removeprefix("#/").split("/"):
                    target = target[part.replace("~1", "/").replace("~0", "~")]


@pytest.mark.parametrize(("value", "size", "expected"), [
    ("bytes=0-", 10, (0, 9)), ("bytes=-3", 10, (7, 9)),
    ("bytes=8-12", 10, (8, 9)), ("bytes=2-2", 10, (2, 2)),
    ("bytes=-100", 10, (0, 9)), ("bytes=1-2,5-6", 10, None),
    ("items=0-3", 10, None), ("bytes=-", 10, None),
    ("bytes=0000000000000000000000000000000000008-", 10, (8, 9)),
    ("bytes=8-" + "9" * 5000, 10, (8, 9)),
    ("bytes=8-6", 10, None), ("bytes=10-5", 10, None), ("bytes=10-000", 10, None),
    ("bytes=" + "9" * 5000 + "-" + "1" * 5000, 10, None),
])
def test_phone_range_boundaries(value, size, expected):
    assert byte_range(value, size) == expected


@pytest.mark.parametrize(("value", "size"), [
    ("bytes=10-", 10), ("bytes=10-12", 10), ("bytes=0-", 0), ("bytes=-0", 10),
])
def test_unsatisfiable_range(value, size):
    with pytest.raises(APIError) as error:
        byte_range(value, size)
    assert error.value.status_code == 416
    assert error.value.headers["Content-Range"] == f"bytes */{size}"


def test_external_photo_declaration_does_not_accept_server_claims():
    fields = {"model": "example model", "prompt": "Example prompt", "session": "s", "harness": "h",
              "paid_api": False, "source_asset_version_ids": []}
    assert ExternalPhotoDeclaration.model_validate(fields).source_asset_version_ids == []
    with pytest.raises(ValueError, match="Extra inputs"):
        ExternalPhotoDeclaration.model_validate({**fields, "externally_generated": True})


@pytest.mark.parametrize(("error", "http_status", "status", "code"), [
    (ContractError(None, [Violation("method.unavailable", "/method", "Cannot build", "unavailable")]),
     422, "unavailable", "method.unavailable"),
    (OperationalError(None, None, RuntimeError("fixture exception detail")),
     503, "service_unavailable", "database.failed"),
    (ProgrammingError(None, None, RuntimeError("fixture exception detail")), 500, "internal", "database.failed"),
    (RuntimeError("fixture exception detail"), 500, "internal", "request.failed"),
])
def test_error_envelopes_distinguish_method_availability_and_failures(error, http_status, status, code):
    app = schema_app()

    @app.get("/fixture")
    def fail():
        raise error

    response = TestClient(app).get("/fixture")
    assert response.status_code == http_status
    detail = response.json()["error"]
    assert (detail["http_status"], detail["status"], detail["code"]) == (http_status, status, code)
    assert detail["request_id"] == response.headers["X-Request-ID"]
    assert "fixture exception detail" not in response.text


def test_slow_and_hung_store_readiness_uses_one_worker_and_recovers(monkeypatch, tmp_path):
    now = 0.0
    store_available = True
    entered = Event()
    unblock = Event()
    workers = []
    is_dir = Path.is_dir

    def blocked(path):
        if path == tmp_path:
            workers.append(current_thread())
            entered.set()
            unblock.wait()
            return store_available
        return is_dir(path)

    class Engine:
        def connect(self):
            return nullcontext(SimpleNamespace(execute=lambda _: None))

    browser = TestClient(create_app(Engine(), SimpleNamespace(root=tmp_path), None))
    monkeypatch.setattr(Path, "is_dir", blocked)
    monkeypatch.setattr(app_module, "monotonic", lambda: now)
    try:
        assert browser.get("/healthz").status_code == 204
        assert not workers
        assert browser.get("/readyz").status_code == 503
        assert entered.wait(5)
        now = 0.3
        unblock.set()
        workers[0].join(timeout=5)
        assert not workers[0].is_alive()
        assert browser.get("/readyz").status_code == 204
        assert len(workers) == 1

        entered.clear()
        unblock.clear()
        now = 16.0
        assert browser.get("/readyz").status_code == 204
        assert entered.wait(5)
        now = 31.0
        for _ in range(3):
            response = browser.get("/readyz")
            assert response.status_code == 503 and response.content == b""
            assert len(workers) == 2 and workers[1].is_alive()
            assert browser.get("/healthz").status_code == 204
        unblock.set()
        workers[1].join(timeout=5)
        assert not workers[1].is_alive()
        assert browser.get("/readyz").status_code == 204

        entered.clear()
        store_available = False
        now = 47.0
        assert browser.get("/readyz").status_code == 204
        assert entered.wait(5)
        workers[2].join(timeout=5)
        assert not workers[2].is_alive()
        assert browser.get("/readyz").status_code == 503
        assert len(workers) == 3
    finally:
        unblock.set()
        for worker in workers:
            worker.join(timeout=5)


@pytest.mark.parametrize(("value", "expected"), [(None, 30), ("5", 5), ("300", 300), ("4", None), ("301", None)])
def test_store_readiness_freshness_environment(monkeypatch, value, expected):
    name = "STUDIO_STORE_FRESHNESS_SECONDS"
    if value is None:
        monkeypatch.delenv(name, raising=False)
    else:
        monkeypatch.setenv(name, value)
    if expected is None:
        with pytest.raises(ValueError, match=name):
            store_freshness_from_environment()
    else:
        assert store_freshness_from_environment() == expected


def test_migration_cli_rejects_downgrade_before_database_configuration(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["studio-api-migrate", "downgrade", "base"])
    monkeypatch.delenv("STUDIO_MIGRATION_DATABASE_URL", raising=False)
    with pytest.raises(SystemExit) as result:
        migrate_main()
    assert result.value.code == 2
    assert "invalid choice: 'downgrade'" in capsys.readouterr().err
