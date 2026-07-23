from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.models import User
from app.services.auth_service import ApiPrincipal, authenticate_api_key
from app.utils.errors import GatewayError
from app.utils.security import decode_access_token


bearer = HTTPBearer(auto_error=False)
DbSession = Annotated[AsyncSession, Depends(get_db)]
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


async def current_user(credentials: Credentials, session: DbSession) -> User:
    if credentials is None:
        raise GatewayError(
            "Authentication required",
            status_code=401,
            error_type="authentication_error",
            code="missing_token",
        )
    user_id = decode_access_token(credentials.credentials)
    user = await session.get(User, user_id) if user_id is not None else None
    if user is None or user.status != "active":
        raise GatewayError(
            "Invalid or expired login",
            status_code=401,
            error_type="authentication_error",
            code="invalid_token",
        )
    return user


async def admin_user(user: Annotated[User, Depends(current_user)]) -> User:
    if not user.is_admin:
        raise GatewayError(
            "Administrator access required",
            status_code=403,
            error_type="permission_error",
            code="admin_required",
        )
    return user


async def api_principal(
    credentials: Credentials, session: DbSession
) -> ApiPrincipal:
    if credentials is None:
        raise GatewayError(
            "API key required",
            status_code=401,
            error_type="authentication_error",
            code="missing_api_key",
        )
    return await authenticate_api_key(session, credentials.credentials)

