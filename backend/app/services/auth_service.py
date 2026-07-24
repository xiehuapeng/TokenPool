import asyncio
from dataclasses import dataclass
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApiKey, User
from app.utils.errors import GatewayError
from app.utils.security import hash_api_key, verify_password
from app.utils.time import utc_now


@dataclass(slots=True)
class ApiPrincipal:
    user: User
    api_key: ApiKey


async def authenticate_password(
    session: AsyncSession, username: str, password: str
) -> User | None:
    user = await session.scalar(
        select(User).where(func.lower(User.username) == username.lower())
    )
    if (
        user is None
        or user.status != "active"
    ):
        return None
    if not await asyncio.to_thread(verify_password, password, user.password_hash):
        return None
    return user


async def authenticate_api_key(
    session: AsyncSession, raw_key: str
) -> ApiPrincipal:
    key_hash = hash_api_key(raw_key)
    result = await session.execute(
        select(ApiKey, User)
        .join(User, User.id == ApiKey.user_id)
        .where(ApiKey.key_hash == key_hash)
    )
    row = result.one_or_none()
    if row is None:
        raise GatewayError(
            "Invalid API key",
            status_code=401,
            error_type="authentication_error",
            code="invalid_api_key",
        )
    api_key, user = row
    now = utc_now()
    if api_key.status != "active" or user.status != "active":
        raise GatewayError(
            "API key is disabled",
            status_code=401,
            error_type="authentication_error",
            code="api_key_disabled",
        )
    if api_key.expires_at and api_key.expires_at <= now:
        raise GatewayError(
            "API key has expired",
            status_code=401,
            error_type="authentication_error",
            code="api_key_expired",
        )
    api_key.last_used_at = now
    await session.commit()
    return ApiPrincipal(user=user, api_key=api_key)
