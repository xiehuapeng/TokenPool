import csv
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from pathlib import Path

from sqlalchemy import select

from app.database.session import SessionLocal
from app.models import UsageLog


BEIJING_TZ = timezone(timedelta(hours=8))
MONEY_QUANT = Decimal("0.000001")
TOKEN_TYPES = ("input_token_cache", "input_token", "output_token")
VALUE_PATTERN = re.compile(r'"value"\s*:\s*"([^"]+)"')


@dataclass
class AliyunDailyBill:
    billing_date: date
    model: str
    uncached_input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    uncached_input_price: Decimal = Decimal("0")
    cached_input_price: Decimal = Decimal("0")
    output_price: Decimal = Decimal("0")
    uncached_input_cost: Decimal = Decimal("0")
    cached_input_cost: Decimal = Decimal("0")
    output_cost: Decimal = Decimal("0")

    @property
    def input_tokens(self) -> int:
        return self.uncached_input_tokens + self.cached_input_tokens

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cache_hit_rate(self) -> Decimal:
        if not self.input_tokens:
            return Decimal("0")
        return Decimal(self.cached_input_tokens) / Decimal(self.input_tokens)

    @property
    def catalog_cost(self) -> Decimal:
        return (
            self.uncached_input_cost + self.cached_input_cost + self.output_cost
        )


def _tokens_from_thousands(value: str) -> int:
    tokens = Decimal(value.strip()) * Decimal(1000)
    return int(tokens.to_integral_value(rounding=ROUND_HALF_UP))


def _extract_model_and_type(selector: str) -> tuple[str, str] | None:
    values = VALUE_PATTERN.findall(selector)
    token_type = next((value for value in values if value in TOKEN_TYPES), None)
    model = next((value for value in values if value.startswith("qwen")), None)
    if token_type and model:
        return model, token_type
    return None


def parse_aliyun_daily_bill(path: str | Path) -> list[AliyunDailyBill]:
    """Parse an Alibaba Cloud consumedetailbillv2 day-summary CSV.

    Alibaba exports quantity in thousands of tokens and unit price per thousand
    tokens.  The stable selector values are used instead of the localized column
    names so the parser also works with exports whose Chinese headers were
    transcoded by the download client.
    """

    groups: dict[tuple[date, str], AliyunDailyBill] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as file:
        rows = csv.reader(file)
        next(rows, None)
        for line_number, row in enumerate(rows, start=2):
            if len(row) < 32:
                raise ValueError(f"Aliyun bill row {line_number} has too few columns")
            parsed = _extract_model_and_type(row[17])
            if parsed is None:
                continue
            model, token_type = parsed
            try:
                billing_date = datetime.strptime(row[8].strip(), "%Y%m%d").date()
                tokens = _tokens_from_thousands(row[26])
                price = Decimal(row[28].strip()) * Decimal(1000)
                cost = Decimal(row[31].strip())
            except (ValueError, ArithmeticError) as exc:
                raise ValueError(
                    f"Invalid Aliyun bill values at row {line_number}"
                ) from exc

            item = groups.setdefault(
                (billing_date, model),
                AliyunDailyBill(billing_date=billing_date, model=model),
            )
            if token_type == "input_token_cache":
                item.cached_input_tokens += tokens
                item.cached_input_price = price
                item.cached_input_cost += cost
            elif token_type == "input_token":
                item.uncached_input_tokens += tokens
                item.uncached_input_price = price
                item.uncached_input_cost += cost
            else:
                item.output_tokens += tokens
                item.output_price = price
                item.output_cost += cost

    if not groups:
        raise ValueError("No Qwen token billing rows found in Aliyun daily bill")
    return [groups[key] for key in sorted(groups)]


def _beijing_date(value: datetime) -> date:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(BEIJING_TZ).date()


def _allocate_integer(total: int, weights: list[int]) -> list[int]:
    if total <= 0 or not weights or sum(weights) <= 0:
        return [0 for _ in weights]
    weight_total = sum(weights)
    raw = [Decimal(total) * Decimal(weight) / Decimal(weight_total) for weight in weights]
    allocated = [int(value.to_integral_value(rounding=ROUND_FLOOR)) for value in raw]
    remaining = total - sum(allocated)
    order = sorted(
        range(len(raw)), key=lambda index: raw[index] - allocated[index], reverse=True
    )
    for index in order[:remaining]:
        allocated[index] += 1
    return allocated


def _allocate_money(total: Decimal, weights: list[int]) -> list[Decimal]:
    if not weights:
        return []
    weight_total = sum(weights)
    if total == 0 or weight_total <= 0:
        return [Decimal("0") for _ in weights]
    allocated = [
        (total * Decimal(weight) / Decimal(weight_total)).quantize(MONEY_QUANT)
        for weight in weights
    ]
    allocated[-1] += total.quantize(MONEY_QUANT) - sum(allocated)
    return allocated


async def reconcile_aliyun_daily_bill(
    bills: list[AliyunDailyBill], *, dry_run: bool = True
) -> dict:
    """Allocate actual daily catalog charges to historical gateway calls.

    Raw input/output token fields are never changed.  Only calls without actual
    cache-token telemetry and without realtime costs are eligible.  Daily input
    and output catalog charges are allocated independently in proportion to each
    call's corresponding token count, so the reconciled daily total equals the
    provider bill even when gateway and provider token scopes differ slightly.
    """

    async with SessionLocal() as session:
        models = sorted({bill.model for bill in bills})
        logs = list(
            await session.scalars(
                select(UsageLog).where(
                    UsageLog.provider == "qwen",
                    UsageLog.model.in_(models),
                    UsageLog.status == "success",
                    UsageLog.cached_input_tokens.is_(None),
                )
            )
        )

        by_key: dict[tuple[date, str], list[UsageLog]] = {}
        for log in logs:
            if log.request_time is None or log.cost_source == "realtime":
                continue
            by_key.setdefault((_beijing_date(log.request_time), log.model), []).append(log)

        updated = 0
        before_cost = Decimal("0")
        after_cost = Decimal("0")
        bill_cost = Decimal("0")
        reports = []
        for bill in bills:
            matched = sorted(
                by_key.get((bill.billing_date, bill.model), []), key=lambda log: log.id
            )
            gateway_input = sum(log.input_tokens or 0 for log in matched)
            gateway_output = sum(log.output_tokens or 0 for log in matched)
            gateway_total = gateway_input + gateway_output
            input_weights = [log.input_tokens or 0 for log in matched]
            output_weights = [log.output_tokens or 0 for log in matched]

            target_cached = int(
                (Decimal(gateway_input) * bill.cache_hit_rate).to_integral_value(
                    rounding=ROUND_HALF_UP
                )
            )
            cached_allocations = _allocate_integer(target_cached, input_weights)
            input_cost_allocations = _allocate_money(
                bill.uncached_input_cost + bill.cached_input_cost, input_weights
            )
            output_cost_allocations = _allocate_money(
                bill.output_cost, output_weights
            )

            group_before = sum((log.cost or Decimal("0")) for log in matched)
            group_after = Decimal("0")
            for index, log in enumerate(matched):
                cost = input_cost_allocations[index] + output_cost_allocations[index]
                log.cost = cost
                log.cost_source = "bill_allocated"
                log.price_detail = {
                    "input_price": float(bill.uncached_input_price),
                    "cached_input_price": float(bill.cached_input_price),
                    "output_price": float(bill.output_price),
                    "peak": False,
                    "tier": "base",
                    "estimated": True,
                    "cache_hit_rate": round(float(bill.cache_hit_rate), 6),
                    "cache_rate_basis": "provider_bill_day",
                    "estimated_cached_tokens": cached_allocations[index],
                    "bill_allocated": True,
                    "bill_date": bill.billing_date.isoformat(),
                    "bill_gateway_input_difference": gateway_input - bill.input_tokens,
                    "bill_gateway_output_difference": gateway_output - bill.output_tokens,
                }
                group_after += cost
                updated += 1

            before_cost += group_before
            after_cost += group_after
            bill_cost += bill.catalog_cost
            reports.append(
                {
                    "date": bill.billing_date.isoformat(),
                    "model": bill.model,
                    "requests": len(matched),
                    "gateway_input_tokens": gateway_input,
                    "bill_input_tokens": bill.input_tokens,
                    "input_difference": gateway_input - bill.input_tokens,
                    "gateway_output_tokens": gateway_output,
                    "bill_output_tokens": bill.output_tokens,
                    "output_difference": gateway_output - bill.output_tokens,
                    "gateway_total_tokens": gateway_total,
                    "bill_total_tokens": bill.total_tokens,
                    "total_difference": gateway_total - bill.total_tokens,
                    "cache_hit_rate": round(float(bill.cache_hit_rate), 6),
                    "before_cost": float(group_before),
                    "after_cost": float(group_after),
                    "bill_catalog_cost": float(bill.catalog_cost),
                }
            )

        if dry_run:
            await session.rollback()
        else:
            await session.commit()

        return {
            "dry_run": dry_run,
            "updated": updated,
            "before_cost": float(before_cost),
            "after_cost": float(after_cost),
            "bill_catalog_cost": float(bill_cost),
            "days": reports,
        }
