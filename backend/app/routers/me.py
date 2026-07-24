from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import case, func, or_, select

from app.config.settings import get_settings
from app.dependencies import DbSession, current_user
from app.models import ApiKey, ModelConfig, ProviderConfig, UsageLog, User
from app.schemas.api_key import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyView,
    SecretReveal,
)
from app.utils.errors import GatewayError
from app.utils.secret_store import decrypt_secret, encrypt_secret
from app.utils.security import generate_api_key, generate_retired_api_key_hash
from app.utils.time import BEIJING_TIMEZONE_NAME, beijing_day_start_utc, utc_now


router = APIRouter(prefix="/api/me", tags=["me"])


@router.get("/config")
async def get_public_config(
    _user: Annotated[User, Depends(current_user)],
) -> dict[str, str]:
    return {
        "base_url": get_settings().public_base_url,
        "timezone": BEIJING_TIMEZONE_NAME,
    }


@router.get("/api-keys", response_model=list[ApiKeyView])
async def list_api_keys(
    user: Annotated[User, Depends(current_user)], session: DbSession
) -> list[ApiKey]:
    now = utc_now()
    expired_keys = list(
        await session.scalars(
            select(ApiKey).where(
                ApiKey.user_id == user.id,
                ApiKey.status == "active",
                ApiKey.expires_at.is_not(None),
                ApiKey.expires_at <= now,
            )
        )
    )
    for expired_key in expired_keys:
        expired_key.status = "expired"
        expired_key.key_hash = generate_retired_api_key_hash()
        expired_key.secret_ciphertext = None
    if expired_keys:
        await session.commit()
    return list(
        await session.scalars(
            select(ApiKey)
            .where(
                ApiKey.user_id == user.id,
                ApiKey.status == "active",
                or_(ApiKey.expires_at.is_(None), ApiKey.expires_at > now),
            )
            .order_by(ApiKey.created_at.desc())
        )
    )


@router.post(
    "/api-keys", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED
)
async def create_api_key(
    body: ApiKeyCreate,
    user: Annotated[User, Depends(current_user)],
    session: DbSession,
) -> ApiKeyCreated:
    raw_key, prefix, key_hash = generate_api_key()
    key = ApiKey(
        user_id=user.id,
        name=body.name,
        key_prefix=prefix,
        key_hash=key_hash,
        secret_ciphertext=encrypt_secret(raw_key),
        status="active",
    )
    session.add(key)
    await session.commit()
    await session.refresh(key)
    return ApiKeyCreated(
        id=key.id,
        name=key.name,
        key_prefix=key.key_prefix,
        status=key.status,
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        expires_at=key.expires_at,
        can_reveal=key.can_reveal,
        key=raw_key,
    )


@router.get("/api-keys/{key_id}/secret", response_model=SecretReveal)
async def reveal_api_key(
    key_id: int,
    user: Annotated[User, Depends(current_user)],
    session: DbSession,
    response: Response,
) -> SecretReveal:
    key = await session.scalar(
        select(ApiKey).where(
            ApiKey.id == key_id,
            ApiKey.user_id == user.id,
            ApiKey.status == "active",
            or_(ApiKey.expires_at.is_(None), ApiKey.expires_at > utc_now()),
        )
    )
    if key is None:
        raise GatewayError(
            "API Key不存在或已失效",
            status_code=404,
            code="key_not_found",
        )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return SecretReveal(value=decrypt_secret(key.secret_ciphertext))


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: int,
    user: Annotated[User, Depends(current_user)],
    session: DbSession,
) -> None:
    key = await session.scalar(
        select(ApiKey).where(
            ApiKey.id == key_id,
            ApiKey.user_id == user.id,
            ApiKey.status == "active",
        )
    )
    if key is None:
        raise GatewayError("API Key不存在", status_code=404, code="key_not_found")
    key.status = "revoked"
    key.key_hash = generate_retired_api_key_hash()
    key.secret_ciphertext = None
    await session.commit()


@router.get("/models")
async def list_available_models(
    _user: Annotated[User, Depends(current_user)], session: DbSession
) -> list[dict]:
    rows = await session.execute(
        select(ModelConfig, ProviderConfig)
        .join(ProviderConfig)
        .order_by(ModelConfig.sort_order, ModelConfig.public_model)
    )
    return [
        {
            "id": model.public_model,
            "display_name": model.display_name,
            "provider": provider.display_name,
            "status": "enabled" if model.enabled and provider.enabled else "planned",
            "capabilities": model.capabilities,
        }
        for model, provider in rows
    ]


@router.get("/usage/summary")
async def usage_summary(
    user: Annotated[User, Depends(current_user)], session: DbSession
) -> dict:
    today = beijing_day_start_utc()
    totals = (
        await session.execute(
            select(
                func.count(UsageLog.id),
                func.coalesce(func.sum(UsageLog.total_tokens), 0),
            ).where(UsageLog.user_id == user.id, UsageLog.request_time >= today)
        )
    ).one()
    by_model = (
        await session.execute(
            select(
                UsageLog.model,
                func.count(UsageLog.id),
                func.coalesce(func.sum(UsageLog.total_tokens), 0),
                func.sum(case((UsageLog.status == "success", 1), else_=0)),
            )
            .where(
                UsageLog.user_id == user.id,
                UsageLog.request_time >= today - timedelta(days=30),
            )
            .group_by(UsageLog.model)
            .order_by(func.sum(UsageLog.total_tokens).desc())
        )
    ).all()
    return {
        "today_requests": totals[0],
        "today_tokens": totals[1],
        "by_model": [
            {
                "model": row[0],
                "requests": row[1],
                "tokens": row[2],
                "successes": row[3],
            }
            for row in by_model
        ],
    }
