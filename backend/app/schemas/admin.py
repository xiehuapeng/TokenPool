from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=256)
    is_admin: bool = False


class UserStatusUpdate(BaseModel):
    status: str = Field(pattern=r"^(active|disabled)$")


class KeyStatusUpdate(BaseModel):
    status: str = Field(pattern=r"^(active|revoked)$")


class ModelUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=160)
    upstream_model: str | None = Field(default=None, max_length=160)
    enabled: bool | None = None
    default_allowed: bool | None = None
    sort_order: int | None = None

