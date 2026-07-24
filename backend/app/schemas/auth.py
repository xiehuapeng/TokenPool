from datetime import datetime

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
)

from app.utils.time import to_beijing


USERNAME_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{1,62}[a-zA-Z0-9]$"


def validate_password_strength(value: str) -> str:
    if not any(character.isalpha() for character in value):
        raise ValueError("密码至少需要包含一个字母")
    if not any(character.isdigit() for character in value):
        raise ValueError("密码至少需要包含一个数字")
    return value


class LoginRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=8, max_length=256)


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(
        min_length=3,
        max_length=64,
        pattern=USERNAME_PATTERN,
    )
    password: str = Field(
        min_length=8,
        max_length=64,
    )
    invite_code: str = Field(
        min_length=8,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_-]+$",
    )

    @field_validator("username", "invite_code", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return validate_password_strength(value)


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    status: str
    is_admin: bool
    created_at: datetime

    @field_serializer("created_at")
    def serialize_beijing_time(self, value: datetime) -> datetime:
        return to_beijing(value)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserView
