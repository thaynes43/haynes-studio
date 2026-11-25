"""Add the matte candidate kind and its independently granted FIFO lane.

PostgreSQL's 500 ms lock timeout applies per lock acquisition. The grant
lock can queue. The other three table prelocks use NOWAIT. A reader queued
behind the migration can wait for the grant lock budget plus the DDL and
commit (about 10 ms at the installed table sizes). API readiness latency
also includes its queries. On the fourth-pin upgrade from 0012, a lock
timeout leaves 0012 in place and the migration Job can retry within its
retry budget.
"""

import sqlalchemy as sa
from alembic import op

from haynes_studio.db.grants import MATTE_GRANTS, grant_runtime

revision = "0013_matte_jobs"
down_revision = "0012_release_constraints"
branch_labels = None
depends_on = None

LANE_CHECKS = {
    "worker_lane_grants": ("worker_lane_grants_lane_check", "'run', 'voice', 'image'"),
    "media_job_lanes": ("media_job_lanes_lane_check", "'image', 'voice'"),
    "queue_lane_events": ("queue_lane_events_lane_check", "'run', 'voice', 'image'"),
}


def _lock_changed_tables():
    # The 0012 readiness transaction reads grants, lanes and pause events in
    # that order. Worker auth reads only grants (in its own transaction);
    # media claims lock a lane, then read pause events and lock the job.
    # Once we hold the first lock, fail immediately on any other contention
    # so that a worker transaction cannot extend the readiness interruption.
    # Take media_jobs last, including for the downgrade's FK check.
    op.execute("SET LOCAL lock_timeout = '500ms'")
    op.execute("LOCK TABLE worker_lane_grants IN ACCESS EXCLUSIVE MODE")
    op.execute(
        "LOCK TABLE media_job_lanes, queue_lane_events, media_jobs IN ACCESS EXCLUSIVE MODE NOWAIT"
    )


def _lanes(suffix):
    for table, (constraint, lanes) in LANE_CHECKS.items():
        op.drop_constraint(constraint, table, type_="check")
        op.create_check_constraint(constraint, table, f"lane IN ({lanes}{suffix})")


def _jobs(kinds, lane, candidate):
    # 0005 created the two multi-column checks without explicit names.
    checks = {
        "media_jobs_kind_check": f"kind IN ({kinds})",
        "media_jobs_check1": lane,
        "media_jobs_check2": (
            f"(({candidate}) AND board_id IS NULL AND story_id IS NULL) OR "
            f"(NOT ({candidate}) AND board_id IS NOT NULL AND story_id IS NOT NULL "
            "AND production_id IS NOT NULL)"
        ),
    }
    for name, predicate in checks.items():
        op.drop_constraint(name, "media_jobs", type_="check")
        op.create_check_constraint(name, "media_jobs", predicate)


def upgrade():
    _lock_changed_tables()
    _lanes(", 'matte'")
    _jobs("'voice', 'photo', 'asset_candidate', 'matte'",
          "(kind = 'voice' AND lane = 'voice') OR (kind = 'matte' AND lane = 'matte') OR "
          "(kind IN ('photo', 'asset_candidate') AND lane = 'image')",
          "kind IN ('asset_candidate', 'matte')")
    op.execute("INSERT INTO media_job_lanes (lane, next_position) VALUES ('matte', 1)")
    op.add_column("media_jobs", sa.Column("matte_releases", sa.SmallInteger(), nullable=False, server_default="0"))
    grant_runtime(MATTE_GRANTS)


def downgrade():
    _lock_changed_tables()
    # Existing matte jobs, lane events or grants block this downgrade. Keep the
    # history and bindings intact if the older schema cannot represent them.
    _jobs("'voice', 'photo', 'asset_candidate'", "(kind = 'voice') = (lane = 'voice')",
          "kind = 'asset_candidate'")
    op.execute("DELETE FROM media_job_lanes WHERE lane = 'matte'")
    _lanes("")
    op.drop_column("media_jobs", "matte_releases")
