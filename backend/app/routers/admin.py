import asyncio
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.dependencies import DbSession, admin_user
from app.models import ApiKey, InviteCode, ModelConfig, ProviderConfig, UsageLog, User
from app.schemas.admin import (
    InviteCodeCreate,
    InviteCodeStatusUpdate,
    KeyStatusUpdate,
    ModelUpdate,
    ProviderModelSync,
    UserCreate,
    UserStatusUpdate,
)
from app.schemas.api_key import SecretReveal
from app.providers.registry import provider_registry
from app.utils.errors import GatewayError
from app.utils.secret_store import decrypt_secret, encrypt_secret
from app.utils.security import (
    generate_retired_api_key_hash,
    hash_invite_code,
    hash_password,
)
from app.utils.time import beijing_iso, utc_now


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


@router.get("/models")
async def list_models(_admin: Admin, session: DbSession) -> list[dict]:
    rows = await session.execute(
        select(ModelConfig, ProviderConfig)
        .join(ProviderConfig)
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
        }
        for model, provider in rows
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
        item.public_model: item
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

    existing = {
        item.public_model: item
        for item in await session.scalars(
            select(ModelConfig).where(ModelConfig.provider_id == provider.id)
        )
    }
    synced = []
    for index, model_id in enumerate(requested_ids):
        model = existing.get(model_id)
        if model is None:
            model = ModelConfig(
                public_model=model_id,
                provider_id=provider.id,
                upstream_model=model_id,
                display_name=_provider_model_display_name(
                    provider.code, model_id
                ),
                enabled=body.enable,
                default_allowed=body.default_allowed,
                capabilities={
                    "chat": True,
                    "stream": True,
                    "tools": True,
                    "json": True,
                    "thinking": True,
                },
                sort_order=-100 + index,
            )
            session.add(model)
        else:
            model.upstream_model = model_id
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
    days: int = Query(default=30, ge=1, le=366),
) -> dict:
    since = utc_now() - timedelta(days=days)
    by_user_rows = await session.execute(
        select(
            User.username,
            UsageLog.provider,
            func.count(UsageLog.id),
            func.coalesce(func.sum(UsageLog.total_tokens), 0),
        )
        .join(User, User.id == UsageLog.user_id)
        .where(UsageLog.request_time >= since)
        .group_by(User.username, UsageLog.provider)
        .order_by(func.sum(UsageLog.total_tokens).desc())
    )
    by_model_rows = await session.execute(
        select(
            UsageLog.model,
            func.count(UsageLog.id),
            func.coalesce(func.sum(UsageLog.total_tokens), 0),
        )
        .where(UsageLog.request_time >= since)
        .group_by(UsageLog.model)
        .order_by(func.sum(UsageLog.total_tokens).desc())
    )
    return {
        "days": days,
        "by_user": [
            {
                "username": row[0],
                "provider": row[1],
                "requests": row[2],
                "tokens": row[3],
            }
            for row in by_user_rows
        ],
        "by_model": [
            {"model": row[0], "requests": row[1], "tokens": row[2]}
            for row in by_model_rows
        ],
    }


@router.get("/usage-logs")
async def usage_logs(
    _admin: Admin,
    session: DbSession,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    username: str | None = None,
    model: str | None = None,
    request_id: str | None = None,
    log_status: str | None = Query(default=None, alias="status"),
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
    if username:
        conditions.append(User.username == username)
    if model:
        conditions.append(UsageLog.model == model)
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
                "input_tokens": log.input_tokens,
                "output_tokens": log.output_tokens,
                "total_tokens": log.total_tokens,
                "status": log.status,
                "latency_ms": log.latency_ms,
                "error_message": log.error_message,
            }
            for log, user in rows
        ],
    }
