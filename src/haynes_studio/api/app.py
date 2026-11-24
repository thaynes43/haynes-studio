"""FastAPI assembly. Startup configuration is supplied by the process environment."""

import asyncio
import logging
import os
from concurrent.futures import Future
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock, Thread
from time import monotonic

import sqlalchemy as sa
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.exc import TimeoutError as DBTimeoutError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from haynes_studio.db.engine import connect_engine
from haynes_studio.db.problems import NotFound, StaleRevision
from haynes_studio.db.schema import sessions
from haynes_studio.errors import ContractError, pointer
from haynes_studio.store.local import LocalStore

from . import auth, media, routes
from .config import from_environment
from .errors import APIError, ErrorDetail, ErrorEnvelope, STATUS, error_response, missing
from .models import build_models
from .oidc import OIDC
from .openapi import install_openapi
from .transport import RequestContextMiddleware

logger = logging.getLogger(__name__)
STORE_CHECK_TIMEOUT = 0.25


class StoreProbe:
    """Share an in-flight filesystem check across readiness requests."""

    def __init__(self, root):
        self.root = Path(root)
        self._lock = Lock()
        self._result: Future[bool] | None = None
        self._deadline = 0.0

    def _check(self, result: Future[bool]) -> None:
        try:
            ready = self.root.is_dir()
        except OSError:
            ready = False
        except Exception as error:
            result.set_exception(error)
            return
        result.set_result(ready)

    async def ready(self) -> bool:
        with self._lock:
            if self._result is None or self._result.done():
                result = Future()
                result.set_running_or_notify_cancel()
                self._deadline = monotonic() + STORE_CHECK_TIMEOUT
                # A stuck kernel call must not prevent process shutdown.
                Thread(target=self._check, args=(result,), name="studio-store-probe",
                       daemon=True).start()
                self._result = result
            result, remaining = self._result, self._deadline - monotonic()
        if remaining <= 0:
            return False
        try:
            return await asyncio.wait_for(asyncio.wrap_future(result), timeout=remaining)
        except TimeoutError:
            return False


def _errors(app: FastAPI):
    @app.exception_handler(APIError)
    async def api_error(request: Request, error: APIError):
        return error_response(request, error)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        if error.status_code == 404:
            problem = missing()
        elif error.status_code == 405:
            problem = APIError(405, "method.not_allowed", "The method is unavailable", headers=error.headers)
        else:
            status = error.status_code if error.status_code in STATUS else 500
            problem = APIError(status, "request.failed", "The request could not be completed")
        return await api_error(request, problem)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, error: RequestValidationError):
        first = error.errors()[0]
        parts = first["loc"]
        code = "schema.unknown_field" if first["type"] == "extra_forbidden" else "schema.invalid"
        path = pointer(*(parts[1:] if parts[0] == "body" else parts))
        return await api_error(request, APIError(422, code, first["msg"], path=path))

    @app.exception_handler(ContractError)
    async def invalid_document(request: Request, error: ContractError):
        first = error.violations[0]
        status = "unavailable" if first.status == "unavailable" else "invalid"
        return await api_error(request, APIError(422, first.rule, first.message,
                                                 path=first.path, status=status))

    @app.exception_handler(StaleRevision)
    async def stale(request: Request, error: StaleRevision):
        return await api_error(request, APIError(
            409, "conflict.revision", "The record has changed", path="/revision",
            current_revision=error.current, headers={"ETag": f'"{error.current}"'},
        ))

    @app.exception_handler(NotFound)
    async def not_found(request: Request, error: NotFound):
        return await api_error(request, missing())

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, error: SQLAlchemyError):
        transient = isinstance(error, (OperationalError, DBTimeoutError))
        logger.error("Studio database operation failed (%s) request_id=%s",
                     type(error).__name__, request.state.request_id)
        return await api_error(request, APIError(503 if transient else 500, "database.failed",
                                                 "The metadata store could not complete the request"))


def _application(engine, store, oidc) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app):
        yield
        if engine is not None:
            engine.dispose()

    app = FastAPI(title="Haynes Studio API", version="1.0.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False)
    app.state.engine, app.state.store, app.state.oidc = engine, store, oidc
    _errors(app)
    app.add_middleware(RequestContextMiddleware)

    build_models()
    for model in (ErrorDetail, ErrorEnvelope):
        model.model_config["defer_build"] = False
        model.model_rebuild()
    auth_router, protected_auth, current_actor, authenticated_route = auth.build_router()
    app.include_router(auth_router)
    app.include_router(protected_auth)
    app.include_router(routes.build_router(current_actor, authenticated_route))
    app.include_router(media.build_router(current_actor, authenticated_route))

    @app.get("/healthz", status_code=204, response_class=Response, operation_id="healthz")
    def healthz():
        return Response(status_code=204)

    store_probe = StoreProbe(store.root) if store is not None else None

    def database_ready():
        try:
            with engine.connect() as conn:
                conn.execute(sa.select(sa.literal(1)).select_from(sessions).limit(0))
        except (SQLAlchemyError, OSError):
            return False
        return True

    @app.get("/readyz", status_code=204, response_class=Response, operation_id="readyz",
             responses={503: {"description": "A dependency is unavailable"}})
    async def readyz():
        ready = store_probe is not None and await store_probe.ready()
        if ready and await run_in_threadpool(database_ready):
            return Response(status_code=204)
        return Response(status_code=503)

    install_openapi(app)
    return app


def create_app(engine, store: LocalStore, oidc: OIDC) -> FastAPI:
    """Compose the service with explicit dependencies, including in isolated tests."""
    return _application(engine, store, oidc)


def from_env() -> FastAPI:
    oidc = OIDC(from_environment())
    dsn, root = os.getenv("STUDIO_DATABASE_URL"), os.getenv("STUDIO_STORE_ROOT")
    if not dsn or not root:
        raise ValueError("STUDIO_DATABASE_URL and STUDIO_STORE_ROOT are required")
    store = LocalStore(root)
    engine = connect_engine(dsn, os.getenv("STUDIO_DATABASE_SCHEMA", "studio"))
    return create_app(engine, store, oidc)


def schema_app() -> FastAPI:
    """Generate OpenAPI without application secrets or external connections."""
    return _application(None, None, None)
