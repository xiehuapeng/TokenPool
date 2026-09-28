"""Append-only bill adjustments and effective reporting cost."""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BillingAdjustment, UsageLog
from app.utils.time import to_beijing


def adjustment_amount_expression():
    """SQL expression for adjustments attached to the current UsageLog row."""
    return (
        select(func.coalesce(func.sum(BillingAdjustment.amount), 0))
        .where(BillingAdjustment.usage_log_id == UsageLog.id)
        .correlate(UsageLog)
        .scalar_subquery()
    )


def effective_cost_expression():
    return func.coalesce(UsageLog.cost, 0) + adjustment_amount_expression()


async def post_user_day_adjustment(
    session: AsyncSession,
    *,
    source_key: str,
    request_id: str,
    amount: Decimal,
    source_day: date,
    source: str,
    evidence: dict | None = None,
    reverses_id: int | None = None,
) -> BillingAdjustment:
    """Post one idempotent, non-request-exact correction in the caller's txn.

    A negative amount reverses an earlier adjustment without deleting it.
    Source keys must be deterministic per vendor record or import decision.
    """
    if not source_key or len(source_key) > 180 or not source or len(source) > 80:
        raise ValueError("Invalid adjustment source")
    if not amount.is_finite() or not amount or amount.as_tuple().exponent < -6:
        raise ValueError("Adjustment must be nonzero and at most six decimals")
    log = await session.scalar(select(UsageLog).where(UsageLog.request_id == request_id))
    if log is None:
        raise ValueError("Gateway request not found")
    if to_beijing(log.request_time).date() != source_day:
        raise ValueError("Adjustment day must match gateway request day")
    existing = await session.scalar(
        select(BillingAdjustment).where(BillingAdjustment.source_key == source_key)
    )
    if existing is not None:
        if (
            existing.usage_log_id != log.id or existing.amount != amount
            or existing.source_day != source_day or existing.source != source
            or existing.reverses_id != reverses_id or existing.evidence != evidence
        ):
            raise ValueError("Source key already used for a different adjustment")
        return existing
    if reverses_id is not None:
        prior = await session.get(BillingAdjustment, reverses_id)
        if (prior is None or prior.usage_log_id != log.id
                or prior.reverses_id is not None or amount != -prior.amount):
            raise ValueError("Invalid adjustment reversal")
    adjustment = BillingAdjustment(
        source_key=source_key,
        usage_log_id=log.id,
        amount=amount,
        source_day=source_day,
        source=source,
        granularity="user_day",
        evidence=evidence,
        reverses_id=reverses_id,
    )
    session.add(adjustment)
    await session.flush()
    if log.usage_source == "missing":
        net_adjustment = await session.scalar(
            select(func.coalesce(func.sum(BillingAdjustment.amount), 0))
            .where(BillingAdjustment.usage_log_id == log.id)
        )
        log.billing_status = "bill_allocated" if net_adjustment else "awaiting_bill"
    return adjustment
