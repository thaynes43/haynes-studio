"""Add immutable approval records, login evidence and editor name uniqueness."""

import logging

from alembic import op

from haynes_studio.db.grants import GO_LIVE_GRANTS, grant_runtime

revision = "0004_go_live_approvals"
down_revision = "0003_studio_run_queue"
branch_labels = None
depends_on = None
logger = logging.getLogger(__name__)


def _install_name_constraints():
    conn = op.get_bind()
    schema = conn.dialect.identifier_preparer.quote_identifier(
        conn.exec_driver_sql("SELECT current_schema()").scalar_one(),
    )
    # JavaScript String.trim() whitespace, followed by NFC and Unicode default lowercasing.
    op.execute(r"""
        CREATE FUNCTION studio_name_key(value TEXT) RETURNS TEXT
        LANGUAGE sql IMMUTABLE STRICT
        SET search_path TO pg_catalog
        AS $$
            SELECT lower(normalize(btrim(value, U&'\0009\000A\000B\000C\000D\0020\00A0'
                                                  '\1680\2000\2001\2002\2003\2004\2005\2006'
                                                  '\2007\2008\2009\200A\2028\2029\202F\205F'
                                                  '\3000\FEFF'), NFC) COLLATE "und-x-icu")
        $$
    """)
    # One unique reservation per key. A migration collision retains all member IDs
    # and continues reserving the name until the final member moves away.
    op.execute("""
        CREATE TABLE draft_names (
            production_id TEXT COLLATE "C" NOT NULL,
            media_kind TEXT COLLATE "C" NOT NULL,
            name_key TEXT COLLATE "C" NOT NULL,
            entity_ids TEXT[] NOT NULL,
            PRIMARY KEY (production_id, media_kind, name_key)
        )
    """)
    op.execute("""
        INSERT INTO draft_names (production_id, media_kind, name_key, entity_ids)
        SELECT '', '', studio_name_key(document->>'name') COLLATE "C", array_agg(id ORDER BY id)
        FROM productions GROUP BY 3
        UNION ALL
        SELECT production_id, media_kind, studio_name_key(document->>'title') COLLATE "C",
               array_agg(id ORDER BY id)
        FROM stories GROUP BY 1, 2, 3
    """)
    for row in conn.exec_driver_sql("""
        SELECT production_id, media_kind, entity_ids
        FROM draft_names WHERE cardinality(entity_ids) > 1 ORDER BY 1, 2, 3
    """):
        scope = f"story ({row.production_id}, {row.media_kind})" if row.production_id else "production"
        logger.warning("0004 retained duplicate %s names for IDs: %s", scope, ", ".join(row.entity_ids))

    # The trigger alone can mutate reservations. Pin name resolution to the
    # migration's schema and put temporary objects last.
    op.execute(f"""
        CREATE FUNCTION studio_reserve_draft_name() RETURNS TRIGGER
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path TO pg_catalog, {schema}, pg_temp
        AS $$
        DECLARE
            field TEXT := TG_ARGV[0];
            old_production TEXT := '';
            new_production TEXT := '';
            old_kind TEXT := '';
            new_kind TEXT := '';
            old_key TEXT COLLATE "C";
            new_key TEXT COLLATE "C";
            existing_id TEXT;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                old_key := studio_name_key(OLD.document->>field);
                IF field = 'title' THEN
                    old_production := OLD.production_id;
                    old_kind := OLD.media_kind;
                END IF;
            END IF;
            IF TG_OP <> 'DELETE' THEN
                new_key := studio_name_key(NEW.document->>field);
                IF field = 'title' THEN
                    new_production := NEW.production_id;
                    new_kind := NEW.media_kind;
                END IF;
                IF TG_OP = 'UPDATE' AND
                   (old_production, old_kind, old_key) = (new_production, new_kind, new_key) THEN
                    RETURN NEW;
                END IF;
                INSERT INTO draft_names (production_id, media_kind, name_key, entity_ids)
                    VALUES (new_production, new_kind, new_key, ARRAY[NEW.id])
                    ON CONFLICT (production_id, media_kind, name_key)
                    DO UPDATE SET entity_ids = draft_names.entity_ids
                    RETURNING entity_ids[1] INTO existing_id;
                IF existing_id <> NEW.id THEN
                    RAISE unique_violation USING
                        MESSAGE = 'The draft name is already in use',
                        CONSTRAINT = 'draft_name_unique', TABLE = TG_TABLE_NAME,
                        DETAIL = existing_id;
                END IF;
            END IF;
            IF TG_OP <> 'INSERT' THEN
                UPDATE draft_names SET entity_ids = array_remove(entity_ids, OLD.id)
                    WHERE (production_id, media_kind, name_key) = (old_production, old_kind, old_key);
                DELETE FROM draft_names
                    WHERE (production_id, media_kind, name_key) = (old_production, old_kind, old_key)
                      AND cardinality(entity_ids) = 0;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END
        $$
    """)
    for table, field in (("productions", "name"), ("stories", "title")):
        op.execute(f"""
            CREATE TRIGGER draft_name_unique
            BEFORE INSERT OR UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION studio_reserve_draft_name('{field}')
        """)
    op.execute("REVOKE EXECUTE ON FUNCTION studio_reserve_draft_name() FROM PUBLIC")


def upgrade():
    op.execute("LOCK TABLE productions, stories IN SHARE ROW EXCLUSIVE MODE")
    op.execute("ALTER TABLE login_attempts ADD COLUMN return_to TEXT NOT NULL DEFAULT '/'")
    op.execute("ALTER TABLE sessions ADD COLUMN auth_time TIMESTAMPTZ")
    op.execute("ALTER TABLE stories ADD COLUMN published BOOLEAN NOT NULL DEFAULT false")
    op.execute("""
        CREATE TABLE go_live_approvals (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs (id),
            delivery_id TEXT NOT NULL REFERENCES deliveries (id),
            document JSONB NOT NULL
        )
    """)
    op.execute("CREATE INDEX go_live_approvals_run ON go_live_approvals (run_id)")
    op.execute("""
        CREATE TABLE go_live_withdrawals (
            approval_id TEXT PRIMARY KEY REFERENCES go_live_approvals (id),
            document JSONB NOT NULL
        )
    """)
    _install_name_constraints()
    grant_runtime(GO_LIVE_GRANTS)


def downgrade():
    for table in ("stories", "productions"):
        op.execute(f"DROP TRIGGER draft_name_unique ON {table}")
    op.execute("DROP FUNCTION studio_reserve_draft_name()")
    op.drop_table("draft_names")
    op.execute("DROP FUNCTION studio_name_key(TEXT)")
    op.drop_table("go_live_withdrawals")
    op.drop_table("go_live_approvals")
    op.drop_column("stories", "published")
    op.drop_column("sessions", "auth_time")
    op.drop_column("login_attempts", "return_to")
