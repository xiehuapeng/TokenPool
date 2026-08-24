"""Add per-key preferred model.

Revision ID: 20260824_0005
Revises: 20260731_0004
Create Date: 2026-08-24
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260824_0005"
down_revision: str | Sequence[str] | None = "20260731_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("api_keys") as batch_op:
        batch_op.add_column(
            sa.Column("preferred_model_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_api_keys_preferred_model_id_model_configs",
            "model_configs",
            ["preferred_model_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("api_keys") as batch_op:
        batch_op.drop_constraint(
            "fk_api_keys_preferred_model_id_model_configs",
            type_="foreignkey",
        )
        batch_op.drop_column("preferred_model_id")
