from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from app.database.session import SessionLocal
from app.models import ApiKey, UsageLog, User
from app.services.usage_service import (
    backfill_usage_costs,
    calibrate_estimated_cache_rates,
)
from app.utils.time import utc_now


async def _clear_usage_logs() -> None:
    async with SessionLocal() as session:
        await session.execute(delete(UsageLog))
        await session.commit()


async def _prepare_identity(client, username: str) -> tuple[int, int]:
    admin_token = (
        await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin-password"},
        )
    ).json()["access_token"]
    created = await client.post(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"username": username, "password": "developer-password1"},
    )
    assert created.status_code in (201, 409)
    user_token = (
        await client.post(
            "/api/auth/login",
            json={"username": username, "password": "developer-password1"},
        )
    ).json()["access_token"]
    await client.post(
        "/api/me/api-keys",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"name": f"{username}-key"},
    )
    async with SessionLocal() as session:
        user = await session.scalar(
            select(User).where(User.username == username)
        )
        key = (
            await session.scalars(
                select(ApiKey).where(ApiKey.user_id == user.id)
            )
        ).first()
        assert key is not None
        return user.id, key.id


async def _insert_log(
    user_id: int,
    api_key_id: int,
    request_id: str,
    *,
    model: str = "glm-5.3",
    provider: str = "glm",
    input_tokens: int | None = None,
    cached_input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost: Decimal | None = None,
    cost_source: str | None = None,
    price_detail: dict | None = None,
    request_time: datetime | None = None,
) -> None:
    has_usage = input_tokens is not None or output_tokens is not None
    async with SessionLocal() as session:
        session.add(
            UsageLog(
                request_id=request_id,
                user_id=user_id,
                api_key_id=api_key_id,
                requested_model=model,
                model=model,
                provider=provider,
                upstream_model=model,
                stream=False,
                request_time=request_time or utc_now(),
                status="success",
                http_status=200,
                input_tokens=input_tokens,
                cached_input_tokens=cached_input_tokens,
                output_tokens=output_tokens,
                total_tokens=(
                    (input_tokens or 0) + (output_tokens or 0)
                    if has_usage
                    else None
                ),
                usage_source="upstream" if has_usage else "missing",
                cost=cost,
                cost_source=cost_source,
                price_detail=price_detail,
            )
        )
        await session.commit()


async def _get_log(request_id: str) -> UsageLog:
    async with SessionLocal() as session:
        return await session.scalar(
            select(UsageLog).where(UsageLog.request_id == request_id)
        )


@pytest.mark.asyncio
async def test_backfill_estimates_missing_cache_from_average_hit_rate(client):
    await _clear_usage_logs()
    user_id, api_key_id = await _prepare_identity(client, "bf-user-a")

    await _insert_log(
        user_id,
        api_key_id,
        "bf-with-cache",
        input_tokens=1000,
        cached_input_tokens=500,
        output_tokens=200,
    )
    await _insert_log(
        user_id,
        api_key_id,
        "bf-missing-cache",
        input_tokens=1000,
        output_tokens=200,
    )

    result = await backfill_usage_costs()

    assert result["scanned"] == 2
    assert result["updated"] == 2
    assert result["estimated_cache_logs"] == 1
    assert result["model_cache_hit_rates"]["glm-5.3"] == pytest.approx(0.5)

    with_cache = await _get_log("bf-with-cache")
    assert with_cache.cost is not None
    assert with_cache.cost_source == "estimated"
    assert with_cache.price_detail["estimated"] is True
    assert "cache_hit_rate" not in with_cache.price_detail
    # glm-5.3 定价 8/2/28：(500*8 + 500*2 + 200*28)/1M = 0.0106
    assert float(with_cache.cost) == pytest.approx(0.0106)

    missing = await _get_log("bf-missing-cache")
    assert missing.cost is not None
    assert missing.cost_source == "estimated"
    assert missing.price_detail["estimated"] is True
    assert missing.price_detail["cache_hit_rate"] == pytest.approx(0.5)
    assert missing.price_detail["estimated_cached_tokens"] == 500
    assert float(missing.cost) == pytest.approx(0.0106)
    # 原始缓存字段不被回填覆盖
    assert missing.cached_input_tokens is None


@pytest.mark.asyncio
async def test_backfill_falls_back_to_global_average_hit_rate(client):
    await _clear_usage_logs()
    user_id, api_key_id = await _prepare_identity(client, "bf-user-f")

    await _insert_log(
        user_id,
        api_key_id,
        "bf-global-source",
        input_tokens=1000,
        cached_input_tokens=500,
        output_tokens=200,
    )
    await _insert_log(
        user_id,
        api_key_id,
        "bf-global-model-avg",
        input_tokens=1000,
        output_tokens=200,
    )
    await _insert_log(
        user_id,
        api_key_id,
        "bf-global-fallback",
        model="qwen3.7-plus",
        provider="qwen",
        input_tokens=1000,
        output_tokens=200,
    )

    result = await backfill_usage_costs()

    assert result["model_cache_hit_rates"] == {"glm-5.3": pytest.approx(0.5)}
    assert result["global_cache_hit_rate"] == pytest.approx(0.5)
    assert result["estimated_cache_logs"] == 2

    model_avg_log = await _get_log("bf-global-model-avg")
    assert model_avg_log.price_detail["cache_rate_basis"] == "model_avg"
    assert model_avg_log.price_detail["estimated_cached_tokens"] == 500

    fallback_log = await _get_log("bf-global-fallback")
    assert fallback_log.price_detail["cache_rate_basis"] == "global_avg"
    assert fallback_log.price_detail["cache_hit_rate"] == pytest.approx(0.5)
    assert fallback_log.price_detail["estimated_cached_tokens"] == 500
    # qwen3.7-plus 折扣价 1.6/0.32/6.4：(500*1.6 + 500*0.32 + 200*6.4)/1M
    assert float(fallback_log.cost) == pytest.approx(0.00224)


@pytest.mark.asyncio
async def test_backfill_dry_run_does_not_persist(client):
    await _clear_usage_logs()
    user_id, api_key_id = await _prepare_identity(client, "bf-user-b")
    await _insert_log(
        user_id,
        api_key_id,
        "bf-dry-run",
        input_tokens=1000,
        cached_input_tokens=500,
        output_tokens=200,
    )

    result = await backfill_usage_costs(dry_run=True)

    assert result["dry_run"] is True
    assert result["updated"] == 1
    assert result["total_estimated_cost"] == pytest.approx(0.0106)

    log = await _get_log("bf-dry-run")
    assert log.cost is None
    assert log.cost_source is None
    assert log.price_detail is None


@pytest.mark.asyncio
async def test_backfill_skips_ineligible_logs_and_is_idempotent(client):
    await _clear_usage_logs()
    user_id, api_key_id = await _prepare_identity(client, "bf-user-c")
    await _insert_log(user_id, api_key_id, "bf-no-tokens")
    await _insert_log(
        user_id,
        api_key_id,
        "bf-realtime",
        input_tokens=1000,
        cached_input_tokens=500,
        output_tokens=200,
        cost=Decimal("0.0106"),
        cost_source="realtime",
        price_detail={
            "input_price": 8.0,
            "cached_input_price": 2.0,
            "output_price": 28.0,
            "peak": False,
            "tier": "base",
        },
    )
    await _insert_log(
        user_id,
        api_key_id,
        "bf-eligible",
        input_tokens=1000,
        cached_input_tokens=500,
        output_tokens=200,
    )

    result = await backfill_usage_costs()

    assert result["scanned"] == 1
    assert result["updated"] == 1

    no_tokens = await _get_log("bf-no-tokens")
    assert no_tokens.cost is None
    realtime = await _get_log("bf-realtime")
    assert realtime.cost_source == "realtime"
    assert float(realtime.cost) == pytest.approx(0.0106)
    eligible = await _get_log("bf-eligible")
    assert eligible.cost_source == "estimated"

    second = await backfill_usage_costs()
    assert second["updated"] == 0


@pytest.mark.asyncio
async def test_backfill_uses_discounted_qwen_pricing_with_tier(client):
    await _clear_usage_logs()
    user_id, api_key_id = await _prepare_identity(client, "bf-user-d")

    await _insert_log(
        user_id,
        api_key_id,
        "bf-qwen-rate",
        model="qwen3.7-plus",
        provider="qwen",
        input_tokens=100000,
        cached_input_tokens=30000,
        output_tokens=50000,
    )
    await _insert_log(
        user_id,
        api_key_id,
        "bf-qwen-long",
        model="qwen3.7-plus",
        provider="qwen",
        input_tokens=300000,
        output_tokens=50000,
    )

    result = await backfill_usage_costs()

    assert result["model_cache_hit_rates"]["qwen3.7-plus"] == pytest.approx(0.3)

    long_log = await _get_log("bf-qwen-long")
    assert long_log.cost_source == "estimated"
    assert long_log.price_detail["tier"] == "high"
    assert long_log.price_detail["input_price"] == 4.8
    assert long_log.price_detail["cache_hit_rate"] == pytest.approx(0.3)
    assert long_log.price_detail["estimated_cached_tokens"] == 90000
    # 限时8折高价档：(210000*4.8 + 90000*0.96 + 50000*19.2)/1M
    expected = (210000 * 4.8 + 90000 * 0.96 + 50000 * 19.2) / 1_000_000
    assert float(long_log.cost) == pytest.approx(expected)


@pytest.mark.asyncio
async def test_backfill_admin_endpoint(client):
    await _clear_usage_logs()
    admin_token = (
        await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin-password"},
        )
    ).json()["access_token"]
    user_id, api_key_id = await _prepare_identity(client, "bf-user-e")
    await _insert_log(
        user_id,
        api_key_id,
        "bf-endpoint",
        input_tokens=1000,
        cached_input_tokens=500,
        output_tokens=200,
    )

    preview = await client.post(
        "/api/admin/usage-logs/backfill-costs?dry_run=true",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert preview.status_code == 200
    assert preview.json()["dry_run"] is True
    assert preview.json()["updated"] == 1

    executed = await client.post(
        "/api/admin/usage-logs/backfill-costs",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert executed.status_code == 200
    body = executed.json()
    assert body["dry_run"] is False
    assert body["updated"] == 1

    log = await _get_log("bf-endpoint")
    assert log.cost is not None
    assert log.cost_source == "estimated"

    user_token = (
        await client.post(
            "/api/auth/login",
            json={"username": "bf-user-e", "password": "developer-password1"},
        )
    ).json()["access_token"]
    forbidden = await client.post(
        "/api/admin/usage-logs/backfill-costs",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert forbidden.status_code in (401, 403)


@pytest.mark.asyncio
async def test_calibrate_estimated_cache_rates_uses_official_rate(client):
    await _clear_usage_logs()
    user_id, api_key_id = await _prepare_identity(client, "cal-user-a")

    beijing = timezone(timedelta(hours=8))
    day = datetime(2026, 8, 24, 10, 30, tzinfo=beijing)
    other_day = datetime(2026, 8, 25, 10, 30, tzinfo=beijing)

    await _insert_log(
        user_id,
        api_key_id,
        "cal-target-old",
        input_tokens=10000,
        output_tokens=500,
        request_time=day,
        cost=Decimal("1.0"),
        cost_source="estimated",
        price_detail={"estimated": True, "cache_rate_basis": "model_avg"},
    )
    await _insert_log(
        user_id,
        api_key_id,
        "cal-target-null-cost",
        input_tokens=20000,
        output_tokens=100,
        request_time=day,
    )
    await _insert_log(
        user_id,
        api_key_id,
        "cal-realtime",
        input_tokens=1000,
        cached_input_tokens=500,
        output_tokens=100,
        request_time=day,
        cost=Decimal("0.5"),
        cost_source="realtime",
        price_detail={"peak": False},
    )
    await _insert_log(
        user_id,
        api_key_id,
        "cal-other-day",
        input_tokens=10000,
        output_tokens=500,
        request_time=other_day,
        cost=Decimal("1.0"),
        cost_source="estimated",
        price_detail={"estimated": True},
    )

    result = await calibrate_estimated_cache_rates(
        calibrations=[{"model": "glm-5.3", "date": "2026-08-24", "hit_rate": 0.9}]
    )
    assert result["dry_run"] is False
    group = result["groups"][0]
    assert group["updated"] == 2
    assert group["scanned"] == 2
    assert group["input_tokens"] == 30000
    assert group["estimated_cached_tokens"] == 27000
    assert group["old_total_cost"] == pytest.approx(1.0)
    # (1000*8 + 9000*2 + 500*28 + 2000*8 + 18000*2 + 100*28)/1M
    assert group["new_total_cost"] == pytest.approx(0.0948)

    target_old = await _get_log("cal-target-old")
    # glm-5.3：(1000*8 + 9000*2 + 500*28)/1M
    assert float(target_old.cost) == pytest.approx(0.04)
    assert target_old.cost_source == "estimated"
    detail = target_old.price_detail
    assert detail["cache_rate_basis"] == "official_export"
    assert detail["cache_hit_rate"] == pytest.approx(0.9)
    assert detail["estimated_cached_tokens"] == 9000
    assert detail["estimated"] is True

    target_null = await _get_log("cal-target-null-cost")
    # glm-5.3：(2000*8 + 18000*2 + 100*28)/1M
    assert float(target_null.cost) == pytest.approx(0.0548)

    realtime = await _get_log("cal-realtime")
    assert realtime.cost == Decimal("0.5")
    assert realtime.cost_source == "realtime"
    assert realtime.price_detail == {"peak": False}

    other = await _get_log("cal-other-day")
    assert other.cost == Decimal("1.0")
    assert other.price_detail.get("cache_rate_basis") != "official_export"


@pytest.mark.asyncio
async def test_calibrate_estimated_cache_rates_dry_run_keeps_data(client):
    await _clear_usage_logs()
    user_id, api_key_id = await _prepare_identity(client, "cal-user-b")

    beijing = timezone(timedelta(hours=8))
    day = datetime(2026, 8, 24, 15, 0, tzinfo=beijing)
    await _insert_log(
        user_id,
        api_key_id,
        "cal-dry-run",
        input_tokens=10000,
        output_tokens=500,
        request_time=day,
        cost=Decimal("1.0"),
        cost_source="estimated",
    )

    result = await calibrate_estimated_cache_rates(
        calibrations=[{"model": "glm-5.3", "date": "2026-08-24", "hit_rate": 0.9}],
        dry_run=True,
    )
    assert result["dry_run"] is True
    group = result["groups"][0]
    assert group["updated"] == 1
    # glm-5.3：(1000*8 + 9000*2 + 500*28)/1M
    assert group["new_total_cost"] == pytest.approx(0.04)

    log = await _get_log("cal-dry-run")
    assert log.cost == Decimal("1.0")
    assert log.cost_source == "estimated"
