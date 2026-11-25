"""Store immutable escalation packages, run check observations and transitions."""

from alembic import op

from haynes_studio.db.grants import ESCALATION_GRANTS, grant_runtime

revision = "0007_escalation_packages"
down_revision = "0006_format_recipes"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE escalation_check_failures (
            record_sha256 VARCHAR(64) PRIMARY KEY,
            evaluation_id VARCHAR(64) NOT NULL UNIQUE,
            failure_id VARCHAR(64) NOT NULL,
            run_id TEXT NOT NULL REFERENCES runs (id),
            recorded_at TIMESTAMPTZ NOT NULL,
            actor JSONB NOT NULL,
            result BYTEA NOT NULL
        )
    """)
    op.execute("""
        CREATE INDEX escalation_matching_checks
        ON escalation_check_failures (failure_id, recorded_at, record_sha256)
    """)
    op.execute("""
        CREATE TABLE escalation_packages (
            id VARCHAR(64) PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs (id),
            production_id TEXT NOT NULL REFERENCES productions (id),
            responder_key_id TEXT NOT NULL UNIQUE,
            expires_at TIMESTAMPTZ NOT NULL,
            sha256 VARCHAR(64) NOT NULL,
            canonical_json BYTEA NOT NULL
        )
    """)
    op.execute("""
        CREATE INDEX escalation_production_packages ON escalation_packages (production_id, id)
    """)
    op.execute("""
        CREATE TABLE escalation_events (
            package_id VARCHAR(64) NOT NULL REFERENCES escalation_packages (id),
            sequence INTEGER NOT NULL,
            state TEXT NOT NULL CHECK (state IN (
                'proposed', 'authorized', 'declined', 'requested', 'done', 'failed', 'escalate', 'cancelled'
            )),
            occurred_at TIMESTAMPTZ NOT NULL,
            actor JSONB NOT NULL,
            detail JSONB NOT NULL,
            external_request_id TEXT UNIQUE,
            PRIMARY KEY (package_id, sequence)
        )
    """)
    op.execute("""
        CREATE INDEX escalation_daily_authorizations ON escalation_events (occurred_at, package_id)
        WHERE state = 'authorized'
    """)
    grant_runtime(ESCALATION_GRANTS)


def downgrade():
    op.drop_table("escalation_events")
    op.drop_table("escalation_packages")
    op.drop_table("escalation_check_failures")
