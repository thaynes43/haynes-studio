"""Store immutable release packages, manual drops and iteration clears."""

from alembic import op

from haynes_studio.db.grants import RELEASE_GRANTS, grant_runtime

revision = "0009_release_packages"
down_revision = "0008_candidate_feedback"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE release_packages (
            sha256 VARCHAR(64) PRIMARY KEY CHECK (sha256 ~ '^[0-9a-f]{64}$'),
            run_id TEXT NOT NULL REFERENCES runs (id),
            target_id TEXT NOT NULL,
            bytes BIGINT NOT NULL CHECK (bytes > 0),
            document_bytes BYTEA NOT NULL,
            position BIGINT GENERATED ALWAYS AS IDENTITY
        )
    """)
    op.execute("CREATE INDEX release_packages_run ON release_packages (run_id, target_id, position DESC)")
    op.execute("""
        CREATE TABLE publications (
            id TEXT PRIMARY KEY,
            package_sha256 VARCHAR(64) NOT NULL UNIQUE REFERENCES release_packages (sha256),
            approval_id TEXT NOT NULL REFERENCES go_live_approvals (id),
            run_id TEXT NOT NULL REFERENCES runs (id),
            idempotency_actor TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            document JSONB NOT NULL,
            UNIQUE (run_id, idempotency_actor, idempotency_key)
        )
    """)
    op.execute("CREATE INDEX publications_approval ON publications (approval_id)")
    op.execute("""
        CREATE TABLE feedback_iteration_clears (
            story_id TEXT NOT NULL REFERENCES stories (id),
            revision BIGINT NOT NULL,
            iteration_id TEXT NOT NULL REFERENCES feedback_iterations (id),
            document JSONB NOT NULL,
            PRIMARY KEY (story_id, revision)
        )
    """)
    _constrain_iteration()
    grant_runtime(RELEASE_GRANTS)


def _constrain_iteration():
    conn = op.get_bind()
    schema = conn.dialect.identifier_preparer.quote_identifier(
        conn.exec_driver_sql("SELECT current_schema()").scalar_one()
    )
    # The runtime cannot rewrite the candidate, iteration or a run's story ID.
    # Validate existing references too, while holding the migration's story lock.
    op.execute("LOCK TABLE stories IN SHARE ROW EXCLUSIVE MODE")
    op.execute(f"""
        CREATE FUNCTION studio_check_feedback_iteration() RETURNS TRIGGER
        LANGUAGE plpgsql SET search_path TO pg_catalog, {schema}, pg_temp
        AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM feedback_iterations i
                JOIN run_candidates c ON c.id = i.candidate_id
                JOIN runs r ON r.id = c.run_id
                WHERE i.id = NEW.feedback_iteration_id AND r.story_id = NEW.id
            ) THEN
                RAISE foreign_key_violation USING
                    MESSAGE = 'The feedback iteration must belong to this story',
                    CONSTRAINT = 'stories_feedback_iteration_same_story';
            END IF;
            RETURN NEW;
        END
        $$
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER stories_feedback_iteration_same_story
        AFTER INSERT OR UPDATE ON stories FOR EACH ROW
        WHEN (NEW.feedback_iteration_id IS NOT NULL)
        EXECUTE FUNCTION studio_check_feedback_iteration()
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM stories s
                JOIN feedback_iterations i ON i.id = s.feedback_iteration_id
                JOIN run_candidates c ON c.id = i.candidate_id
                JOIN runs r ON r.id = c.run_id
                WHERE r.story_id <> s.id
            ) THEN
                RAISE foreign_key_violation USING
                    MESSAGE = 'An existing feedback iteration belongs to another story',
                    CONSTRAINT = 'stories_feedback_iteration_same_story';
            END IF;
        END
        $$
    """)


def downgrade():
    op.execute("DROP TRIGGER stories_feedback_iteration_same_story ON stories")
    op.execute("DROP FUNCTION studio_check_feedback_iteration()")
    op.drop_table("feedback_iteration_clears")
    op.drop_table("publications")
    op.drop_table("release_packages")
