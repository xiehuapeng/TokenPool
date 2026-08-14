import pytest
from sqlalchemy import select

from app.database.session import SessionLocal
from app.models import ModelConfig, ProviderConfig


@pytest.mark.asyncio
async def test_qwen_target_models_are_enabled_when_key_is_configured(client):
    async with SessionLocal() as session:
        provider = await session.scalar(
            select(ProviderConfig).where(ProviderConfig.code == "qwen")
        )
        models = list(
            await session.scalars(
                select(ModelConfig)
                .where(ModelConfig.provider_id == provider.id)
                .where(
                    ModelConfig.public_model.in_(
                        ("qwen3.8-max", "qwen3.7-plus", "qwen3.7-max")
                    )
                )
            )
        )

    assert provider.enabled is True
    assert {model.public_model for model in models} == {
        "qwen3.8-max",
        "qwen3.7-plus",
        "qwen3.7-max",
    }
    assert all(model.enabled for model in models)
    assert all(model.default_allowed for model in models)
    assert all(model.capabilities["stream"] for model in models)
    assert all(model.capabilities["tools"] for model in models)
