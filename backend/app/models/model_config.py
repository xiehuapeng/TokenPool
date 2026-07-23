from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.provider_config import ProviderConfig


class ModelConfig(TimestampMixin, Base):
    __tablename__ = "model_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_model: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("provider_configs.id"))
    upstream_model: Mapped[str] = mapped_column(String(160))
    display_name: Mapped[str] = mapped_column(String(160))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    default_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    sort_order: Mapped[int] = mapped_column(default=0)

    provider: Mapped["ProviderConfig"] = relationship(back_populates="models")

