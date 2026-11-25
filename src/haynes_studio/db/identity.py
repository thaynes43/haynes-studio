"""The credential digests, OIDC challenge state, and per-subject selections."""

import hashlib
import re

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from haynes_studio.agent_tokens import valid_agent_token

from .problems import StaleRevision
from .schema import agent_grants, agent_keys, login_attempts, selections, sessions, worker_lane_grants, worker_tokens

AGENT_SCOPES = frozenset({"read", "draft:write", "assets:generate", "assets:upload",
                          "runs:queue", "formats:write", "archive:read", "archive:write"})
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43,128}")


def digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def token_digest(token: str | None) -> str | None:
    return digest(token) if token is not None and _TOKEN.fullmatch(token) else None


def create_attempt(conn, secret: str, *, state: str, nonce: str, verifier: str, expires_at,
                   return_to: str = "/"):
    conn.execute(login_attempts.delete().where(login_attempts.c.expires_at <= sa.func.now()))
    conn.execute(login_attempts.insert().values(
        digest=digest(secret), state=state, nonce=nonce, verifier=verifier, expires_at=expires_at,
        return_to=return_to,
    ))


def consume_attempt(conn, secret: str | None, state: str):
    return conn.execute(login_attempts.delete().where(
        login_attempts.c.digest == token_digest(secret), login_attempts.c.state == state,
        login_attempts.c.expires_at > sa.func.now(),
    ).returning(login_attempts.c.nonce, login_attempts.c.verifier, login_attempts.c.return_to)).one_or_none()


def create_session(conn, secret: str, *, iss: str, sub: str, display_name: str | None,
                   csrf: str, expires_at, auth_time=None):
    conn.execute(sessions.delete().where(sessions.c.expires_at <= sa.func.now()))
    conn.execute(sessions.insert().values(digest=digest(secret), iss=iss, sub=sub,
                                          display_name=display_name, csrf=csrf, expires_at=expires_at,
                                          auth_time=auth_time))


def get_session(conn, secret: str | None):
    return conn.execute(sa.select(sessions).where(
        sessions.c.digest == token_digest(secret), sessions.c.expires_at > sa.func.now(),
    )).one_or_none()


def delete_session(conn, secret: str | None):
    conn.execute(sessions.delete().where(sessions.c.digest == token_digest(secret)))


def _active(table):
    return sa.and_(table.c.revoked_at.is_(None), sa.or_(
        table.c.expires_at.is_(None), table.c.expires_at > sa.func.now(),
    ))


def get_agent(conn, secret: str | None) -> tuple[str, dict[str, frozenset[str]]] | None:
    if not valid_agent_token(secret):
        return None
    key_id = conn.scalar(sa.select(agent_keys.c.id).where(
        agent_keys.c.digest == digest(secret), _active(agent_keys),
    ))
    if key_id is None:
        return None
    by_production: dict[str, set[str]] = {}
    for row in conn.execute(sa.select(agent_grants.c.production_id, agent_grants.c.scope).where(
        agent_grants.c.key_id == key_id, agent_grants.c.active,
    )):
        if row.scope in AGENT_SCOPES:
            by_production.setdefault(row.production_id, set()).add(row.scope)
    return key_id, {id_: frozenset(scopes) for id_, scopes in by_production.items()}


def _worker_token(secret):
    return sa.and_(worker_tokens.c.digest == token_digest(secret), _active(worker_tokens))


def get_worker(conn, secret: str | None) -> str | None:
    return conn.scalar(sa.select(worker_tokens.c.worker_id).where(_worker_token(secret)))


def get_worker_lane(conn, secret: str):
    """Read the active identity and its optional grant in one query."""
    tokens_with_lanes = worker_tokens.outerjoin(
        worker_lane_grants, worker_tokens.c.worker_id == worker_lane_grants.c.worker_id,
    )
    return conn.execute(
        sa.select(worker_tokens.c.worker_id, worker_lane_grants.c.lane)
        .select_from(tokens_with_lanes).where(_worker_token(secret))
    ).one_or_none()


def get_selections(conn, iss: str, sub: str) -> dict:
    row = conn.execute(sa.select(selections.c.revision, selections.c.document).where(
        selections.c.iss == iss, selections.c.sub == sub,
    )).one_or_none()
    if row is None:
        return {"revision": 0, "values": {}}
    return {"revision": row.revision, "values": row.document}


def put_selections(conn, iss: str, sub: str, revision: int, values: dict) -> dict:
    if revision == 0:
        stmt = insert(selections).values(iss=iss, sub=sub, revision=1, document=values)
        stmt = stmt.on_conflict_do_nothing()
    else:
        stmt = selections.update().where(
            selections.c.iss == iss, selections.c.sub == sub, selections.c.revision == revision,
        ).values(revision=revision + 1, document=values)
    if conn.scalar(stmt.returning(selections.c.revision)) is None:
        raise StaleRevision(get_selections(conn, iss, sub)["revision"])
    return {"revision": revision + 1, "values": values}
