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
            select(ModelConfig).where(
                ModelConfig.public_model == "kimi-k2.7-code"
            )
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


@pytest.mark.asyncio
async def test_discovery_preserves_pinned_public_alias_when_official_base_is_listed(client):
    async with SessionLocal() as session:
        provider = await session.scalar(
            select(ProviderConfig).where(ProviderConfig.code == "qwen")
        )
        public = await session.scalar(
            select(ModelConfig).where(ModelConfig.public_model == "qwen3.8-max")
        )
        public.upstream_model = "qwen3.8-max-0902"
        public.enabled = True
        public.default_allowed = True
        await session.commit()

        official = [
            ProviderModel(id="qwen3.8-max"),
            ProviderModel(id="qwen3.8-max-0902"),
        ]
        first = await record_provider_model_discovery(session, provider, official)
        await session.commit()
        second = await record_provider_model_discovery(session, provider, official)
        await session.commit()

        rows = list(await session.scalars(
            select(ModelConfig).where(ModelConfig.provider_id == provider.id)
        ))
        public = next(row for row in rows if row.public_model == "qwen3.8-max")
        discovery = next(row for row in rows if row.upstream_model == "qwen3.8-max")

    assert first.created >= 1
    assert second.created == 0
    assert public.upstream_model == "qwen3.8-max-0902"
    assert public.enabled is True
    assert public.default_allowed is True
    assert public.capabilities["official_available"] is True
    assert discovery.public_model == "qwen:qwen3.8-max"
    assert discovery.enabled is False
    assert discovery.default_allowed is False
