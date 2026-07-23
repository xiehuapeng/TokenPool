from datetime import datetime, timezone

from sqlalchemy import update

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
