"""Source checks require no external credentials, database, or media."""

import sys
from pathlib import Path
from threading import Event, current_thread
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError, ProgrammingError

from haynes_studio.api.app import create_app, schema_app
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
    assert "derived" not in schemas["BoardWrite"]["properties"]
    assert schemas["StoryCreate"]["required"] == ["title"]
    assert "id" not in schemas["NoteInput"]["required"]
    assert "/internal/v1/work/claim" not in document["paths"]
    assert "/v1/boards/{id}/photo-versions" not in document["paths"]
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
    fields = {"model": "example model", "prompt": "Example prompt", "session": "s", "harness": "h"}
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


def test_hung_store_readiness_uses_one_worker_and_recovers(monkeypatch, tmp_path):
    unblock = Event()
    workers = []
    is_dir = Path.is_dir

    def blocked(path):
        if path == tmp_path:
            workers.append(current_thread())
            unblock.wait(5)
        return is_dir(path)

    class Engine:
        def connect(self):
            from contextlib import nullcontext
            return nullcontext(SimpleNamespace(execute=lambda _: None))

    app = create_app(Engine(), SimpleNamespace(root=tmp_path), None)
    browser = TestClient(app)
    monkeypatch.setattr(Path, "is_dir", blocked)
    try:
        for _ in range(3):
            response = browser.get("/readyz")
            assert response.status_code == 503 and response.content == b""
            assert len(workers) == 1 and workers[0].is_alive()
            assert browser.get("/healthz").status_code == 204
    finally:
        unblock.set()
        for worker in workers:
            worker.join(timeout=2)
    assert browser.get("/readyz").status_code == 204


def test_migration_cli_rejects_downgrade_before_database_configuration(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["studio-api-migrate", "downgrade", "base"])
    monkeypatch.delenv("STUDIO_MIGRATION_DATABASE_URL", raising=False)
    with pytest.raises(SystemExit) as result:
        migrate_main()
    assert result.value.code == 2
    assert "invalid choice: 'downgrade'" in capsys.readouterr().err
