"""Record administrator actions in an append-only audit log.

Revision ID: 20260916_0010
Revises: 20260915_0009
"""

from alembic import op
import sqlalchemy as sa

revision = "20260916_0010"
down_revision = "20260915_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '1s'")
    op.create_table(
        "admin_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("admin_user_id", sa.Integer(), nullable=False),
        sa.Column("admin_username", sa.String(64), nullable=False),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("target_type", sa.String(40), nullable=True),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("target_label", sa.String(200), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["admin_user_id"], ["users.id"], name="fk_admin_audit_admin_user"
        ),
    )
    op.create_index(
        "ix_admin_audit_logs_admin_user_id", "admin_audit_logs", ["admin_user_id"]
    )
    op.create_index("ix_admin_audit_logs_action", "admin_audit_logs", ["action"])
    op.create_index("ix_admin_audit_time", "admin_audit_logs", ["created_at"])
    op.create_index(
        "ix_admin_audit_admin_time", "admin_audit_logs", ["admin_user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_admin_audit_admin_time", table_name="admin_audit_logs")
    op.drop_index("ix_admin_audit_time", table_name="admin_audit_logs")
    op.drop_index("ix_admin_audit_logs_action", table_name="admin_audit_logs")
    op.drop_index("ix_admin_audit_logs_admin_user_id", table_name="admin_audit_logs")
    op.drop_table("admin_audit_logs")
