from dataclasses import dataclass

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ModelConfig, ProviderConfig, User, UserModelPermission
from app.providers.base import BaseProvider
from app.providers.registry import provider_registry
from app.utils.errors import GatewayError


GATEWAY_MODEL_ID = "team-coding"

_THINKING_NAME_HINTS = ("reasoner", "thinking", "think", "-r1")


def model_requires_reasoning_content(model: ModelConfig) -> bool:
    capabilities = model.capabilities or {}
    thinking = capabilities.get("thinking")
    if thinking is not None:
        return bool(thinking)
    name = (model.upstream_model or "").lower()
    return any(hint in name for hint in _THINKING_NAME_HINTS)


_IMAGE_PART_TYPES = ("image_url", "image")


def payload_contains_images(payload: dict) -> bool:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return False
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, list) and any(
            isinstance(part, dict) and part.get("type") in _IMAGE_PART_TYPES
            for part in content
        ):
            return True
    return False


def model_supports_vision(model: ModelConfig) -> bool:
    return bool((model.capabilities or {}).get("vision"))


def ensure_reasoning_content(payload: dict) -> dict:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return payload
    patched = False
    new_messages = []
    for message in messages:
        if (
            isinstance(message, dict)
            and message.get("role") == "assistant"
            and "reasoning_content" not in message
        ):
            message = {**message, "reasoning_content": ""}
            patched = True
        new_messages.append(message)
    if not patched:
        return payload
    return {**payload, "messages": new_messages}


@dataclass(slots=True)
class ModelRoute:
    model: ModelConfig
    provider_config: ProviderConfig
    provider: BaseProvider


async def resolve_model(
    session: AsyncSession, *, user_id: int, public_model: str
) -> ModelRoute:
    result = await session.execute(
        select(ModelConfig, ProviderConfig, UserModelPermission.allowed)
        .join(ProviderConfig, ProviderConfig.id == ModelConfig.provider_id)
        .outerjoin(
            UserModelPermission,
            and_(
                UserModelPermission.model_config_id == ModelConfig.id,
                UserModelPermission.user_id == user_id,
            ),
        )
        .where(ModelConfig.public_model == public_model)
    )
    row = result.one_or_none()
    if row is None:
        raise GatewayError(
            f"Model '{public_model}' does not exist",
            status_code=404,
            code="model_not_found",
            param="model",
        )
    model, provider_config, explicit_allowed = row
    if not model.enabled or not provider_config.enabled:
        raise GatewayError(
            f"Model '{public_model}' is not available",
            status_code=503,
            code="model_unavailable",
            param="model",
        )
    allowed = model.default_allowed if explicit_allowed is None else explicit_allowed
    if not allowed:
        raise GatewayError(
            f"Access to model '{public_model}' is denied",
            status_code=403,
            error_type="permission_error",
            code="model_permission_denied",
            param="model",
        )
    return ModelRoute(
        model=model,
        provider_config=provider_config,
        provider=provider_registry.get(provider_config.code),
    )


async def resolve_requested_model(
    session: AsyncSession,
    *,
    user_id: int,
    requested_model: str,
    key_preferred_model_id: int | None = None,
) -> ModelRoute:
    if requested_model != GATEWAY_MODEL_ID:
        return await resolve_model(
            session,
            user_id=user_id,
            public_model=requested_model,
        )

    if key_preferred_model_id is not None:
        key_model = await session.get(ModelConfig, key_preferred_model_id)
        if key_model is not None:
            return await resolve_model(
                session,
                user_id=user_id,
                public_model=key_model.public_model,
            )

    user = await session.get(User, user_id)
    if user is None:
        raise GatewayError(
            "User does not exist",
            status_code=401,
            error_type="authentication_error",
            code="invalid_api_key",
        )
    if user.preferred_model_id is not None:
        preferred = await session.get(ModelConfig, user.preferred_model_id)
        if preferred is None:
            raise GatewayError(
                "The selected model no longer exists",
                status_code=503,
                code="selected_model_unavailable",
                param="model",
            )
        return await resolve_model(
            session,
            user_id=user_id,
            public_model=preferred.public_model,
        )

    permitted = await list_permitted_models(session, user_id=user_id)
    if not permitted:
        raise GatewayError(
            "No model is available for this user",
            status_code=403,
            error_type="permission_error",
            code="no_permitted_model",
            param="model",
        )
    return await resolve_model(
        session,
        user_id=user_id,
        public_model=permitted[0].public_model,
    )


async def list_permitted_models(
    session: AsyncSession, *, user_id: int
) -> list[ModelConfig]:
    rows = await session.execute(
        select(ModelConfig, UserModelPermission.allowed)
        .join(ProviderConfig, ProviderConfig.id == ModelConfig.provider_id)
        .outerjoin(
            UserModelPermission,
            and_(
                UserModelPermission.model_config_id == ModelConfig.id,
                UserModelPermission.user_id == user_id,
            ),
        )
        .where(ModelConfig.enabled.is_(True), ProviderConfig.enabled.is_(True))
        .order_by(ModelConfig.sort_order, ModelConfig.public_model)
    )
    return [
        model
        for model, explicit_allowed in rows
        if (
            model.default_allowed
            if explicit_allowed is None
            else explicit_allowed
        )
    ]


async def find_vision_fallback(
    session: AsyncSession, *, user_id: int, exclude_model_id: int
) -> ModelRoute | None:
    permitted = await list_permitted_models(session, user_id=user_id)
    for model in permitted:
        if model.id != exclude_model_id and model_supports_vision(model):
            return await resolve_model(
                session,
                user_id=user_id,
                public_model=model.public_model,
            )
    return None
