import csv
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from app.database.session import SessionLocal
from app.models import ApiKey, UsageLog, User
from app.services.billing_reconciliation import (
    AliyunDailyBill,
    parse_aliyun_daily_bill,
    reconcile_aliyun_daily_bill,
)


def _bill_row(
    day: str, token_type: str, quantity_thousands: str, price_per_thousand: str, cost: str
) -> list[str]:
    row = [""] * 40
    row[8] = day
    row[17] = (
        f'[{ {"name": "Token", "value": token_type}!s},'
        f'{{"name":"model","value":"qwen3.8-max"}}]'
    ).replace("'", '"')
    row[26] = quantity_thousands
    row[28] = price_per_thousand
    row[31] = cost
    return row


def test_parse_aliyun_daily_bill(tmp_path):
    path = tmp_path / "aliyun-daysummary.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([f"column-{index}" for index in range(40)])
        writer.writerow(_bill_row("20260823", "input_token", "516.374", "0.012", "6.196488"))
        writer.writerow(_bill_row("20260823", "input_token_cache", "10627.456", "0.0015", "15.941184"))
        writer.writerow(_bill_row("20260823", "output_token", "112.055", "0.036", "4.03398"))

    bills = parse_aliyun_daily_bill(path)

    assert len(bills) == 1
    bill = bills[0]
    assert bill.model == "qwen3.8-max"
    assert bill.uncached_input_tokens == 516_374
    assert bill.cached_input_tokens == 10_627_456
    assert bill.output_tokens == 112_055
    assert bill.total_tokens == 11_255_885
    assert bill.uncached_input_price == Decimal("12")
    assert bill.cached_input_price == Decimal("1.5")
    assert bill.output_price == Decimal("36")
    assert bill.catalog_cost == Decimal("26.171652")


async def _identity(client) -> tuple[int, int]:
    admin_token = (
        await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin-password"},
        )
    ).json()["access_token"]
    await client.post(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"username": "bill-user", "password": "developer-password1"},
    )
    user_token = (
        await client.post(
            "/api/auth/login",
            json={"username": "bill-user", "password": "developer-password1"},
        )
    ).json()["access_token"]
    await client.post(
        "/api/me/api-keys",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"name": "bill-key"},
    )
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.username == "bill-user"))
        key = (
            await session.scalars(select(ApiKey).where(ApiKey.user_id == user.id))
        ).first()
        return user.id, key.id


@pytest.mark.asyncio
async def test_reconcile_allocates_exact_daily_bill_cost_without_overwriting_raw_cache(
    client,
):
    async with SessionLocal() as session:
        await session.execute(delete(UsageLog))
        await session.commit()
    user_id, api_key_id = await _identity(client)
    async with SessionLocal() as session:
        for index, (input_tokens, output_tokens) in enumerate(((750, 100), (250, 300))):
            session.add(
                UsageLog(
                    request_id=f"bill-log-{index}",
                    user_id=user_id,
                    api_key_id=api_key_id,
                    requested_model="team-coding",
                    model="qwen3.8-max",
                    provider="qwen",
                    upstream_model="qwen3.8-max",
                    stream=True,
                    request_time=datetime(2026, 8, 23, 1, index, tzinfo=timezone.utc),
                    status="success",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens,
                    usage_source="upstream",
                    cost=Decimal("1"),
                    cost_source="estimated",
                    price_detail={"estimated": True},
                )
            )
        await session.commit()

    bill = AliyunDailyBill(
        billing_date=datetime(2026, 8, 23).date(),
        model="qwen3.8-max",
        uncached_input_tokens=100,
        cached_input_tokens=900,
        output_tokens=400,
        uncached_input_price=Decimal("12"),
        cached_input_price=Decimal("1.5"),
        output_price=Decimal("36"),
        uncached_input_cost=Decimal("0.0012"),
        cached_input_cost=Decimal("0.00135"),
        output_cost=Decimal("0.0144"),
    )

    preview = await reconcile_aliyun_daily_bill([bill])
    assert preview["dry_run"] is True
    assert preview["updated"] == 2
    assert preview["after_cost"] == pytest.approx(0.01695)

    applied = await reconcile_aliyun_daily_bill([bill], dry_run=False)
    assert applied["updated"] == 2
    assert applied["after_cost"] == pytest.approx(0.01695)

    async with SessionLocal() as session:
        logs = list(
            await session.scalars(
                select(UsageLog).where(UsageLog.request_id.like("bill-log-%"))
            )
        )
    assert sum(log.cost for log in logs) == Decimal("0.016950")
    assert all(log.cost_source == "bill_allocated" for log in logs)
    assert all(log.cached_input_tokens is None for log in logs)
    assert sum(log.price_detail["estimated_cached_tokens"] for log in logs) == 900
    assert all(
        log.price_detail["cache_rate_basis"] == "provider_bill_day"
        for log in logs
    )


@pytest.mark.asyncio
async def test_reconcile_does_not_overwrite_realtime_cost(client):
    async with SessionLocal() as session:
        await session.execute(delete(UsageLog))
        await session.commit()
    user_id, api_key_id = await _identity(client)
    async with SessionLocal() as session:
        session.add(
            UsageLog(
                request_id="bill-realtime",
                user_id=user_id,
                api_key_id=api_key_id,
                requested_model="team-coding",
                model="qwen3.8-max",
                provider="qwen",
                upstream_model="qwen3.8-max",
                stream=False,
                request_time=datetime(2026, 8, 23, 1, 0, tzinfo=timezone.utc),
                status="success",
                input_tokens=100,
                cached_input_tokens=90,
                output_tokens=10,
                total_tokens=110,
                usage_source="upstream",
                cost=Decimal("0.0001"),
                cost_source="realtime",
                price_detail={"estimated": False},
            )
        )
        await session.commit()

    bill = AliyunDailyBill(
        billing_date=datetime(2026, 8, 23).date(),
        model="qwen3.8-max",
        cached_input_tokens=90,
        uncached_input_tokens=10,
        output_tokens=10,
    )
    result = await reconcile_aliyun_daily_bill([bill], dry_run=False)
    assert result["updated"] == 0
    async with SessionLocal() as session:
        log = await session.scalar(
            select(UsageLog).where(UsageLog.request_id == "bill-realtime")
        )
    assert log.cost_source == "realtime"
    assert log.cost == Decimal("0.000100")
