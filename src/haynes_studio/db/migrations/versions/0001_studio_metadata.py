"""Create the initial Studio metadata and authentication schema."""

from alembic import op

from haynes_studio.db.grants import METADATA_GRANTS, grant_runtime

revision = "0001_studio_metadata"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE agent_keys (
            id TEXT NOT NULL,
            digest VARCHAR(64) NOT NULL,
            expires_at TIMESTAMP WITH TIME ZONE,
            revoked_at TIMESTAMP WITH TIME ZONE,
            PRIMARY KEY (id),
            UNIQUE (digest)
        )
    """)
    op.execute("""
        CREATE TABLE draft_ids (
            id TEXT NOT NULL,
            PRIMARY KEY (id)
        )
    """)
    op.execute("""
        CREATE TABLE login_attempts (
            digest VARCHAR(64) NOT NULL,
            state TEXT NOT NULL,
            nonce TEXT NOT NULL,
            verifier TEXT NOT NULL,
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            PRIMARY KEY (digest)
        )
    """)
    op.execute('CREATE INDEX ix_login_attempts_expires_at ON login_attempts (expires_at)')
    op.execute("""
        CREATE TABLE productions (
            id TEXT NOT NULL,
            document JSONB NOT NULL,
            PRIMARY KEY (id)
        )
    """)
    op.execute("""
        CREATE TABLE selections (
            iss TEXT NOT NULL,
            sub TEXT NOT NULL,
            revision BIGINT NOT NULL,
            document JSONB NOT NULL,
            PRIMARY KEY (iss, sub)
        )
    """)
    op.execute("""
        CREATE TABLE sessions (
            digest VARCHAR(64) NOT NULL,
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            iss TEXT NOT NULL,
            sub TEXT NOT NULL,
            display_name TEXT,
            csrf TEXT NOT NULL,
            PRIMARY KEY (digest)
        )
    """)
    op.execute('CREATE INDEX ix_sessions_expires_at ON sessions (expires_at)')
    op.execute("""
        CREATE TABLE worker_tokens (
            digest VARCHAR(64) NOT NULL,
            worker_id TEXT NOT NULL,
            expires_at TIMESTAMP WITH TIME ZONE,
            revoked_at TIMESTAMP WITH TIME ZONE,
            PRIMARY KEY (digest)
        )
    """)
    op.execute("""
        CREATE TABLE agent_grants (
            key_id TEXT NOT NULL,
            production_id TEXT NOT NULL,
            scope TEXT NOT NULL,
            PRIMARY KEY (key_id, production_id, scope),
            FOREIGN KEY(key_id) REFERENCES agent_keys (id),
            FOREIGN KEY(production_id) REFERENCES productions (id)
        )
    """)
    op.execute("""
        CREATE TABLE media_types (
            production_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            document JSONB NOT NULL,
            PRIMARY KEY (production_id, kind),
            CONSTRAINT media_kind CHECK (kind IN ('short', 'video')),
            FOREIGN KEY(production_id) REFERENCES productions (id)
        )
    """)
    op.execute("""
        CREATE TABLE stories (
            id TEXT NOT NULL,
            production_id TEXT NOT NULL,
            media_kind TEXT NOT NULL,
            source_key TEXT,
            document JSONB NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(production_id, media_kind) REFERENCES media_types (production_id, kind),
            UNIQUE (source_key)
        )
    """)
    op.execute('CREATE INDEX stories_media_id ON stories (production_id, media_kind, id)')
    op.execute("""
        CREATE TABLE boards (
            id TEXT NOT NULL,
            story_id TEXT NOT NULL,
            number BIGINT NOT NULL,
            source_key TEXT,
            tombstone BOOLEAN DEFAULT false NOT NULL,
            document JSONB NOT NULL,
            PRIMARY KEY (id),
            UNIQUE (story_id, number),
            FOREIGN KEY(story_id) REFERENCES stories (id),
            UNIQUE (source_key)
        )
    """)
    op.execute("""
        CREATE TABLE deliveries (
            run_id TEXT NOT NULL,
            id TEXT NOT NULL,
            story_id TEXT NOT NULL,
            document JSONB NOT NULL,
            PRIMARY KEY (run_id),
            UNIQUE (id),
            FOREIGN KEY(story_id) REFERENCES stories (id)
        )
    """)
    op.execute("""
        CREATE TABLE assets (
            id TEXT NOT NULL,
            production_id TEXT,
            story_id TEXT,
            board_id TEXT,
            kind TEXT NOT NULL,
            labels TEXT[] NOT NULL,
            document JSONB NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(production_id) REFERENCES productions (id),
            FOREIGN KEY(story_id) REFERENCES stories (id),
            FOREIGN KEY(board_id) REFERENCES boards (id)
        )
    """)
    op.execute('CREATE INDEX assets_production_kind ON assets (production_id, kind, id)')
    op.execute("""
        CREATE TABLE delivery_media (
            run_id TEXT NOT NULL,
            locator TEXT NOT NULL,
            sha256 VARCHAR(64) NOT NULL,
            size BIGINT,
            PRIMARY KEY (run_id, locator),
            CONSTRAINT delivery_media_size CHECK (size >= 0),
            FOREIGN KEY(run_id) REFERENCES deliveries (run_id)
        )
    """)
    op.execute('CREATE INDEX ix_delivery_media_sha256 ON delivery_media (sha256)')
    op.execute("""
        CREATE TABLE asset_sources (
            source_key TEXT NOT NULL,
            asset_id TEXT NOT NULL,
            PRIMARY KEY (source_key),
            FOREIGN KEY(asset_id) REFERENCES assets (id)
        )
    """)
    op.execute("""
        CREATE TABLE asset_versions (
            id TEXT NOT NULL,
            asset_id TEXT NOT NULL,
            number BIGINT NOT NULL,
            state TEXT NOT NULL,
            received_sha256 VARCHAR(64),
            document JSONB NOT NULL,
            PRIMARY KEY (id),
            UNIQUE (asset_id, number),
            FOREIGN KEY(asset_id) REFERENCES assets (id)
        )
    """)
    op.execute("""
        CREATE TABLE asset_media (
            version_id TEXT NOT NULL,
            locator TEXT NOT NULL,
            sha256 VARCHAR(64) NOT NULL,
            size BIGINT,
            PRIMARY KEY (version_id, locator),
            CONSTRAINT asset_media_size CHECK (size >= 0),
            FOREIGN KEY(version_id) REFERENCES asset_versions (id)
        )
    """)
    op.execute('CREATE INDEX ix_asset_media_sha256 ON asset_media (sha256)')
    op.execute("""
        CREATE TABLE story_asset_refs (
            story_id TEXT NOT NULL,
            version_id TEXT NOT NULL,
            PRIMARY KEY (story_id, version_id),
            FOREIGN KEY(story_id) REFERENCES stories (id),
            FOREIGN KEY(version_id) REFERENCES asset_versions (id)
        )
    """)
    op.execute('CREATE INDEX story_asset_refs_version ON story_asset_refs (version_id)')
    grant_runtime(METADATA_GRANTS, schema_usage=True)


def downgrade():
    op.drop_table("story_asset_refs")
    op.drop_table("asset_media")
    op.drop_table("asset_versions")
    op.drop_table("asset_sources")
    op.drop_table("delivery_media")
    op.drop_table("assets")
    op.drop_table("deliveries")
    op.drop_table("boards")
    op.drop_table("stories")
    op.drop_table("media_types")
    op.drop_table("agent_grants")
    op.drop_table("worker_tokens")
    op.drop_table("sessions")
    op.drop_table("selections")
    op.drop_table("productions")
    op.drop_table("login_attempts")
    op.drop_table("draft_ids")
    op.drop_table("agent_keys")
