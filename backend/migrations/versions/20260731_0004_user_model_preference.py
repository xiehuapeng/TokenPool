"""Add per-user model preference and requested model audit field.

Revision ID: 20260731_0004
Revises: 20260724_0003
Create Date: 2026-07-31
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260731_0004"
down_revision: str | Sequence[str] | None = "20260724_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("preferred_model_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_users_preferred_model_id_model_configs",
            "model_configs",
            ["preferred_model_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if op.get_bind().dialect.name == "sqlite":
        op.create_index(
            "uq_users_username_lower",
            "users",
            [sa.text("lower(username)")],
            unique=True,
        )
    op.add_column(
        "usage_logs",
        sa.Column("requested_model", sa.String(120), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE usage_logs "
            "SET requested_model = model "
            "WHERE requested_model IS NULL"
        )
    )


def downgrade() -> None:
    op.drop_column("usage_logs", "requested_model")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint(
            "fk_users_preferred_model_id_model_configs",
            type_="foreignkey",
        )
        batch_op.drop_column("preferred_model_id")
    if op.get_bind().dialect.name == "sqlite":
        op.create_index(
            "uq_users_username_lower",
            "users",
            [sa.text("lower(username)")],
            unique=True,
        )
