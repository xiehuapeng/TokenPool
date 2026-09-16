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
    assert model.sort_order == 3
    assert (model.capabilities or {}).get("vision") is True
    assert pricing is not None
    assert pricing.input_price == Decimal("1")
    assert pricing.peak_input_price == Decimal("2")
    assert pricing.peak_output_price == Decimal("8")


@pytest.mark.asyncio
async def test_bootstrap_seeds_official_flash_with_vision_and_pricing(client):
    # 官方现已推荐 deepseek-flash（V4.1-Flash）：支持图像理解、价格与
    # deepseek-v4-flash 相同，且同步任务可能已提前把它入库为关闭状态。
    async with SessionLocal() as session:
        model = await session.scalar(
            select(ModelConfig).where(ModelConfig.public_model == "deepseek-flash")
        )
        assert model is not None
        assert model.enabled is True
        assert model.default_allowed is True
        assert model.display_name == "DeepSeek Flash"
        assert (model.capabilities or {}).get("vision") is True
        pricing = await session.scalar(
            select(ModelPricing).where(ModelPricing.model_config_id == model.id)
        )
        assert pricing is not None
        assert pricing.input_price == Decimal("1")
        assert pricing.cached_input_price == Decimal("0.02")
        assert pricing.output_price == Decimal("4")
        assert pricing.peak_input_price == Decimal("2")
        assert pricing.peak_cached_input_price == Decimal("0.04")
        assert pricing.peak_output_price == Decimal("8")


@pytest.mark.asyncio
async def test_deepseek_flash_precedes_other_vision_models_for_fallback(client):
    # 视觉回退取 list_permitted_models 中第一个带视觉标记的模型，而该列表
    # 按 sort_order 排序。deepseek-flash 必须排在其余视觉模型之前，才能在
    # 带图请求中成为回退首选；同时 deepseek-v4-flash 仍保持第一位，
    # 使 team-coding 无偏好时的默认模型不变。
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(ModelConfig.public_model, ModelConfig.sort_order)
                .where(ModelConfig.enabled.is_(True))
                .order_by(ModelConfig.sort_order, ModelConfig.public_model)
            )
        ).all()
        vision_flags = {
            item.public_model: bool((item.capabilities or {}).get("vision"))
            for item in await session.scalars(select(ModelConfig))
        }

    ordered = [name for name, _ in rows]
    assert ordered[0] == "deepseek-v4-flash", "默认模型必须保持第一位"
    vision_order = [name for name in ordered if vision_flags.get(name)]
    assert vision_order[0] == "deepseek-flash", (
        f"视觉回退首选应为 deepseek-flash，实际为 {vision_order[:3]}"
    )


@pytest.mark.asyncio
async def test_bootstrap_adopts_sync_discovered_official_flash_once(client):
    # 同步任务提前发现时默认关闭且无视觉标记；上架种子应补齐能力并按
    # Provider 开启一次，之后保留管理员的启停选择。
    async with SessionLocal() as session:
        model = await session.scalar(
            select(ModelConfig).where(ModelConfig.public_model == "deepseek-flash")
        )
        model.enabled = False
        model.default_allowed = False
        model.sort_order = 1001
        model.display_name = "deepseek-flash"
        model.capabilities = {
            "chat": True,
            "stream": True,
            "official_available": True,
            "official_synced_at": "2026-09-13T16:55:46+00:00",
        }
        await session.commit()

    await seed_initial_data()

    async with SessionLocal() as session:
        model = await session.scalar(
            select(ModelConfig).where(ModelConfig.public_model == "deepseek-flash")
        )
        assert model.enabled is True
        assert model.default_allowed is True
        assert (model.capabilities or {}).get("vision") is True
        assert model.display_name == "DeepSeek Flash"

        model.enabled = False
        model.default_allowed = False
        await session.commit()

    await seed_initial_data()

    async with SessionLocal() as session:
        model = await session.scalar(
            select(ModelConfig).where(ModelConfig.public_model == "deepseek-flash")
        )
        assert model.enabled is False
        assert model.default_allowed is False


@pytest.mark.asyncio
async def test_v4_pro_remains_available_with_official_pricing(client):
    # DeepSeek 于 2026-09-14 撤销了 V4 Pro 下线计划，改为继续按原价提供。
    # 计价与开关都必须保持不变；退役流程不应被触发。
    async with SessionLocal() as session:
        model = await session.scalar(
            select(ModelConfig).where(ModelConfig.public_model == "deepseek-v4-pro")
        )
        assert model is not None
        assert model.enabled is True
        assert model.default_allowed is True
        pricing = await session.scalar(
            select(ModelPricing).where(ModelPricing.model_config_id == model.id)
        )
        assert pricing is not None
        assert pricing.input_price == Decimal("4.5")
        assert pricing.cached_input_price == Decimal("0.15")
        assert pricing.output_price == Decimal("13.5")
        assert pricing.peak_input_price == Decimal("9")
        assert pricing.peak_cached_input_price == Decimal("0.3")
        assert pricing.peak_output_price == Decimal("27")


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
