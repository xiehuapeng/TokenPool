"""Add optional cache pricing; historical usage/costs remain untouched."""
from alembic import op
import sqlalchemy as sa

revision = "20260922_0011"
down_revision = "20260916_0010"
branch_labels = depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '1s'")
    op.add_column("model_pricings", sa.Column("cache_pricing", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("model_pricings", "cache_pricing")
