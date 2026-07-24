"""Add administrator-managed registration invite codes.

Revision ID: 20260724_0002
Revises: 20260723_0001
Create Date: 2026-07-24
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260724_0002"
down_revision: str | Sequence[str] | None = "20260723_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "invite_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("code_prefix", sa.String(20), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=True),
        sa.Column("usage_count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
    )
    op.create_index(
        "ix_invite_codes_code_hash", "invite_codes", ["code_hash"], unique=True
    )
    op.create_index("ix_invite_codes_status", "invite_codes", ["status"])
    # Enforce case-insensitive username uniqueness consistently on SQLite/PostgreSQL.
    op.create_index(
        "uq_users_username_lower",
        "users",
        [sa.text("lower(username)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_users_username_lower", table_name="users")
    op.drop_table("invite_codes")
