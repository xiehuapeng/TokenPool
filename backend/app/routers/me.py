from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
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


MODEL_DESCRIPTIONS = {
    "glm-5.3": "智谱当前旗舰编码模型，复杂代码生成、重构与 Agentic 编程能力最强，长上下文工程表现好，团队编程首选。",
    "glm-5.3-flash": "GLM-5.3 高速轻量版，响应更快、价格更低，适合日常问答、轻量编码与高并发场景。",
    "glm-5.2": "上一代 GLM 旗舰，能力稳定均衡，可作为 glm-5.3 的备选。",
    "glm-5.1": "上一代 GLM 旗舰，综合编码与推理能力良好，价格低于最新旗舰。",
    "glm-5": "GLM 5 系列基础旗舰，适合常规编码与对话任务。",
    "glm-5-turbo": "GLM-5 加速版，延迟更低、价格更便宜，适合高频轻量调用。",
    "glm-4.7": "GLM 4.x 高性价比档位，日常编码与文本任务够用且便宜。",
    "glm-4.6": "GLM 4.x 均衡型模型，工具调用与 JSON 输出稳定。",
    "glm-4.5": "GLM 4.5 标准版，适合低成本兜底场景。",
    "glm-4.5-air": "GLM 4.5 Air 轻量版，速度快、成本最低，适合简单任务与批量处理。",
    "deepseek-v4-pro": "DeepSeek 推理旗舰，深度思考、复杂推理与代码任务表现突出。",
    "deepseek-v4-flash": "DeepSeek 轻量快速版，性价比最高，适合日常辅助与非复杂任务。",
    "kimi-k3": "Kimi K3，长上下文与 Agent 任务表现出色，适合大文档分析与多步工具调用。",
    "kimi-k2.7-code": "Kimi 代码特化模型，面向仓库级代码理解与生成。",
    "kimi-k2.7-code-highspeed": "Kimi K2.7 Code 高速版，保持代码能力的同时显著降低延迟。",
    "qwen3.8-max": "通义千问当前旗舰，中文理解与综合推理强，适合数据分析与通用办公场景。",
    "qwen3.7-plus": "通义千问 Plus 档位，速度与成本平衡，适合高频日常任务。",
    "qwen3.7-max": "通义千问上一代 Max 档位，综合能力稳定。",
}


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
                "description": MODEL_DESCRIPTIONS.get(model.public_model),
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
    user: Annotated[User, Depends(current_user)],
    session: DbSession,
    days: int = Query(default=30, ge=0, le=3660),
    today: bool = Query(default=False),
    model: str | None = None,
) -> dict:
    conditions = [UsageLog.user_id == user.id]
    if today:
        day_start = beijing_day_start_utc()
        conditions.append(UsageLog.request_time >= day_start)
        conditions.append(UsageLog.request_time < day_start + timedelta(days=1))
    elif days:
        conditions.append(UsageLog.request_time >= utc_now() - timedelta(days=days))
    if model:
        conditions.append(UsageLog.model == model)

    summary = (
        await session.execute(
            select(
                func.count(UsageLog.id),
                func.sum(case((UsageLog.status == "success", 1), else_=0)),
                func.coalesce(func.sum(UsageLog.input_tokens), 0),
                func.coalesce(func.sum(UsageLog.output_tokens), 0),
                func.coalesce(func.sum(UsageLog.cached_input_tokens), 0),
                func.coalesce(func.sum(UsageLog.reasoning_tokens), 0),
                func.coalesce(func.sum(UsageLog.total_tokens), 0),
                func.coalesce(func.sum(UsageLog.cost), 0),
            ).where(*conditions)
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
            .where(*conditions)
            .group_by(UsageLog.model, UsageLog.provider)
            .order_by(func.sum(UsageLog.total_tokens).desc())
        )
    ).all()

    filter_models = list(
        await session.scalars(
            select(UsageLog.model)
            .where(UsageLog.user_id == user.id)
            .distinct()
            .order_by(UsageLog.model)
        )
    )

    return {
        "days": days,
        "today": today,
        "model": model,
        "summary": {
            "requests": summary[0],
            "success_requests": summary[1] or 0,
            "input_tokens": summary[2],
            "output_tokens": summary[3],
            "cached_input_tokens": summary[4],
            "reasoning_tokens": summary[5],
            "total_tokens": summary[6],
            "cost": float(summary[7] or 0),
        },
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
        "filter_options": {"models": filter_models},
    }
