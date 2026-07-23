from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.dependencies import DbSession, admin_user
from app.models import ApiKey, ModelConfig, ProviderConfig, UsageLog, User
from app.schemas.admin import (
    KeyStatusUpdate,
    ModelUpdate,
    UserCreate,
    UserStatusUpdate,
)
from app.utils.errors import GatewayError
from app.utils.security import hash_password


router = APIRouter(prefix="/api/admin", tags=["admin"])
Admin = Annotated[User, Depends(admin_user)]


@router.get("/users")
async def list_users(_admin: Admin, session: DbSession) -> list[dict]:
    users = await session.scalars(select(User).order_by(User.created_at.desc()))
    return [
        {
            "id": user.id,
            "username": user.username,
            "status": user.status,
            "is_admin": user.is_admin,
            "created_at": user.created_at,
        }
        for user in users
    ]


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, _admin: Admin, session: DbSession) -> dict:
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
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
            "created_at": key.created_at,
            "last_used_at": key.last_used_at,
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


@router.get("/stats")
async def token_stats(
    _admin: Admin,
    session: DbSession,
    days: int = Query(default=30, ge=1, le=366),
) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
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
                "request_time": log.request_time,
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
