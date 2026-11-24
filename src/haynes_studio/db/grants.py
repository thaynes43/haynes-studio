"""Runtime privileges issued by the schema owner within Alembic's transaction."""

from alembic import op


def grant_runtime(grants: tuple[tuple[str, tuple[str, ...]], ...], *, schema_usage=False) -> None:
    context = op.get_context()
    role = context.config.attributes.get("runtime_role")
    if role is None:
        return
    conn = op.get_bind()
    quote = conn.dialect.identifier_preparer.quote_identifier
    schema = quote(conn.exec_driver_sql("SELECT current_schema()").scalar_one())
    grantee = quote(role)
    if schema_usage:
        conn.exec_driver_sql(f"GRANT USAGE ON SCHEMA {schema} TO {grantee}")
    for privilege, tables in grants:
        names = ", ".join(f"{schema}.{quote(table)}" for table in tables)
        conn.exec_driver_sql(f"GRANT {privilege} ON TABLE {names} TO {grantee}")


# Frozen privileges for the metadata schema introduced in 0001. Revision
# 0003 reapplies them for installations that ran 0001 before executable grants.
METADATA_GRANTS = (
    ("SELECT, INSERT", ("productions", "stories", "boards", "selections", "media_types",
                        "draft_ids", "assets", "asset_versions", "asset_sources",
                        "asset_media", "deliveries", "delivery_media")),
    ("UPDATE (document)", ("productions", "stories")),
    ("UPDATE (document, tombstone)", ("boards",)),
    ("UPDATE (document, revision)", ("selections",)),
    ("SELECT, INSERT, DELETE", ("login_attempts", "sessions", "story_asset_refs")),
    ("SELECT", ("agent_keys", "agent_grants", "worker_tokens")),
)


# Table-level SELECT on agent_grants also covers the active column added in 0002.
RUNTIME_GRANTS = METADATA_GRANTS + (
    ("SELECT", ("run_lane",)),
    ("UPDATE (next_position, worker_seen_at)", ("run_lane",)),
    ("SELECT, INSERT", ("runs", "run_wan_attempts", "run_check_overrides")),
    ("UPDATE (document, revision, worker_id, fence, claim_until, retry_at, admission_refusals, "
     "cancel_requested, publishing)",
     ("runs",)),
    ("UPDATE (state, outcome)", ("run_wan_attempts",)),
)
