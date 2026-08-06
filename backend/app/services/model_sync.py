import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.database.session import SessionLocal
from app.models import ModelConfig, ProviderConfig
from app.providers.base import ProviderModel
from app.providers.registry import provider_registry
from app.utils.time import utc_now


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ModelSyncResult:
    provider: str
    discovered: int
    created: int
    available: int
    unavailable: int


def _public_model_id(
    provider_code: str,
    upstream_model: str,
    occupied: dict[str, int],
    provider_id: int,
) -> str:
    owner = occupied.get(upstream_model)
    if owner is None or owner == provider_id:
        return upstream_model
    return f"{provider_code}:{upstream_model}"


async def record_provider_model_discovery(
    session: AsyncSession,
    provider: ProviderConfig,
    upstream_models: list[ProviderModel],
) -> ModelSyncResult:
    synced_at = utc_now().isoformat()
    available_ids = {item.id for item in upstream_models}
    provider_models = list(
        await session.scalars(
            select(ModelConfig).where(ModelConfig.provider_id == provider.id)
        )
    )
    by_upstream = {item.upstream_model: item for item in provider_models}
    occupied = {
        item.public_model: item.provider_id
        for item in await session.scalars(select(ModelConfig))
    }

    unavailable = 0
    for model in provider_models:
        is_available = model.upstream_model in available_ids
        capabilities = dict(model.capabilities or {})
        capabilities["official_available"] = is_available
        capabilities["official_synced_at"] = synced_at
        model.capabilities = capabilities
        if not is_available:
            unavailable += 1

    created = 0
    for index, upstream in enumerate(upstream_models):
        existing = by_upstream.get(upstream.id)
        if existing is not None:
            continue
        public_model = _public_model_id(
            provider.code,
            upstream.id,
            occupied,
            provider.id,
        )
        model = ModelConfig(
            public_model=public_model,
            provider_id=provider.id,
            upstream_model=upstream.id,
            display_name=upstream.id,
            enabled=False,
            default_allowed=False,
            capabilities={
                "chat": True,
                "stream": True,
                "official_available": True,
                "official_synced_at": synced_at,
            },
            sort_order=1000 + index,
        )
        session.add(model)
        occupied[public_model] = provider.id
        by_upstream[upstream.id] = model
        created += 1

    await session.flush()
    return ModelSyncResult(
        provider=provider.code,
        discovered=len(available_ids),
        created=created,
        available=len(available_ids),
        unavailable=unavailable,
    )


async def sync_configured_provider_models() -> list[ModelSyncResult]:
    async with SessionLocal() as session:
        provider_codes = list(
            await session.scalars(
                select(ProviderConfig.code)
                .where(ProviderConfig.enabled.is_(True))
                .order_by(ProviderConfig.id)
            )
        )

    results: list[ModelSyncResult] = []
    for provider_code in provider_codes:
        async with SessionLocal() as session:
            provider = await session.scalar(
                select(ProviderConfig).where(
                    ProviderConfig.code == provider_code
                )
            )
            if provider is None or not provider.enabled:
                continue
            try:
                upstream_models = await provider_registry.get(
                    provider.code
                ).list_models(timeout_seconds=min(provider.timeout_seconds, 60))
                if not upstream_models:
                    raise ValueError("upstream returned an empty model list")
                result = await record_provider_model_discovery(
                    session,
                    provider,
                    upstream_models,
                )
                await session.commit()
                results.append(result)
                logger.info(
                    "Official model sync completed provider=%s discovered=%d created=%d unavailable=%d",
                    result.provider,
                    result.discovered,
                    result.created,
                    result.unavailable,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await session.rollback()
                logger.warning(
                    "Official model sync failed provider=%s error=%s",
                    provider_code,
                    exc,
                )
    return results


async def automatic_model_sync_loop() -> None:
    settings = get_settings()
    await asyncio.sleep(settings.model_sync_initial_delay_seconds)
    while True:
        try:
            await sync_configured_provider_models()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Automatic official model sync cycle failed")
        await asyncio.sleep(settings.model_sync_interval_seconds)
