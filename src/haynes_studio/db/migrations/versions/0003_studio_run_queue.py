"""Persist Studio's ordered run queue, fenced claims and Wan job attempts."""

from alembic import op

from haynes_studio.db.grants import RUNTIME_GRANTS, grant_runtime

revision = "0003_studio_run_queue"
down_revision = "0002_active_agent_grants"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE run_lane (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            next_position BIGINT NOT NULL,
            worker_seen_at TIMESTAMPTZ
        )
    """)
    op.execute("INSERT INTO run_lane (id, next_position) VALUES (1, 1)")
    op.execute("""
        CREATE TABLE runs (
            id TEXT PRIMARY KEY,
            story_id TEXT NOT NULL REFERENCES stories (id),
            production_id TEXT NOT NULL REFERENCES productions (id),
            position BIGINT NOT NULL UNIQUE,
            number BIGINT NOT NULL,
            idempotency_actor TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            snapshot JSONB NOT NULL,
            frozen_library JSONB NOT NULL,
            estimate_methods JSONB NOT NULL,
            document JSONB NOT NULL,
            revision BIGINT NOT NULL DEFAULT 1,
            worker_id TEXT,
            fence BIGINT NOT NULL DEFAULT 0,
            claim_until TIMESTAMPTZ,
            retry_at TIMESTAMPTZ,
            admission_refusals INTEGER NOT NULL DEFAULT 0,
            cancel_requested BOOLEAN NOT NULL DEFAULT false,
            publishing BOOLEAN NOT NULL DEFAULT false,
            UNIQUE (production_id, number),
            UNIQUE (story_id, idempotency_actor, idempotency_key),
            CHECK ((worker_id IS NULL) = (claim_until IS NULL)),
            CHECK (document->>'status' IN ('queued', 'running', 'held', 'succeeded', 'failed', 'cancelled'))
        )
    """)
    op.execute("""
        CREATE INDEX runs_active_fifo ON runs (position)
        WHERE (document->>'status') IN ('queued', 'running', 'held')
    """)
    op.execute("CREATE INDEX runs_story_fifo ON runs (story_id, position)")
    op.execute("""
        CREATE TABLE run_wan_attempts (
            job_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs (id),
            clip_key TEXT NOT NULL,
            attempt INTEGER NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('i2v', 's2v')),
            request JSONB NOT NULL,
            request_sha256 VARCHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            state TEXT NOT NULL CHECK (
                state IN ('reserved', 'sent', 'succeeded', 'failed', 'restart_failed', 'busy', 'cancelled')
            ),
            outcome JSONB,
            UNIQUE (run_id, clip_key, attempt)
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX run_wan_unsettled ON run_wan_attempts (run_id)
        WHERE state IN ('reserved', 'sent')
    """)
    op.execute("""
        CREATE TABLE run_check_overrides (
            run_id TEXT NOT NULL REFERENCES runs (id),
            artifact TEXT NOT NULL,
            document JSONB NOT NULL,
            PRIMARY KEY (run_id, artifact)
        )
    """)
    grant_runtime(RUNTIME_GRANTS, schema_usage=True)



def downgrade():
    op.drop_table("run_check_overrides")
    op.drop_table("run_wan_attempts")
    op.drop_table("runs")
    op.drop_table("run_lane")
