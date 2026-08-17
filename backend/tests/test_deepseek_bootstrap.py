import pytest
from sqlalchemy import func, select

from app.database.session import SessionLocal
from app.models import ModelConfig, ProviderConfig, User, UserModelPermission
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
