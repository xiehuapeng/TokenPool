import asyncio
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.dependencies import DbSession, current_user
from app.models import InviteCode, User
from app.schemas.auth import LoginRequest, LoginResponse, RegisterRequest, UserView
from app.services.auth_service import authenticate_password
from app.utils.errors import GatewayError
from app.utils.security import create_access_token, hash_invite_code, hash_password


router = APIRouter(prefix="/api/auth", tags=["auth"])


def build_login_response(user: User) -> LoginResponse:
    token, expires_in = create_access_token(user.id)
    return LoginResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserView.model_validate(user),
    )


@router.post(
    "/register",
    response_model=LoginResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(body: RegisterRequest, session: DbSession) -> LoginResponse:
    invite = await session.scalar(
        select(InviteCode)
        .where(InviteCode.code_hash == hash_invite_code(body.invite_code))
        .with_for_update()
    )
    now = datetime.now(timezone.utc)
    invite_expired = False
    if invite is not None and invite.expires_at is not None:
        expires_at = invite.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        invite_expired = expires_at <= now
    invite_exhausted = bool(
        invite is not None
        and invite.max_uses is not None
        and invite.usage_count >= invite.max_uses
    )
    if (
        invite is None
        or invite.status != "active"
        or invite_expired
        or invite_exhausted
    ):
        raise GatewayError(
            "邀请码无效、已停用、已过期或已达到使用次数",
            status_code=400,
            code="invalid_invite_code",
        )

    existing = await session.scalar(
        select(User).where(func.lower(User.username) == body.username.lower())
    )
    if existing is not None:
        raise GatewayError(
            "用户名已存在",
            status_code=409,
            code="username_exists",
        )

    user = User(
        username=body.username,
        password_hash=await asyncio.to_thread(hash_password, body.password),
        status="active",
        is_admin=False,
    )
    invite.usage_count += 1
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise GatewayError(
            "用户名已存在",
            status_code=409,
            code="username_exists",
        ) from exc
    await session.refresh(user)
    return build_login_response(user)


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, session: DbSession) -> LoginResponse:
    user = await authenticate_password(session, body.username, body.password)
    if user is None:
        raise GatewayError(
            "用户名或密码错误",
            status_code=401,
            error_type="authentication_error",
            code="invalid_credentials",
        )
    return build_login_response(user)


@router.get("/me", response_model=UserView)
async def me(user: Annotated[User, Depends(current_user)]) -> UserView:
    return UserView.model_validate(user)
