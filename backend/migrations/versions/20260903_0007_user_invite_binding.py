"""Track invite code binding per user and bind existing users.

Revision ID: 20260903_0007
Revises: 20260824_0006
Create Date: 2026-09-03
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260903_0007"
down_revision: str | Sequence[str] | None = "20260824_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TEAM_INVITE_PREFIX = "lian...ey"


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("invite_code_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_users_invite_code_id_invite_codes",
            "invite_codes",
            ["invite_code_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_users_invite_code_id", "users", ["invite_code_id"]
    )
    bind = op.get_bind()
    target_id = bind.execute(
        sa.text(
            "SELECT id FROM invite_codes "
            "WHERE code_prefix = :prefix AND status = 'active' "
            "ORDER BY id LIMIT 1"
        ),
        {"prefix": TEAM_INVITE_PREFIX},
    ).scalar()
    if target_id is not None:
        bind.execute(
            sa.text(
                "UPDATE users SET invite_code_id = :invite_code_id "
                "WHERE invite_code_id IS NULL"
            ),
            {"invite_code_id": target_id},
        )
        bind.execute(
            sa.text(
                "UPDATE invite_codes SET usage_count = "
                "(SELECT count(*) FROM users "
                "WHERE users.invite_code_id = invite_codes.id) "
                "WHERE id = :invite_code_id"
            ),
            {"invite_code_id": target_id},
        )


def downgrade() -> None:
    op.drop_index("ix_users_invite_code_id", table_name="users")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint(
            "fk_users_invite_code_id_invite_codes", type_="foreignkey"
        )
        batch_op.drop_column("invite_code_id")
