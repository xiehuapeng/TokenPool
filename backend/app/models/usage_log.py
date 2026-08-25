from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class UsageLog(Base):
    __tablename__ = "usage_logs"
    __table_args__ = (
        Index("ix_usage_user_time", "user_id", "request_time"),
        Index("ix_usage_model_time", "model", "request_time"),
        Index("ix_usage_provider_time", "provider", "request_time"),
        Index("ix_usage_status_time", "status", "request_time"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    api_key_id: Mapped[int] = mapped_column(ForeignKey("api_keys.id"), index=True)
    requested_model: Mapped[str | None] = mapped_column(String(120))
    model: Mapped[str] = mapped_column(String(120))
    provider: Mapped[str] = mapped_column(String(40))
    upstream_model: Mapped[str] = mapped_column(String(160))
    stream: Mapped[bool] = mapped_column(Boolean, default=False)
    input_tokens: Mapped[int | None] = mapped_column()
    cached_input_tokens: Mapped[int | None] = mapped_column()
    reasoning_tokens: Mapped[int | None] = mapped_column()
    output_tokens: Mapped[int | None] = mapped_column()
    total_tokens: Mapped[int | None] = mapped_column()
    usage_source: Mapped[str] = mapped_column(String(20), default="missing")
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    cost_source: Mapped[str | None] = mapped_column(String(20))
    price_detail: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    request_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    first_token_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latency_ms: Mapped[int | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(30), default="pending")
    http_status: Mapped[int | None] = mapped_column()
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    upstream_request_id: Mapped[str | None] = mapped_column(String(160))
