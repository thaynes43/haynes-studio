"""Overlap revision 0013 with the transaction served by the third pin."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError

from haynes_studio.db.migrate import migrate
from tests.db.test_studio_api import engine, owner_engine, runtime_db, runtime_role

pytestmark = pytest.mark.db
PREDECESSOR = "0012_release_constraints"
TARGET = "0013_matte_jobs"

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
    first_locked, second_entered, readiness_released = Event(), Event(), Event()
    lock_acquired = None
    migration_pid = None

    def before_ddl(conn, cursor, statement, parameters, context, executemany):
        nonlocal migration_pid
        if first == "readiness" and statement.startswith(
            ("LOCK TABLE worker_lane_grants", "ALTER TABLE worker_lane_grants")
        ):
            migration_pid = conn.connection.driver_connection.info.backend_pid
            second_entered.set()

    def after_ddl(conn, cursor, statement, parameters, context, executemany):
        nonlocal lock_acquired
        if statement.startswith(("LOCK TABLE ", "ALTER TABLE ")) and lock_acquired is None:
            lock_acquired = monotonic()
            if first == "migration":
                first_locked.set()
                assert second_entered.wait(timeout=3)
            else:
                # PostgreSQL can grant this lock while the readiness backend
                # is still releasing the relations used by the NOWAIT locks.
                assert readiness_released.wait(timeout=3)

    with ThreadPoolExecutor(max_workers=1) as background, engine.connect() as read:
        read.exec_driver_sql("SET LOCAL statement_timeout = '3s'")
        for query in BEFORE_GRANTS:
            read.exec_driver_sql(query)
        if first == "readiness":
            read.exec_driver_sql(GRANTS)
            readiness_pid = read.connection.driver_connection.info.backend_pid
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
                if first == "readiness":
                    wait_for_blocker(read, migration_pid, readiness_pid)
            finally:
                read.rollback()
            if first == "readiness":
                with engine.connect() as observer:
                    assert observer.exec_driver_sql(
                        "SELECT NOT EXISTS (SELECT FROM pg_locks WHERE pid = %s AND locktype = 'relation')",
                        (readiness_pid,),
                    ).scalar_one()
                readiness_released.set()
            upgraded.result(timeout=3)
            lock_seconds = monotonic() - lock_acquired
        finally:
            second_entered.set()
            readiness_released.set()
            read.rollback()
            sa.event.remove(owner_engine, "before_cursor_execute", before_ddl)
            sa.event.remove(owner_engine, "after_cursor_execute", after_ddl)

    record_property("readiness_ms", round(1000 * readiness_seconds, 1))
    record_property("ddl_lock_window_ms", round(1000 * lock_seconds, 1))
    with engine.connect() as read:
        assert read.exec_driver_sql("SELECT lane FROM media_job_lanes ORDER BY lane").scalars().all() == [
            "image", "matte", "voice",
        ]


def wait_for_blocker(observer, blocked_pid, blocker_pid):
    deadline = monotonic() + 2
    while monotonic() < deadline:
        blockers = observer.exec_driver_sql("SELECT pg_blocking_pids(%s)", (blocked_pid,)).scalar_one()
        if blocker_pid in blockers:
            return
        sleep(0.005)
    pytest.fail(f"PostgreSQL did not queue backend {blocked_pid} behind {blocker_pid}")


def test_upgrade_refuses_late_readiness_lock_then_retries(predecessor, owner_engine, engine, runtime_role):
    with engine.connect() as readiness:
        # Model the observable release order: grants are free and a later
        # relation from predecessor readiness still has an AccessShareLock.
        readiness.exec_driver_sql(AFTER_GRANTS[0])
        with pytest.raises(OperationalError, match="could not obtain lock") as caught:
            migrate(owner_engine, runtime_role=runtime_role[0])
        assert caught.value.orig.sqlstate == "55P03"
        assert caught.value.statement.startswith("LOCK TABLE media_job_lanes,")
        assert caught.value.statement.endswith("NOWAIT")
        with owner_engine.connect() as owner:
            assert owner.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == PREDECESSOR

    migrate(owner_engine, runtime_role=runtime_role[0])
    with owner_engine.connect() as owner:
        assert owner.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == TARGET


@pytest.mark.parametrize("release_holder", [True, False], ids=["commit", "timeout"])
def test_reader_queues_behind_waiting_upgrade(
    release_holder, predecessor, owner_engine, engine, runtime_role, record_property,
):
    migrating, reading = Event(), Event()
    migration_pid = reader_pid = None

    def before_lock(conn, cursor, statement, parameters, context, executemany):
        nonlocal migration_pid
        if statement == "LOCK TABLE worker_lane_grants IN ACCESS EXCLUSIVE MODE":
            # Check the GUC on the migrating connection, without wall-clock
            # tolerances that could let a different configured timeout pass.
            cursor.execute("SHOW lock_timeout")
            assert cursor.fetchone() == ("500ms",)
            migration_pid = conn.connection.driver_connection.info.backend_pid
            migrating.set()

    def read_ready():
        nonlocal reader_pid
        with engine.connect() as reader:
            reader.exec_driver_sql("SET LOCAL statement_timeout = '3s'")
            for query in BEFORE_GRANTS:
                reader.exec_driver_sql(query)
            reader_pid = reader.connection.driver_connection.info.backend_pid
            started = monotonic()
            reading.set()
            reader.exec_driver_sql(GRANTS)
            for query in AFTER_GRANTS:
                reader.exec_driver_sql(query)
            return monotonic() - started

    with ThreadPoolExecutor(max_workers=2) as background, engine.connect() as holder:
        holder.exec_driver_sql(GRANTS)
        holder_pid = holder.connection.driver_connection.info.backend_pid
        sa.event.listen(owner_engine, "before_cursor_execute", before_lock)
        try:
            upgraded = background.submit(migrate, owner_engine, runtime_role=runtime_role[0])
            try:
                assert migrating.wait(timeout=2)
                wait_for_blocker(holder, migration_pid, holder_pid)
                reader = background.submit(read_ready)
                assert reading.wait(timeout=2)
                wait_for_blocker(holder, reader_pid, migration_pid)
                if release_holder:
                    holder.rollback()
                    upgraded.result(timeout=3)
                else:
                    with pytest.raises(OperationalError, match="lock timeout") as caught:
                        upgraded.result(timeout=3)
                    assert caught.value.orig.sqlstate == "55P03"
                # In the timeout case the grant holder still has its lock.
                # The reader can proceed as soon as the queued upgrade leaves.
                record_property("queued_readiness_ms", round(1000 * reader.result(timeout=3), 1))
            finally:
                holder.rollback()
        finally:
            sa.event.remove(owner_engine, "before_cursor_execute", before_lock)

    with owner_engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == (
            TARGET if release_holder else PREDECESSOR
        )


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


@pytest.mark.parametrize("table", ["worker_lane_grants", "queue_lane_events"])
def test_downgrade_prelocks_contended_tables(table, owner_engine, engine):
    def bound_test_statement(conn):
        conn.exec_driver_sql("SET LOCAL statement_timeout = '3s'")

    with engine.connect() as serving:
        serving.exec_driver_sql(f"SELECT 1 FROM {table} LIMIT 0")
        sa.event.listen(owner_engine, "begin", bound_test_statement)
        try:
            reason = "lock timeout" if table == "worker_lane_grants" else "could not obtain lock"
            with pytest.raises(OperationalError, match=reason) as caught:
                migrate(owner_engine, direction="downgrade", target=PREDECESSOR)
            assert caught.value.orig.sqlstate == "55P03"
            assert caught.value.statement.startswith("LOCK TABLE ")
        finally:
            sa.event.remove(owner_engine, "begin", bound_test_statement)
    with owner_engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == TARGET
        assert conn.exec_driver_sql("SELECT next_position FROM media_job_lanes WHERE lane = 'matte'").scalar_one() == 1
