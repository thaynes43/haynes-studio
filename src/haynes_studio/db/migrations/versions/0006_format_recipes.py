"""Add an append-only format catalog and a nullable story pin."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from haynes_studio.db.grants import FORMAT_GRANTS, grant_runtime

revision = "0006_format_recipes"
down_revision = "0005_job_operations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "formats",
        sa.Column("id", sa.Text(collation="C"), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
    )
    op.create_table(
        "format_versions",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("format_id", sa.Text, sa.ForeignKey("formats.id"), nullable=False),
        sa.Column("number", sa.BigInteger, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("recipe", JSONB, nullable=False),
        sa.UniqueConstraint("format_id", "number"),
    )
    # Old drafts could carry an unverified fmv-shaped value in their document.
    # Preserve those documents and record a relational pin when the draft pins a real version.
    op.add_column("stories", sa.Column("format_version_id", sa.Text))
    op.create_foreign_key("stories_format_version_fk", "stories", "format_versions",
                          ["format_version_id"], ["id"])
    op.create_check_constraint("stories_format_version_matches_document", "stories",
                               "format_version_id IS NULL OR "
                               "format_version_id IS NOT DISTINCT FROM document->>'format_version_id'")
    grant_runtime(FORMAT_GRANTS)


def downgrade():
    op.drop_constraint("stories_format_version_matches_document", "stories", type_="check")
    op.drop_constraint("stories_format_version_fk", "stories", type_="foreignkey")
    op.drop_column("stories", "format_version_id")
    op.drop_table("format_versions")
    op.drop_table("formats")
