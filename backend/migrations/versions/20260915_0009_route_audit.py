"""Record model routing decisions without rewriting historical usage.

Revision ID: 20260915_0009
Revises: 20260908_0008
"""

from alembic import op
import sqlalchemy as sa

revision = "20260915_0009"
down_revision = "20260908_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '1s'")
    op.add_column("usage_logs", sa.Column("original_model", sa.String(120), nullable=True))
    op.add_column("usage_logs", sa.Column("route_reason", sa.String(40), nullable=True))


def downgrade() -> None:
    op.drop_column("usage_logs", "route_reason")
    op.drop_column("usage_logs", "original_model")
