from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo


BEIJING_TIMEZONE_NAME = "Asia/Shanghai"
BEIJING_TZ = ZoneInfo(BEIJING_TIMEZONE_NAME)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_beijing(value: datetime) -> datetime:
    return to_utc(value).astimezone(BEIJING_TZ)


def beijing_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return to_beijing(value).isoformat(timespec="seconds")


def beijing_day_start_utc(reference: datetime | None = None) -> datetime:
    local_reference = to_beijing(reference or utc_now())
    local_start = datetime.combine(
        local_reference.date(),
        time.min,
        tzinfo=BEIJING_TZ,
    )
    return local_start.astimezone(timezone.utc)
