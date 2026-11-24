"""Integration tests against the disposable PostgreSQL 16 fixture."""

import base64
import copy
import hashlib
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import av
import httpx
import jwt
import pytest
import sqlalchemy as sa
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends
from fastapi.testclient import TestClient

from haynes_studio.api.app import create_app
from haynes_studio.api.auth import CSRF_HEADER, LOGIN_COOKIE, SESSION_COOKIE, worker_access
from haynes_studio.api.config import OIDCSettings
from haynes_studio.api.oidc import OIDC, random_secret
from haynes_studio.canonical import to_document
from haynes_studio.canonical.ids import Minter
from haynes_studio.db import drafts, identity
from haynes_studio.db.catalog import record_asset_version, record_delivery
from haynes_studio.db.engine import connect_engine
from haynes_studio.db.migrate import migrate
from haynes_studio.db.problems import StaleRevision
from haynes_studio.db.schema import agent_grants, agent_keys, asset_versions, metadata, sessions, worker_tokens
from haynes_studio.delivery import deliver
from haynes_studio.errors import ContractError
from haynes_studio.store.layout import blob_locator
from haynes_studio.store.local import LocalStore
from tests.canonical.fixtures import example
from tests.delivery.media import write_master
from tests.library.fixtures import imported, winter_menu

pytestmark = pytest.mark.db
ORIGIN = "https://studio.example.invalid"
ISSUER = "https://issuer.example.invalid/provider/"
CLIENT_ID = "studio-example"


class FakeIssuer:
    """A loopback-free OIDC provider with a disposable signing key and one-use codes."""

    def __init__(self):
        self.signer = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.jwk = jwt.algorithms.RSAAlgorithm.to_jwk(self.signer.public_key(), as_dict=True)
        self.jwk.update({"kid": "test-signing-key", "use": "sig", "alg": "RS256"})
        self.secret = random_secret()
        self.codes = {}
        self.exchanges = 0

    def settings(self):
        return OIDCSettings(ISSUER, CLIENT_ID, self.secret, ORIGIN, frozenset({"one", "two"}))

    def authorize(self, query, subject, **claim_overrides):
        assert query["response_type"] == ["code"]
        assert query["code_challenge_method"] == ["S256"]
        assert query["redirect_uri"] == [ORIGIN + "/auth/callback"]
        assert query["scope"] == ["openid profile"]
        now = datetime.now(UTC)
        claims = {"iss": ISSUER, "sub": subject, "aud": CLIENT_ID, "name": "Fixture Person",
                  "iat": now, "exp": now + timedelta(minutes=10), "nonce": query["nonce"][0],
                  **claim_overrides}
        code = random_secret()
        self.codes[code] = (query["code_challenge"][0], claims)
        return code

    def request(self, request):
        match request.url.path:
            case "/provider/.well-known/openid-configuration":
                return httpx.Response(200, json={
                    "issuer": ISSUER, "authorization_endpoint": ISSUER + "authorize",
                    "token_endpoint": ISSUER + "token", "jwks_uri": ISSUER + "keys",
                })
            case "/provider/keys":
                return httpx.Response(200, json={"keys": [self.jwk]})
            case "/provider/token":
                self.exchanges += 1
                raw = base64.b64decode(request.headers["authorization"].removeprefix("Basic "))
                assert raw == f"{CLIENT_ID}:{self.secret}".encode()
                form = parse_qs(request.content.decode())
                assert form["grant_type"] == ["authorization_code"]
                assert form["redirect_uri"] == [ORIGIN + "/auth/callback"]
                old = self.codes.pop(form["code"][0], None)
                if old is None:
                    return httpx.Response(400)
                challenge, claims = old
                computed = hashlib.sha256(form["code_verifier"][0].encode()).digest()
                assert challenge == base64.urlsafe_b64encode(computed).decode().rstrip("=")
                token = jwt.encode(claims, self.signer, algorithm="RS256",
                                   headers={"kid": self.jwk["kid"]})
                return httpx.Response(200, json={"id_token": token, "access_token": random_secret()})
            case _:
                raise AssertionError("Unexpected fake issuer request")


@pytest.fixture(scope="module")
def engine(studio_db):
    engine = connect_engine(studio_db.url, studio_db.schema)
    try:
        migrate(engine)
        migrate(engine, "downgrade", "base")
        with engine.connect() as conn:
            assert sa.inspect(conn).get_table_names(schema=studio_db.schema) == ["alembic_version"]
        migrate(engine)
        with engine.connect() as conn:
            names = set(sa.inspect(conn).get_table_names(schema=studio_db.schema))
            assert names == {*metadata.tables, "alembic_version"}
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def service(engine, tmp_path):
    issuer = FakeIssuer()
    root = tmp_path / "store"
    root.mkdir()
    store = LocalStore(root)
    oidc = OIDC(issuer.settings(), httpx.MockTransport(issuer.request))
    app = create_app(engine, store, oidc)
    return app, store, issuer


def client(app):
    return TestClient(app, base_url=ORIGIN, follow_redirects=False)


def begin_login(browser):
    response = browser.get("/auth/login")
    assert response.status_code == 303
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    return parse_qs(urlsplit(response.headers["location"]).query)


def sign_in(browser, issuer, subject="one"):
    query = begin_login(browser)
    code = issuer.authorize(query, subject)
    response = browser.get("/auth/callback", params={"code": code, "state": query["state"][0]})
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "access_token" not in response.text
    cookies = response.headers.get_list("set-cookie")
    cookie = next(value for value in cookies if value.startswith(SESSION_COOKIE + "="))
    assert all(attr in cookie for attr in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"))
    assert "Domain=" not in cookie
    assert browser.cookies.get(LOGIN_COOKIE) is None
    me = browser.get("/v1/me").json()
    assert me["principal"] == {"kind": "human", "iss": ISSUER, "sub": subject}
    return {CSRF_HEADER: me["csrf_token"]}


def bearer(secret):
    return {"Authorization": f"Bearer {secret}"}


def register_agent(engine, grants, *, expires_at=None, revoked_at=None):
    key, secret = Minter().mint("key"), random_secret()
    with engine.begin() as conn:
        conn.execute(agent_keys.insert().values(
            id=key, digest=identity.digest(secret), expires_at=expires_at, revoked_at=revoked_at,
        ))
        for production_id, scopes in grants.items():
            conn.execute(agent_grants.insert(), [
                {"key_id": key, "production_id": production_id, "scope": scope} for scope in scopes
            ])
    return key, bearer(secret)


def new_production(browser, csrf):
    response = browser.post("/v1/productions", json={"name": "A fixture production"}, headers=csrf)
    assert response.status_code == 201, response.text
    id_ = response.json()["id"]
    response = browser.put(f"/v1/productions/{id_}/media-types/short",
                           headers={**csrf, "If-Match": response.headers["etag"]})
    assert response.status_code == 200, response.text
    assert response.json()["media_types"][0]["aspect"] == "9:16"
    return id_


def new_story(browser, headers, production):
    response = browser.post(f"/v1/productions/{production}/media-types/short/stories",
                            json={"title": "A fixture story"}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_login_is_bound_to_the_browser_and_token_and_state_are_single_use(service, engine):
    app, _, issuer = service
    browser, other = client(app), client(app)
    query = begin_login(browser)
    code = issuer.authorize(query, "one")
    callback = {"code": code, "state": query["state"][0]}
    assert other.get("/auth/callback", params=callback).status_code == 401
    assert browser.get("/auth/callback", params={**callback, "state": "wrong"}).status_code == 401
    assert issuer.exchanges == 0
    attempt_cookie = browser.cookies.get(LOGIN_COOKIE)
    assert browser.get("/auth/callback", params=callback).status_code == 303
    assert issuer.exchanges == 1
    assert browser.get("/auth/callback", params=callback,
                       headers={"Cookie": f"{LOGIN_COOKIE}={attempt_cookie}"}).status_code == 401
    assert issuer.exchanges == 1
    session = browser.cookies.get(SESSION_COOKIE)
    with engine.connect() as conn:
        assert conn.scalar(sa.select(sessions.c.digest).where(
            sessions.c.digest == identity.digest(session),
        )) is not None
    assert browser.post("/auth/logout").status_code == 403
    assert browser.get("/v1/me", headers=bearer(random_secret())).status_code == 401


@pytest.mark.parametrize(("subject", "changes", "status"), [
    ("outside", {}, 403), ("one", {"nonce": "wrong"}, 401),
    ("one", {"aud": "wrong"}, 401), ("one", {"iss": "https://other.example.invalid/"}, 401),
    ("one", {"azp": "wrong"}, 401), ("one", {"exp": 1}, 401),
])
def test_oidc_rejects_wrong_identity_or_claims(service, subject, changes, status):
    app, _, issuer = service
    browser = client(app)
    query = begin_login(browser)
    code = issuer.authorize(query, subject, **changes)
    response = browser.get("/auth/callback", params={"code": code, "state": query["state"][0]})
    assert response.status_code == status
    assert browser.cookies.get(SESSION_COOKIE) is None


def test_selections_are_per_subject_and_survive_another_replica(service, engine, studio_db):
    app, store, issuer = service
    replica_engine = connect_engine(studio_db.url, studio_db.schema)
    replica = create_app(replica_engine, store, app.state.oidc)
    with client(app) as one, client(replica) as two:
        csrf_one = sign_in(one, issuer)
        csrf_two = sign_in(two, issuer, "two")
        path = "/v1/me/selections"
        assert one.get(path).json() == {"revision": 0, "values": {}}
        vals = {"panel": "library", "filter": {"label": ["test"]}}
        assert one.put(path, json={"values": vals}, headers={"If-Match": '"0"'}).status_code == 403
        assert one.put(path, json={"values": vals}, headers={**csrf_one, "If-Match": '"0"'}).json() == {
            "revision": 1, "values": vals,
        }
        assert two.put(path, json={"values": {"panel": "editor"}},
                       headers={**csrf_two, "If-Match": '"0"'}).status_code == 200
        cookie = one.cookies.get(SESSION_COOKIE)
        assert two.get(path, headers={"Cookie": f"{SESSION_COOKIE}={cookie}"}).json() == {
            "revision": 1, "values": vals,
        }
        stale = one.put(path, json={"values": {}}, headers={**csrf_one, "If-Match": "0"})
        assert stale.status_code == 409
        assert stale.json()["error"]["current_revision"] == 1
        assert two.get(path).json()["values"] == {"panel": "editor"}


def test_draft_transactions_conflicts_child_ids_and_tombstones(service, engine):
    app, _, issuer = service
    browser, agent = client(app), client(app)
    csrf = sign_in(browser, issuer)
    production = new_production(browser, csrf)
    other = new_production(browser, csrf)
    story = new_story(browser, csrf, production)
    _, write = register_agent(engine, {production: ("read", "draft:write"), other: ("read",)})
    _, read = register_agent(engine, {production: ("read", "go_live:approve")})
    draft = f"/v1/stories/{story}"
    assert agent.get(draft).status_code == 401
    assert agent.post(f"/v1/productions/{other}/media-types/short/stories",
                      json={"title": "No access"}, headers=write).status_code == 403
    assert agent.post("/v1/productions", json={"name": "No access"}, headers=write).status_code == 403
    assert agent.post(draft + "/boards", json={}, headers={**read, "If-Match": "1"}).status_code == 403
    assert agent.get("/v1/me/selections", headers=write).status_code == 403
    assert agent.get("/v1/me", headers=read).json()["production_scopes"] == {production: ["read"]}

    created = agent.post(draft + "/boards", json={"notes": [{"text": "Hold"}]},
                         headers={**write, "If-Match": '"1"'})
    assert created.status_code == 201, created.text
    board = created.json()
    path = created.headers["location"]
    tag = created.headers["etag"]
    assert board["notes"][0]["id"].startswith("nte_")
    assert board["drafted_by"]["kind"] == "agent"
    assert agent.get(draft + "/timing", headers=read).json()["frames_known"] == 24
    assert agent.get(draft, headers=read).json()["revision"] == 2
    assert agent.patch(path, json={"derived": {}}, headers={**write, "If-Match": tag}).status_code == 422
    assert agent.patch(path, json={"notes": [{"id": Minter().mint("nte"), "text": "Forged"}]},
                       headers={**write, "If-Match": tag}).status_code == 422
    response = agent.patch(path, json={"notes": [{**board["notes"][0], "text": "Edited"}]},
                           headers={**write, "If-Match": tag})
    assert response.status_code == 200, response.text
    assert response.json()["notes"] == [{**board["notes"][0], "text": "Edited"}]
    stale = agent.patch(path, json={"title": "Stale"}, headers={**write, "If-Match": tag})
    assert stale.status_code == 409
    assert stale.json()["error"]["current_revision"] == 2
    assert agent.get(draft, headers=read).json()["revision"] == 3
    assert agent.patch(draft, json={"title": "Stale"}, headers={**write, "If-Match": "2"}).status_code == 409
    invalid_order = agent.put(draft + "/board-order", json={"board_order": []},
                              headers={**write, "If-Match": "3"})
    assert invalid_order.json()["error"]["code"] == "story.board_order"
    second = agent.post(draft + "/boards", json={}, headers={**write, "If-Match": "3"}).json()
    reordered = agent.put(draft + "/board-order", json={"board_order": [second["id"], board["id"]]},
                          headers={**write, "If-Match": "4"})
    assert reordered.json()["board_order"] == [second["id"], board["id"]]
    assert agent.delete(path, headers={**write, "If-Match": "2"}).status_code == 204
    assert agent.get(path, headers=read).status_code == 404
    third = agent.post(draft + "/boards", json={}, headers={**write, "If-Match": "6"}).json()
    assert third["number"] == 3
    assert agent.get(draft, headers=read).json()["derived"]["next_board_number"] == 4
    page = agent.get("/v1/productions?limit=1", headers=write).json()
    assert page["next_cursor"] == page["items"][0]["id"]
    next_page = agent.get("/v1/productions", params={"cursor": page["next_cursor"]}, headers=write).json()
    assert {page["items"][0]["id"], next_page["items"][0]["id"]} == {production, other}


def test_winter_menu_metadata_round_trips_and_reimport_preserves_edits(service, engine):
    app, _, issuer = service
    winter = imported(4)
    library = winter_menu().library
    versions = library.documents()
    original = winter.story
    production = example("valid/production.json")
    with engine.begin() as conn:
        first = drafts.import_draft(conn, production, original, versions)
        assert first.story["revision"] == original["revision"]
    browser = client(app)
    csrf = sign_in(browser, issuer)
    path = f'/v1/stories/{original["id"]}'
    result = browser.get(path)
    assert result.status_code == 200, result.text
    assert result.json()["board_order"] == original["board_order"]
    assert "boards" not in result.json()
    assert result.json()["revision"] == original["revision"]
    for board in original["boards"]:
        saved = browser.get(f'/v1/boards/{board["id"]}').json()
        assert {k: value for k, value in saved.items() if k != "derived"} == {
            k: value for k, value in board.items() if k != "derived"
        }
    edit = browser.patch(path, json={"title": "Revised fixture title"},
                         headers={**csrf, "If-Match": result.headers["etag"]})
    assert edit.status_code == 200, edit.text
    duplicate = copy.deepcopy(original)
    duplicate["id"] = Minter().mint("sty")
    for board in duplicate["boards"]:
        board["story_id"] = duplicate["id"]
    with engine.begin() as conn:
        resumed = drafts.import_draft(conn, production, duplicate, versions).story
        assert resumed["id"] == original["id"]
        assert resumed["revision"] == edit.json()["revision"]
    assert browser.get(path).json()["title"] == "Revised fixture title"
    board = next(board for board in original["boards"] if board["cast"])
    response = browser.get("/v1/assets", params={"production": production["id"], "board": board["id"]})
    assert response.status_code == 200, response.text
    chosen = next(item for item in response.json()["items"] if item["kind"] == "cast")
    assert chosen["id"] in {entry["asset_version_id"] for entry in board["cast"]}
    asset = browser.get(f'/v1/assets/{chosen["asset_id"]}').json()
    assert asset["asset"]["revision"] == 1
    assert asset["versions"][0]["id"] == chosen["id"]


def test_strict_ingress_health_and_worker_credential_boundary(service, engine):
    app, _, issuer = service
    # Add the future queue's dependency to a test-only endpoint.
    @app.get("/internal/v1/work/test")
    def internal(worker=Depends(worker_access)):
        return to_document(worker)

    browser = client(app)
    assert browser.get("/healthz").content == browser.get("/readyz").content == b""
    assert browser.get("/openapi.json").status_code == 404
    csrf = sign_in(browser, issuer)
    path = "/v1/productions"
    headers = {"Content-Type": "application/json", **csrf}
    for value in ('{"name":"One","name":"Two"}', '{"name":NaN}', '{"name":"\\ud800"}'):
        assert browser.post(path, content=value, headers=headers).status_code == 422
    assert browser.post(path, content=b" " * (2 * 1024 * 1024 + 1), headers=headers).status_code == 413
    secret = random_secret()
    with engine.begin() as conn:
        conn.execute(worker_tokens.insert().values(digest=identity.digest(secret), worker_id="render"))
    assert browser.get("/internal/v1/work/test", headers=bearer(secret)).json() == {
        "kind": "worker", "worker_id": "render",
    }
    assert browser.get("/v1/me", headers=bearer(secret)).status_code == 401
    _, agent = register_agent(engine, {})
    assert browser.get("/internal/v1/work/test", headers=agent).status_code == 401
    expired = datetime.now(UTC) - timedelta(seconds=1)
    for kwargs in ({"expires_at": expired}, {"revoked_at": expired}):
        _, revoked = register_agent(engine, {}, **kwargs)
        assert browser.get("/v1/me", headers=revoked).status_code == 401


def test_phone_proxy_ranges_and_next_read_after_logout_or_expiry(service, engine, tmp_path):
    app, store, issuer = service
    browser, stranger = client(app), client(app)
    csrf = sign_in(browser, issuer)
    production = new_production(browser, csrf)
    other = new_production(browser, csrf)
    story = new_story(browser, csrf, production)
    _, wrong = register_agent(engine, {other: ("read",), production: ("draft:write",)})
    _, allowed = register_agent(engine, {production: ("read",)})
    run = Minter().mint("run")
    master = write_master(tmp_path / "master.mp4", frames=24)
    delivery = deliver(master, store=store, production_id=production, run_id=run,
                       expected_frames=24, now=datetime.now(UTC))
    with engine.begin() as conn:
        record_delivery(conn, story, to_document(delivery))
    path = f"/v1/media/{delivery.proxy.sha256}"
    data = (tmp_path / "store" / delivery.proxy.locator).read_bytes()
    assert browser.get(f"/v1/runs/{run}/delivery").json()["proxy"]["sha256"] == delivery.proxy.sha256
    assert stranger.get(f"/v1/runs/{run}/delivery", headers=wrong).status_code == 403
    response = browser.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"
    assert response.content == data
    with av.open(io.BytesIO(response.content)) as container:
        assert next(container.decode(video=0)).width == 720

    size = len(data)
    for header, first, last in [
        ("bytes=0-", 0, size - 1),
        ("bytes=-127", size - 127, size - 1),
        (f"bytes={size * 3 // 4}-", size * 3 // 4, size - 1),
        ("bytes=3-255", 3, 255),
    ]:
        response = browser.get(path, headers={"Range": header})
        assert response.status_code == 206
        assert response.headers["accept-ranges"] == "bytes"
        assert response.headers["content-range"] == f"bytes {first}-{last}/{size}"
        assert int(response.headers["content-length"]) == last + 1 - first
        assert response.content == data[first:last + 1]
    head = browser.head(path, headers={"Range": "bytes=-127"})
    assert head.status_code == 206
    assert head.headers["content-range"] == f"bytes {size - 127}-{size - 1}/{size}"
    assert head.content == b""
    assert stranger.head(path, headers=allowed).headers["content-length"] == str(size)
    impossible = browser.get(path, headers={"Range": f"bytes={size}-"})
    assert impossible.status_code == 416
    assert impossible.headers["content-range"] == f"bytes */{size}"
    assert browser.get(path, headers={"Range": "bytes=10-", "If-Range": '"old"'}).status_code == 200
    assert stranger.get(path, headers={"Range": "bytes=0-"}).status_code == 401
    refused = stranger.get(path, headers={**wrong, "Range": "bytes=0-"})
    assert refused.status_code == 404 and "Content-Range" not in refused.headers
    assert refused.json()["error"]["code"] == "not_found"
    assert stranger.head(path, headers=wrong).content == b""
    assert browser.get("/v1/media/%2e%2e%2Fmaster.mp4").status_code == 404
    assert browser.get("/v1/media/%5c..%5cmaster.mp4").status_code == 404

    old_session = browser.cookies.get(SESSION_COOKIE)
    assert browser.post("/auth/logout", headers=csrf).status_code == 204
    assert stranger.get(path, headers={"Cookie": f"{SESSION_COOKIE}={old_session}",
                                       "Range": "bytes=0-"}).status_code == 401
    sign_in(browser, issuer)
    with engine.begin() as conn:
        conn.execute(sessions.update().where(sessions.c.digest == identity.digest(
            browser.cookies.get(SESSION_COOKIE),
        )).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    assert browser.get(path, headers={"Range": "bytes=0-"}).status_code == 401

    # Even an authorized hash may never leave the configured store via a link.
    file = tmp_path / "store" / delivery.proxy.locator
    file.unlink()
    outside = tmp_path / "elsewhere.mp4"
    outside.write_bytes(data)
    file.symlink_to(outside)
    assert stranger.get(path, headers=allowed).status_code == 404


def test_global_media_needs_a_reference_in_one_of_the_callers_productions(
    service, engine, synthetic_wav,
):
    app, store, issuer = service
    browser, agent = client(app), client(app)
    csrf = sign_in(browser, issuer)
    production = new_production(browser, csrf)
    other = new_production(browser, csrf)
    story = new_story(browser, csrf, production)
    _, allowed = register_agent(engine, {production: ("read",)})
    _, wrong = register_agent(engine, {other: ("read",)})
    version = next(doc for doc in winter_menu().library.documents() if doc["kind"] == "sound")
    minter = Minter()
    with synthetic_wav.open("rb") as source:
        blob = store.publish(source, scope="library", media_type="audio/wav")
    version.update(id=minter.mint("asv"), asset_id=minter.mint("ast"),
                   scope={"production_id": None}, content=to_document(blob))
    version["legacy"] = None
    version["provenance"] = {**version["provenance"], "source_key": None}
    with engine.begin() as conn:
        record_asset_version(conn, version)
    media = f"/v1/media/{blob.sha256}"
    assert agent.get(media, headers=allowed).status_code == 404
    path = f"/v1/stories/{story}"
    bed = {"type": "bed", "asset_version_id": version["id"], "level_rms_dbfs": -22, "clock": "film"}
    response = browser.patch(path, json={"beds": [bed]}, headers={**csrf, "If-Match": "1"})
    assert response.status_code == 200, response.text
    assert agent.get(media, headers=allowed).content == synthetic_wav.read_bytes()
    refused = agent.get(media, headers=wrong)
    assert refused.status_code == 404 and refused.json()["error"]["code"] == "not_found"
    assert browser.patch(path, json={"beds": []}, headers={**csrf, "If-Match": "2"}).status_code == 200
    assert agent.get(media, headers=allowed).status_code == 404
    assert (Path(store.root) / blob.locator).is_file()


def test_two_transactions_cannot_create_boards_at_the_same_story_revision(service, engine):
    app, _, issuer = service
    browser = client(app)
    csrf = sign_in(browser, issuer)
    production = new_production(browser, csrf)
    story = new_story(browser, csrf, production)
    by = browser.get("/v1/me").json()["principal"]

    def add():
        try:
            with engine.begin() as conn:
                drafts.add_board(conn, story, 1, {}, by)
            return 201
        except StaleRevision as error:
            assert error.current == 2
            return 409

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(add), pool.submit(add)
        assert sorted([first.result(), second.result()]) == [201, 409]
    doc = browser.get(f"/v1/stories/{story}").json()
    assert doc["revision"] == 2
    assert len(doc["board_order"]) == 1


def test_external_photo_metadata_keeps_the_received_and_stored_hashes(service, engine):
    app, _, issuer = service
    browser = client(app)
    csrf = sign_in(browser, issuer)
    production = new_production(browser, csrf)
    story = new_story(browser, csrf, production)
    added = browser.post(f"/v1/stories/{story}/boards", json={}, headers={**csrf, "If-Match": "1"})
    assert added.status_code == 201, added.text

    photo = example("valid/asset-version-photo-external.json")
    minter = Minter()
    photo["id"], photo["asset_id"] = minter.mint("asv"), minter.mint("ast")
    photo["scope"] = {"production_id": production, "story_id": story, "board_id": added.json()["id"]}
    photo["content"]["locator"] = blob_locator(production, photo["content"]["sha256"], "image/png")
    received = hashlib.sha256(b"synthetic received photo").hexdigest()
    with engine.begin() as conn:
        record_asset_version(conn, photo, received_sha256=received)
        record_asset_version(conn, photo, received_sha256=received)
        persisted = conn.execute(sa.select(asset_versions.c.document, asset_versions.c.received_sha256)
                                 .where(asset_versions.c.id == photo["id"])).one()
        assert persisted.received_sha256 == received != persisted.document["content"]["sha256"]
        assert persisted.document["provenance"]["external"]["externally_generated"] is True
    with engine.begin() as conn, pytest.raises(ContractError, match="immutable version identity"):
        record_asset_version(conn, photo, received_sha256="a" * 64)
