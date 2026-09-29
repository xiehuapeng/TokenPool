from decimal import Decimal

import pytest
from sqlalchemy import select

from app.database.session import SessionLocal
from app.models import ModelConfig, ModelPricing, ProviderConfig
from app.services.bootstrap import seed_initial_data
from app.services.model_router import resolve_model


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
    assert flash.capabilities.get("vision") is True
    max_model = next(
        model for model in models if model.public_model == "qwen3.8-max"
    )
    assert max_model.upstream_model == "qwen3.8-max-0902"
    assert max_model.display_name == "Qwen 3.8 Max"


@pytest.mark.asyncio
async def test_qwen_max_snapshot_keeps_public_id_and_pricing_on_reseed(client):
    async with SessionLocal() as session:
        model = await session.scalar(
            select(ModelConfig).where(ModelConfig.public_model == "qwen3.8-max")
        )
        model_id = model.id
        # 模拟旧生产行；升级不得更换公开 ID/主键或创建第二条开放模型。
        model.upstream_model = "qwen3.8-max"
        await session.commit()

    await seed_initial_data()

    async with SessionLocal() as session:
        route = await resolve_model(
            session, user_id=1, public_model="qwen3.8-max"
        )
        pricing = await session.scalar(
            select(ModelPricing).where(ModelPricing.model_config_id == model_id)
        )
        assert route.model.id == model_id
        assert route.model.public_model == "qwen3.8-max"
        assert route.model.upstream_model == "qwen3.8-max-0902"
        assert route.model.display_name == "Qwen 3.8 Max"
        assert pricing is not None
        assert pricing.input_price == Decimal("12")
        assert pricing.cached_input_price == Decimal("1.5")
        assert pricing.output_price == Decimal("36")


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
