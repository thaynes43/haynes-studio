"""Overlap revision 0013 with the transaction served by the third pin."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError

from haynes_studio.db.migrate import migrate
from tests.db.test_studio_api import engine, owner_engine, runtime_db, runtime_role

pytestmark = pytest.mark.db
PREDECESSOR = "0012_release_constraints"
TARGET = "0013_matte_jobs"
LOCK_BOUND_SECONDS = 0.5

# The 80975a9 /readyz transaction, with its SQLAlchemy LIMIT parameters inlined.
BEFORE_GRANTS = (
    "SELECT 1 FROM sessions LIMIT 0",
    "SELECT id FROM run_lane LIMIT 0",
)
GRANTS = "SELECT lane FROM worker_lane_grants LIMIT 0"
AFTER_GRANTS = (
    "SELECT lane FROM media_job_lanes LIMIT 0",
    "SELECT lane FROM queue_lane_events LIMIT 0",
    "SELECT id FROM go_live_approvals LIMIT 0",
    "SELECT id FROM format_versions LIMIT 0",
    "SELECT id FROM escalation_packages LIMIT 0",
    "SELECT stories.feedback_iteration_id FROM stories "
    "JOIN feedback_iterations ON feedback_iterations.id = stories.feedback_iteration_id "
    "JOIN run_candidates ON run_candidates.id = feedback_iterations.candidate_id "
    "JOIN candidate_feedback ON run_candidates.id = candidate_feedback.candidate_id LIMIT 0",
    "SELECT archive_versions.id FROM archive_versions "
    "JOIN archive_records ON archive_records.id = archive_versions.record_id LIMIT 0",
    "SELECT release_packages.document_bytes, publications.idempotency_key FROM release_packages "
    "JOIN publications ON release_packages.sha256 = publications.package_sha256 LIMIT 0",
)


@pytest.fixture
def predecessor(owner_engine, runtime_role):
    migrate(owner_engine, direction="downgrade", target=PREDECESSOR)
    yield
    migrate(owner_engine, runtime_role=runtime_role[0])


@pytest.mark.parametrize("first", ["readiness", "migration"])
def test_predecessor_readiness_overlaps_upgrade(
    first, predecessor, owner_engine, engine, runtime_role, record_property,
):
    first_locked, second_entered = Event(), Event()
    lock_acquired = None

    def before_ddl(conn, cursor, statement, parameters, context, executemany):
        if first == "readiness" and statement.startswith(
            ("LOCK TABLE worker_lane_grants", "ALTER TABLE worker_lane_grants")
        ):
            second_entered.set()

    def after_ddl(conn, cursor, statement, parameters, context, executemany):
        nonlocal lock_acquired
        if statement.startswith(("LOCK TABLE ", "ALTER TABLE ")) and lock_acquired is None:
            lock_acquired = monotonic()
            if first == "migration":
                first_locked.set()
                assert second_entered.wait(timeout=3)

    with ThreadPoolExecutor(max_workers=1) as background, engine.connect() as read:
        read.exec_driver_sql("SET LOCAL statement_timeout = '3s'")
        for query in BEFORE_GRANTS:
            read.exec_driver_sql(query)
        if first == "readiness":
            read.exec_driver_sql(GRANTS)
        sa.event.listen(owner_engine, "before_cursor_execute", before_ddl)
        sa.event.listen(owner_engine, "after_cursor_execute", after_ddl)
        try:
            upgraded = background.submit(migrate, owner_engine, runtime_role=runtime_role[0])
            if first == "readiness":
                assert second_entered.wait(timeout=3)
            else:
                assert first_locked.wait(timeout=3)
            started = monotonic()
            try:
                if first == "migration":
                    second_entered.set()
                    read.exec_driver_sql(GRANTS)
                for query in AFTER_GRANTS:
                    read.exec_driver_sql(query)
                readiness_seconds = monotonic() - started
            finally:
                read.rollback()
            upgraded.result(timeout=3)
            lock_seconds = monotonic() - lock_acquired
        finally:
            second_entered.set()
            read.rollback()
            sa.event.remove(owner_engine, "before_cursor_execute", before_ddl)
            sa.event.remove(owner_engine, "after_cursor_execute", after_ddl)

    record_property("readiness_ms", round(1000 * readiness_seconds, 1))
    record_property("ddl_lock_window_ms", round(1000 * lock_seconds, 1))
    assert readiness_seconds < LOCK_BOUND_SECONDS
    with engine.connect() as read:
        assert read.exec_driver_sql("SELECT lane FROM media_job_lanes ORDER BY lane").scalars().all() == [
            "image", "matte", "voice",
        ]


@pytest.mark.parametrize("table", ["worker_lane_grants", "media_job_lanes", "queue_lane_events", "media_jobs"])
def test_upgrade_refuses_contended_tables_and_preserves_predecessor(
    table, predecessor, owner_engine, engine, runtime_role,
):
    with engine.connect() as serving:
        serving.exec_driver_sql(f"SELECT 1 FROM {table} LIMIT 0")
        with pytest.raises(OperationalError) as caught:
            migrate(owner_engine, runtime_role=runtime_role[0])
        assert caught.value.orig.sqlstate == "55P03"
        reason = "lock timeout" if table == "worker_lane_grants" else "could not obtain lock"
        assert reason in str(caught.value.orig)
    with owner_engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == PREDECESSOR
