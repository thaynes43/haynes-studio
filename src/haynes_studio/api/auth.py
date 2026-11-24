"""Studio principal resolution and browser session endpoints."""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import compare_digest
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Security
from fastapi.responses import RedirectResponse, Response
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer
from fastapi.security.utils import get_authorization_scheme_param
from starlette.concurrency import run_in_threadpool

from haynes_studio.canonical.model import Principal
from haynes_studio.db import identity
from haynes_studio.db.engine import snapshot

from .config import OIDCSettings
from .errors import APIError, ERROR_RESPONSES, forbidden, unauthenticated
from .oidc import random_secret
from .transport import MetadataRoute

SESSION_COOKIE = "__Host-studio-session"
GROUP_SESSION_PREFIX = "group."
LOGIN_COOKIE = "__Host-studio-login"
CSRF_HEADER = "X-Studio-CSRF"
ATTEMPT_SECONDS = 300
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF = Annotated[str | None, Header(alias=CSRF_HEADER,
    description="Required on unsafe methods when authenticating with the session cookie")]


@dataclass(frozen=True)
class Actor:
    principal: Principal
    grants: dict[str, frozenset[str]] = field(default_factory=dict, repr=False)
    csrf: str | None = field(default=None, repr=False)
    display_name: str | None = None

    def human(self) -> None:
        if self.principal.kind != "human":
            raise forbidden()

    def productions(self, scope: str) -> frozenset[str] | None:
        if self.principal.kind == "human":
            return None
        return frozenset(id_ for id_, scopes in self.grants.items() if scope in scopes)

    def require(self, scope: str, production_id: str) -> None:
        productions = self.productions(scope)
        if productions is not None and production_id not in productions:
            raise forbidden()


def worker_access(request: Request) -> Principal:
    """P-14 boundary for the internal queue routes owned by story 410."""
    headers = request.headers.getlist("authorization")
    if len(headers) != 1:
        raise unauthenticated()
    scheme, token = get_authorization_scheme_param(headers[0])
    if scheme.lower() != "bearer" or not token:
        raise unauthenticated()
    with snapshot(request.app.state.engine) as conn:
        worker_id = identity.get_worker(conn, token)
    if worker_id is None:
        raise unauthenticated()
    principal = Principal(kind="worker", worker_id=worker_id)
    request.state.principal = principal
    return principal


class WorkerRoute(MetadataRoute):
    """Authenticate a service token before routing through strict request parsing."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def authenticated(request):
            await run_in_threadpool(worker_access, request)
            return await handler(request)

        return authenticated


def _set_cookie(response: Response, name: str, value: str, age: int):
    response.set_cookie(name, value, max_age=age, secure=True, httponly=True,
                        samesite="lax", path="/")


def _clear_cookie(response: Response, name: str):
    response.delete_cookie(name, path="/", secure=True, httponly=True, samesite="lax")


def _session_key(cookie: str | None, settings: OIDCSettings) -> str | None:
    if cookie is None or not cookie.startswith(GROUP_SESSION_PREFIX):
        return cookie
    if not settings.allowed_groups:
        return None
    # Bind group-only sessions to the complete group policy without storing
    # claims or altering the sessions table. Subject sessions keep their key.
    policy_key = json.dumps([cookie, sorted(settings.allowed_groups)])
    return sha256(policy_key.encode("ascii")).hexdigest()


def build_router():
    """Create the authentication routes and the downstream actor dependency."""
    session_cookie = APIKeyCookie(name=SESSION_COOKIE, scheme_name="StudioSession", auto_error=False)
    bearer = HTTPBearer(scheme_name="StudioBearer", auto_error=False)

    def resolve_actor(request: Request, authorization, session, csrf) -> Actor:
        # A supplied Authorization header takes precedence. An invalid bearer cannot
        # silently become a session-cookie request.
        if "authorization" in request.headers:
            if authorization is None or len(request.headers.getlist("authorization")) != 1:
                raise unauthenticated()
            with snapshot(request.app.state.engine) as conn:
                agent = identity.get_agent(conn, authorization.credentials)
            if agent is None:
                raise unauthenticated()
            key, grants = agent
            principal = Principal(kind="agent", key_id=key)
            request.state.principal = principal
            return Actor(principal, grants)
        if not session:
            raise unauthenticated()
        settings = request.app.state.oidc.settings
        with snapshot(request.app.state.engine) as conn:
            row = identity.get_session(conn, _session_key(session, settings))
        if row is None or row.iss != settings.issuer:
            raise unauthenticated()
        if not session.startswith(GROUP_SESSION_PREFIX) and row.sub not in settings.allowed_subjects:
            raise unauthenticated()
        principal = Principal(kind="human", iss=row.iss, sub=row.sub)
        request.state.principal = principal
        if request.method not in SAFE_METHODS:
            if csrf is None or not csrf.isascii() or not compare_digest(csrf, row.csrf):
                raise forbidden("auth.csrf", "The session requires a valid CSRF header")
        return Actor(principal, csrf=row.csrf, display_name=row.display_name)

    async def access(request: Request,
                     authorization: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)],
                     session: Annotated[str | None, Security(session_cookie)],
                     csrf: CSRF = None) -> Actor:
        actor = getattr(request.state, "actor", None)
        if actor is None:
            actor = await run_in_threadpool(resolve_actor, request, authorization, session, csrf)
            request.state.actor = actor
        return actor

    class AuthenticatedRoute(MetadataRoute):
        def get_route_handler(self):
            handler = super().get_route_handler()

            async def authenticated(request):
                # FastAPI would otherwise parse the body before solving dependencies.
                await access(request, await bearer(request), await session_cookie(request),
                             request.headers.get(CSRF_HEADER))
                return await handler(request)

            return authenticated

    CurrentActor = Annotated[Actor, Depends(access)]

    router = APIRouter(prefix="/auth", tags=["authentication"], responses=ERROR_RESPONSES,
                       route_class=MetadataRoute)
    protected = APIRouter(prefix="/auth", tags=["authentication"], responses=ERROR_RESPONSES,
                          route_class=AuthenticatedRoute)


    @router.get("/login", status_code=303, response_class=RedirectResponse, operation_id="login")
    def login(request: Request):
        secret, state, nonce, verifier = (random_secret() for _ in range(4))
        url = request.app.state.oidc.authorize(state, nonce, verifier)
        with request.app.state.engine.begin() as conn:
            identity.create_attempt(conn, secret, state=state, nonce=nonce, verifier=verifier,
                                    expires_at=datetime.now(timezone.utc) + timedelta(seconds=ATTEMPT_SECONDS))
        response = RedirectResponse(url, status_code=303)
        _set_cookie(response, LOGIN_COOKIE, secret, ATTEMPT_SECONDS)
        return response


    @router.get("/callback", status_code=303, response_class=RedirectResponse, operation_id="callback")
    def callback(request: Request, state: Annotated[str, Query(min_length=1, max_length=128)],
                 code: Annotated[str | None, Query(min_length=1, max_length=4096)] = None):
        # The cookie and state must agree, and one callback can consume the state.
        if len(request.query_params.getlist("state")) != 1 or len(request.query_params.getlist("code")) > 1:
            raise APIError(401, "auth.oidc_state", "The login callback is invalid")
        engine = request.app.state.engine
        with engine.begin() as conn:
            attempt = identity.consume_attempt(conn, request.cookies.get(LOGIN_COOKIE), state)
        if attempt is None:
            raise APIError(401, "auth.oidc_state", "The login attempt expired or does not match this browser")
        if not code or "error" in request.query_params:
            raise APIError(401, "auth.oidc_invalid", "OIDC did not return an authorization code")
        oidc = request.app.state.oidc
        claims = oidc.exchange(code, attempt.nonce, attempt.verifier)
        settings = oidc.settings
        secret, csrf = random_secret(), random_secret()
        if claims["sub"] not in settings.allowed_subjects:
            secret = GROUP_SESSION_PREFIX + secret
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=settings.session_seconds)
        name = claims.get("name")
        if not isinstance(name, str) or not name.isprintable() or len(name) > 200:
            name = None
        with engine.begin() as conn:
            identity.delete_session(conn, _session_key(request.cookies.get(SESSION_COOKIE), settings))
            identity.create_session(conn, _session_key(secret, settings), iss=claims["iss"], sub=claims["sub"],
                                    display_name=name, csrf=csrf, expires_at=expires_at)
        request.state.principal = Principal(kind="human", iss=claims["iss"], sub=claims["sub"])
        response = RedirectResponse("/", status_code=303)
        _clear_cookie(response, LOGIN_COOKIE)
        _set_cookie(response, SESSION_COOKIE, secret, max(0, int((expires_at - now).total_seconds())))
        return response


    @protected.post("/logout", status_code=204, response_class=Response, operation_id="logout")
    def logout(request: Request, actor: CurrentActor):
        actor.human()
        settings = request.app.state.oidc.settings
        with request.app.state.engine.begin() as conn:
            identity.delete_session(conn, _session_key(request.cookies.get(SESSION_COOKIE), settings))
        response = Response(status_code=204)
        _clear_cookie(response, SESSION_COOKIE)
        _clear_cookie(response, LOGIN_COOKIE)
        return response

    return router, protected, CurrentActor, AuthenticatedRoute
