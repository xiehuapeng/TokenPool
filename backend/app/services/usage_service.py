from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, or_, select, update

from app.database.session import SessionLocal
from app.models import ModelConfig, ModelPricing, UsageLog
from app.services.pricing_service import (
    BEIJING_TZ,
    compute_cost,
    get_pricing_by_model_config_id,
    normalize_usage,
)
from app.utils.redaction import redact_secrets
from app.utils.time import utc_now


async def create_usage_log(
    *,
    request_id: str,
    user_id: int,
    api_key_id: int,
    requested_model: str,
    model: str,
    provider: str,
    upstream_model: str,
    stream: bool,
) -> datetime:
    started = utc_now()
    async with SessionLocal() as session:
        session.add(
            UsageLog(
                request_id=request_id,
                user_id=user_id,
                api_key_id=api_key_id,
                requested_model=requested_model,
                model=model,
                provider=provider,
                upstream_model=upstream_model,
                stream=stream,
                request_time=started,
                status="pending",
                usage_source="missing",
            )
        )
        await session.commit()
    return started


async def finish_usage_log(
    request_id: str,
    started: datetime,
    *,
    status: str,
    http_status: int | None,
    usage: dict | None = None,
    first_token_time: datetime | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    upstream_request_id: str | None = None,
    model_config_id: int | None = None,
) -> None:
    finished = utc_now()
    tokens = normalize_usage(usage)
    values = {
        "response_time": finished,
        "latency_ms": int((finished - started).total_seconds() * 1000),
        "status": status,
        "http_status": http_status,
        "first_token_time": first_token_time,
        "input_tokens": tokens.get("prompt_tokens"),
        "cached_input_tokens": tokens.get("cached_input_tokens"),
        "reasoning_tokens": tokens.get("reasoning_tokens"),
        "output_tokens": tokens.get("completion_tokens"),
        "total_tokens": tokens.get("total_tokens"),
        "usage_source": "upstream" if usage else "missing",
        "error_code": error_code,
        "error_message": (
            redact_secrets(error_message)[:500] if error_message else None
        ),
        "upstream_request_id": upstream_request_id,
    }
    async with SessionLocal() as session:
        if model_config_id is not None:
            pricing = await get_pricing_by_model_config_id(session, model_config_id)
            if pricing is not None:
                computed = compute_cost(
                    pricing,
                    input_tokens=tokens.get("prompt_tokens"),
                    cached_tokens=tokens.get("cached_input_tokens"),
                    output_tokens=tokens.get("completion_tokens"),
                    request_time_utc=started,
                )
                if computed is not None:
                    cost, price_detail = computed
                    values["cost"] = cost
                    values["cost_source"] = "realtime"
                    values["price_detail"] = price_detail
        await session.execute(
            update(UsageLog)
            .where(UsageLog.request_id == request_id)
            .values(**values)
        )
        await session.commit()


async def backfill_usage_costs(*, dry_run: bool = False) -> dict:
    """历史日志费用回填。

    目标：计费功能上线前产生的历史调用（cost 为空但有 token 数据）。
    方法：先从当前实际带回传缓存数据的调用统计每模型平均缓存命中率
    （SUM(缓存命中)/SUM(输入)），对缺失缓存数据的历史调用按该命中率推算
    缓存 tokens；模型自身无缓存数据时退回全部模型汇总的全局平均命中率。
    再按现行定价计费；cost_source 标记为 estimated，price_detail 附带
    估算标记（含所用命中率与推算出的缓存 tokens），便于与实时计价区分。
    """
    async with SessionLocal() as session:
        pricings: dict[str, ModelPricing] = {}
        pricing_rows = await session.execute(
            select(ModelConfig, ModelPricing)
            .join(ModelPricing, ModelPricing.model_config_id == ModelConfig.id)
            .where(ModelPricing.enabled.is_(True))
        )
        for model_config, pricing in pricing_rows:
            pricings[model_config.public_model] = pricing

        cache_rates: dict[str, float] = {}
        if pricings:
            rate_rows = await session.execute(
                select(
                    UsageLog.model,
                    func.sum(UsageLog.cached_input_tokens),
                    func.sum(UsageLog.input_tokens),
                )
                .where(
                    UsageLog.cached_input_tokens.isnot(None),
                    UsageLog.input_tokens.isnot(None),
                    UsageLog.input_tokens > 0,
                )
                .group_by(UsageLog.model)
            )
            global_cached_sum = 0
            global_input_sum = 0
            for model, cached_sum, input_sum in rate_rows:
                if cached_sum and input_sum:
                    cache_rates[model] = min(1.0, cached_sum / input_sum)
                    global_cached_sum += cached_sum
                    global_input_sum += input_sum
            global_cache_rate = (
                min(1.0, global_cached_sum / global_input_sum)
                if global_input_sum
                else None
            )

        candidates: list[UsageLog] = []
        if pricings:
            candidates = list(
                await session.scalars(
                    select(UsageLog).where(
                        UsageLog.cost.is_(None),
                        or_(
                            UsageLog.input_tokens.isnot(None),
                            UsageLog.output_tokens.isnot(None),
                        ),
                        UsageLog.model.in_(list(pricings.keys())),
                    )
                )
            )

        updated = 0
        estimated_cache_logs = 0
        total_cost = Decimal("0")
        for usage_log in candidates:
            pricing = pricings[usage_log.model]
            request_time = usage_log.request_time
            if request_time is None:
                continue
            if request_time.tzinfo is None:
                request_time = request_time.replace(tzinfo=timezone.utc)

            cached_tokens = usage_log.cached_input_tokens
            cache_rate = cache_rates.get(usage_log.model)
            cache_rate_basis = "model_avg"
            if cache_rate is None:
                cache_rate = global_cache_rate
                cache_rate_basis = "global_avg"
            cache_estimated = False
            if (
                cached_tokens is None
                and usage_log.input_tokens
                and cache_rate is not None
            ):
                cached_tokens = int(round(usage_log.input_tokens * cache_rate))
                cache_estimated = True

            computed = compute_cost(
                pricing,
                input_tokens=usage_log.input_tokens,
                cached_tokens=cached_tokens,
                output_tokens=usage_log.output_tokens,
                request_time_utc=request_time,
            )
            if computed is None:
                continue
            cost, price_detail = computed
            price_detail["estimated"] = True
            if cache_estimated:
                estimated_cache_logs += 1
                price_detail["cache_hit_rate"] = round(cache_rate, 6)
                price_detail["cache_rate_basis"] = cache_rate_basis
                price_detail["estimated_cached_tokens"] = cached_tokens
            usage_log.cost = cost
            usage_log.cost_source = "estimated"
            usage_log.price_detail = price_detail
            updated += 1
            total_cost += cost

        if dry_run:
            await session.rollback()
        else:
            await session.commit()

        return {
            "dry_run": dry_run,
            "scanned": len(candidates),
            "updated": updated,
            "estimated_cache_logs": estimated_cache_logs,
            "total_estimated_cost": float(total_cost),
            "model_cache_hit_rates": {
                model: round(rate, 6)
                for model, rate in sorted(cache_rates.items())
            },
            "global_cache_hit_rate": (
                round(global_cache_rate, 6)
                if global_cache_rate is not None
                else None
            ),
        }


async def calibrate_estimated_cache_rates(
    *, calibrations: list[dict], dry_run: bool = False
) -> dict:
    """用官方平台导出的真实缓存命中率校准历史估算日志。

    回填按“模型平均命中率”推算缓存 tokens，但命中率随使用模式波动很大
    （重上下文复用日可达 98%）。官方平台导出的按天 token 明细给出真实
    命中率（命中 /（命中 + 未命中）），用于重算对应模型/日期的估算日志，
    使费用向官方账单对齐。校准后 price_detail 的 cache_rate_basis 标记为
    official_export 保留追溯性；已有缓存数据的实时日志不受影响。
    """
    async with SessionLocal() as session:
        pricings: dict[str, ModelPricing] = {}
        pricing_rows = await session.execute(
            select(ModelConfig, ModelPricing)
            .join(ModelPricing, ModelPricing.model_config_id == ModelConfig.id)
            .where(ModelPricing.enabled.is_(True))
        )
        for model_config, pricing in pricing_rows:
            pricings[model_config.public_model] = pricing

        groups = []
        for item in calibrations:
            model = item["model"]
            date_str = str(item["date"])
            hit_rate = min(1.0, max(0.0, float(item["hit_rate"])))
            group = {
                "model": model,
                "date": date_str,
                "hit_rate": round(hit_rate, 6),
                "scanned": 0,
                "updated": 0,
                "input_tokens": 0,
                "estimated_cached_tokens": 0,
                "old_total_cost": 0.0,
                "new_total_cost": 0.0,
            }
            groups.append(group)
            if model not in pricings:
                group["error"] = "no_enabled_pricing"
                continue
            try:
                day = date.fromisoformat(date_str)
            except ValueError:
                group["error"] = "invalid_date"
                continue

            candidates = list(
                await session.scalars(
                    select(UsageLog).where(
                        UsageLog.model == model,
                        UsageLog.cached_input_tokens.is_(None),
                        UsageLog.input_tokens.isnot(None),
                        UsageLog.input_tokens > 0,
                        or_(
                            UsageLog.cost.is_(None),
                            UsageLog.cost_source == "estimated",
                        ),
                    )
                )
            )
            targets = []
            for usage_log in candidates:
                request_time = usage_log.request_time
                if request_time is None:
                    continue
                if request_time.tzinfo is None:
                    request_time = request_time.replace(tzinfo=timezone.utc)
                if request_time.astimezone(BEIJING_TZ).date() == day:
                    targets.append(usage_log)
            group["scanned"] = len(targets)

            old_cost = Decimal("0")
            new_cost = Decimal("0")
            for usage_log in targets:
                request_time = usage_log.request_time
                if request_time.tzinfo is None:
                    request_time = request_time.replace(tzinfo=timezone.utc)
                cached_tokens = int(round(usage_log.input_tokens * hit_rate))
                computed = compute_cost(
                    pricings[model],
                    input_tokens=usage_log.input_tokens,
                    cached_tokens=cached_tokens,
                    output_tokens=usage_log.output_tokens,
                    request_time_utc=request_time,
                )
                if computed is None:
                    continue
                cost, price_detail = computed
                if usage_log.cost is not None:
                    old_cost += usage_log.cost
                price_detail["estimated"] = True
                price_detail["cache_hit_rate"] = round(hit_rate, 6)
                price_detail["cache_rate_basis"] = "official_export"
                price_detail["estimated_cached_tokens"] = cached_tokens
                usage_log.cost = cost
                usage_log.cost_source = "estimated"
                usage_log.price_detail = price_detail
                new_cost += cost
                group["input_tokens"] += usage_log.input_tokens
                group["estimated_cached_tokens"] += cached_tokens
                group["updated"] += 1
            group["old_total_cost"] = float(old_cost)
            group["new_total_cost"] = float(new_cost)

        if dry_run:
            await session.rollback()
        else:
            await session.commit()

        return {"dry_run": dry_run, "groups": groups}


async def recover_stale_usage_logs(max_age_minutes: int = 5) -> int:
    """Close pending calls left behind by a previous interrupted process.

    Normal client disconnects are finalized by the cancellation-safe stream
    cleanup. This startup recovery covers hard process termination, power loss,
    and records created by older gateway versions.
    """

    finished = utc_now()
    cutoff = finished - timedelta(minutes=max_age_minutes)
    async with SessionLocal() as session:
        stale_logs = list(
            await session.scalars(
                select(UsageLog).where(
                    UsageLog.status == "pending",
                    UsageLog.request_time < cutoff,
                )
            )
        )
        for usage_log in stale_logs:
            started = usage_log.request_time
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            usage_log.response_time = finished
            usage_log.latency_ms = max(
                0, int((finished - started).total_seconds() * 1000)
            )
            usage_log.status = "interrupted"
            usage_log.error_code = "stale_pending_recovered"
            usage_log.error_message = (
                "Request ended without a terminal status and was recovered at startup"
            )
        if stale_logs:
            await session.commit()
        return len(stale_logs)
