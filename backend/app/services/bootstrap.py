from decimal import Decimal

from sqlalchemy import delete, select, update

from app.config.settings import get_settings
from app.database.session import SessionLocal
from app.models import ModelConfig, ModelPricing, ProviderConfig, User, UserModelPermission
from app.utils.security import hash_password
from app.utils.time import utc_now


VISION_CAPABLE_MODELS = {
    "glm-5.3-flash",
    "qwen3.8-max",
    "qwen3.7-plus",
    "kimi-k3",
    "kimi-k2.7-code",
    "kimi-k2.7-code-highspeed",
}

SEED_PRICINGS: dict[str, dict] = {
    "deepseek-v4-flash": {
        "input_price": Decimal("1.5"),
        "cached_input_price": Decimal("0.05"),
        "output_price": Decimal("4.5"),
        "peak_input_price": Decimal("3"),
        "peak_cached_input_price": Decimal("0.1"),
        "peak_output_price": Decimal("9"),
        "note": "DeepSeek官网价，非高峰档；工作日9-12/14-18（北京时间）高峰翻倍",
    },
    "deepseek-v4-pro": {
        "input_price": Decimal("4.5"),
        "cached_input_price": Decimal("0.15"),
        "output_price": Decimal("13.5"),
        "peak_input_price": Decimal("9"),
        "peak_cached_input_price": Decimal("0.3"),
        "peak_output_price": Decimal("27"),
        "note": "DeepSeek官网价，非高峰档；工作日9-12/14-18（北京时间）高峰翻倍",
    },
    "glm-5.3": {
        "input_price": Decimal("8"),
        "cached_input_price": Decimal("2"),
        "output_price": Decimal("28"),
        "note": "智谱官网价，不分档",
    },
    "glm-5.3-flash": {
        "input_price": Decimal("0.4"),
        "cached_input_price": Decimal("0.115"),
        "output_price": Decimal("1.4"),
        "note": (
            "智谱官网限时半价（GLM-5.3的1/20），折扣至2026-09-09，"
            "9月10日起恢复原价输入0.8/输出2.8，需同步调整"
        ),
    },
    "glm-5": {
        "input_price": Decimal("4"),
        "cached_input_price": Decimal("1"),
        "output_price": Decimal("18"),
        "tier_threshold_tokens": 32768,
        "high_input_price": Decimal("6"),
        "high_cached_input_price": Decimal("1.5"),
        "high_output_price": Decimal("22"),
        "note": "智谱官网价，输入≤32K/＞32K两档",
    },
    "glm-5-turbo": {
        "input_price": Decimal("5"),
        "cached_input_price": Decimal("1.2"),
        "output_price": Decimal("22"),
        "tier_threshold_tokens": 32768,
        "high_input_price": Decimal("7"),
        "high_cached_input_price": Decimal("1.8"),
        "high_output_price": Decimal("26"),
        "note": "智谱官网价，输入≤32K/＞32K两档",
    },
    "glm-4.7": {
        "input_price": Decimal("3"),
        "cached_input_price": Decimal("0.6"),
        "output_price": Decimal("14"),
        "tier_threshold_tokens": 32768,
        "high_input_price": Decimal("4"),
        "high_cached_input_price": Decimal("0.8"),
        "high_output_price": Decimal("16"),
        "note": "智谱官网价；输入≤32K且输出＜0.2K另有2/8/0.4档，未细分",
    },
    "glm-4.6": {
        "input_price": Decimal("5"),
        "cached_input_price": Decimal("1"),
        "output_price": Decimal("5"),
        "note": "输入/输出为官方价；缓存命中价官方未公布，按惯例约20%估为1元",
    },
    "glm-4.5": {
        "input_price": Decimal("0.8"),
        "cached_input_price": Decimal("0.16"),
        "output_price": Decimal("2"),
        "tier_threshold_tokens": 32768,
        "high_input_price": Decimal("1"),
        "high_cached_input_price": Decimal("0.2"),
        "high_output_price": Decimal("4"),
        "note": "智谱官网价；高档取(32K,128K]档，输入＞128K实际为2/0.4/6",
    },
    "glm-4.5-air": {
        "input_price": Decimal("0.8"),
        "cached_input_price": Decimal("0.16"),
        "output_price": Decimal("6"),
        "tier_threshold_tokens": 32768,
        "high_input_price": Decimal("1.2"),
        "high_cached_input_price": Decimal("0.24"),
        "high_output_price": Decimal("8"),
        "note": "智谱官网价；输出＜0.2K时输出价为2元档，未细分",
    },
    "kimi-k3": {
        "input_price": Decimal("20"),
        "cached_input_price": Decimal("2"),
        "output_price": Decimal("100"),
        "note": "Moonshot官网价（国内站），不分档",
    },
    "kimi-k2.7-code": {
        "input_price": Decimal("6.5"),
        "cached_input_price": Decimal("1.3"),
        "output_price": Decimal("27"),
        "note": "Moonshot官网价（国内站），不分档",
    },
    "kimi-k2.7-code-highspeed": {
        "input_price": Decimal("13"),
        "cached_input_price": Decimal("2.6"),
        "output_price": Decimal("54"),
        "note": "Moonshot官网价（国内站），不分档",
    },
    "qwen3.8-max": {
        "input_price": Decimal("12"),
        "cached_input_price": Decimal("1.5"),
        "output_price": Decimal("36"),
        "note": "阿里云百炼官网价（北京地域），不分档",
    },
    "qwen3.8-flash": {
        "input_price": Decimal("0.8"),
        "cached_input_price": Decimal("0.1"),
        "output_price": Decimal("2.7"),
        "note": "阿里云百炼官网价（北京地域），不分档",
    },
    "qwen3.7-plus": {
        "input_price": Decimal("1.6"),
        "cached_input_price": Decimal("0.32"),
        "output_price": Decimal("6.4"),
        "tier_threshold_tokens": 262144,
        "high_input_price": Decimal("4.8"),
        "high_cached_input_price": Decimal("0.96"),
        "high_output_price": Decimal("19.2"),
        "note": "阿里云百炼限时8折价（北京地域，输入/输出/缓存同折），原价2/0.4/8、>256K档6/1.2/24，官方未公布折扣截止时间",
    },
}


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
            capabilities = {
                "chat": True,
                "stream": True,
                "tools": True,
                "json": True,
                "thinking": True,
                **({"vision": True} if model_id in VISION_CAPABLE_MODELS else {}),
            }
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
                        capabilities=capabilities,
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

        glm_capabilities = {
            "chat": True,
            "stream": True,
            "tools": True,
            "json": True,
            "thinking": True,
        }
        for index, model_id in enumerate(
            (
                "glm-4.5",
                "glm-4.5-air",
                "glm-4.6",
                "glm-4.7",
                "glm-5",
                "glm-5-turbo",
                "glm-5.3",
                "glm-5.3-flash",
            )
        ):
            capabilities = {
                **glm_capabilities,
                **({"vision": True} if model_id in VISION_CAPABLE_MODELS else {}),
            }
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
                        capabilities=capabilities,
                        sort_order=100 + index,
                    )
                )
            else:
                existing_model.capabilities = {
                    **(existing_model.capabilities or {}),
                    **capabilities,
                }

        # GLM-5.1/5.2已被5.3系列取代。升级时迁移用户偏好并删除历史
        # 模型配置，避免继续展示或路由到已退役的模型名。
        retired_glm_ids = list(
            await session.scalars(
                select(ModelConfig.id).where(
                    ModelConfig.public_model.in_(("glm-5.1", "glm-5.2"))
                )
            )
        )
        if retired_glm_ids:
            replacement = await session.scalar(
                select(ModelConfig).where(ModelConfig.public_model == "glm-5.3")
            )
            await session.execute(
                update(User)
                .where(User.preferred_model_id.in_(retired_glm_ids))
                .values(
                    preferred_model_id=(replacement.id if replacement else None)
                )
            )
            await session.execute(
                delete(UserModelPermission).where(
                    UserModelPermission.model_config_id.in_(retired_glm_ids)
                )
            )
            await session.execute(
                delete(ModelConfig).where(ModelConfig.id.in_(retired_glm_ids))
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
                    ("qwen3.8-flash", "Qwen 3.8 Flash"),
                    ("qwen3.7-plus", "Qwen 3.7 Plus"),
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
                if model_id in VISION_CAPABLE_MODELS:
                    capabilities["vision"] = True
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

        # qwen3.7-max已下线，由qwen3.8-flash/3.8-max取代。升级时迁移用户
        # 偏好并删除历史模型配置，避免继续展示或路由到已退役的模型名。
        retired_qwen_max = await session.scalar(
            select(ModelConfig).where(ModelConfig.public_model == "qwen3.7-max")
        )
        if retired_qwen_max is not None:
            replacement = await session.scalar(
                select(ModelConfig).where(
                    ModelConfig.public_model == "qwen3.8-max"
                )
            )
            await session.execute(
                update(User)
                .where(User.preferred_model_id == retired_qwen_max.id)
                .values(
                    preferred_model_id=(replacement.id if replacement else None)
                )
            )
            await session.execute(
                delete(UserModelPermission).where(
                    UserModelPermission.model_config_id == retired_qwen_max.id
                )
            )
            await session.delete(retired_qwen_max)

        # 定价种子：仅首次插入，已存在（含管理员改过的）不覆盖。
        for public_model, pricing_data in SEED_PRICINGS.items():
            model = await session.scalar(
                select(ModelConfig).where(ModelConfig.public_model == public_model)
            )
            if model is None:
                continue
            existing_pricing = await session.scalar(
                select(ModelPricing).where(
                    ModelPricing.model_config_id == model.id
                )
            )
            if existing_pricing is not None:
                continue
            session.add(
                ModelPricing(
                    model_config_id=model.id,
                    effective_at=utc_now(),
                    **pricing_data,
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
