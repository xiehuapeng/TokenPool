from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import ModelConfig, ModelPricing, ProviderConfig
from app.database.session import SessionLocal
from app.providers.base import ProviderModel
from app.services.bootstrap import SEED_PRICINGS
from app.services.pricing_service import compute_cost, is_peak_time
from app.services.cache_billing import request_cache_context
from app.services.model_sync import record_provider_model_discovery


def cost(model, *, inputs=1000, cached=0, outputs=0, details=None, context=None, date=None):
    return compute_cost(ModelPricing(**SEED_PRICINGS[model]), input_tokens=inputs,
        cached_tokens=cached, output_tokens=outputs,
        request_time_utc=date or datetime(2026, 9, 22, 2, tzinfo=timezone.utc),
        usage={"prompt_tokens_details": details or {}}, cache_context=context)


@pytest.mark.parametrize("day,peak", [("2026-09-25",False),("2026-10-01",False),
    ("2026-10-07",False),("2026-10-08",True),("2026-10-10",False),
    ("2026-09-20",False),("2026-02-23",False)])
def test_official_holidays_and_makeup_weekends(day, peak):
    assert is_peak_time(datetime.fromisoformat(day+"T02:00:00+00:00")) is peak


@pytest.mark.parametrize("inputs,tier", [(256000,"base"),(256001,"high"),(262144,"high")])
def test_decimal_k_boundary(inputs,tier):
    assert cost("qwen3.7-plus",inputs=inputs)[1]["tier"] == tier


def test_qwen_reproduced_undercharge_corrected():
    assert cost("qwen3.7-plus",inputs=260000,outputs=1000)[0] == Decimal("1.2672")


def test_unknown_calendar_is_not_claimed_exact():
    _,detail=cost("deepseek-flash",date=datetime(2027,1,1,2,tzinfo=timezone.utc))
    assert detail["estimated"] and not detail["holiday_calendar_verified"]


@pytest.mark.parametrize("ttl,expected", [("5m","0.02"),("1h","0.04")])
def test_kimi_disjoint_write_tokens_no_double_charge(ttl,expected):
    amount, detail=cost("kimi-k3",details={"cache_write_tokens":1000},context={"ttl":ttl})
    assert amount == Decimal(expected)
    assert detail["estimated"] # request TTL cannot prove the TTL of an existing prefix
    assert detail["cache"]["write_tokens"] == 1000


def test_kimi_cached_read_has_no_write_fee():
    assert cost("kimi-k3",cached=1000,details={"cache_write_tokens":0},context={"ttl":"1h"})[0] == Decimal("0.002")


def test_missing_write_usage_is_estimated():
    _,detail=cost("kimi-k3",context={"ttl":"1h"})
    assert "cache_write_usage_missing" in detail["cache"]["estimate_reasons"]


def test_qwen_explicit_creation_and_hit():
    amount,detail=cost("qwen3.8-max",cached=200,details={"cache_creation_input_tokens":600},context={"explicit":True})
    assert amount == Decimal("0.0116") # 200*12 + 600*15 + 200*1
    assert detail["cache"]["read_price"] == "1"
    assert cost("qwen3.8-max",cached=1000,details={"cache_creation_input_tokens":0},context={"explicit":True})[0] == Decimal("0.001")
    assert cost("qwen3.8-max",cached=1000)[0] == Decimal("0.0015")


@pytest.mark.parametrize("bad",[-10,2000,True,"1000"])
def test_invalid_write_usage_cannot_produce_negative_cost(bad):
    amount,detail=cost("qwen3.8-max",details={"cache_creation_input_tokens":bad},context={"explicit":True})
    assert amount >= 0 and detail["estimated"]


def test_context_contains_no_prompt_or_credentials():
    payload={"messages":[{"content":[{"text":"private text","cache_control":{"type":"ephemeral"}}]}],"api_key":"private"}
    assert request_cache_context("qwen",payload) == {"provider":"qwen","explicit":True,"ttl":"5m"}


@pytest.mark.asyncio
async def test_aliases_available_and_vision_without_automatic_enabling(client):
    async with SessionLocal() as session:
        provider=await session.scalar(select(ProviderConfig).where(ProviderConfig.code=="deepseek"))
        alias=await session.scalar(select(ModelConfig).where(ModelConfig.public_model=="deepseek-v4-flash"))
        assert alias.capabilities["vision"] is True
        await record_provider_model_discovery(session,provider,[ProviderModel("deepseek-flash"),ProviderModel("deepseek-v4-pro")])
        assert alias.capabilities["official_available"] is True
        assert alias.capabilities["official_listed"] is False
        assert alias.capabilities["official_alias_of"] == "deepseek-flash"
        await session.rollback()


@pytest.mark.asyncio
async def test_repair_is_idempotent_and_preserves_enabled_flags(client):
    from scripts.apply_pricing_20260922 import repair
    async with SessionLocal() as session:
        pricing = await session.scalar(select(ModelPricing).join(ModelConfig)
            .where(ModelConfig.public_model == "qwen3.7-plus"))
        pricing.tier_threshold_tokens = 262144
        pricing.cache_pricing = None
        before = {m.id: (m.enabled, m.default_allowed) for m in await session.scalars(select(ModelConfig))}
        changes = await repair(session)
        assert pricing.tier_threshold_tokens == 256000 and pricing.cache_pricing
        assert changes
        assert await repair(session) == []
        assert before == {m.id: (m.enabled, m.default_allowed) for m in await session.scalars(select(ModelConfig))}
        await session.rollback()


@pytest.mark.asyncio
async def test_repair_refuses_custom_price_without_commit(client):
    from scripts.apply_pricing_20260922 import repair
    async with SessionLocal() as session:
        pricing = await session.scalar(select(ModelPricing).join(ModelConfig)
            .where(ModelConfig.public_model == "kimi-k3"))
        pricing.cache_pricing = None
        pricing.input_price = Decimal("123")
        with pytest.raises(ValueError, match="Custom pricing"):
            await repair(session)
        await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_cache_snapshot_is_persisted_end_to_end(client, monkeypatch, stream):
    import test_gateway_cost as fixture
    from app.providers.registry import provider_registry
    telemetry={"prompt_tokens":1000,"completion_tokens":0,"total_tokens":1000,
               "prompt_tokens_details":{"cached_tokens":200,"cache_write_tokens":600}}
    monkeypatch.setattr(fixture, "GLM_USAGE", telemetry)
    monkeypatch.setitem(provider_registry._providers, "kimi", fixture.CostProvider())
    headers = await fixture._create_api_key(client, f"cache-e2e-{stream}")
    response = await client.post("/v1/chat/completions", headers=headers, json={
        "model":"kimi-k3", "stream":stream,
        "prompt_cache_options":{"mode":"implicit","ttl":"1h"},
        "messages":[{"role":"user","content":"private prompt not to be logged"}],
    })
    assert response.status_code == 200
    log=await fixture._get_usage_log(response.headers["x-request-id"])
    assert log.cost == Decimal("0.028400")
    assert log.cost_source == "estimated"
    assert log.price_detail["cache"]["write_tokens"] == 600
    assert log.price_detail["cache"]["requested_ttl"] == "1h"
    assert "private prompt" not in str(log.price_detail)
