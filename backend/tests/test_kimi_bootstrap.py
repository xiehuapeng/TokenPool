import pytest
from sqlalchemy import func, select

from app.database.session import SessionLocal
from app.models import ModelConfig, ProviderConfig, User, UserModelPermission
from app.services.bootstrap import seed_initial_data


@pytest.mark.asyncio
async def test_kimi_models_are_enabled_and_legacy_preference_is_migrated(
    client,
):
    async with SessionLocal() as session:
        provider = await session.scalar(
            select(ProviderConfig).where(ProviderConfig.code == "kimi")
        )
        user = User(
            username="retired-kimi-user",
            password_hash="not-used-in-this-test",
            status="active",
            is_admin=False,
        )
        retired = ModelConfig(
            public_model="kimi-k2",
            provider_id=provider.id,
            upstream_model="kimi-k2",
            display_name="Kimi K2",
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
        provider = await session.scalar(
            select(ProviderConfig).where(ProviderConfig.code == "kimi")
        )
        models = list(
            await session.scalars(
                select(ModelConfig).where(
                    ModelConfig.public_model.in_(
                        (
                            "kimi-k3",
                            "kimi-k2.7-code",
                            "kimi-k2.7-code-highspeed",
                        )
                    )
                )
            )
        )
        retired_count = await session.scalar(
            select(func.count(ModelConfig.id)).where(
                ModelConfig.public_model == "kimi-k2"
            )
        )
        migrated_user = await session.scalar(
            select(User).where(User.username == "retired-kimi-user")
        )
        replacement = await session.scalar(
            select(ModelConfig).where(
                ModelConfig.public_model == "kimi-k2.7-code"
            )
        )
        permission_count = await session.scalar(
            select(func.count(UserModelPermission.id)).where(
                UserModelPermission.user_id == migrated_user.id
            )
        )

    assert provider.enabled is True
    assert {model.public_model for model in models} == {
        "kimi-k3",
        "kimi-k2.7-code",
        "kimi-k2.7-code-highspeed",
    }
    assert all(model.enabled for model in models)
    assert all(model.default_allowed for model in models)
    assert all(model.capabilities["tools"] for model in models)
    assert retired_count == 0
    assert migrated_user.preferred_model_id == replacement.id
    assert permission_count == 0


@pytest.mark.asyncio
async def test_kimi_admin_disable_survives_restart(client):
    async with SessionLocal() as session:
        model = await session.scalar(
            select(ModelConfig).where(ModelConfig.public_model == "kimi-k3")
        )
        model.enabled = False
        model.default_allowed = False
        await session.commit()

    await seed_initial_data()

    async with SessionLocal() as session:
        model = await session.scalar(
            select(ModelConfig).where(ModelConfig.public_model == "kimi-k3")
        )
        assert model.enabled is False
        assert model.default_allowed is False

        # Leave the shared test database in its default state for later tests.
        model.enabled = True
        model.default_allowed = True
        await session.commit()
