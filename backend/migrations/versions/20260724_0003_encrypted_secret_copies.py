"""Add encrypted copies for repeat secret viewing.

Revision ID: 20260724_0003
Revises: 20260724_0002
Create Date: 2026-07-24
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260724_0003"
down_revision: str | Sequence[str] | None = "20260724_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column("secret_ciphertext", sa.Text(), nullable=True),
    )
    op.add_column(
        "invite_codes",
        sa.Column("code_ciphertext", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("invite_codes", "code_ciphertext")
    op.drop_column("api_keys", "secret_ciphertext")
