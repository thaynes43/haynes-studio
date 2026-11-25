"""Add append-only candidates, feedback notes and draft iteration records."""

from alembic import op

from haynes_studio.db.grants import FEEDBACK_GRANTS, grant_runtime

revision = "0008_candidate_feedback"
down_revision = "0007_escalation_packages"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE run_candidates (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs (id),
            target_id TEXT NOT NULL,
            presented_by JSONB NOT NULL,
            presented_at TIMESTAMPTZ NOT NULL,
            UNIQUE (run_id, target_id)
        )
    """)
    op.execute("""
        CREATE TABLE candidate_feedback (
            id TEXT PRIMARY KEY,
            candidate_id TEXT NOT NULL REFERENCES run_candidates (id),
            text TEXT NOT NULL CHECK (length(btrim(text)) BETWEEN 1 AND 4000),
            board_ids TEXT[] NOT NULL CHECK (cardinality(board_ids) <= 256),
            replaces_id TEXT UNIQUE,
            written_by JSONB NOT NULL CHECK (written_by->>'kind' IS NOT DISTINCT FROM 'human'),
            written_at TIMESTAMPTZ NOT NULL,
            UNIQUE (candidate_id, id),
            FOREIGN KEY (candidate_id, replaces_id) REFERENCES candidate_feedback (candidate_id, id)
        )
    """)
    op.execute("""
        CREATE TABLE feedback_iterations (
            id TEXT PRIMARY KEY,
            candidate_id TEXT NOT NULL REFERENCES run_candidates (id),
            note_ids TEXT[] NOT NULL CHECK (cardinality(note_ids) BETWEEN 1 AND 64),
            started_by JSONB NOT NULL CHECK (started_by->>'kind' IS NOT DISTINCT FROM 'human'),
            started_at TIMESTAMPTZ NOT NULL,
            started_revision BIGINT NOT NULL CHECK (started_revision > 1)
        )
    """)
    op.execute("""
        ALTER TABLE stories ADD COLUMN feedback_iteration_id TEXT
        CONSTRAINT stories_feedback_iteration_fk REFERENCES feedback_iterations (id)
    """)
    op.execute("""
        CREATE INDEX runs_answer_candidate ON runs (story_id, (document->'answers'->>'candidate_id'))
        WHERE document ? 'answers'
    """)
    grant_runtime(FEEDBACK_GRANTS)


def downgrade():
    op.drop_index("runs_answer_candidate", table_name="runs")
    op.drop_column("stories", "feedback_iteration_id")
    op.drop_table("feedback_iterations")
    op.drop_table("candidate_feedback")
    op.drop_table("run_candidates")
