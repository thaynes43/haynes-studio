"""Add media job lanes, immutable job inputs and append-only promotions."""

from alembic import op

from haynes_studio.db.grants import JOB_GRANTS, grant_runtime

revision = "0005_job_operations"
down_revision = "0004_go_live_approvals"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE media_job_lanes (
            lane TEXT PRIMARY KEY CHECK (lane IN ('image', 'voice')),
            next_position BIGINT NOT NULL
        )
    """)
    op.execute("INSERT INTO media_job_lanes (lane, next_position) VALUES ('image', 1), ('voice', 1)")
    op.execute("""
        CREATE TABLE media_jobs (
            id TEXT PRIMARY KEY,
            production_id TEXT REFERENCES productions (id),
            story_id TEXT REFERENCES stories (id),
            board_id TEXT REFERENCES boards (id),
            lane TEXT NOT NULL REFERENCES media_job_lanes (lane),
            position BIGINT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('voice', 'photo', 'asset_candidate')),
            idempotency_target TEXT NOT NULL,
            idempotency_actor TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_signature TEXT NOT NULL,
            requester JSONB NOT NULL,
            inputs JSONB NOT NULL,
            document JSONB NOT NULL,
            worker_id TEXT,
            fence BIGINT NOT NULL DEFAULT 0,
            claim_until TIMESTAMPTZ,
            dispatched BOOLEAN NOT NULL DEFAULT false,
            UNIQUE (lane, position),
            UNIQUE (kind, idempotency_target, idempotency_actor, idempotency_key),
            CHECK ((worker_id IS NULL) = (claim_until IS NULL)),
            CHECK ((kind = 'voice') = (lane = 'voice')),
            CHECK ((kind = 'asset_candidate' AND board_id IS NULL AND story_id IS NULL)
                OR (kind != 'asset_candidate' AND board_id IS NOT NULL
                    AND story_id IS NOT NULL AND production_id IS NOT NULL)),
            CHECK (document->>'status' IN ('queued', 'running', 'succeeded', 'failed', 'cancelled'))
        )
    """)
    op.execute("""
        CREATE INDEX media_jobs_active_fifo ON media_jobs (lane, position)
        WHERE (document->>'status') IN ('queued', 'running')
    """)
    op.execute("CREATE INDEX media_jobs_board ON media_jobs (board_id, id)")
    op.execute("CREATE INDEX media_jobs_story ON media_jobs (story_id) WHERE (document->>'status') IN ('queued', 'running')")
    op.execute("""
        CREATE TABLE asset_promotions (
            version_id TEXT PRIMARY KEY REFERENCES asset_versions (id),
            promoted_by JSONB NOT NULL,
            promoted_at TIMESTAMPTZ NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE queue_lane_events (
            lane TEXT NOT NULL CHECK (lane IN ('run', 'voice', 'image')),
            sequence BIGINT NOT NULL CHECK (sequence > 0),
            paused BOOLEAN NOT NULL,
            changed_by JSONB NOT NULL,
            changed_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (lane, sequence)
        )
    """)
    grant_runtime(JOB_GRANTS)


def downgrade():
    op.drop_table("queue_lane_events")
    op.drop_table("asset_promotions")
    op.drop_table("media_jobs")
    op.drop_table("media_job_lanes")
