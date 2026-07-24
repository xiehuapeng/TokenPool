from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.database.session import SessionLocal
from app.models import UsageLog
from app.utils.redaction import redact_secrets


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def create_usage_log(
    *,
    request_id: str,
    user_id: int,
    api_key_id: int,
    model: str,
    provider: str,
    upstream_model: str,
    stream: bool,
) -> datetime:
    started = now_utc()
    async with SessionLocal() as session:
        session.add(
            UsageLog(
                request_id=request_id,
                user_id=user_id,
                api_key_id=api_key_id,
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
) -> None:
    finished = now_utc()
    usage = usage or {}
    values = {
        "response_time": finished,
        "latency_ms": int((finished - started).total_seconds() * 1000),
        "status": status,
        "http_status": http_status,
        "first_token_time": first_token_time,
        "input_tokens": usage.get("prompt_tokens"),
        "output_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "usage_source": "upstream" if usage else "missing",
        "error_code": error_code,
        "error_message": (
            redact_secrets(error_message)[:500] if error_message else None
        ),
        "upstream_request_id": upstream_request_id,
    }
    async with SessionLocal() as session:
        await session.execute(
            update(UsageLog)
            .where(UsageLog.request_id == request_id)
            .values(**values)
        )
        await session.commit()


async def recover_stale_usage_logs(max_age_minutes: int = 5) -> int:
    """Close pending calls left behind by a previous interrupted process.

    Normal client disconnects are finalized by the cancellation-safe stream
    cleanup. This startup recovery covers hard process termination, power loss,
    and records created by older gateway versions.
    """

    finished = now_utc()
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
