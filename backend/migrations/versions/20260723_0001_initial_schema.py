"""Initial AI Gateway schema.

Revision ID: 20260723_0001
Revises:
Create Date: 2026-07-23
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260723_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_index("ix_users_status", "users", ["status"])

    op.create_table(
        "provider_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("base_url", sa.String(512), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        *_timestamps(),
    )
    op.create_index(
        "ix_provider_configs_code", "provider_configs", ["code"], unique=True
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("key_prefix", sa.String(32), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)
    op.create_index("ix_api_keys_status", "api_keys", ["status"])

    op.create_table(
        "model_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_model", sa.String(120), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("upstream_model", sa.String(160), nullable=False),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("default_allowed", sa.Boolean(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["provider_id"], ["provider_configs.id"]),
    )
    op.create_index(
        "ix_model_configs_public_model",
        "model_configs",
        ["public_model"],
        unique=True,
    )
    op.create_index("ix_model_configs_enabled", "model_configs", ["enabled"])

    op.create_table(
        "user_model_permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("model_config_id", sa.Integer(), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["model_config_id"], ["model_configs.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("user_id", "model_config_id", name="uq_user_model"),
    )
    op.create_index(
        "ix_user_model_permissions_user_id",
        "user_model_permissions",
        ["user_id"],
    )
    op.create_index(
        "ix_user_model_permissions_model_config_id",
        "user_model_permissions",
        ["model_config_id"],
    )

    op.create_table(
        "usage_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("api_key_id", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("upstream_model", sa.String(160), nullable=False),
        sa.Column("stream", sa.Boolean(), nullable=False),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("total_tokens", sa.Integer()),
        sa.Column("usage_source", sa.String(20), nullable=False),
        sa.Column("request_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_token_time", sa.DateTime(timezone=True)),
        sa.Column("response_time", sa.DateTime(timezone=True)),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("http_status", sa.Integer()),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message", sa.Text()),
        sa.Column("upstream_request_id", sa.String(160)),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"]),
    )
    op.create_index(
        "ix_usage_logs_request_id", "usage_logs", ["request_id"], unique=True
    )
    op.create_index("ix_usage_logs_user_id", "usage_logs", ["user_id"])
    op.create_index("ix_usage_logs_api_key_id", "usage_logs", ["api_key_id"])
    op.create_index(
        "ix_usage_user_time", "usage_logs", ["user_id", "request_time"]
    )
    op.create_index(
        "ix_usage_model_time", "usage_logs", ["model", "request_time"]
    )
    op.create_index(
        "ix_usage_provider_time", "usage_logs", ["provider", "request_time"]
    )
    op.create_index(
        "ix_usage_status_time", "usage_logs", ["status", "request_time"]
    )


def downgrade() -> None:
    op.drop_table("usage_logs")
    op.drop_table("user_model_permissions")
    op.drop_table("model_configs")
    op.drop_table("api_keys")
    op.drop_table("provider_configs")
    op.drop_table("users")
