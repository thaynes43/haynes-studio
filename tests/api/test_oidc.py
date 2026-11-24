from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from threading import Event
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from haynes_studio.api import oidc as oidc_module
from haynes_studio.api.app import create_app, from_env
from haynes_studio.api.config import OIDCSettings, from_environment
from haynes_studio.api.errors import APIError
from haynes_studio.api.oidc import OIDC
from haynes_studio.db import identity

ISSUER = "https://issuer.example.invalid"
ORIGIN = "https://studio.example.invalid"


def test_login_discovery_outage_is_single_flight_and_recovers(monkeypatch):
    now = 0.0
    fail = True
    calls = 0
    entered = Event()
    complete = Event()
    monkeypatch.setattr(oidc_module, "monotonic", lambda: now)

    def discover(request):
        nonlocal calls
        calls += 1
        entered.set()
        complete.wait()
        if fail:
            return httpx.Response(503)
        return httpx.Response(200, json={
            "issuer": ISSUER, "authorization_endpoint": ISSUER + "/authorize",
            "token_endpoint": ISSUER + "/token", "jwks_uri": ISSUER + "/keys",
        })

    settings = OIDCSettings(ISSUER, "fixture", "fixture", ORIGIN, frozenset({"one"}))
    oidc = OIDC(settings, httpx.MockTransport(discover))
    engine = SimpleNamespace(begin=nullcontext, dispose=lambda: None)
    monkeypatch.setattr(identity, "create_attempt", lambda *_args, **_kwargs: None)
    app = create_app(engine, None, oidc)

    def login():
        with TestClient(app, follow_redirects=False) as browser:
            return browser.get("/auth/login")

    def assert_unavailable(response):
        assert response.status_code == 503
        assert response.json()["error"]["status"] == "service_unavailable"

    with ThreadPoolExecutor(max_workers=2) as pool:
        fetch = pool.submit(login)
        try:
            assert entered.wait(5)
            for _ in range(3):
                assert_unavailable(pool.submit(login).result(timeout=5))
            now = 2.0
        finally:
            complete.set()
        assert_unavailable(fetch.result(timeout=5))
    assert calls == 1

    now = 11.9
    assert_unavailable(login())
    assert calls == 1
    now = 12.0
    fail = False
    assert login().status_code == 303
    assert login().status_code == 303
    assert calls == 2


def test_signing_keys_outage_never_returns_expired_keys_and_recovers(monkeypatch):
    now = 0.0
    fail = False
    calls = 0
    entered = Event()
    complete = Event()
    monkeypatch.setattr(oidc_module, "monotonic", lambda: now)

    def jwks(request):
        nonlocal calls
        calls += 1
        if fail:
            entered.set()
            complete.wait()
            return httpx.Response(503)
        return httpx.Response(200, json={"keys": [{"kid": "one"}]})

    settings = OIDCSettings(ISSUER, "fixture", "fixture", ORIGIN, frozenset({"one"}),
                            cache_ttl_seconds=5, failure_ttl_seconds=10)
    oidc = OIDC(settings, httpx.MockTransport(jwks))

    def keys(kid="one"):
        with oidc._client() as client:
            return oidc._signing_keys(client, ISSUER + "/keys", kid)

    assert keys() == [{"kid": "one"}]
    fail = True
    now = 4.0
    with ThreadPoolExecutor(max_workers=2) as pool:
        fetch = pool.submit(keys, "rotated")
        try:
            assert entered.wait(5)
            assert pool.submit(keys).result(timeout=5) == [{"kid": "one"}]
            with pytest.raises(APIError) as unavailable:
                pool.submit(keys, "rotated").result(timeout=5)
            assert unavailable.value.status_code == 503
        finally:
            complete.set()
        with pytest.raises(APIError) as unavailable:
            fetch.result(timeout=5)
        assert unavailable.value.status_code == 503
    assert calls == 2

    now = 5.0
    with pytest.raises(APIError) as unavailable:
        keys()
    assert unavailable.value.status_code == 503
    assert calls == 2

    now = 14.0
    fail = False
    assert keys() == [{"kid": "one"}]
    assert keys() == [{"kid": "one"}]
    assert calls == 3


@pytest.mark.parametrize(("name", "field", "minimum", "maximum"), [
    ("STUDIO_OIDC_LEEWAY_SECONDS", "leeway_seconds", 0, 300),
    ("STUDIO_OIDC_CACHE_TTL_SECONDS", "cache_ttl_seconds", 1, 3600),
    ("STUDIO_OIDC_FAILURE_TTL_SECONDS", "failure_ttl_seconds", 1, 60),
])
def test_oidc_environment_enforces_setting_bounds(monkeypatch, name, field, minimum, maximum):
    monkeypatch.setenv("STUDIO_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("STUDIO_PUBLIC_ORIGIN", ORIGIN)
    monkeypatch.setenv("STUDIO_OIDC_CLIENT_ID", "fixture")
    monkeypatch.setenv("STUDIO_OIDC_CLIENT_SECRET", "fixture")
    monkeypatch.setenv("STUDIO_OIDC_ALLOWED_SUBJECTS", '["one"]')
    for value in (minimum, maximum):
        monkeypatch.setenv(name, str(value))
        assert getattr(from_environment(), field) == value
    for value in (minimum - 1, maximum + 1):
        monkeypatch.setenv(name, str(value))
        with pytest.raises(ValueError, match=name):
            from_environment()


@pytest.fixture
def oidc_environment(monkeypatch):
    monkeypatch.setenv("STUDIO_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("STUDIO_PUBLIC_ORIGIN", ORIGIN)
    monkeypatch.setenv("STUDIO_OIDC_CLIENT_ID", "fixture")
    monkeypatch.setenv("STUDIO_OIDC_CLIENT_SECRET", "fixture")
    monkeypatch.delenv("STUDIO_OIDC_ALLOWED_SUBJECTS", raising=False)
    monkeypatch.delenv("STUDIO_OIDC_ALLOWED_GROUPS", raising=False)
    return monkeypatch


def test_oidc_environment_accepts_groups_without_subjects(oidc_environment):
    oidc_environment.setenv("STUDIO_OIDC_ALLOWED_GROUPS", '["Studio Test"]')
    settings = from_environment()
    assert settings.allowed_groups == frozenset({"Studio Test"})
    assert not settings.allowed_subjects


@pytest.mark.parametrize("explicit_empty", [False, True])
def test_api_startup_requires_an_oidc_allowlist(oidc_environment, explicit_empty):
    if explicit_empty:
        oidc_environment.setenv("STUDIO_OIDC_ALLOWED_GROUPS", "[]")
        oidc_environment.setenv("STUDIO_OIDC_ALLOWED_SUBJECTS", "[]")
    with pytest.raises(ValueError, match="must be non-empty"):
        from_env()


@pytest.mark.parametrize("value", ['"Studio Test"', '{"group": "Studio Test"}', '[""]', '[1]', '['])
def test_oidc_groups_setting_must_be_an_array_of_group_names(oidc_environment, value):
    oidc_environment.setenv("STUDIO_OIDC_ALLOWED_SUBJECTS", '["one"]')
    oidc_environment.setenv("STUDIO_OIDC_ALLOWED_GROUPS", value)
    with pytest.raises(ValueError, match="STUDIO_OIDC_ALLOWED_GROUPS"):
        from_environment()
