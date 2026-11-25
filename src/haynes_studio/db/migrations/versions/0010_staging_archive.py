"""Add production-scoped append-only staging records and text versions."""

from alembic import op

from haynes_studio.db.grants import ARCHIVE_GRANTS, grant_runtime

revision = "0010_staging_archive"
down_revision = "0009_release_packages"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE archive_records (
            id TEXT COLLATE "C" PRIMARY KEY,
            production_id TEXT NOT NULL REFERENCES productions (id),
            kind TEXT NOT NULL CHECK (kind IN ('brief', 'script', 'storyboard')),
            title TEXT NOT NULL CHECK (char_length(title) BETWEEN 1 AND 80)
        )
    """)
    op.create_index("archive_records_production_id", "archive_records", ["production_id", "id"])
    op.execute("""
        CREATE TABLE archive_versions (
            id TEXT PRIMARY KEY,
            record_id TEXT NOT NULL REFERENCES archive_records (id),
            number BIGINT NOT NULL CHECK (number > 0),
            revises_version_id TEXT UNIQUE,
            text TEXT NOT NULL,
            bytes INTEGER NOT NULL CHECK (bytes = octet_length(text) AND bytes <= 262144),
            sha256 VARCHAR(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
            format_version_id TEXT REFERENCES format_versions (id),
            provenance JSONB NOT NULL,
            written_by JSONB NOT NULL CHECK (coalesce(written_by->>'kind', '') IN ('human', 'agent')),
            written_at TIMESTAMPTZ NOT NULL,
            request_key_sha256 VARCHAR(64) NOT NULL UNIQUE,
            request_sha256 VARCHAR(64) NOT NULL,
            CHECK ((number = 1) = (revises_version_id IS NULL)),
            CHECK (revises_version_id IS DISTINCT FROM id),
            UNIQUE (record_id, number),
            UNIQUE (record_id, id),
            FOREIGN KEY (record_id, revises_version_id) REFERENCES archive_versions (record_id, id)
        )
    """)
    grant_runtime(ARCHIVE_GRANTS)


def downgrade():
    op.drop_table("archive_versions")
    op.drop_table("archive_records")
