"""Add the matte candidate kind and its independently granted FIFO lane."""

from alembic import op

revision = "0013_matte_jobs"
down_revision = "0012_release_constraints"
branch_labels = None
depends_on = None

LANE_CHECKS = {
    "media_job_lanes": ("media_job_lanes_lane_check", "'image', 'voice'"),
    "queue_lane_events": ("queue_lane_events_lane_check", "'run', 'voice', 'image'"),
    "worker_lane_grants": ("worker_lane_grants_lane_check", "'run', 'voice', 'image'"),
}


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
    _lanes(", 'matte'")
    _jobs("'voice', 'photo', 'asset_candidate', 'matte'",
          "(kind = 'voice' AND lane = 'voice') OR (kind = 'matte' AND lane = 'matte') OR "
          "(kind IN ('photo', 'asset_candidate') AND lane = 'image')",
          "kind IN ('asset_candidate', 'matte')")
    op.execute("INSERT INTO media_job_lanes (lane, next_position) VALUES ('matte', 1)")


def downgrade():
    # Existing matte jobs, lane events or grants block this downgrade. Keep the
    # history and bindings intact if the older schema cannot represent them.
    _jobs("'voice', 'photo', 'asset_candidate'", "(kind = 'voice') = (lane = 'voice')",
          "kind = 'asset_candidate'")
    op.execute("DELETE FROM media_job_lanes WHERE lane = 'matte'")
    _lanes("")
