import asyncio
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError

from app.dependencies import DbSession, admin_user
from app.models import (
    ApiKey,
    InviteCode,
    ModelConfig,
    ModelPricing,
    ProviderConfig,
    UsageLog,
    User,
)
from app.schemas.admin import (
    InviteCodeCreate,
    InviteCodeStatusUpdate,
    KeyStatusUpdate,
    ModelPricingUpdate,
    ModelUpdate,
    ProviderModelSync,
    UserCreate,
    UserStatusUpdate,
)
from app.schemas.api_key import SecretReveal
from app.providers.registry import provider_registry
from app.services.model_sync import record_provider_model_discovery
from app.services.usage_service import backfill_usage_costs
from app.utils.errors import GatewayError
from app.utils.secret_store import decrypt_secret, encrypt_secret
from app.utils.security import (
    generate_retired_api_key_hash,
    hash_invite_code,
    hash_password,
)
from app.utils.time import beijing_day_start_utc, beijing_iso, to_beijing, utc_now


router = APIRouter(prefix="/api/admin", tags=["admin"])
Admin = Annotated[User, Depends(admin_user)]


def _provider_model_display_name(provider_code: str, model_id: str) -> str:
    if provider_code == "deepseek":
        names = {
            "deepseek-v4-flash": "DeepSeek V4 Flash",
            "deepseek-v4-pro": "DeepSeek V4 Pro",
        }
        return names.get(model_id, model_id)
    return model_id


async def _list_upstream_models(provider: ProviderConfig) -> list:
    implementation = provider_registry.get(provider.code)
    try:
        models = await implementation.list_models(
            timeout_seconds=provider.timeout_seconds
        )
    except NotImplementedError as exc:
        raise GatewayError(
            f"Provider '{provider.code}'暂不支持查询模型列表",
            status_code=400,
            code="provider_model_listing_unsupported",
        ) from exc
    if not models:
        raise GatewayError(
            f"Provider '{provider.code}'没有返回可用模型",
            status_code=502,
            code="empty_provider_model_list",
        )
    return models


@router.get("/users")
async def list_users(_admin: Admin, session: DbSession) -> list[dict]:
    users = await session.scalars(select(User).order_by(User.created_at.desc()))
    return [
        {
            "id": user.id,
            "username": user.username,
            "status": user.status,
            "is_admin": user.is_admin,
            "created_at": beijing_iso(user.created_at),
        }
        for user in users
    ]


@router.get("/invite-codes")
async def list_invite_codes(_admin: Admin, session: DbSession) -> list[dict]:
    codes = await session.scalars(
        select(InviteCode).order_by(InviteCode.created_at.desc())
    )
    return [
        {
            "id": item.id,
            "label": item.label,
            "code_prefix": item.code_prefix,
            "status": item.status,
            "max_uses": item.max_uses,
            "usage_count": item.usage_count,
            "expires_at": beijing_iso(item.expires_at),
            "created_at": beijing_iso(item.created_at),
            "can_reveal": bool(item.code_ciphertext),
        }
        for item in codes
    ]


@router.post("/invite-codes", status_code=status.HTTP_201_CREATED)
async def create_invite_code(
    body: InviteCodeCreate, admin: Admin, session: DbSession
) -> dict:
    code_hash = hash_invite_code(body.code)
    existing = await session.scalar(
        select(InviteCode).where(InviteCode.code_hash == code_hash)
    )
    if existing is not None:
        raise GatewayError(
            "该邀请码已经存在",
            status_code=409,
            code="invite_code_exists",
        )
    item = InviteCode(
        label=body.label,
        code_prefix=f"{body.code[:4]}...{body.code[-2:]}",
        code_hash=code_hash,
        code_ciphertext=encrypt_secret(body.code),
        status="active",
        max_uses=body.max_uses,
        usage_count=0,
        expires_at=body.expires_at,
        created_by=admin.id,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return {
        "id": item.id,
        "label": item.label,
        "code_prefix": item.code_prefix,
        "status": item.status,
        "code": body.code,
    }


@router.get(
    "/invite-codes/{invite_code_id}/secret",
    response_model=SecretReveal,
)
async def reveal_invite_code(
    invite_code_id: int,
    _admin: Admin,
    session: DbSession,
    response: Response,
) -> SecretReveal:
    item = await session.get(InviteCode, invite_code_id)
    if item is None:
        raise GatewayError(
            "邀请码不存在",
            status_code=404,
            code="invite_code_not_found",
        )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return SecretReveal(value=decrypt_secret(item.code_ciphertext))


@router.patch("/invite-codes/{invite_code_id}/status")
async def update_invite_code_status(
    invite_code_id: int,
    body: InviteCodeStatusUpdate,
    _admin: Admin,
    session: DbSession,
) -> dict:
    item = await session.get(InviteCode, invite_code_id)
    if item is None:
        raise GatewayError(
            "邀请码不存在", status_code=404, code="invite_code_not_found"
        )
    item.status = body.status
    await session.commit()
    return {"id": item.id, "status": item.status}


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, _admin: Admin, session: DbSession) -> dict:
    existing = await session.scalar(
        select(User).where(func.lower(User.username) == body.username.lower())
    )
    if existing is not None:
        raise GatewayError(
            "用户名已存在", status_code=409, code="username_exists"
        )
    user = User(
        username=body.username,
        password_hash=await asyncio.to_thread(hash_password, body.password),
        status="active",
        is_admin=body.is_admin,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise GatewayError(
            "用户名已存在", status_code=409, code="username_exists"
        ) from exc
    await session.refresh(user)
    return {"id": user.id, "username": user.username, "status": user.status}


@router.patch("/users/{user_id}/status")
async def update_user_status(
    user_id: int, body: UserStatusUpdate, admin: Admin, session: DbSession
) -> dict:
    user = await session.get(User, user_id)
    if user is None:
        raise GatewayError("用户不存在", status_code=404, code="user_not_found")
    if user.id == admin.id and body.status == "disabled":
        raise GatewayError("不能禁用当前管理员", code="cannot_disable_self")
    user.status = body.status
    await session.commit()
    return {"id": user.id, "status": user.status}


@router.get("/api-keys")
async def list_keys(_admin: Admin, session: DbSession) -> list[dict]:
    rows = await session.execute(
        select(ApiKey, User)
        .join(User, User.id == ApiKey.user_id)
        .order_by(ApiKey.created_at.desc())
    )
    return [
        {
            "id": key.id,
            "username": user.username,
            "name": key.name,
            "key_prefix": key.key_prefix,
            "status": key.status,
            "created_at": beijing_iso(key.created_at),
            "last_used_at": beijing_iso(key.last_used_at),
        }
        for key, user in rows
    ]


@router.patch("/api-keys/{key_id}/status")
async def update_key_status(
    key_id: int, body: KeyStatusUpdate, _admin: Admin, session: DbSession
) -> dict:
    key = await session.get(ApiKey, key_id)
    if key is None:
        raise GatewayError("API Key不存在", status_code=404, code="key_not_found")
    key.status = body.status
    key.key_hash = generate_retired_api_key_hash()
    key.secret_ciphertext = None
    await session.commit()
    return {"id": key.id, "status": key.status}


def _pricing_payload(pricing: ModelPricing | None) -> dict | None:
    if pricing is None:
        return None

    def _num(value) -> float | None:
        return float(value) if value is not None else None

    return {
        "id": pricing.id,
        "input_price": _num(pricing.input_price),
        "cached_input_price": _num(pricing.cached_input_price),
        "output_price": _num(pricing.output_price),
        "peak_input_price": _num(pricing.peak_input_price),
        "peak_cached_input_price": _num(pricing.peak_cached_input_price),
        "peak_output_price": _num(pricing.peak_output_price),
        "tier_threshold_tokens": pricing.tier_threshold_tokens,
        "high_input_price": _num(pricing.high_input_price),
        "high_cached_input_price": _num(pricing.high_cached_input_price),
        "high_output_price": _num(pricing.high_output_price),
        "currency": pricing.currency,
        "enabled": pricing.enabled,
        "note": pricing.note,
    }


@router.get("/models")
async def list_models(_admin: Admin, session: DbSession) -> list[dict]:
    rows = await session.execute(
        select(ModelConfig, ProviderConfig, ModelPricing)
        .join(ProviderConfig)
        .outerjoin(ModelPricing, ModelPricing.model_config_id == ModelConfig.id)
        .order_by(ModelConfig.sort_order, ModelConfig.public_model)
    )
    return [
        {
            "id": model.id,
            "public_model": model.public_model,
            "display_name": model.display_name,
            "upstream_model": model.upstream_model,
            "provider": provider.code,
            "provider_name": provider.display_name,
            "enabled": model.enabled,
            "default_allowed": model.default_allowed,
            "capabilities": model.capabilities,
            "official_available": (model.capabilities or {}).get(
                "official_available"
            ),
            "official_synced_at": (model.capabilities or {}).get(
                "official_synced_at"
            ),
            "pricing": _pricing_payload(pricing),
        }
        for model, provider, pricing in rows
    ]


@router.patch("/models/{model_id}")
async def update_model(
    model_id: int, body: ModelUpdate, _admin: Admin, session: DbSession
) -> dict:
    model = await session.get(ModelConfig, model_id)
    if model is None:
        raise GatewayError("模型不存在", status_code=404, code="model_not_found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(model, field, value)
    await session.commit()
    return {"id": model.id, "enabled": model.enabled}


PRICING_NULLABLE_FIELDS = frozenset(
    {
        "peak_input_price",
        "peak_cached_input_price",
        "peak_output_price",
        "tier_threshold_tokens",
        "high_input_price",
        "high_cached_input_price",
        "high_output_price",
        "note",
    }
)


@router.patch("/models/{model_id}/pricing")
async def update_model_pricing(
    model_id: int, body: ModelPricingUpdate, _admin: Admin, session: DbSession
) -> dict:
    model = await session.get(ModelConfig, model_id)
    if model is None:
        raise GatewayError("模型不存在", status_code=404, code="model_not_found")
    pricing = await session.scalar(
        select(ModelPricing).where(ModelPricing.model_config_id == model.id)
    )
    created = pricing is None
    if created:
        pricing = ModelPricing(
            model_config_id=model.id, effective_at=utc_now(), enabled=True
        )
        session.add(pricing)
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if value is None and field not in PRICING_NULLABLE_FIELDS:
            raise GatewayError(
                f"字段 {field} 不允许为空",
                status_code=400,
                code="pricing_field_not_nullable",
            )
        setattr(pricing, field, value)
    await session.commit()
    await session.refresh(pricing)
    return {
        "id": model.id,
        "created": created,
        "pricing": _pricing_payload(pricing),
    }


@router.get("/providers")
async def list_providers(_admin: Admin, session: DbSession) -> list[dict]:
    providers = await session.scalars(
        select(ProviderConfig).order_by(ProviderConfig.id)
    )
    return [
        {
            "id": item.id,
            "code": item.code,
            "display_name": item.display_name,
            "base_url": item.base_url,
            "enabled": item.enabled,
            "timeout_seconds": item.timeout_seconds,
        }
        for item in providers
    ]


@router.get("/providers/{provider_code}/available-models")
async def provider_available_models(
    provider_code: str, _admin: Admin, session: DbSession
) -> dict:
    provider = await session.scalar(
        select(ProviderConfig).where(ProviderConfig.code == provider_code)
    )
    if provider is None:
        raise GatewayError(
            "Provider不存在", status_code=404, code="provider_not_found"
        )
    upstream_models = await _list_upstream_models(provider)
    configured = {
        item.upstream_model: item
        for item in await session.scalars(
            select(ModelConfig).where(ModelConfig.provider_id == provider.id)
        )
    }
    return {
        "provider": provider.code,
        "source": "upstream",
        "models": [
            {
                "id": item.id,
                "owned_by": item.owned_by,
                "configured": item.id in configured,
                "enabled": (
                    configured[item.id].enabled if item.id in configured else False
                ),
            }
            for item in upstream_models
        ],
    }


@router.post("/providers/{provider_code}/sync-models")
async def sync_provider_models(
    provider_code: str,
    body: ProviderModelSync,
    _admin: Admin,
    session: DbSession,
) -> dict:
    provider = await session.scalar(
        select(ProviderConfig).where(ProviderConfig.code == provider_code)
    )
    if provider is None:
        raise GatewayError(
            "Provider不存在", status_code=404, code="provider_not_found"
        )
    upstream_models = await _list_upstream_models(provider)
    available_ids = {item.id for item in upstream_models}
    requested_ids = list(dict.fromkeys(body.models))
    unavailable = [item for item in requested_ids if item not in available_ids]
    if unavailable:
        raise GatewayError(
            f"Provider当前未返回模型: {', '.join(unavailable)}",
            status_code=400,
            code="provider_model_unavailable",
        )

    await record_provider_model_discovery(
        session,
        provider,
        upstream_models,
    )

    existing = {
        item.upstream_model: item
        for item in await session.scalars(
            select(ModelConfig).where(ModelConfig.provider_id == provider.id)
        )
    }
    synced = []
    for index, model_id in enumerate(requested_ids):
        model = existing.get(model_id)
        if model is None:
            raise GatewayError(
                f"模型同步状态异常: {model_id}",
                status_code=500,
                code="provider_model_sync_failed",
            )
        model.upstream_model = model_id
        model.display_name = _provider_model_display_name(
            provider.code, model_id
        )
        model.enabled = body.enable
        model.default_allowed = body.default_allowed
        model.sort_order = -100 + index
        synced.append(model_id)
    await session.commit()
    return {"provider": provider.code, "synced": synced}


@router.get("/stats")
async def token_stats(
    _admin: Admin,
    session: DbSession,
    days: int = Query(default=30, ge=0, le=3660),
    username: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    today: bool = Query(default=False),
) -> dict:
    conditions = []
    if today:
        day_start = beijing_day_start_utc()
        conditions.append(UsageLog.request_time >= day_start)
        conditions.append(UsageLog.request_time < day_start + timedelta(days=1))
    else:
        since = utc_now() - timedelta(days=days) if days else None
        if since is not None:
            conditions.append(UsageLog.request_time >= since)
    if username:
        conditions.append(User.username == username)
    if model:
        conditions.append(UsageLog.model == model)
    if provider:
        conditions.append(UsageLog.provider == provider)

    summary_statement = select(
        func.count(UsageLog.id),
        func.coalesce(func.sum(UsageLog.input_tokens), 0),
        func.coalesce(func.sum(UsageLog.output_tokens), 0),
        func.coalesce(func.sum(UsageLog.total_tokens), 0),
        func.sum(case((UsageLog.status == "success", 1), else_=0)),
        func.sum(case((UsageLog.status == "failed", 1), else_=0)),
        func.count(func.distinct(UsageLog.user_id)),
        func.count(func.distinct(UsageLog.model)),
        func.coalesce(func.sum(UsageLog.cost), 0),
    ).join(User, User.id == UsageLog.user_id)
    if conditions:
        summary_statement = summary_statement.where(*conditions)
    summary = (await session.execute(summary_statement)).one()

    by_user_statement = (
        select(
            User.username,
            func.count(UsageLog.id),
            func.coalesce(func.sum(UsageLog.input_tokens), 0),
            func.coalesce(func.sum(UsageLog.output_tokens), 0),
            func.coalesce(func.sum(UsageLog.total_tokens), 0),
            func.sum(case((UsageLog.status == "success", 1), else_=0)),
            func.count(func.distinct(UsageLog.model)),
            func.count(func.distinct(UsageLog.provider)),
            func.max(UsageLog.request_time),
            func.coalesce(func.sum(UsageLog.cost), 0),
        )
        .join(User, User.id == UsageLog.user_id)
        .group_by(User.username)
        .order_by(func.sum(UsageLog.total_tokens).desc())
    )
    if conditions:
        by_user_statement = by_user_statement.where(*conditions)
    by_user_rows = await session.execute(
        by_user_statement
    )
    usage_by_username = {
        row[0]: {
            "username": row[0],
            "requests": row[1],
            "input_tokens": row[2],
            "output_tokens": row[3],
            "total_tokens": row[4],
            "success_requests": row[5] or 0,
            "models_used": row[6],
            "providers_used": row[7],
            "last_request_time": beijing_iso(row[8]),
            "cost": float(row[9] or 0),
        }
        for row in by_user_rows
    }
    user_statement = select(User.username).order_by(User.username)
    if username:
        user_statement = user_statement.where(User.username == username)
    all_usernames = list(await session.scalars(user_statement))
    by_user = [
        usage_by_username.get(
            item,
            {
                "username": item,
                "requests": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "success_requests": 0,
                "models_used": 0,
                "providers_used": 0,
                "last_request_time": None,
                "cost": 0.0,
            },
        )
        for item in all_usernames
    ]
    by_user.sort(key=lambda item: (-item["total_tokens"], item["username"]))

    by_model_statement = (
        select(
            UsageLog.model,
            func.count(UsageLog.id),
            func.coalesce(func.sum(UsageLog.input_tokens), 0),
            func.coalesce(func.sum(UsageLog.output_tokens), 0),
            func.coalesce(func.sum(UsageLog.total_tokens), 0),
            func.count(func.distinct(UsageLog.user_id)),
            func.sum(case((UsageLog.status == "success", 1), else_=0)),
            func.coalesce(func.sum(UsageLog.cost), 0),
        )
        .join(User, User.id == UsageLog.user_id)
        .group_by(UsageLog.model)
        .order_by(func.sum(UsageLog.total_tokens).desc())
    )
    if conditions:
        by_model_statement = by_model_statement.where(*conditions)
    by_model_rows = await session.execute(by_model_statement)

    by_provider_statement = (
        select(
            UsageLog.provider,
            func.count(UsageLog.id),
            func.coalesce(func.sum(UsageLog.total_tokens), 0),
            func.count(func.distinct(UsageLog.user_id)),
            func.coalesce(func.sum(UsageLog.cost), 0),
        )
        .join(User, User.id == UsageLog.user_id)
        .group_by(UsageLog.provider)
        .order_by(func.sum(UsageLog.total_tokens).desc())
    )
    if conditions:
        by_provider_statement = by_provider_statement.where(*conditions)
    by_provider_rows = await session.execute(by_provider_statement)

    filter_models = list(
        await session.scalars(
            select(UsageLog.model).distinct().order_by(UsageLog.model)
        )
    )
    filter_providers = list(
        await session.scalars(
            select(UsageLog.provider).distinct().order_by(UsageLog.provider)
        )
    )

    total_requests = summary[0] or 0
    success_requests = summary[4] or 0
    return {
        "days": days,
        "filters": {
            "username": username,
            "model": model,
            "provider": provider,
        },
        "summary": {
            "requests": total_requests,
            "success_requests": success_requests,
            "failed_requests": summary[5] or 0,
            "non_success_requests": total_requests - success_requests,
            "success_rate": round(success_requests / total_requests * 100, 1)
            if total_requests
            else 0,
            "input_tokens": summary[1],
            "output_tokens": summary[2],
            "total_tokens": summary[3],
            "active_users": summary[6],
            "models_used": summary[7],
            "cost": float(summary[8] or 0),
        },
        "filter_options": {
            "models": filter_models,
            "providers": filter_providers,
        },
        "by_user": by_user,
        "by_model": [
            {
                "model": row[0],
                "requests": row[1],
                "input_tokens": row[2],
                "output_tokens": row[3],
                "total_tokens": row[4],
                "users": row[5],
                "success_requests": row[6] or 0,
                "cost": float(row[7] or 0),
            }
            for row in by_model_rows
        ],
        "by_provider": [
            {
                "provider": row[0],
                "requests": row[1],
                "total_tokens": row[2],
                "users": row[3],
                "cost": float(row[4] or 0),
            }
            for row in by_provider_rows
        ],
    }


@router.get("/users/{user_id}/usage")
async def user_usage_detail(
    user_id: int,
    _admin: Admin,
    session: DbSession,
    days: int = Query(default=30, ge=0, le=3660),
    today: bool = Query(default=False),
) -> dict:
    user = await session.get(User, user_id)
    if user is None:
        raise GatewayError("用户不存在", status_code=404, code="user_not_found")

    statement = (
        select(
            UsageLog.request_time,
            UsageLog.model,
            UsageLog.provider,
            UsageLog.input_tokens,
            UsageLog.output_tokens,
            UsageLog.total_tokens,
            UsageLog.cost,
            UsageLog.status,
        )
        .where(UsageLog.user_id == user_id)
        .order_by(UsageLog.request_time)
    )
    if today:
        day_start = beijing_day_start_utc()
        statement = statement.where(
            UsageLog.request_time >= day_start,
            UsageLog.request_time < day_start + timedelta(days=1),
        )
    else:
        since = utc_now() - timedelta(days=days) if days else None
        if since is not None:
            statement = statement.where(UsageLog.request_time >= since)
    rows = await session.execute(statement)

    by_model: dict[tuple[str, str], dict] = {}
    by_day: dict[str, dict] = {}
    for row in rows:
        (
            request_time,
            model,
            provider,
            input_tokens,
            output_tokens,
            total_tokens,
            cost,
            status,
        ) = row
        input_tokens = input_tokens or 0
        output_tokens = output_tokens or 0
        total_tokens = total_tokens or 0
        cost_value = float(cost) if cost is not None else 0.0

        model_bucket = by_model.setdefault(
            (model, provider),
            {
                "model": model,
                "provider": provider,
                "requests": 0,
                "success_requests": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "cost": 0.0,
            },
        )
        model_bucket["requests"] += 1
        if status == "success":
            model_bucket["success_requests"] += 1
        model_bucket["input_tokens"] += input_tokens
        model_bucket["output_tokens"] += output_tokens
        model_bucket["total_tokens"] += total_tokens
        model_bucket["cost"] += cost_value

        day = to_beijing(request_time).date().isoformat()
        day_bucket = by_day.setdefault(
            day,
            {
                "date": day,
                "requests": 0,
                "success_requests": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "cost": 0.0,
            },
        )
        day_bucket["requests"] += 1
        if status == "success":
            day_bucket["success_requests"] += 1
        day_bucket["input_tokens"] += input_tokens
        day_bucket["output_tokens"] += output_tokens
        day_bucket["total_tokens"] += total_tokens
        day_bucket["cost"] += cost_value

    by_model_list = sorted(
        by_model.values(), key=lambda item: (-item["total_tokens"], item["model"])
    )
    by_day_list = sorted(by_day.values(), key=lambda item: item["date"])
    for item in by_model_list:
        item["cost"] = round(item["cost"], 6)
    for item in by_day_list:
        item["cost"] = round(item["cost"], 6)

    return {
        "days": days,
        "today": today,
        "user": {"id": user.id, "username": user.username},
        "summary": {
            "requests": sum(item["requests"] for item in by_day_list),
            "input_tokens": sum(item["input_tokens"] for item in by_day_list),
            "output_tokens": sum(item["output_tokens"] for item in by_day_list),
            "total_tokens": sum(item["total_tokens"] for item in by_day_list),
            "cost": round(sum(item["cost"] for item in by_day_list), 6),
            "active_days": len(by_day_list),
        },
        "by_model": by_model_list,
        "by_day": by_day_list,
    }


@router.get("/usage-logs")
async def usage_logs(
    _admin: Admin,
    session: DbSession,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    days: int = Query(default=30, ge=0, le=3660),
    username: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    request_id: str | None = None,
    log_status: str | None = Query(default=None, alias="status"),
    today: bool = Query(default=False),
) -> dict:
    statement = (
        select(UsageLog, User)
        .join(User, User.id == UsageLog.user_id)
        .order_by(UsageLog.request_time.desc())
    )
    count_statement = select(func.count(UsageLog.id)).join(
        User, User.id == UsageLog.user_id
    )
    conditions = []
    if today:
        day_start = beijing_day_start_utc()
        conditions.append(UsageLog.request_time >= day_start)
        conditions.append(UsageLog.request_time < day_start + timedelta(days=1))
    elif days:
        conditions.append(UsageLog.request_time >= utc_now() - timedelta(days=days))
    if username:
        conditions.append(User.username == username)
    if model:
        conditions.append(UsageLog.model == model)
    if provider:
        conditions.append(UsageLog.provider == provider)
    if request_id:
        conditions.append(UsageLog.request_id == request_id)
    if log_status:
        conditions.append(UsageLog.status == log_status)
    if conditions:
        statement = statement.where(*conditions)
        count_statement = count_statement.where(*conditions)
    total = await session.scalar(count_statement)
    rows = await session.execute(statement.limit(limit).offset(offset))
    return {
        "total": total or 0,
        "items": [
            {
                "request_id": log.request_id,
                "username": user.username,
                "request_time": beijing_iso(log.request_time),
                "requested_model": log.requested_model or log.model,
                "model": log.model,
                "provider": log.provider,
                "stream": log.stream,
                "input_tokens": log.input_tokens,
                "output_tokens": log.output_tokens,
                "total_tokens": log.total_tokens,
                "cached_input_tokens": log.cached_input_tokens,
                "reasoning_tokens": log.reasoning_tokens,
                "usage_source": log.usage_source,
                "cost": float(log.cost) if log.cost is not None else None,
                "cost_source": log.cost_source,
                "price_detail": log.price_detail,
                "status": log.status,
                "http_status": log.http_status,
                "latency_ms": log.latency_ms,
                "error_code": log.error_code,
                "error_message": log.error_message,
            }
            for log, user in rows
        ],
    }


@router.post("/usage-logs/backfill-costs")
async def run_usage_cost_backfill(
    _admin: Admin,
    dry_run: bool = Query(default=False),
) -> dict:
    """按模型平均缓存命中率推算历史日志费用，标记为 estimated。

    dry_run=true 时仅预览将回填的数量与推算出的总费用，不落库。
    """
    return await backfill_usage_costs(dry_run=dry_run)
