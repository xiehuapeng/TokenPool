from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import and_, case, func, or_, select

from app.config.settings import get_settings
from app.dependencies import DbSession, current_user
from app.models import (
    ApiKey,
    ModelConfig,
    ModelPricing,
    ProviderConfig,
    UsageLog,
    User,
    UserModelPermission,
)
from app.schemas.api_key import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyPreferredModelUpdate,
    ApiKeyView,
    SecretReveal,
)
from app.schemas.model import ModelPreferenceUpdate, ModelPreferenceView
from app.services.model_router import (
    GATEWAY_MODEL_ID,
    list_permitted_models,
    resolve_model,
)
from app.utils.errors import GatewayError
from app.utils.secret_store import decrypt_secret, encrypt_secret
from app.utils.security import generate_api_key, generate_retired_api_key_hash
from app.utils.time import BEIJING_TIMEZONE_NAME, beijing_day_start_utc, utc_now


router = APIRouter(prefix="/api/me", tags=["me"])


@router.get("/config")
async def get_public_config(
    _user: Annotated[User, Depends(current_user)],
) -> dict:
    return {
        "base_url": get_settings().public_base_url,
        "timezone": BEIJING_TIMEZONE_NAME,
        "max_api_keys": get_settings().max_api_keys_per_user,
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
    keys = list(
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
    return await _key_views(session, keys)


async def _key_views(
    session, keys: list[ApiKey]
) -> list[ApiKeyView]:
    preferred_ids = {
        key.preferred_model_id for key in keys if key.preferred_model_id is not None
    }
    model_names: dict[int, str] = {}
    if preferred_ids:
        rows = await session.scalars(
            select(ModelConfig).where(ModelConfig.id.in_(preferred_ids))
        )
        model_names = {model.id: model.public_model for model in rows}
    return [
        ApiKeyView(
            id=key.id,
            name=key.name,
            key_prefix=key.key_prefix,
            status=key.status,
            created_at=key.created_at,
            last_used_at=key.last_used_at,
            expires_at=key.expires_at,
            can_reveal=key.can_reveal,
            preferred_model_id=key.preferred_model_id,
            preferred_model=model_names.get(key.preferred_model_id or 0),
        )
        for key in keys
    ]


@router.post(
    "/api-keys", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED
)
async def create_api_key(
    body: ApiKeyCreate,
    user: Annotated[User, Depends(current_user)],
    session: DbSession,
) -> ApiKeyCreated:
    max_keys = get_settings().max_api_keys_per_user
    active_count = await session.scalar(
        select(func.count(ApiKey.id)).where(
            ApiKey.user_id == user.id, ApiKey.status == "active"
        )
    )
    if (active_count or 0) >= max_keys:
        raise GatewayError(
            f"每人最多持有{max_keys}个有效API Key，请先吊销不用的Key",
            status_code=400,
            code="api_key_limit_reached",
        )
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
        preferred_model_id=key.preferred_model_id,
        preferred_model=None,
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


@router.patch("/api-keys/{key_id}/preferred-model", response_model=ApiKeyView)
async def update_key_preferred_model(
    key_id: int,
    body: ApiKeyPreferredModelUpdate,
    user: Annotated[User, Depends(current_user)],
    session: DbSession,
) -> ApiKeyView:
    key = await session.scalar(
        select(ApiKey).where(
            ApiKey.id == key_id,
            ApiKey.user_id == user.id,
            ApiKey.status == "active",
        )
    )
    if key is None:
        raise GatewayError("API Key不存在", status_code=404, code="key_not_found")
    preferred_model = None
    if body.model is not None:
        route = await resolve_model(
            session, user_id=user.id, public_model=body.model
        )
        key.preferred_model_id = route.model.id
        preferred_model = route.model.public_model
    else:
        key.preferred_model_id = None
    await session.commit()
    await session.refresh(key)
    return ApiKeyView(
        id=key.id,
        name=key.name,
        key_prefix=key.key_prefix,
        status=key.status,
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        expires_at=key.expires_at,
        can_reveal=key.can_reveal,
        preferred_model_id=key.preferred_model_id,
        preferred_model=preferred_model,
    )


def _pricing_view(pricing: ModelPricing | None) -> dict | None:
    if pricing is None or not pricing.enabled:
        return None

    def _num(value) -> float | None:
        return float(value) if value is not None else None

    return {
        "input_price": _num(pricing.input_price),
        "cached_input_price": _num(pricing.cached_input_price),
        "output_price": _num(pricing.output_price),
        "peak_input_price": _num(pricing.peak_input_price),
        "tier_threshold_tokens": pricing.tier_threshold_tokens,
        "high_input_price": _num(pricing.high_input_price),
        "enabled": pricing.enabled,
    }


@router.get("/models")
async def list_available_models(
    user: Annotated[User, Depends(current_user)], session: DbSession
) -> list[dict]:
    rows = await session.execute(
        select(
            ModelConfig,
            ProviderConfig,
            ModelPricing,
            UserModelPermission.allowed,
        )
        .join(ProviderConfig, ProviderConfig.id == ModelConfig.provider_id)
        .outerjoin(ModelPricing, ModelPricing.model_config_id == ModelConfig.id)
        .outerjoin(
            UserModelPermission,
            and_(
                UserModelPermission.model_config_id == ModelConfig.id,
                UserModelPermission.user_id == user.id,
            ),
        )
        .where(ModelConfig.enabled.is_(True), ProviderConfig.enabled.is_(True))
        .order_by(ModelConfig.sort_order, ModelConfig.public_model)
    )
    models = []
    for model, provider, pricing, explicit_allowed in rows:
        allowed = (
            model.default_allowed if explicit_allowed is None else explicit_allowed
        )
        if not allowed:
            continue
        models.append(
            {
                "id": model.public_model,
                "display_name": model.display_name,
                "provider": provider.display_name,
                "status": "enabled",
                "capabilities": model.capabilities,
                "selected": model.id == user.preferred_model_id,
                "pricing": _pricing_view(pricing),
            }
        )
    return models


@router.get("/model-preference", response_model=ModelPreferenceView)
async def get_model_preference(
    user: Annotated[User, Depends(current_user)], session: DbSession
) -> ModelPreferenceView:
    if user.preferred_model_id is not None:
        preferred = await session.get(ModelConfig, user.preferred_model_id)
        return ModelPreferenceView(
            gateway_model=GATEWAY_MODEL_ID,
            selected_model=preferred.public_model if preferred else None,
            selection_source="user",
        )

    permitted = await list_permitted_models(session, user_id=user.id)
    return ModelPreferenceView(
        gateway_model=GATEWAY_MODEL_ID,
        selected_model=permitted[0].public_model if permitted else None,
        selection_source="default",
    )


@router.put("/model-preference", response_model=ModelPreferenceView)
async def update_model_preference(
    body: ModelPreferenceUpdate,
    user: Annotated[User, Depends(current_user)],
    session: DbSession,
) -> ModelPreferenceView:
    route = await resolve_model(
        session,
        user_id=user.id,
        public_model=body.model,
    )
    user.preferred_model_id = route.model.id
    await session.commit()
    return ModelPreferenceView(
        gateway_model=GATEWAY_MODEL_ID,
        selected_model=route.model.public_model,
        selection_source="user",
    )


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
                func.coalesce(func.sum(UsageLog.input_tokens), 0),
                func.coalesce(func.sum(UsageLog.output_tokens), 0),
                func.coalesce(func.sum(UsageLog.cost), 0),
            ).where(UsageLog.user_id == user.id, UsageLog.request_time >= today)
        )
    ).one()
    by_model = (
        await session.execute(
            select(
                UsageLog.model,
                UsageLog.provider,
                func.count(UsageLog.id),
                func.sum(case((UsageLog.status == "success", 1), else_=0)),
                func.coalesce(func.sum(UsageLog.input_tokens), 0),
                func.coalesce(func.sum(UsageLog.output_tokens), 0),
                func.coalesce(func.sum(UsageLog.cached_input_tokens), 0),
                func.coalesce(func.sum(UsageLog.reasoning_tokens), 0),
                func.coalesce(func.sum(UsageLog.total_tokens), 0),
                func.coalesce(func.sum(UsageLog.cost), 0),
            )
            .where(
                UsageLog.user_id == user.id,
                UsageLog.request_time >= today - timedelta(days=30),
            )
            .group_by(UsageLog.model, UsageLog.provider)
            .order_by(func.sum(UsageLog.total_tokens).desc())
        )
    ).all()
    return {
        "today_requests": totals[0],
        "today_tokens": totals[1],
        "today_input_tokens": totals[2],
        "today_output_tokens": totals[3],
        "today_cost": float(totals[4] or 0),
        "by_model": [
            {
                "model": row[0],
                "provider": row[1],
                "requests": row[2],
                "success_requests": row[3] or 0,
                "input_tokens": row[4],
                "output_tokens": row[5],
                "cached_input_tokens": row[6],
                "reasoning_tokens": row[7],
                "total_tokens": row[8],
                "cost": float(row[9] or 0),
            }
            for row in by_model
        ],
    }
