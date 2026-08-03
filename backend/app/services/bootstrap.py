from sqlalchemy import select

from app.config.settings import get_settings
from app.database.session import SessionLocal
from app.models import ModelConfig, ProviderConfig, User
from app.utils.security import hash_password


async def seed_initial_data() -> None:
    settings = get_settings()
    async with SessionLocal() as session:
        deepseek = await session.scalar(
            select(ProviderConfig).where(ProviderConfig.code == "deepseek")
        )
        if deepseek is None:
            deepseek = ProviderConfig(
                code="deepseek",
                display_name="DeepSeek",
                base_url=settings.deepseek_base_url,
                enabled=bool(settings.deepseek_api_key.get_secret_value()),
                timeout_seconds=300,
            )
            session.add(deepseek)
            await session.flush()
        else:
            # Provider secret仍只来自环境变量；这里同步非敏感运行配置，
            # 避免首次无Key启动后，即使补齐.env仍保持不可用。
            deepseek.base_url = settings.deepseek_base_url
            deepseek.enabled = bool(settings.deepseek_api_key.get_secret_value())

        model = await session.scalar(
            select(ModelConfig).where(ModelConfig.public_model == "deepseek-chat")
        )
        if model is None:
            session.add(
                ModelConfig(
                    public_model="deepseek-chat",
                    provider_id=deepseek.id,
                    upstream_model="deepseek-chat",
                    display_name="DeepSeek Chat",
                    enabled=True,
                    default_allowed=True,
                    capabilities={
                        "chat": True,
                        "stream": True,
                        "tools": True,
                        "json": True,
                    },
                )
            )

        glm = await session.scalar(
            select(ProviderConfig).where(ProviderConfig.code == "glm")
        )
        if glm is None:
            glm = ProviderConfig(
                code="glm",
                display_name="Zhipu GLM",
                base_url=settings.glm_base_url,
                enabled=bool(settings.glm_api_key.get_secret_value()),
                timeout_seconds=300,
            )
            session.add(glm)
            await session.flush()
        else:
            glm.display_name = "Zhipu GLM"
            glm.base_url = settings.glm_base_url
            glm.enabled = bool(settings.glm_api_key.get_secret_value())

        for index, model_id in enumerate(
            (
                "glm-4.5",
                "glm-4.5-air",
                "glm-4.6",
                "glm-4.7",
                "glm-5",
                "glm-5-turbo",
                "glm-5.1",
                "glm-5.2",
            )
        ):
            existing_model = await session.scalar(
                select(ModelConfig).where(ModelConfig.public_model == model_id)
            )
            if existing_model is None:
                session.add(
                    ModelConfig(
                        public_model=model_id,
                        provider_id=glm.id,
                        upstream_model=model_id,
                        display_name=model_id.upper(),
                        enabled=True,
                        default_allowed=True,
                        capabilities={
                            "chat": True,
                            "stream": True,
                            "tools": True,
                            "json": True,
                            "thinking": True,
                        },
                        sort_order=100 + index,
                    )
                )

        for code, name, public_model in (
            ("kimi", "Kimi", "kimi-k2"),
            ("qwen", "阿里云 Qwen", "qwen-coder"),
        ):
            provider = await session.scalar(
                select(ProviderConfig).where(ProviderConfig.code == code)
            )
            if provider is None:
                provider = ProviderConfig(
                    code=code,
                    display_name=name,
                    base_url="",
                    enabled=False,
                    timeout_seconds=300,
                )
                session.add(provider)
                await session.flush()
            existing_model = await session.scalar(
                select(ModelConfig).where(ModelConfig.public_model == public_model)
            )
            if existing_model is None:
                session.add(
                    ModelConfig(
                        public_model=public_model,
                        provider_id=provider.id,
                        upstream_model=public_model,
                        display_name=public_model,
                        enabled=False,
                        default_allowed=False,
                        capabilities={"chat": True, "stream": True},
                    )
                )

        admin_password = settings.admin_password.get_secret_value()
        if admin_password:
            admin = await session.scalar(
                select(User).where(User.username == settings.admin_username)
            )
            if admin is None:
                session.add(
                    User(
                        username=settings.admin_username,
                        password_hash=hash_password(admin_password),
                        status="active",
                        is_admin=True,
                    )
                )
        await session.commit()
