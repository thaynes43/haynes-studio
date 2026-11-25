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

formats = sa.Table("formats", metadata, sa.Column("id", sa.Text(collation="C"), primary_key=True),
                   sa.Column("name", sa.Text, nullable=False))
format_versions = sa.Table(
    "format_versions", metadata, identifier(), foreign("format_id", "formats.id"),
    sa.Column("number", sa.BigInteger, nullable=False), sa.Column("sha256", sa.String(64), nullable=False),
    sa.Column("recipe", JSONB, nullable=False), sa.UniqueConstraint("format_id", "number"),
)
stories = sa.Table(
    "stories", metadata, identifier(), sa.Column("production_id", sa.Text, nullable=False),
    sa.Column("media_kind", sa.Text, nullable=False),
    sa.Column("source_key", sa.Text, unique=True), document(),
    foreign("format_version_id", "format_versions.id", nullable=True),
    sa.Column("feedback_iteration_id", sa.Text, sa.ForeignKey(
        "feedback_iterations.id", name="stories_feedback_iteration_fk", use_alter=True,
    )),
    sa.CheckConstraint("format_version_id IS NULL OR "
                       "format_version_id IS NOT DISTINCT FROM document->>'format_version_id'",
                       name="stories_format_version_matches_document"),
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
asset_promotions = sa.Table(
    "asset_promotions", metadata, foreign("version_id", "asset_versions.id", primary_key=True),
    sa.Column("promoted_by", JSONB, nullable=False),
    sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=False),
)
queue_lane_events = sa.Table(
    "queue_lane_events", metadata,
    sa.Column("lane", sa.Text, primary_key=True),
    sa.Column("sequence", sa.BigInteger, primary_key=True),
    sa.Column("paused", sa.Boolean, nullable=False),
    sa.Column("changed_by", JSONB, nullable=False),
    sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
)
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
worker_lane_grants = sa.Table("worker_lane_grants", metadata,
                             sa.Column("worker_id", sa.Text, primary_key=True),
                             sa.Column("lane", sa.Text, nullable=False),
                             sa.CheckConstraint("lane IN ('run', 'voice', 'image')"))


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


media_job_lanes = sa.Table(
    "media_job_lanes", metadata, sa.Column("lane", sa.Text, primary_key=True),
    sa.Column("next_position", sa.BigInteger, nullable=False),
)
media_jobs = sa.Table(
    "media_jobs", metadata, identifier(),
    foreign("production_id", "productions.id", nullable=True),
    foreign("story_id", "stories.id", nullable=True),
    foreign("board_id", "boards.id", nullable=True),
    foreign("lane", "media_job_lanes.lane"),
    sa.Column("position", sa.BigInteger, nullable=False),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("idempotency_target", sa.Text, nullable=False),
    sa.Column("idempotency_actor", sa.Text, nullable=False),
    sa.Column("idempotency_key", sa.Text, nullable=False),
    sa.Column("request_signature", sa.Text, nullable=False),
    sa.Column("requester", JSONB, nullable=False),
    sa.Column("inputs", JSONB, nullable=False), document(),
    sa.Column("worker_id", sa.Text),
    sa.Column("fence", sa.BigInteger, nullable=False),
    sa.Column("claim_until", sa.DateTime(timezone=True)),
    sa.Column("dispatched", sa.Boolean, nullable=False),
)

go_live_approvals = sa.Table("go_live_approvals", metadata, identifier(),
    foreign("run_id", "runs.id"), foreign("delivery_id", "deliveries.id"), document(),
)
go_live_withdrawals = sa.Table("go_live_withdrawals", metadata,
    foreign("approval_id", "go_live_approvals.id", primary_key=True), document(),
)

release_packages = sa.Table(
    "release_packages", metadata, sa.Column("sha256", sa.String(64), primary_key=True),
    foreign("run_id", "runs.id"), sa.Column("target_id", sa.Text, nullable=False),
    sa.Column("bytes", sa.BigInteger, nullable=False),
    sa.Column("document_bytes", sa.LargeBinary, nullable=False),
    sa.Column("position", sa.BigInteger, sa.Identity(always=True), nullable=False),
)
publications = sa.Table(
    "publications", metadata, identifier(),
    sa.Column("package_sha256", sa.String(64), sa.ForeignKey("release_packages.sha256"),
              nullable=False, unique=True),
    foreign("approval_id", "go_live_approvals.id"), foreign("run_id", "runs.id"),
    sa.Column("idempotency_actor", sa.Text, nullable=False),
    sa.Column("idempotency_key", sa.Text, nullable=False), document(),
    sa.UniqueConstraint("run_id", "idempotency_actor", "idempotency_key"),
)

run_candidates = sa.Table(
    "run_candidates", metadata, identifier(), foreign("run_id", "runs.id"),
    sa.Column("target_id", sa.Text, nullable=False),
    sa.Column("presented_by", JSONB, nullable=False),
    sa.Column("presented_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint("run_id", "target_id"),
)
candidate_feedback = sa.Table(
    "candidate_feedback", metadata, identifier(), foreign("candidate_id", "run_candidates.id"),
    sa.Column("text", sa.Text, nullable=False),
    sa.Column("board_ids", ARRAY(sa.Text), nullable=False),
    sa.Column("replaces_id", sa.Text, unique=True),
    sa.Column("written_by", JSONB, nullable=False),
    sa.Column("written_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint("candidate_id", "id"),
    sa.ForeignKeyConstraint(["candidate_id", "replaces_id"], ["candidate_feedback.candidate_id", "candidate_feedback.id"]),
)
feedback_iterations = sa.Table(
    "feedback_iterations", metadata, identifier(), foreign("candidate_id", "run_candidates.id"),
    sa.Column("note_ids", ARRAY(sa.Text), nullable=False),
    sa.Column("started_by", JSONB, nullable=False),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("started_revision", sa.BigInteger, nullable=False),
)
feedback_iteration_clears = sa.Table(
    "feedback_iteration_clears", metadata, foreign("story_id", "stories.id", primary_key=True),
    sa.Column("revision", sa.BigInteger, primary_key=True),
    foreign("iteration_id", "feedback_iterations.id"), document(),
)

archive_records = sa.Table(
    "archive_records", metadata, sa.Column("id", sa.Text(collation="C"), primary_key=True),
    foreign("production_id", "productions.id"),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("title", sa.Text, nullable=False),
    sa.Index("archive_records_production_id", "production_id", "id"),
)
archive_versions = sa.Table(
    "archive_versions", metadata, identifier(), foreign("record_id", "archive_records.id"),
    sa.Column("number", sa.BigInteger, nullable=False),
    sa.Column("revises_version_id", sa.Text, unique=True),
    sa.Column("text", sa.Text, nullable=False),
    sa.Column("bytes", sa.Integer, nullable=False),
    sa.Column("sha256", sa.String(64), nullable=False),
    foreign("format_version_id", "format_versions.id", nullable=True),
    sa.Column("provenance", JSONB, nullable=False),
    sa.Column("written_by", JSONB, nullable=False),
    sa.Column("written_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("request_key_sha256", sa.String(64), nullable=False, unique=True),
    sa.Column("request_sha256", sa.String(64), nullable=False),
    sa.UniqueConstraint("record_id", "number"),
    sa.UniqueConstraint("record_id", "id"),
    sa.ForeignKeyConstraint(["record_id", "revises_version_id"], ["archive_versions.record_id", "archive_versions.id"]),
)
