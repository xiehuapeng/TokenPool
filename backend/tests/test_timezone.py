from datetime import datetime, timezone

from app.utils.time import (
    beijing_day_start_utc,
    beijing_iso,
    to_beijing,
)


def test_beijing_serialization_uses_explicit_offset():
    utc_value = datetime(2026, 7, 24, 6, 30, 45, tzinfo=timezone.utc)

    assert beijing_iso(utc_value) == "2026-07-24T14:30:45+08:00"
    assert to_beijing(utc_value).utcoffset().total_seconds() == 8 * 3600


def test_beijing_today_starts_at_previous_utc_day_16():
    utc_value = datetime(2026, 7, 24, 3, 0, tzinfo=timezone.utc)

    assert beijing_day_start_utc(utc_value) == datetime(
        2026,
        7,
        23,
        16,
        0,
        tzinfo=timezone.utc,
    )
