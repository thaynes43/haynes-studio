"""Source checks require no external credentials, database, or media."""

import pytest

from haynes_studio.api.app import schema_app
from haynes_studio.api.errors import APIError
from haynes_studio.api.media import byte_range
from haynes_studio.api.models import ExternalPhotoDeclaration


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
    assert {(header["name"], header["required"]) for header in patch["parameters"]
            if header["in"] == "header"} == {("If-Match", True), ("X-Studio-CSRF", False)}
    media = document["paths"]["/v1/media/{sha256}"]
    assert set(media["get"]["responses"]["206"]["headers"]) == {"Accept-Ranges", "Content-Range"}
    assert "content" not in media["head"]["responses"]["206"]
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
])
def test_phone_range_boundaries(value, size, expected):
    assert byte_range(value, size) == expected


@pytest.mark.parametrize(("value", "size"), [
    ("bytes=10-", 10), ("bytes=8-6", 10), ("bytes=0-", 0), ("bytes=-0", 10),
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
