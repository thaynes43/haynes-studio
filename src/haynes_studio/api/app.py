"""FastAPI assembly. Startup configuration is supplied by the process environment."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock, Thread
from time import monotonic

import sqlalchemy as sa
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.exc import TimeoutError as DBTimeoutError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from haynes_studio.db import runs
from haynes_studio.db.engine import connect_engine
from haynes_studio.db.problems import NotFound, StaleRevision
from haynes_studio.db.schema import go_live_approvals, run_lane, sessions
from haynes_studio.errors import ContractError, pointer
from haynes_studio.store.local import LocalStore

from . import approval_routes, auth, media, routes, run_routes
from .config import DEFAULT_STORE_FRESHNESS_SECONDS, from_environment, store_freshness_from_environment
from .errors import APIError, ErrorDetail, ErrorEnvelope, STATUS, error_response, missing
from .models import build_models
from .oidc import OIDC
from .openapi import install_openapi
from .transport import RequestContextMiddleware

logger = logging.getLogger(__name__)


class StoreProbe:
    """Answer from the last completed filesystem check and refresh it in the background."""

    def __init__(self, root, freshness_seconds: int):
        self.root = Path(root)
        self.freshness_seconds = freshness_seconds
        self._lock = Lock()
        self._result: tuple[float, bool] | None = None
        self._checking = False

    def _check(self) -> None:
        try:
            ready = self.root.is_dir()
        except OSError:
            ready = False
        except Exception as error:
            logger.warning("Studio store check failed (%s)", type(error).__name__)
            ready = False
        finished_at = monotonic()
        with self._lock:
            self._result = finished_at, ready
            self._checking = False

    def ready(self) -> bool:
        with self._lock:
            finished_at, ready = self._result or (float("-inf"), False)
            age = monotonic() - finished_at
            if age > self.freshness_seconds / 2 and not self._checking:
                # A stuck kernel call must not prevent process shutdown.
                Thread(target=self._check, name="studio-store-probe", daemon=True).start()
                self._checking = True
            return ready and age <= self.freshness_seconds


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

    @app.exception_handler(runs.IdempotencyMismatch)
    async def idempotency_mismatch(request: Request, error: runs.IdempotencyMismatch):
        return await api_error(request, APIError(422, "idempotency.mismatch",
                                                 "This key already queued a different story revision"))

    @app.exception_handler(runs.QueueConflict)
    async def queue_conflict(request: Request, error: runs.QueueConflict):
        return await api_error(request, APIError(409, error.code, str(error)))

    @app.exception_handler(NotFound)
    async def not_found(request: Request, error: NotFound):
        return await api_error(request, missing())

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, error: SQLAlchemyError):
        if isinstance(error, IntegrityError):
            diagnostic = getattr(error.orig, "diag", None)
            if getattr(diagnostic, "constraint_name", None) == "draft_name_unique":
                production = diagnostic.table_name == "productions"
                return await api_error(request, APIError(
                    409, "production.name_duplicate" if production else "story.title_duplicate",
                    "That production name is already in use" if production else "That story title is already in use",
                    path="/name" if production else "/title", existing_entity_id=diagnostic.message_detail,
                ))
        transient = isinstance(error, (OperationalError, DBTimeoutError))
        logger.error("Studio database operation failed (%s) request_id=%s",
                     type(error).__name__, request.state.request_id)
        return await api_error(request, APIError(503 if transient else 500, "database.failed",
                                                 "The metadata store could not complete the request"))


def _application(engine, store, oidc, store_freshness_seconds: int = DEFAULT_STORE_FRESHNESS_SECONDS,
                 build_stage_root: str | Path | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app):
        yield
        if engine is not None:
            engine.dispose()

    app = FastAPI(title="Haynes Studio API", version="1.0.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False)
    app.state.engine, app.state.store, app.state.oidc = engine, store, oidc
    app.state.build_revision = run_routes.build_revision_from_environment()
    app.state.build_stage_root = build_stage_root
    _errors(app)
    app.add_middleware(RequestContextMiddleware)

    build_models(*run_routes.transport_models(), approval_routes.ApprovalWrite,
                 approval_routes.ApprovalState, approval_routes.ApprovalView)
    for model in (ErrorDetail, ErrorEnvelope):
        model.model_config["defer_build"] = False
        model.model_rebuild()
    auth_router, protected_auth, current_actor, authenticated_route, approval_route = auth.build_router()
    app.include_router(auth_router)
    app.include_router(protected_auth)
    app.include_router(routes.build_router(current_actor, authenticated_route))
    app.include_router(media.build_router(current_actor, authenticated_route))
    app.include_router(run_routes.build_router(current_actor, authenticated_route))
    app.include_router(approval_routes.build_router(current_actor, approval_route))
    app.include_router(run_routes.worker_router())

    @app.get("/healthz", status_code=204, response_class=Response, operation_id="healthz")
    def healthz():
        return Response(status_code=204)

    store_probe = StoreProbe(store.root, store_freshness_seconds) if store is not None else None

    def database_ready():
        try:
            with engine.connect() as conn:
                conn.execute(sa.select(sa.literal(1)).select_from(sessions).limit(0))
                conn.execute(sa.select(run_lane.c.id).limit(0))
                conn.execute(sa.select(go_live_approvals.c.id).limit(0))
        except (SQLAlchemyError, OSError):
            return False
        return True

    @app.get("/readyz", status_code=204, response_class=Response, operation_id="readyz",
             responses={503: {"description": "A dependency is unavailable"}})
    async def readyz():
        ready = store_probe is not None and store_probe.ready()
        if ready and await run_in_threadpool(database_ready):
            return Response(status_code=204)
        return Response(status_code=503)

    install_openapi(app)
    return app


def create_app(engine, store: LocalStore, oidc: OIDC, *,
               store_freshness_seconds: int = DEFAULT_STORE_FRESHNESS_SECONDS,
               build_stage_root: str | Path | None = None) -> FastAPI:
    """Compose the service with explicit dependencies, including in isolated tests."""
    return _application(engine, store, oidc, store_freshness_seconds, build_stage_root)


def from_env() -> FastAPI:
    oidc = OIDC(from_environment())
    dsn, root = os.getenv("STUDIO_DATABASE_URL"), os.getenv("STUDIO_STORE_ROOT")
    if not dsn or not root:
        raise ValueError("STUDIO_DATABASE_URL and STUDIO_STORE_ROOT are required")
    store_freshness_seconds = store_freshness_from_environment()
    store = LocalStore(root)
    engine = connect_engine(dsn, os.getenv("STUDIO_DATABASE_SCHEMA", "studio"))
    return create_app(engine, store, oidc, store_freshness_seconds=store_freshness_seconds,
                      build_stage_root=os.getenv("STUDIO_BUILD_STAGE_ROOT"))


def schema_app() -> FastAPI:
    """Generate OpenAPI without application secrets or external connections."""
    return _application(None, None, None)
