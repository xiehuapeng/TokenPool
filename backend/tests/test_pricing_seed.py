from decimal import Decimal

import pytest
from sqlalchemy import select

from app.database.session import SessionLocal
from app.models import ModelConfig, ModelPricing
from app.services.bootstrap import SEED_PRICINGS, seed_initial_data


@pytest.mark.asyncio
async def test_all_seed_models_have_pricing(client):
    async with SessionLocal() as session:
        models = list(await session.scalars(select(ModelConfig)))
        priced_model_ids = set(
            await session.scalars(select(ModelPricing.model_config_id))
        )

    seeded = {
        model.public_model: model.id
        for model in models
        if model.id in priced_model_ids
    }
    assert set(SEED_PRICINGS.keys()) <= set(seeded.keys())


@pytest.mark.asyncio
async def test_seed_pricing_values_match_official_prices(client):
    async with SessionLocal() as session:
        deepseek_flash = await session.scalar(
            select(ModelConfig).where(
                ModelConfig.public_model == "deepseek-v4-flash"
            )
        )
        flash_pricing = await session.scalar(
            select(ModelPricing).where(
                ModelPricing.model_config_id == deepseek_flash.id
            )
        )
        glm_53 = await session.scalar(
            select(ModelConfig).where(ModelConfig.public_model == "glm-5.3")
        )
        glm_pricing = await session.scalar(
            select(ModelPricing).where(
                ModelPricing.model_config_id == glm_53.id
            )
        )
        qwen_plus = await session.scalar(
            select(ModelConfig).where(
                ModelConfig.public_model == "qwen3.7-plus"
            )
        )
        qwen_pricing = await session.scalar(
            select(ModelPricing).where(
                ModelPricing.model_config_id == qwen_plus.id
            )
        )

    assert flash_pricing.input_price == Decimal("1.5")
    assert flash_pricing.cached_input_price == Decimal("0.05")
    assert flash_pricing.output_price == Decimal("4.5")
    assert flash_pricing.peak_input_price == Decimal("3")
    assert flash_pricing.peak_cached_input_price == Decimal("0.1")
    assert flash_pricing.peak_output_price == Decimal("9")
    assert flash_pricing.currency == "CNY"
    assert flash_pricing.enabled is True
    assert flash_pricing.effective_at is not None
    assert flash_pricing.note is not None

    assert glm_pricing.input_price == Decimal("8")
    assert glm_pricing.cached_input_price == Decimal("2")
    assert glm_pricing.output_price == Decimal("28")
    assert glm_pricing.peak_input_price is None
    assert glm_pricing.tier_threshold_tokens is None

    assert qwen_pricing.input_price == Decimal("1.6")
    assert qwen_pricing.cached_input_price == Decimal("0.32")
    assert qwen_pricing.output_price == Decimal("6.4")
    assert qwen_pricing.tier_threshold_tokens == 262144
    assert qwen_pricing.high_input_price == Decimal("4.8")
    assert qwen_pricing.high_cached_input_price == Decimal("0.96")
    assert qwen_pricing.high_output_price == Decimal("19.2")


@pytest.mark.asyncio
async def test_pricing_seed_does_not_overwrite_manual_edit(client):
    async with SessionLocal() as session:
        model = await session.scalar(
            select(ModelConfig).where(ModelConfig.public_model == "glm-5.3")
        )
        pricing = await session.scalar(
            select(ModelPricing).where(
                ModelPricing.model_config_id == model.id
            )
        )
        pricing.input_price = Decimal("99")
        await session.commit()

    await seed_initial_data()

    async with SessionLocal() as session:
        model = await session.scalar(
            select(ModelConfig).where(ModelConfig.public_model == "glm-5.3")
        )
        pricing = await session.scalar(
            select(ModelPricing).where(
                ModelPricing.model_config_id == model.id
            )
        )
        assert pricing.input_price == Decimal("99")

        # Restore the seeded value for tests that rely on it.
        pricing.input_price = Decimal("8")
        await session.commit()
