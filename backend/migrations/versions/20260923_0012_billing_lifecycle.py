"""Track upstream and billing outcomes independently from client status.

Existing rows and historical cost/usage remain unchanged. Nullable lifecycle
fields distinguish legacy records from newly observed requests.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260923_0012"
down_revision = "20260922_0011"
branch_labels = depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '1s'")
    op.add_column("usage_logs", sa.Column("upstream_status", sa.String(30), nullable=True))
    op.add_column("usage_logs", sa.Column("billing_status", sa.String(30), nullable=True))
    op.add_column("usage_logs", sa.Column("stream_observation", sa.JSON(), nullable=True))
    op.create_index("ix_usage_billing_status_time", "usage_logs", ["billing_status", "request_time"])
    op.create_table(
        "billing_adjustments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_key", sa.String(180), nullable=False, unique=True),
        sa.Column("usage_log_id", sa.Integer(), sa.ForeignKey("usage_logs.id"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 6), nullable=False),
        sa.Column("source_day", sa.Date(), nullable=False),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("granularity", sa.String(30), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reverses_id", sa.Integer(), sa.ForeignKey("billing_adjustments.id"),
                  nullable=True, unique=True),
    )
    op.create_index("ix_billing_adjustments_usage_log_id", "billing_adjustments", ["usage_log_id"])
    op.create_index("ix_billing_adjustments_source_day", "billing_adjustments", ["source_day"])


def downgrade():
    op.drop_index("ix_billing_adjustments_source_day", table_name="billing_adjustments")
    op.drop_index("ix_billing_adjustments_usage_log_id", table_name="billing_adjustments")
    op.drop_table("billing_adjustments")
    op.drop_index("ix_usage_billing_status_time", table_name="usage_logs")
    op.drop_column("usage_logs", "stream_observation")
    op.drop_column("usage_logs", "billing_status")
    op.drop_column("usage_logs", "upstream_status")
