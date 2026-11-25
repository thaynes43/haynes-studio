"""Source tests for approval policy and the CR-15 request boundary."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from haynes_studio.api.approval_routes import licence_register
from haynes_studio.api.app import schema_app
from haynes_studio.api.auth import Actor, _auth_time
from haynes_studio.api.config import OIDCSettings, from_environment
from haynes_studio.api.errors import APIError
from haynes_studio.build.provenance import Use, credits, engines
from haynes_studio.canonical.model import Principal
from haynes_studio.golive.checks import AI_DESCRIPTION_LINE, release_checks
from haynes_studio.golive.policy import require_approver

ISSUER = "https://issuer.example.invalid/"
ORIGIN = "https://studio.example.invalid"


@pytest.mark.parametrize("value", [
    "https://elsewhere.example.invalid/", "//elsewhere.example.invalid/",
    "///elsewhere.example.invalid/", "/a//b", "/\\elsewhere.example.invalid/",
    "/%2Felsewhere.example.invalid/", "/%255celsewhere.example.invalid/",
    "/x%0d%0a", "/x#fragment", "x", "", "/" + "x" * 2048,
])
def test_invalid_return_paths_refuse_before_oidc(value):
    with TestClient(schema_app(), follow_redirects=False) as browser:
        answer = browser.get("/auth/login", params={"return_to": value})
    assert answer.status_code == 422
    assert answer.json()["error"]["code"] == "auth.return_to_invalid"


@pytest.mark.parametrize("query", ["", "?state=a&state=b", "?state=%00", "?state=%FF"])
def test_malformed_callback_redirects_to_safe_page(query):
    with TestClient(schema_app(), follow_redirects=False) as browser:
        answer = browser.get("/auth/callback" + query)
    code = "schema.invalid" if "%" in query else "auth.oidc_state"
    assert answer.status_code == 303
    assert answer.headers["location"] == f"/?auth_error={code}"
    assert answer.content == b""


def test_approval_operations_document_the_cookie_only_scope():
    paths = schema_app().openapi()["paths"]
    for path, operation in (
        ("/v1/runs/{id}/go-live-approvals", "approve_go_live"),
        ("/v1/go-live-approvals/{id}/withdraw", "withdraw_go_live"),
    ):
        route = paths[path]["post"]
        assert route["operationId"] == operation
        assert route["security"] == [{"StudioSession": []}]
        assert route["x-studio-scope"] == "go_live:approve"


def test_approver_configuration_defaults_empty_and_rejects_wrong_type(monkeypatch):
    for key, value in {
        "STUDIO_OIDC_ISSUER": ISSUER, "STUDIO_PUBLIC_ORIGIN": ORIGIN,
        "STUDIO_OIDC_CLIENT_ID": "fixture", "STUDIO_OIDC_CLIENT_SECRET": "fixture",
        "STUDIO_OIDC_ALLOWED_SUBJECTS": '["one"]',
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("STUDIO_GO_LIVE_APPROVER_SUBJECTS", raising=False)
    monkeypatch.delenv("STUDIO_GO_LIVE_FRESHNESS_SECONDS", raising=False)
    settings = from_environment()
    assert settings.go_live_approver_subjects == frozenset()
    assert settings.go_live_freshness_seconds == 900
    monkeypatch.setenv("STUDIO_GO_LIVE_APPROVER_SUBJECTS", '["one"]')
    monkeypatch.setenv("STUDIO_GO_LIVE_FRESHNESS_SECONDS", "60")
    assert from_environment().go_live_approver_subjects == {"one"}
    assert from_environment().go_live_freshness_seconds == 60
    monkeypatch.setenv("STUDIO_GO_LIVE_FRESHNESS_SECONDS", "3600")
    assert from_environment().go_live_freshness_seconds == 3600
    monkeypatch.setenv("STUDIO_GO_LIVE_FRESHNESS_SECONDS", "3601")
    with pytest.raises(ValueError, match="between 1 and 3600"):
        from_environment()
    monkeypatch.setenv("STUDIO_GO_LIVE_FRESHNESS_SECONDS", "60")
    monkeypatch.setenv("STUDIO_GO_LIVE_APPROVER_SUBJECTS", '{"sub": "one"}')
    with pytest.raises(ValueError, match="JSON array"):
        from_environment()


def test_allowlist_compares_issuer_and_freshness_exactly():
    now = datetime(2026, 11, 24, 20, 0, tzinfo=UTC)
    actor = Actor(Principal(kind="human", iss=ISSUER, sub="one"), group_session=True,
                  auth_time=now - timedelta(minutes=15))
    settings = OIDCSettings(ISSUER, "fixture", "fixture", ORIGIN, frozenset({"one"}),
                            go_live_approver_subjects=frozenset({"one"}))
    require_approver(actor, settings, now)
    with pytest.raises(APIError) as stale:
        require_approver(actor, settings, now + timedelta(microseconds=1))
    assert stale.value.details["code"] == "approval.sign_in_again"
    with pytest.raises(APIError) as wrong_issuer:
        require_approver(actor, replace(settings, issuer=ORIGIN), now)
    assert wrong_issuer.value.details["code"] == "approval.group_not_permitted"


def test_auth_time_applies_oidc_leeway_without_extending_freshness():
    now = datetime(2026, 11, 24, 20, 0, tzinfo=UTC)
    claims = {"auth_time": int(now.timestamp()) + 5}
    assert _auth_time(claims, now, leeway_seconds=5) == now
    with pytest.raises(APIError) as beyond_leeway:
        _auth_time(claims, now, leeway_seconds=4)
    assert beyond_leeway.value.details["code"] == "auth.oidc_invalid"


def test_release_description_uses_reported_generators_and_keeps_unknown_terms_visible():
    register = licence_register()
    hardware = "two RTX 3090s"
    engine_list = engines(register, {"wan-ti2v": Use("video", hardware=hardware),
                                    "stable-audio": Use("sound"), "qwen-image": Use("image")}, {})
    public = credits(engine_list, {"wan-ti2v": hardware})
    public.append({"engine_key": "qwen-image", "text": "Private board generator"})
    result = release_checks({"provenance": {"engines": engine_list,
                                           "public": {"ai_generated": True, "credits": public}}},
                            {"result": "pass"}, True, register)
    description = result["ai_label"]["description"]
    assert description.splitlines()[0] == AI_DESCRIPTION_LINE
    assert all(value in description for value in (hardware, "Wan2.2", "Stable Audio"))
    assert all(value not in description for value in ("Private board generator", "Qwen", "namespace"))
    assert any(row["state"] == "unknown" for row in result["licences"]["rows"])
