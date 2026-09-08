"""Track process ownership without rewriting historical usage or costs.

Revision ID: 20260908_0008
Revises: 20260903_0007
"""

from alembic import op
import sqlalchemy as sa


revision = "20260908_0008"
down_revision = "20260903_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        # Fail quickly rather than queue a table lock behind live requests.
        op.execute("SET LOCAL lock_timeout = '1s'")
    op.add_column("usage_logs", sa.Column("runtime_id", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("usage_logs", "runtime_id")
