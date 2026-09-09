from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.database.session import SessionLocal
from app.models import (
    ModelConfig,
    ModelPricing,
    ProviderConfig,
    User,
    UserModelPermission,
)
from app.services.bootstrap import seed_initial_data


@pytest.mark.asyncio
async def test_bootstrap_removes_retired_deepseek_models_and_migrates_preference(
    client,
):
    async with SessionLocal() as session:
        provider = await session.scalar(
            select(ProviderConfig).where(ProviderConfig.code == "deepseek")
        )
        user = User(
            username="retired-model-user",
            password_hash="not-used-in-this-test",
            status="active",
            is_admin=False,
        )
        retired = ModelConfig(
            public_model="deepseek-chat",
            provider_id=provider.id,
            upstream_model="deepseek-chat",
            display_name="DeepSeek Chat",
            enabled=True,
            default_allowed=True,
            capabilities={"chat": True},
        )
        session.add_all((user, retired))
        await session.flush()
        user.preferred_model_id = retired.id
        session.add(
            UserModelPermission(
                user_id=user.id,
                model_config_id=retired.id,
                allowed=True,
            )
        )
        await session.commit()

    await seed_initial_data()

    async with SessionLocal() as session:
        retired_count = await session.scalar(
            select(func.count(ModelConfig.id)).where(
                ModelConfig.public_model.in_(
                    ("deepseek-chat", "deepseek-reasoner")
                )
            )
        )
        migrated_user = await session.scalar(
            select(User).where(User.username == "retired-model-user")
        )
        replacement = await session.scalar(
            select(ModelConfig).where(
                ModelConfig.public_model == "deepseek-v4-flash"
            )
        )
        permission_count = await session.scalar(
            select(func.count(UserModelPermission.id)).where(
                UserModelPermission.user_id == migrated_user.id
            )
        )

        assert retired_count == 0
        assert migrated_user.preferred_model_id == replacement.id
        assert permission_count == 0


@pytest.mark.asyncio
async def test_bootstrap_seeds_vision_exp_model(client):
    async with SessionLocal() as session:
        model = await session.scalar(
            select(ModelConfig).where(
                ModelConfig.public_model == "deepseek-v4-flash-vision-exp"
            )
        )
        pricing = await session.scalar(
            select(ModelPricing).where(
                ModelPricing.model_config_id == model.id
            )
        )

    assert model is not None
    assert model.enabled is True
    assert model.default_allowed is True
    assert model.sort_order == 2
    assert (model.capabilities or {}).get("vision") is True
    assert pricing is not None
    assert pricing.input_price == Decimal("1.5")
    assert pricing.peak_input_price == Decimal("3")
    assert pricing.peak_output_price == Decimal("9")


@pytest.mark.asyncio
async def test_bootstrap_adopts_sync_discovered_vision_exp_once(client):
    # 模拟官方同步任务先于上架种子发现该模型：默认关闭、无视觉标记、
    # 排序落在同步区段。
    async with SessionLocal() as session:
        model = await session.scalar(
            select(ModelConfig).where(
                ModelConfig.public_model == "deepseek-v4-flash-vision-exp"
            )
        )
        model.enabled = False
        model.default_allowed = False
        model.sort_order = 1002
        model.display_name = "deepseek-v4-flash-vision-exp"
        model.capabilities = {
            "chat": True,
            "stream": True,
            "official_available": True,
            "official_synced_at": "2026-09-09T01:58:26+00:00",
        }
        await session.commit()

    await seed_initial_data()

    async with SessionLocal() as session:
        model = await session.scalar(
            select(ModelConfig).where(
                ModelConfig.public_model == "deepseek-v4-flash-vision-exp"
            )
        )
        assert model.enabled is True
        assert model.default_allowed is True
        assert (model.capabilities or {}).get("vision") is True
        assert model.display_name == "DeepSeek V4 Flash Vision Exp"

        # 已被种子管理过的模型再次进入关闭状态时，不得被重新开启，
        # 以保留管理员的启停选择。
        model.enabled = False
        model.default_allowed = False
        await session.commit()

    await seed_initial_data()

    async with SessionLocal() as session:
        model = await session.scalar(
            select(ModelConfig).where(
                ModelConfig.public_model == "deepseek-v4-flash-vision-exp"
            )
        )
        assert model.enabled is False
        assert model.default_allowed is False
