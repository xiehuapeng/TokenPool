"""Guarded, idempotent catalog repair. No changes to users, keys or usage history.

Run after schema migration. Default is dry-run; --apply commits the transaction.
Capture the JSON result in the private deployment backup for data rollback.
"""
import argparse
import asyncio
import json
from sqlalchemy import select, text

from app.database.session import SessionLocal, engine
from app.models import ModelConfig, ModelPricing, ProviderConfig
from app.services.bootstrap import SEED_PRICINGS
from app.services.model_aliases import OFFICIAL_ALIASES
from app.utils.time import utc_now


async def repair(session):
    changes = []
    rows = (await session.execute(select(ModelConfig, ModelPricing)
        .join(ModelPricing, ModelPricing.model_config_id == ModelConfig.id)
        .where(ModelConfig.public_model.in_(SEED_PRICINGS))
        .with_for_update())).all()
    for model, pricing in rows:
        expected = SEED_PRICINGS[model.public_model]
        updates = {}
        rules = expected.get("cache_pricing")
        if rules and pricing.cache_pricing is None:
            for field in ("input_price", "cached_input_price", "output_price",
                          "high_input_price", "high_cached_input_price", "high_output_price"):
                if getattr(pricing, field) != expected.get(field):
                    raise ValueError(f"Custom pricing conflict: {model.public_model}/{field}")
            updates["cache_pricing"] = rules
        elif rules and pricing.cache_pricing != rules:
            raise ValueError(f"Custom cache pricing conflict: {model.public_model}")
        if model.public_model == "qwen3.7-plus":
            if pricing.tier_threshold_tokens not in (256000, 262144):
                raise ValueError("Custom Qwen threshold conflict")
            if pricing.tier_threshold_tokens == 262144:
                updates["tier_threshold_tokens"] = 256000
        if updates:
            changes.append({"model": model.public_model, "pricing_before": {
                field: getattr(pricing, field) for field in updates}, "pricing_after": updates})
            for field, value in updates.items():
                setattr(pricing, field, value)
            pricing.effective_at = utc_now()
    aliases = OFFICIAL_ALIASES["deepseek"]
    models = list(await session.scalars(select(ModelConfig).join(ProviderConfig)
        .where(ProviderConfig.code == "deepseek", ModelConfig.public_model.in_(aliases))
        .with_for_update()))
    for model in models:
        if model.upstream_model != model.public_model:
            raise ValueError(f"Custom upstream mapping conflict: {model.public_model}")
        caps = dict(model.capabilities or {})
        next_caps = {**caps, "vision": True, "official_alias_of": aliases[model.public_model]}
        # Availability is recomputed by discovery, not forced by seed presence.
        canonical = await session.scalar(select(ModelConfig).where(
            ModelConfig.provider_id == model.provider_id,
            ModelConfig.upstream_model == aliases[model.public_model]))
        if canonical and (canonical.capabilities or {}).get("official_available"):
            next_caps["official_available"] = True
        if next_caps != caps:
            changes.append({"model": model.public_model, "capabilities_before": caps,
                            "capabilities_after": next_caps})
            model.capabilities = next_caps
    return changes


async def main(apply):
    async with SessionLocal() as session:
        if session.bind.dialect.name == "postgresql":
            await session.execute(text("SET LOCAL lock_timeout = '1s'"))
        changes = await repair(session)
        if apply:
            await session.commit()
        else:
            await session.rollback()
        print(json.dumps({"applied": apply, "changes": changes}, ensure_ascii=False, default=str))
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    asyncio.run(main(parser.parse_args().apply))
