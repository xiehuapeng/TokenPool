from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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


class ApiKeyCreated(ApiKeyView):
    key: str

