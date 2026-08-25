"""Add model pricing table and usage cost fields.

Revision ID: 20260824_0006
Revises: 20260824_0005
Create Date: 2026-08-24
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260824_0006"
down_revision: str | Sequence[str] | None = "20260824_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_pricings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model_config_id", sa.Integer(), nullable=False),
        sa.Column("input_price", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("cached_input_price", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("output_price", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("peak_input_price", sa.Numeric(10, 4), nullable=True),
        sa.Column("peak_cached_input_price", sa.Numeric(10, 4), nullable=True),
        sa.Column("peak_output_price", sa.Numeric(10, 4), nullable=True),
        sa.Column("tier_threshold_tokens", sa.Integer(), nullable=True),
        sa.Column("high_input_price", sa.Numeric(10, 4), nullable=True),
        sa.Column("high_cached_input_price", sa.Numeric(10, 4), nullable=True),
        sa.Column("high_output_price", sa.Numeric(10, 4), nullable=True),
        sa.Column("currency", sa.String(8), nullable=False, server_default="CNY"),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["model_config_id"], ["model_configs.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_model_pricings_model_config_id",
        "model_pricings",
        ["model_config_id"],
        unique=True,
    )
    with op.batch_alter_table("usage_logs") as batch_op:
        batch_op.add_column(sa.Column("cached_input_tokens", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("reasoning_tokens", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("cost", sa.Numeric(12, 6), nullable=True))
        batch_op.add_column(sa.Column("cost_source", sa.String(20), nullable=True))
        batch_op.add_column(sa.Column("price_detail", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("usage_logs") as batch_op:
        batch_op.drop_column("price_detail")
        batch_op.drop_column("cost_source")
        batch_op.drop_column("cost")
        batch_op.drop_column("reasoning_tokens")
        batch_op.drop_column("cached_input_tokens")
    op.drop_index("ix_model_pricings_model_config_id", table_name="model_pricings")
    op.drop_table("model_pricings")
