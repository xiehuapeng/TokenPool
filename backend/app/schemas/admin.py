from typing import Literal

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.auth import USERNAME_PATTERN, validate_password_strength


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=USERNAME_PATTERN)
    password: str = Field(min_length=8, max_length=64)
    is_admin: bool = False

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return validate_password_strength(value)


class UserStatusUpdate(BaseModel):
    status: str = Field(pattern=r"^(active|disabled)$")


class KeyStatusUpdate(BaseModel):
    status: Literal["revoked"]


class ModelUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=160)
    upstream_model: str | None = Field(default=None, max_length=160)
    enabled: bool | None = None
    default_allowed: bool | None = None
    sort_order: int | None = None


class InviteCodeCreate(BaseModel):
    label: str = Field(default="团队邀请码", min_length=1, max_length=80)
    code: str = Field(
        min_length=8,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_-]+$",
    )
    max_uses: int | None = Field(default=None, ge=1, le=10000)
    expires_at: datetime | None = None


class InviteCodeStatusUpdate(BaseModel):
    status: Literal["active", "disabled"]
