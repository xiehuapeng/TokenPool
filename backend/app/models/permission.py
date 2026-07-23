from sqlalchemy import Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class UserModelPermission(TimestampMixin, Base):
    __tablename__ = "user_model_permissions"
    __table_args__ = (
        UniqueConstraint("user_id", "model_config_id", name="uq_user_model"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    model_config_id: Mapped[int] = mapped_column(
        ForeignKey("model_configs.id", ondelete="CASCADE"), index=True
    )
    allowed: Mapped[bool] = mapped_column(Boolean, default=True)

