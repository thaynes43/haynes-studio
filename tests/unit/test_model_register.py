"""The installed register is independent of CWD and shares the API/worker override."""

import json
from importlib.resources import files

import pytest

from haynes_studio.library.winter_menu import load_licence_register
from haynes_studio.model_register import load_model_register


@pytest.fixture
def approval_register(monkeypatch):
    from haynes_studio.api.approval_routes import licence_register

    monkeypatch.delenv("STUDIO_MODEL_REGISTER", raising=False)
    return licence_register


def test_api_and_library_read_the_packaged_register_from_any_directory(
        tmp_path, monkeypatch, approval_register):
    monkeypatch.chdir(tmp_path)
    document = load_model_register()
    assert document == json.loads(files("haynes_studio").joinpath("model_licences.json")
                                  .read_text(encoding="utf-8"))
    expected = {engine["key"] for engine in document["engines"]}
    assert {"kokoro", "wan-ti2v", "wan-s2v"} <= expected
    assert set(approval_register().engines) == expected
    assert {engine.key for engine in load_licence_register().engines} == expected


def test_environment_override_is_shared_by_api_and_library(
        tmp_path, monkeypatch, approval_register):
    document = load_model_register()
    document["engines"] = [dict(document["engines"][0], key="fixture-register")]
    override = tmp_path / "models.json"
    override.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setenv("STUDIO_MODEL_REGISTER", str(override))
    monkeypatch.chdir(tmp_path)

    assert load_model_register() == document
    assert set(approval_register().engines) == {"fixture-register"}
    assert [engine.key for engine in load_licence_register().engines] == ["fixture-register"]


def test_explicit_path_takes_precedence_over_environment(tmp_path, monkeypatch):
    override = tmp_path / "models.json"
    override.write_text('{"engines": [], "files": []}', encoding="utf-8")
    monkeypatch.setenv("STUDIO_MODEL_REGISTER", str(tmp_path / "missing.json"))
    assert load_model_register(override) == {"engines": [], "files": []}


@pytest.mark.parametrize("contents", [None, "[]", '{"engines": [], "engines": []}'])
def test_bad_override_refuses_without_falling_back_to_packaged_terms(
        contents, tmp_path, monkeypatch, approval_register):
    from haynes_studio.api.errors import APIError

    override = tmp_path / "models.json"
    if contents is not None:
        override.write_text(contents, encoding="utf-8")
    monkeypatch.setenv("STUDIO_MODEL_REGISTER", str(override))
    with pytest.raises((OSError, ValueError)):
        load_model_register()
    with pytest.raises(APIError) as refused:
        approval_register()
    assert refused.value.status_code == 503
    assert refused.value.details["code"] == "approval.licence_register_unavailable"
