"""Append-only provider-bill corrections independent from request telemetry."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.utils.time import utc_now


class BillingAdjustment(Base):
    __tablename__ = "billing_adjustments"
    __table_args__ = (
        Index("ix_billing_adjustments_usage_log_id", "usage_log_id"),
        Index("ix_billing_adjustments_source_day", "source_day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_key: Mapped[str] = mapped_column(String(180), unique=True)
    usage_log_id: Mapped[int] = mapped_column(ForeignKey("usage_logs.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    source_day: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(80))
    granularity: Mapped[str] = mapped_column(String(30), default="user_day")
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    reverses_id: Mapped[int | None] = mapped_column(
        ForeignKey("billing_adjustments.id"), unique=True
    )
