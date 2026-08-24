from sqlalchemy import delete, select, update

from app.config.settings import get_settings
from app.database.session import SessionLocal
from app.models import ModelConfig, ProviderConfig, User, UserModelPermission
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

        for index, (model_id, display_name) in enumerate(
            (
                ("deepseek-v4-flash", "DeepSeek V4 Flash"),
                ("deepseek-v4-pro", "DeepSeek V4 Pro"),
            )
        ):
            model = await session.scalar(
                select(ModelConfig).where(ModelConfig.public_model == model_id)
            )
            if model is None:
                session.add(
                    ModelConfig(
                        public_model=model_id,
                        provider_id=deepseek.id,
                        upstream_model=model_id,
                        display_name=display_name,
                        enabled=deepseek.enabled,
                        default_allowed=deepseek.enabled,
                        capabilities={
                            "chat": True,
                            "stream": True,
                            "tools": True,
                            "json": True,
                            "thinking": True,
                        },
                        sort_order=index,
                    )
                )
        await session.flush()

        # DeepSeek于2026-07-24停止旧模型名。清理历史配置，避免旧数据库
        # 在升级后继续向用户暴露或路由到已退役的上游模型。
        retired_model_ids = list(
            await session.scalars(
                select(ModelConfig.id).where(
                    ModelConfig.public_model.in_(
                        ("deepseek-chat", "deepseek-reasoner")
                    )
                )
            )
        )
        if retired_model_ids:
            replacement = await session.scalar(
                select(ModelConfig).where(
                    ModelConfig.public_model == "deepseek-v4-flash"
                )
            )
            await session.execute(
                update(User)
                .where(User.preferred_model_id.in_(retired_model_ids))
                .values(
                    preferred_model_id=(replacement.id if replacement else None)
                )
            )
            await session.execute(
                delete(UserModelPermission).where(
                    UserModelPermission.model_config_id.in_(retired_model_ids)
                )
            )
            await session.execute(
                delete(ModelConfig).where(ModelConfig.id.in_(retired_model_ids))
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

        for code, name, base_url, api_key in (
            (
                "kimi",
                "Kimi",
                settings.kimi_base_url,
                settings.kimi_api_key.get_secret_value(),
            ),
            (
                "qwen",
                "阿里云 Qwen",
                settings.qwen_base_url,
                settings.qwen_api_key.get_secret_value(),
            ),
        ):
            provider = await session.scalar(
                select(ProviderConfig).where(ProviderConfig.code == code)
            )
            if provider is None:
                provider = ProviderConfig(
                    code=code,
                    display_name=name,
                    base_url=base_url,
                    enabled=bool(api_key),
                    timeout_seconds=300,
                )
                session.add(provider)
                await session.flush()
            else:
                provider.display_name = name
                provider.base_url = base_url
                provider.enabled = bool(api_key)
            seed_models = (
                (
                    ("qwen3.8-max", "Qwen 3.8 Max"),
                    ("qwen3.7-plus", "Qwen 3.7 Plus"),
                    ("qwen3.7-max", "Qwen 3.7 Max"),
                )
                if code == "qwen"
                else (
                    ("kimi-k3", "Kimi K3"),
                    ("kimi-k2.7-code", "Kimi K2.7 Code"),
                    (
                        "kimi-k2.7-code-highspeed",
                        "Kimi K2.7 Code Highspeed",
                    ),
                )
            )
            sort_base = 200 if code == "qwen" else 300
            for index, (model_id, display_name) in enumerate(seed_models):
                existing_model = await session.scalar(
                    select(ModelConfig).where(
                        ModelConfig.public_model == model_id
                    )
                )
                enabled_by_default = bool(api_key)
                capabilities = {
                    "chat": True,
                    "stream": True,
                    "tools": True,
                    "json": True,
                    "thinking": True,
                }
                if existing_model is None:
                    session.add(
                        ModelConfig(
                            public_model=model_id,
                            provider_id=provider.id,
                            upstream_model=model_id,
                            display_name=display_name,
                            enabled=enabled_by_default,
                            default_allowed=enabled_by_default,
                            capabilities=capabilities,
                            sort_order=sort_base + index,
                        )
                    )
                else:
                    existing_model.provider_id = provider.id
                    existing_model.upstream_model = model_id
                    existing_model.display_name = display_name
                    # Kimi首次接入时默认开放；后续启动保留管理员在模型
                    # 管理页做出的启停选择。Qwen暂时沿用原有启动策略。
                    if code == "qwen":
                        existing_model.enabled = enabled_by_default
                        existing_model.default_allowed = enabled_by_default
                    existing_model.capabilities = {
                        **(existing_model.capabilities or {}),
                        **capabilities,
                    }
                    existing_model.sort_order = sort_base + index

        # 旧版kimi-k2已不在当前官方模型列表中。升级时迁移用户偏好并
        # 删除历史模型配置，避免继续展示或路由到已退役的模型名。
        retired_kimi = await session.scalar(
            select(ModelConfig).where(ModelConfig.public_model == "kimi-k2")
        )
        if retired_kimi is not None:
            replacement = await session.scalar(
                select(ModelConfig).where(
                    ModelConfig.public_model == "kimi-k2.7-code"
                )
            )
            await session.execute(
                update(User)
                .where(User.preferred_model_id == retired_kimi.id)
                .values(
                    preferred_model_id=(replacement.id if replacement else None)
                )
            )
            await session.execute(
                delete(UserModelPermission).where(
                    UserModelPermission.model_config_id == retired_kimi.id
                )
            )
            await session.delete(retired_kimi)

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
