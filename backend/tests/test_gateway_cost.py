from typing import AsyncIterator
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.database.session import SessionLocal
from app.models import UsageLog
from app.providers.base import (
    BaseProvider,
    ProviderResult,
    ProviderStream,
    StreamEvent,
)
from app.providers.registry import provider_registry
from app.services.billing_adjustments import post_user_day_adjustment
from app.utils.time import to_beijing

GLM_USAGE = {
    "prompt_tokens": 1000,
    "completion_tokens": 200,
    "total_tokens": 1200,
    "prompt_tokens_details": {"cached_tokens": 600},
    "completion_tokens_details": {"reasoning_tokens": 80},
}


class CostStream(ProviderStream):
    http_status = 200
    upstream_request_id = "upstream-cost-stream"

    async def events(self) -> AsyncIterator[StreamEvent]:
        yield StreamEvent(
            data={
                "id": "chatcmpl-cost-stream",
                "object": "chat.completion.chunk",
                "model": "upstream",
                "choices": [{"index": 0, "delta": {"content": "你好"}}],
            }
        )
        yield StreamEvent(
            data={
                "id": "chatcmpl-cost-stream",
                "object": "chat.completion.chunk",
                "model": "upstream",
                "choices": [],
                "usage": dict(GLM_USAGE),
            }
        )
        yield StreamEvent(done=True)

    async def close(self) -> None:
        pass


class CostProvider(BaseProvider):
    code = "glm"

    async def chat_completion(
        self, payload, *, upstream_model, timeout_seconds
    ) -> ProviderResult:
        return ProviderResult(
            data={
                "id": "chatcmpl-cost",
                "object": "chat.completion",
                "model": upstream_model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "你好"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": dict(GLM_USAGE),
            },
            http_status=200,
            upstream_request_id="upstream-cost",
        )

    async def open_chat_stream(
        self, payload, *, upstream_model, timeout_seconds
    ) -> ProviderStream:
        return CostStream()


class MissingUsageStream(CostStream):
    async def events(self) -> AsyncIterator[StreamEvent]:
        yield StreamEvent(data={"choices": [{"delta": {"content": "answer"},
                                              "finish_reason": "stop"}]})
        yield StreamEvent(done=True)


class MissingUsageProvider(CostProvider):
    async def open_chat_stream(self, payload, *, upstream_model, timeout_seconds):
        return MissingUsageStream()


async def _create_api_key(client, username: str) -> dict:
    admin_token = (
        await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin-password"},
        )
    ).json()["access_token"]
    created_user = await client.post(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"username": username, "password": "developer-password1"},
    )
    assert created_user.status_code in (201, 409)
    user_token = (
        await client.post(
            "/api/auth/login",
            json={"username": username, "password": "developer-password1"},
        )
    ).json()["access_token"]
    key = (
        await client.post(
            "/api/me/api-keys",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"name": f"cost-test-{username}"},
        )
    ).json()["key"]
    return {"Authorization": f"Bearer {key}"}


async def _get_usage_log(request_id: str) -> UsageLog:
    async with SessionLocal() as session:
        return await session.scalar(
            select(UsageLog).where(UsageLog.request_id == request_id)
        )


@pytest.mark.asyncio
async def test_non_stream_cost_is_persisted(client):
    original_provider = provider_registry._providers["glm"]
    provider_registry._providers["glm"] = CostProvider()
    try:
        api_headers = await _create_api_key(client, "cost-user")
        response = await client.post(
            "/v1/chat/completions",
            headers=api_headers,
            json={
                "model": "glm-5.3",
                "messages": [{"role": "user", "content": "你好"}],
            },
        )
        assert response.status_code == 200, response.text

        log = await _get_usage_log(response.headers["x-request-id"])
        assert log is not None
        assert log.input_tokens == 1000
        assert log.cached_input_tokens == 600
        assert log.reasoning_tokens == 80
        assert log.output_tokens == 200
        assert log.total_tokens == 1200
        # glm-5.3: (400 * 8 + 600 * 2 + 200 * 28) / 1M = 0.01 CNY
        assert log.cost is not None
        assert float(log.cost) == pytest.approx(0.01)
        assert log.cost_source == "realtime"
        assert log.upstream_status == "completed"
        assert log.billing_status == "usage_priced"
        assert log.price_detail == {
            "input_price": 8.0,
            "cached_input_price": 2.0,
            "output_price": 28.0,
            "peak": False,
            "tier": "base",
        }
    finally:
        provider_registry._providers["glm"] = original_provider


@pytest.mark.asyncio
async def test_stream_cost_is_persisted(client):
    original_provider = provider_registry._providers["glm"]
    provider_registry._providers["glm"] = CostProvider()
    try:
        api_headers = await _create_api_key(client, "cost-stream-user")
        async with client.stream(
            "POST",
            "/v1/chat/completions",
            headers=api_headers,
            json={
                "model": "glm-5.3",
                "messages": [{"role": "user", "content": "你好"}],
                "stream": True,
            },
        ) as stream:
            request_id = stream.headers["x-request-id"]
            async for _ in stream.aiter_text():
                pass

        log = await _get_usage_log(request_id)
        assert log is not None
        assert log.status == "success"
        assert log.cached_input_tokens == 600
        assert log.reasoning_tokens == 80
        assert log.cost is not None
        assert float(log.cost) == pytest.approx(0.01)
        assert log.cost_source == "realtime"
        assert log.upstream_status == "completed"
        assert log.billing_status == "usage_priced"
        assert log.stream_observation["usage_seen"] is True
        assert log.stream_observation["done_seen"] is True
        assert log.stream_observation["provider_response_id"] == "chatcmpl-cost-stream"
    finally:
        provider_registry._providers["glm"] = original_provider


@pytest.mark.asyncio
async def test_missing_stream_usage_enters_admin_reconciliation_queue(client):
    original_provider = provider_registry._providers["glm"]
    provider_registry._providers["glm"] = MissingUsageProvider()
    try:
        api_headers = await _create_api_key(client, "awaiting-bill-user")
        response = await client.post(
            "/v1/chat/completions", headers=api_headers,
            json={"model": "glm-5.3", "stream": True,
                  "messages": [{"role": "user", "content": "test"}]},
        )
        assert response.status_code == 200
        log = await _get_usage_log(response.headers["x-request-id"])
        assert log.status == "success"
        assert log.upstream_status == "completed"
        assert log.billing_status == "awaiting_bill"
        assert log.cost is None
        assert log.stream_observation["finish_reason_seen"] is True
        assert log.stream_observation["usage_seen"] is False
        assert log.stream_observation["done_seen"] is True
        admin_token = (await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin-password"},
        )).json()["access_token"]
        pending = await client.get(
            "/api/admin/usage-logs",
            headers={"Authorization": f"Bearer {admin_token}"},
            params={"billing_status": "awaiting_bill", "request_id": log.request_id},
        )
        assert pending.status_code == 200
        assert pending.json()["total"] == 1
        assert pending.json()["items"][0]["stream_observation"]["usage_seen"] is False
    finally:
        provider_registry._providers["glm"] = original_provider


@pytest.mark.asyncio
async def test_append_only_bill_adjustment_reconciles_all_admin_totals(client):
    original_provider = provider_registry._providers["glm"]
    provider_registry._providers["glm"] = CostProvider()
    try:
        api_headers = await _create_api_key(client, "ledger-user")
        response = await client.post(
            "/v1/chat/completions", headers=api_headers,
            json={"model": "glm-5.3", "messages": [{"role": "user", "content": "test"}]},
        )
        assert response.status_code == 200
        request_id = response.headers["x-request-id"]
        log = await _get_usage_log(request_id)
        admin_token = (await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin-password"},
        )).json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        async def stats_cost():
            result = await client.get(
                "/api/admin/stats", headers=admin_headers,
                params={"days": 0, "username": "ledger-user", "model": "glm-5.3"},
            )
            assert result.status_code == 200
            return Decimal(str(result.json()["summary"]["cost"]))

        before = await stats_cost()
        day = to_beijing(log.request_time).date()
        async with SessionLocal() as session:
            adjustment = await post_user_day_adjustment(
                session, source_key="test-ledger-001", request_id=request_id,
                amount=Decimal("0.123456"), source_day=day,
                source="test_provider_bill", evidence={"request_level_exact": False},
            )
            await session.commit()
            adjustment_id = adjustment.id
        assert await stats_cost() == before + Decimal("0.123456")
        async with SessionLocal() as session:
            same = await post_user_day_adjustment(
                session, source_key="test-ledger-001", request_id=request_id,
                amount=Decimal("0.123456"), source_day=day,
                source="test_provider_bill", evidence={"request_level_exact": False},
            )
            assert same.id == adjustment_id
            with pytest.raises(ValueError, match="different adjustment"):
                await post_user_day_adjustment(
                    session, source_key="test-ledger-001", request_id=request_id,
                    amount=Decimal("0.000001"), source_day=day,
                    source="test_provider_bill",
                )
        result = await client.get(
            "/api/admin/usage-logs", headers=admin_headers,
            params={"request_id": request_id, "days": 0},
        )
        row = result.json()["items"][0]
        assert row["cost"] == pytest.approx(float(log.cost + Decimal("0.123456")))
        assert row["request_cost"] == pytest.approx(float(log.cost))
        assert row["adjustment_cost"] == pytest.approx(0.123456)
        assert row["cost_source"] == "bill_adjustment"
        ledger = await client.get(
            "/api/admin/billing-adjustments", headers=admin_headers,
            params={"request_id": request_id},
        )
        assert ledger.status_code == 200
        assert ledger.json()["total"] == 1
        assert ledger.json()["items"][0]["amount"] == pytest.approx(0.123456)
        async with SessionLocal() as session:
            await post_user_day_adjustment(
                session, source_key="test-ledger-001-reversal", request_id=request_id,
                amount=Decimal("-0.123456"), source_day=day,
                source="test_provider_bill", reverses_id=adjustment_id,
            )
            await session.commit()
        assert await stats_cost() == before
        reversal_rows = await client.get(
            "/api/admin/billing-adjustments", headers=admin_headers,
            params={"request_id": request_id},
        )
        assert reversal_rows.json()["total"] == 2
        assert sum(item["amount"] for item in reversal_rows.json()["items"]) == pytest.approx(0)
    finally:
        provider_registry._providers["glm"] = original_provider
