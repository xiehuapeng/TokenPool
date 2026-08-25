from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.model_config import ModelConfig


class ModelPricing(TimestampMixin, Base):
    __tablename__ = "model_pricings"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_config_id: Mapped[int] = mapped_column(
        ForeignKey("model_configs.id", ondelete="CASCADE"), unique=True, index=True
    )

    input_price: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=0)
    cached_input_price: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=0)
    output_price: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=0)

    peak_input_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    peak_cached_input_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    peak_output_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))

    tier_threshold_tokens: Mapped[int | None] = mapped_column()
    high_input_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    high_cached_input_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    high_output_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))

    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(String(255))

    model_config: Mapped["ModelConfig"] = relationship(back_populates="pricing")
