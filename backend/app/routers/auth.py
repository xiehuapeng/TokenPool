from typing import Annotated

from fastapi import APIRouter, Depends

from app.dependencies import DbSession, current_user
from app.models import User
from app.schemas.auth import LoginRequest, LoginResponse, UserView
from app.services.auth_service import authenticate_password
from app.utils.errors import GatewayError
from app.utils.security import create_access_token


router = APIRouter(prefix="/api/auth", tags=["auth"])


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
    token, expires_in = create_access_token(user.id)
    return LoginResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserView.model_validate(user),
    )


@router.get("/me", response_model=UserView)
async def me(user: Annotated[User, Depends(current_user)]) -> UserView:
    return UserView.model_validate(user)

