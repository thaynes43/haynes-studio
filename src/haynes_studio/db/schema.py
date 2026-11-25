"""SQLAlchemy Core tables. Canonical documents remain JSONB; keys and relationships
used for filtering, access control and transaction ordering are relational.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

metadata = sa.MetaData()
table = metadata.tables


def foreign(name, target, *, primary_key=False, nullable=False):
    return sa.Column(name, sa.Text, sa.ForeignKey(target), primary_key=primary_key,
                     nullable=nullable)


def identifier():
    return sa.Column("id", sa.Text, primary_key=True)


def document():
    return sa.Column("document", JSONB, nullable=False)


def digest():
    return sa.Column("digest", sa.String(64), primary_key=True)


def expiry():
    return sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True)


productions = sa.Table("productions", metadata, identifier(), document())
media_types = sa.Table("media_types", metadata,
                       foreign("production_id", "productions.id", primary_key=True),
                       sa.Column("kind", sa.Text, primary_key=True), document(),
                       sa.CheckConstraint("kind IN ('short', 'video')", name="media_kind"))

stories = sa.Table(
    "stories", metadata, identifier(), sa.Column("production_id", sa.Text, nullable=False),
    sa.Column("media_kind", sa.Text, nullable=False),
    sa.Column("source_key", sa.Text, unique=True), document(),
    sa.Column("published", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.ForeignKeyConstraint(["production_id", "media_kind"],
                            ["media_types.production_id", "media_types.kind"]),
    sa.Index("stories_media_id", "production_id", "media_kind", "id"),
)
draft_names = sa.Table("draft_names", metadata,
    sa.Column("production_id", sa.Text(collation="C"), primary_key=True),
    sa.Column("media_kind", sa.Text(collation="C"), primary_key=True),
    sa.Column("name_key", sa.Text(collation="C"), primary_key=True),
    sa.Column("entity_ids", ARRAY(sa.Text), nullable=False),
)
boards = sa.Table(
    "boards", metadata, identifier(), foreign("story_id", "stories.id"),
    sa.Column("number", sa.BigInteger, nullable=False),
    sa.Column("source_key", sa.Text, unique=True),
    sa.Column("tombstone", sa.Boolean, nullable=False, server_default=sa.false()), document(),
    sa.UniqueConstraint("story_id", "number"),
)
draft_ids = sa.Table("draft_ids", metadata, identifier())
assets = sa.Table("assets", metadata, identifier(),
                  foreign("production_id", "productions.id", nullable=True),
                  foreign("story_id", "stories.id", nullable=True),
                  foreign("board_id", "boards.id", nullable=True),
                  sa.Column("kind", sa.Text, nullable=False),
                  sa.Column("labels", ARRAY(sa.Text), nullable=False), document(),
                  sa.Index("assets_production_kind", "production_id", "kind", "id"))
asset_versions = sa.Table("asset_versions", metadata, identifier(),
                          foreign("asset_id", "assets.id"),
                          sa.Column("number", sa.BigInteger, nullable=False),
                          sa.Column("state", sa.Text, nullable=False),
                          sa.Column("received_sha256", sa.String(64)), document(),
                          sa.UniqueConstraint("asset_id", "number"))
asset_sources = sa.Table("asset_sources", metadata, sa.Column("source_key", sa.Text, primary_key=True),
                         foreign("asset_id", "assets.id"))
story_asset_refs = sa.Table(
    "story_asset_refs", metadata, foreign("story_id", "stories.id", primary_key=True),
    foreign("version_id", "asset_versions.id", primary_key=True),
    sa.Index("story_asset_refs_version", "version_id"),
)

deliveries = sa.Table(
    "deliveries", metadata, sa.Column("run_id", sa.Text, primary_key=True),
    sa.Column("id", sa.Text, nullable=False, unique=True), foreign("story_id", "stories.id"), document(),
)


def media_index(name, entity_key, target):
    return sa.Table(name, metadata, foreign(entity_key, target, primary_key=True),
                    sa.Column("locator", sa.Text, primary_key=True),
                    sa.Column("sha256", sa.String(64), nullable=False, index=True),
                    sa.Column("size", sa.BigInteger),
                    sa.CheckConstraint("size >= 0", name=f"{name}_size"))


asset_media = media_index("asset_media", "version_id", "asset_versions.id")
delivery_media = media_index("delivery_media", "run_id", "deliveries.run_id")

login_attempts = sa.Table("login_attempts", metadata, digest(),
                          sa.Column("state", sa.Text, nullable=False),
                          sa.Column("nonce", sa.Text, nullable=False),
                          sa.Column("verifier", sa.Text, nullable=False), expiry(),
                          sa.Column("return_to", sa.Text, nullable=False, server_default="/"))
sessions = sa.Table("sessions", metadata, digest(), expiry(),
                    sa.Column("iss", sa.Text, nullable=False),
                    sa.Column("sub", sa.Text, nullable=False),
                    sa.Column("display_name", sa.Text),
                    sa.Column("csrf", sa.Text, nullable=False),
                    sa.Column("auth_time", sa.DateTime(timezone=True)))
selections = sa.Table("selections", metadata,
                      sa.Column("iss", sa.Text, primary_key=True),
                      sa.Column("sub", sa.Text, primary_key=True),
                      sa.Column("revision", sa.BigInteger, nullable=False), document())
agent_keys = sa.Table("agent_keys", metadata, identifier(),
                      sa.Column("digest", sa.String(64), nullable=False, unique=True),
                      sa.Column("expires_at", sa.DateTime(timezone=True)),
                      sa.Column("revoked_at", sa.DateTime(timezone=True)))
agent_grants = sa.Table("agent_grants", metadata,
                        foreign("key_id", "agent_keys.id", primary_key=True),
                        foreign("production_id", "productions.id", primary_key=True),
                        sa.Column("scope", sa.Text, primary_key=True),
                        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()))
worker_tokens = sa.Table("worker_tokens", metadata, digest(),
                         sa.Column("worker_id", sa.Text, nullable=False),
                         sa.Column("expires_at", sa.DateTime(timezone=True)),
                         sa.Column("revoked_at", sa.DateTime(timezone=True)))


run_lane = sa.Table("run_lane", metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("next_position", sa.BigInteger, nullable=False),
    sa.Column("worker_seen_at", sa.DateTime(timezone=True)),
)
runs = sa.Table("runs", metadata, identifier(),
    foreign("story_id", "stories.id"), foreign("production_id", "productions.id"),
    sa.Column("position", sa.BigInteger, nullable=False),
    sa.Column("number", sa.BigInteger, nullable=False),
    sa.Column("idempotency_actor", sa.Text, nullable=False),
    sa.Column("idempotency_key", sa.Text, nullable=False),
    sa.Column("snapshot", JSONB, nullable=False),
    sa.Column("frozen_library", JSONB, nullable=False),
    sa.Column("estimate_methods", JSONB, nullable=False),
    document(),
    sa.Column("revision", sa.BigInteger, nullable=False),
    sa.Column("worker_id", sa.Text),
    sa.Column("fence", sa.BigInteger, nullable=False),
    sa.Column("claim_until", sa.DateTime(timezone=True)),
    sa.Column("retry_at", sa.DateTime(timezone=True)),
    sa.Column("admission_refusals", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column("cancel_requested", sa.Boolean, nullable=False),
    sa.Column("publishing", sa.Boolean, nullable=False),
)
run_wan_attempts = sa.Table("run_wan_attempts", metadata,
    sa.Column("job_id", sa.Text, primary_key=True),
    foreign("run_id", "runs.id"),
    sa.Column("clip_key", sa.Text, nullable=False),
    sa.Column("attempt", sa.Integer, nullable=False),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("request", JSONB, nullable=False),
    sa.Column("request_sha256", sa.String(64), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("state", sa.Text, nullable=False),
    sa.Column("outcome", JSONB),
)
run_check_overrides = sa.Table("run_check_overrides", metadata,
    foreign("run_id", "runs.id", primary_key=True),
    sa.Column("artifact", sa.Text, primary_key=True),
    document(),
)

go_live_approvals = sa.Table("go_live_approvals", metadata, identifier(),
    foreign("run_id", "runs.id"), foreign("delivery_id", "deliveries.id"), document(),
)
go_live_withdrawals = sa.Table("go_live_withdrawals", metadata,
    foreign("approval_id", "go_live_approvals.id", primary_key=True), document(),
)
