from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.utils.time import to_beijing


class ApiKeyCreate(BaseModel):
    name: str = Field(default="default", min_length=1, max_length=80)


class ApiKeyView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    key_prefix: str
    status: str
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    can_reveal: bool
    preferred_model_id: int | None = None
    preferred_model: str | None = None

    @field_serializer("created_at", "last_used_at", "expires_at")
    def serialize_beijing_time(
        self, value: datetime | None
    ) -> datetime | None:
        return to_beijing(value) if value is not None else None


class ApiKeyCreated(ApiKeyView):
    key: str


class ApiKeyPreferredModelUpdate(BaseModel):
    model: str | None = Field(default=None, min_length=1, max_length=120)


class SecretReveal(BaseModel):
    value: str
