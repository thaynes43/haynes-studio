"""Bind each installed worker identity to its queue lane."""

from alembic import op

from haynes_studio.db.grants import WORKER_LANE_GRANTS, grant_runtime

revision = "0011_worker_lane_grants"
down_revision = "0008_candidate_feedback"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE worker_lane_grants (
            worker_id TEXT PRIMARY KEY,
            lane TEXT NOT NULL CHECK (lane IN ('run', 'voice', 'image'))
        )
    """)
    # Installed registration Jobs can run on either side of this migration.
    # A binding is usable only with a live token for the same ID.
    op.execute("""
        INSERT INTO worker_lane_grants (worker_id, lane) VALUES
            ('studio-worker', 'run'),
            ('studio-voice-worker', 'voice'),
            ('studio-image-worker', 'image')
    """)
    grant_runtime(WORKER_LANE_GRANTS)


def downgrade():
    op.drop_table("worker_lane_grants")
