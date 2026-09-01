from decimal import Decimal

import pytest
from sqlalchemy import select

from app.database.session import SessionLocal
from app.models import ModelConfig, ModelPricing, ProviderConfig
from app.services.bootstrap import seed_initial_data


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
                        ("qwen3.8-max", "qwen3.8-flash", "qwen3.7-plus")
                    )
                )
            )
        )
        retired = await session.scalar(
            select(ModelConfig).where(ModelConfig.public_model == "qwen3.7-max")
        )

    assert provider.enabled is True
    assert {model.public_model for model in models} == {
        "qwen3.8-max",
        "qwen3.8-flash",
        "qwen3.7-plus",
    }
    assert all(model.enabled for model in models)
    assert all(model.default_allowed for model in models)
    assert all(model.capabilities["stream"] for model in models)
    assert all(model.capabilities["tools"] for model in models)
    assert retired is None or not retired.enabled
    flash = next(
        model for model in models if model.public_model == "qwen3.8-flash"
    )
    assert flash.capabilities.get("vision") is not True


@pytest.mark.asyncio
async def test_qwen_retirement_removes_existing_pricing_before_model(client):
    async with SessionLocal() as session:
        provider = await session.scalar(
            select(ProviderConfig).where(ProviderConfig.code == "qwen")
        )
        retired = ModelConfig(
            public_model="qwen3.7-max",
            provider_id=provider.id,
            upstream_model="qwen3.7-max",
            display_name="Qwen 3.7 Max",
            enabled=True,
            default_allowed=True,
            capabilities={"stream": True, "tools": True},
            sort_order=99,
        )
        session.add(retired)
        await session.flush()
        session.add(
            ModelPricing(
                model_config_id=retired.id,
                input_price=Decimal("6"),
                cached_input_price=Decimal("1.2"),
                output_price=Decimal("18"),
                enabled=True,
            )
        )
        await session.commit()
        retired_id = retired.id

    await seed_initial_data()

    async with SessionLocal() as session:
        retired = await session.scalar(
            select(ModelConfig).where(ModelConfig.id == retired_id)
        )
        retired_pricing = await session.scalar(
            select(ModelPricing).where(ModelPricing.model_config_id == retired_id)
        )

    assert retired is None
    assert retired_pricing is None
