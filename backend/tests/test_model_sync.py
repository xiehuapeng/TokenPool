import pytest
from sqlalchemy import select

from app.database.session import SessionLocal
from app.models import ModelConfig, ProviderConfig
from app.providers.base import ProviderModel
from app.services.model_sync import record_provider_model_discovery


@pytest.mark.asyncio
async def test_model_discovery_adds_disabled_models_and_marks_availability(client):
    async with SessionLocal() as session:
        provider = await session.scalar(
            select(ProviderConfig).where(ProviderConfig.code == "kimi")
        )
        existing = await session.scalar(
            select(ModelConfig).where(ModelConfig.public_model == "kimi-k2")
        )
        existing.enabled = True
        existing.default_allowed = True

        result = await record_provider_model_discovery(
            session,
            provider,
            [ProviderModel(id="moonshot-v1-128k", owned_by="moonshot")],
        )
        await session.commit()

        discovered = await session.scalar(
            select(ModelConfig).where(
                ModelConfig.upstream_model == "moonshot-v1-128k"
            )
        )
        await session.refresh(existing)

    assert result.discovered == 1
    assert result.created == 1
    assert discovered.enabled is False
    assert discovered.default_allowed is False
    assert discovered.capabilities["official_available"] is True
    assert existing.enabled is True
    assert existing.capabilities["official_available"] is False
