from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.models import ModelPricing

MILLION = Decimal(1_000_000)

BEIJING_TZ = timezone(timedelta(hours=8))
DEEPSEEK_PEAK_HOUR_RANGES = ((9, 12), (14, 18))


def _as_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def normalize_usage(usage: dict | None) -> dict:
    if not isinstance(usage, dict):
        return {}

    prompt = _as_int(usage.get("prompt_tokens"))
    completion = _as_int(usage.get("completion_tokens"))
    total = _as_int(usage.get("total_tokens"))

    cached_candidates = []
    hit = _as_int(usage.get("prompt_cache_hit_tokens"))
    if hit is not None:
        cached_candidates.append(hit)
    prompt_details = usage.get("prompt_tokens_details")
    if isinstance(prompt_details, dict):
        details_cached = _as_int(prompt_details.get("cached_tokens"))
        if details_cached is not None:
            cached_candidates.append(details_cached)
    top_cached = _as_int(usage.get("cached_tokens"))
    if top_cached is not None:
        cached_candidates.append(top_cached)
    cached = max(cached_candidates) if cached_candidates else None
    if cached is not None and prompt is not None and cached > prompt:
        cached = prompt

    reasoning = None
    completion_details = usage.get("completion_tokens_details")
    if isinstance(completion_details, dict):
        reasoning = _as_int(completion_details.get("reasoning_tokens"))

    return {
        "prompt_tokens": prompt,
        "cached_input_tokens": cached,
        "completion_tokens": completion,
        "reasoning_tokens": reasoning,
        "total_tokens": total,
    }


def is_peak_time(request_time_utc: datetime) -> bool:
    if request_time_utc.tzinfo is None:
        request_time_utc = request_time_utc.replace(tzinfo=timezone.utc)
    beijing = request_time_utc.astimezone(BEIJING_TZ)
    if beijing.weekday() >= 5:
        return False
    hour = beijing.hour
    return any(start <= hour < end for start, end in DEEPSEEK_PEAK_HOUR_RANGES)


def _apply_tier(
    pricing: ModelPricing,
    input_tokens: int,
) -> tuple[str, Decimal, Decimal, Decimal]:
    input_price = pricing.input_price
    cached_input_price = pricing.cached_input_price
    output_price = pricing.output_price
    tier = "base"
    if (
        pricing.tier_threshold_tokens is not None
        and input_tokens > pricing.tier_threshold_tokens
        and pricing.high_input_price is not None
    ):
        tier = "high"
        input_price = pricing.high_input_price
        if pricing.high_cached_input_price is not None:
            cached_input_price = pricing.high_cached_input_price
        if pricing.high_output_price is not None:
            output_price = pricing.high_output_price
    return tier, input_price, cached_input_price, output_price


def _apply_peak(
    pricing: ModelPricing,
    request_time_utc: datetime,
    input_price: Decimal,
    cached_input_price: Decimal,
    output_price: Decimal,
) -> tuple[bool, Decimal, Decimal, Decimal]:
    peak = False
    if pricing.peak_input_price is not None and is_peak_time(request_time_utc):
        peak = True
        input_price = pricing.peak_input_price
        if pricing.peak_cached_input_price is not None:
            cached_input_price = pricing.peak_cached_input_price
        if pricing.peak_output_price is not None:
            output_price = pricing.peak_output_price
    return peak, input_price, cached_input_price, output_price


def compute_cost(
    pricing: ModelPricing,
    *,
    input_tokens: int | None,
    cached_tokens: int | None,
    output_tokens: int | None,
    request_time_utc: datetime,
) -> tuple[Decimal, dict] | None:
    if input_tokens is None and output_tokens is None:
        return None
    input_tokens = input_tokens or 0
    output_tokens = output_tokens or 0
    cached_tokens = min(cached_tokens or 0, input_tokens)

    tier, input_price, cached_input_price, output_price = _apply_tier(
        pricing, input_tokens
    )
    peak, input_price, cached_input_price, output_price = _apply_peak(
        pricing, request_time_utc, input_price, cached_input_price, output_price
    )

    miss_tokens = input_tokens - cached_tokens
    cost = (
        Decimal(miss_tokens) * input_price
        + Decimal(cached_tokens) * cached_input_price
        + Decimal(output_tokens) * output_price
    ) / MILLION

    detail = {
        "input_price": float(input_price),
        "cached_input_price": float(cached_input_price),
        "output_price": float(output_price),
        "peak": peak,
        "tier": tier,
    }
    return cost, detail


async def get_pricing_by_model_config_id(
    session, model_config_id: int
) -> ModelPricing | None:
    result = await session.execute(
        select(ModelPricing).where(
            ModelPricing.model_config_id == model_config_id,
            ModelPricing.enabled.is_(True),
        )
    )
    return result.scalars().first()
