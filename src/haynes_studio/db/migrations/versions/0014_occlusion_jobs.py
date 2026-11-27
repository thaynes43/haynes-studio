"""Add the independently granted occlusion lane without rewriting old jobs."""

from importlib import import_module

from alembic import op

revision = "0014_occlusion_jobs"
down_revision = "0013_matte_jobs"
branch_labels = None
depends_on = None

previous = import_module("haynes_studio.db.migrations.versions.0013_matte_jobs")


def _checks(*, occlusion):
    extra = ", 'occlusion'" if occlusion else ""
    previous._lanes(", 'matte'" + extra)
    previous._jobs(
        "'voice', 'photo', 'asset_candidate', 'matte'" + extra,
        "(kind = 'voice' AND lane = 'voice') OR (kind = 'matte' AND lane = 'matte') OR "
        "(kind IN ('photo', 'asset_candidate') AND lane = 'image')"
        + (" OR (kind = 'occlusion' AND lane = 'occlusion')" if occlusion else ""),
        "kind IN ('asset_candidate', 'matte'" + extra + ")",
    )


def upgrade():
    previous._lock_changed_tables()
    _checks(occlusion=True)
    op.execute("INSERT INTO media_job_lanes (lane, next_position) VALUES ('occlusion', 1)")


def downgrade():
    previous._lock_changed_tables()
    # The checks and FK refuse a downgrade that would discard queue history.
    op.execute("DELETE FROM media_job_lanes WHERE lane = 'occlusion'")
    _checks(occlusion=False)
