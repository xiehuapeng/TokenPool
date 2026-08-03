from fastapi import APIRouter
from sqlalchemy import select

from app.config.settings import get_settings
from app.dependencies import DbSession
from app.models import ProviderConfig


router = APIRouter(tags=["health"])


@router.get("/health")
async def health(session: DbSession) -> dict:
    providers = await session.scalars(
        select(ProviderConfig).order_by(ProviderConfig.id)
    )
    settings = get_settings()
    provider_states: dict[str, str] = {}
    for provider in providers:
        if not provider.enabled:
            provider_states[provider.code] = "disabled"
        elif (
            provider.code == "deepseek"
            and not settings.deepseek_api_key.get_secret_value()
        ):
            provider_states[provider.code] = "unconfigured"
        elif (
            provider.code == "glm"
            and not settings.glm_api_key.get_secret_value()
        ):
            provider_states[provider.code] = "unconfigured"
        else:
            provider_states[provider.code] = "available"
    return {"status": "ok", "providers": provider_states}
