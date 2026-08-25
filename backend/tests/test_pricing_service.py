from datetime import datetime, timezone
from decimal import Decimal

from app.models import ModelPricing
from app.services.pricing_service import (
    compute_cost,
    is_peak_time,
    normalize_usage,
)


def make_pricing(**overrides) -> ModelPricing:
    values = {
        "input_price": Decimal("1.5"),
        "cached_input_price": Decimal("0.05"),
        "output_price": Decimal("4.5"),
    }
    values.update(overrides)
    return ModelPricing(**values)


# 2026-08-24 is a Monday; 2026-08-29/30 fall on the weekend.
MONDAY_PEAK_MORNING = datetime(2026, 8, 24, 2, 0, tzinfo=timezone.utc)
MONDAY_LUNCH = datetime(2026, 8, 24, 5, 0, tzinfo=timezone.utc)
MONDAY_PEAK_AFTERNOON = datetime(2026, 8, 24, 6, 0, tzinfo=timezone.utc)
MONDAY_AFTER_HOURS = datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc)
SATURDAY_MORNING = datetime(2026, 8, 29, 2, 0, tzinfo=timezone.utc)
SUNDAY_MORNING = datetime(2026, 8, 30, 2, 0, tzinfo=timezone.utc)


def test_normalize_usage_deepseek_format():
    tokens = normalize_usage(
        {
            "prompt_tokens": 1000,
            "completion_tokens": 200,
            "total_tokens": 1200,
            "prompt_cache_hit_tokens": 600,
            "prompt_tokens_details": {"cached_tokens": 600},
            "completion_tokens_details": {"reasoning_tokens": 120},
        }
    )
    assert tokens == {
        "prompt_tokens": 1000,
        "cached_input_tokens": 600,
        "completion_tokens": 200,
        "reasoning_tokens": 120,
        "total_tokens": 1200,
    }


def test_normalize_usage_takes_max_of_cache_candidates():
    tokens = normalize_usage(
        {
            "prompt_tokens": 1000,
            "completion_tokens": 10,
            "prompt_cache_hit_tokens": 500,
            "prompt_tokens_details": {"cached_tokens": 700},
        }
    )
    assert tokens["cached_input_tokens"] == 700


def test_normalize_usage_kimi_format():
    tokens = normalize_usage(
        {
            "prompt_tokens": 1000,
            "completion_tokens": 10,
            "total_tokens": 1010,
            "cached_tokens": 300,
        }
    )
    assert tokens["cached_input_tokens"] == 300


def test_normalize_usage_openai_style_details_only():
    tokens = normalize_usage(
        {
            "prompt_tokens": 1000,
            "completion_tokens": 10,
            "prompt_tokens_details": {"cached_tokens": 250},
        }
    )
    assert tokens["cached_input_tokens"] == 250
    assert tokens["reasoning_tokens"] is None


def test_normalize_usage_clamps_cached_to_prompt():
    tokens = normalize_usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 10,
            "cached_tokens": 500,
        }
    )
    assert tokens["cached_input_tokens"] == 100


def test_normalize_usage_without_cache_fields():
    tokens = normalize_usage(
        {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}
    )
    assert tokens["cached_input_tokens"] is None
    assert tokens["reasoning_tokens"] is None


def test_normalize_usage_coerces_numeric_strings():
    tokens = normalize_usage(
        {
            "prompt_tokens": "100",
            "completion_tokens": "10",
            "total_tokens": "110",
            "cached_tokens": "40",
            "completion_tokens_details": {"reasoning_tokens": "5"},
        }
    )
    assert tokens["prompt_tokens"] == 100
    assert tokens["cached_input_tokens"] == 40
    assert tokens["reasoning_tokens"] == 5


def test_normalize_usage_ignores_invalid_values():
    tokens = normalize_usage(
        {
            "prompt_tokens": True,
            "completion_tokens": None,
            "cached_tokens": "not-a-number",
            "prompt_tokens_details": "not-a-dict",
            "completion_tokens_details": ["not-a-dict"],
        }
    )
    assert tokens["prompt_tokens"] is None
    assert tokens["cached_input_tokens"] is None
    assert tokens["reasoning_tokens"] is None


def test_normalize_usage_returns_empty_for_missing_usage():
    assert normalize_usage(None) == {}
    assert normalize_usage("not-a-dict") == {}


def test_is_peak_time_weekday_ranges():
    assert is_peak_time(MONDAY_PEAK_MORNING) is True
    assert is_peak_time(MONDAY_LUNCH) is False
    assert is_peak_time(MONDAY_PEAK_AFTERNOON) is True
    assert is_peak_time(MONDAY_AFTER_HOURS) is False


def test_is_peak_time_weekend_is_off_peak():
    assert is_peak_time(SATURDAY_MORNING) is False
    assert is_peak_time(SUNDAY_MORNING) is False


def test_is_peak_time_treats_naive_datetime_as_utc():
    assert is_peak_time(datetime(2026, 8, 24, 2, 0)) is True
    assert is_peak_time(datetime(2026, 8, 24, 5, 0)) is False


def test_compute_cost_basic_without_cache():
    pricing = make_pricing()
    cost, detail = compute_cost(
        pricing,
        input_tokens=1_000_000,
        cached_tokens=0,
        output_tokens=1_000_000,
        request_time_utc=MONDAY_PEAK_MORNING,
    )
    assert cost == Decimal("6")
    assert detail == {
        "input_price": 1.5,
        "cached_input_price": 0.05,
        "output_price": 4.5,
        "peak": False,
        "tier": "base",
    }


def test_compute_cost_with_cache_discount():
    pricing = make_pricing()
    cost, _ = compute_cost(
        pricing,
        input_tokens=1_000_000,
        cached_tokens=800_000,
        output_tokens=1_000_000,
        request_time_utc=MONDAY_LUNCH,
    )
    # (200k * 1.5 + 800k * 0.05 + 1M * 4.5) / 1M = 0.3 + 0.04 + 4.5
    assert cost == Decimal("4.84")


def test_compute_cost_peak_pricing():
    pricing = make_pricing(
        peak_input_price=Decimal("3"),
        peak_cached_input_price=Decimal("0.1"),
        peak_output_price=Decimal("9"),
    )
    peak_cost, peak_detail = compute_cost(
        pricing,
        input_tokens=1_000_000,
        cached_tokens=800_000,
        output_tokens=1_000_000,
        request_time_utc=MONDAY_PEAK_MORNING,
    )
    assert peak_cost == Decimal("9.68")
    assert peak_detail["peak"] is True
    assert peak_detail["input_price"] == 3

    off_peak_cost, off_peak_detail = compute_cost(
        pricing,
        input_tokens=1_000_000,
        cached_tokens=800_000,
        output_tokens=1_000_000,
        request_time_utc=MONDAY_LUNCH,
    )
    assert off_peak_cost == Decimal("4.84")
    assert off_peak_detail["peak"] is False


def test_compute_cost_peak_prices_only_apply_on_weekdays():
    pricing = make_pricing(
        peak_input_price=Decimal("3"),
        peak_cached_input_price=Decimal("0.1"),
        peak_output_price=Decimal("9"),
    )
    cost, detail = compute_cost(
        pricing,
        input_tokens=1_000_000,
        cached_tokens=800_000,
        output_tokens=1_000_000,
        request_time_utc=SATURDAY_MORNING,
    )
    assert cost == Decimal("4.84")
    assert detail["peak"] is False


def test_compute_cost_tier_pricing():
    pricing = make_pricing(
        input_price=Decimal("6"),
        cached_input_price=Decimal("1.3"),
        output_price=Decimal("24"),
        tier_threshold_tokens=32768,
        high_input_price=Decimal("8"),
        high_cached_input_price=Decimal("2"),
        high_output_price=Decimal("28"),
    )
    high_cost, high_detail = compute_cost(
        pricing,
        input_tokens=40_000,
        cached_tokens=10_000,
        output_tokens=2_000,
        request_time_utc=MONDAY_LUNCH,
    )
    # (30k * 8 + 10k * 2 + 2k * 28) / 1M
    assert high_cost == Decimal("0.316")
    assert high_detail["tier"] == "high"

    base_cost, base_detail = compute_cost(
        pricing,
        input_tokens=32_768,
        cached_tokens=10_000,
        output_tokens=2_000,
        request_time_utc=MONDAY_LUNCH,
    )
    # (22768 * 6 + 10k * 1.3 + 2k * 24) / 1M
    assert base_cost == Decimal("0.197608")
    assert base_detail["tier"] == "base"


def test_compute_cost_tier_and_peak_combine():
    pricing = make_pricing(
        input_price=Decimal("6"),
        cached_input_price=Decimal("1.3"),
        output_price=Decimal("24"),
        tier_threshold_tokens=32768,
        high_input_price=Decimal("8"),
        high_cached_input_price=Decimal("2"),
        high_output_price=Decimal("28"),
        peak_input_price=Decimal("12"),
        peak_cached_input_price=Decimal("2.6"),
        peak_output_price=Decimal("48"),
    )
    cost, detail = compute_cost(
        pricing,
        input_tokens=40_000,
        cached_tokens=10_000,
        output_tokens=2_000,
        request_time_utc=MONDAY_PEAK_MORNING,
    )
    # (30k * 12 + 10k * 2.6 + 2k * 48) / 1M
    assert cost == Decimal("0.482")
    assert detail["peak"] is True
    assert detail["tier"] == "high"


def test_compute_cost_returns_none_without_tokens():
    pricing = make_pricing()
    assert (
        compute_cost(
            pricing,
            input_tokens=None,
            cached_tokens=None,
            output_tokens=None,
            request_time_utc=MONDAY_LUNCH,
        )
        is None
    )


def test_compute_cost_allows_output_only():
    pricing = make_pricing()
    cost, _ = compute_cost(
        pricing,
        input_tokens=None,
        cached_tokens=None,
        output_tokens=100_000,
        request_time_utc=MONDAY_LUNCH,
    )
    assert cost == Decimal("0.45")


def test_compute_cost_clamps_cached_to_input():
    pricing = make_pricing()
    cost, _ = compute_cost(
        pricing,
        input_tokens=1000,
        cached_tokens=5000,
        output_tokens=0,
        request_time_utc=MONDAY_LUNCH,
    )
    # Cached is clamped to 1000, so every input token bills at the cache price.
    assert cost == Decimal("0.05") * Decimal(1000) / Decimal(1_000_000)
