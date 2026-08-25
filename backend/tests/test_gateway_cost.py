from typing import AsyncIterator

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
    finally:
        provider_registry._providers["glm"] = original_provider
