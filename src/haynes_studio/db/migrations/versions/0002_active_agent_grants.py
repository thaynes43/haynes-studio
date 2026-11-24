"""Support replacing agent grants with a role that cannot delete rows."""

import sqlalchemy as sa
from alembic import op

revision = "0002_active_agent_grants"
down_revision = "0001_studio_metadata"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agent_grants", sa.Column(
        "active", sa.Boolean, nullable=False, server_default=sa.true(),
    ))


def downgrade():
    # Do not restore access when removing the flag.
    op.execute("DELETE FROM agent_grants WHERE NOT active")
    op.drop_column("agent_grants", "active")
