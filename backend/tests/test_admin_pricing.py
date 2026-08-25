from typing import AsyncIterator

import pytest
from sqlalchemy import delete, select

from app.database.session import SessionLocal
from app.models import ModelConfig, ModelPricing, ProviderConfig
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


class PricingStream(ProviderStream):
    http_status = 200
    upstream_request_id = "upstream-pricing-stream"

    async def events(self) -> AsyncIterator[StreamEvent]:
        yield StreamEvent(
            data={
                "id": "chatcmpl-pricing-stream",
                "object": "chat.completion.chunk",
                "model": "upstream",
                "choices": [{"index": 0, "delta": {"content": "你好"}}],
            }
        )
        yield StreamEvent(done=True)

    async def close(self) -> None:
        pass


class PricingProvider(BaseProvider):
    code = "glm"

    async def chat_completion(
        self, payload, *, upstream_model, timeout_seconds
    ) -> ProviderResult:
        return ProviderResult(
            data={
                "id": "chatcmpl-pricing",
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
            upstream_request_id="upstream-pricing",
        )

    async def open_chat_stream(
        self, payload, *, upstream_model, timeout_seconds
    ) -> ProviderStream:
        return PricingStream()


async def _admin_token(client) -> str:
    response = await client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin-password"}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def _get_models(client, admin_token: str) -> dict:
    response = await client.get(
        "/api/admin/models", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200, response.text
    return {item["public_model"]: item for item in response.json()}


async def _create_api_key(client, username: str) -> dict:
    admin_token = await _admin_token(client)
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
            json={"name": f"pricing-test-{username}"},
        )
    ).json()["key"]
    return {"Authorization": f"Bearer {key}"}


@pytest.mark.asyncio
async def test_models_list_includes_pricing(client):
    admin_token = await _admin_token(client)
    models = await _get_models(client, admin_token)

    glm = models["glm-5.3"]
    assert glm["pricing"] is not None
    assert glm["pricing"]["input_price"] == 8.0
    assert glm["pricing"]["cached_input_price"] == 2.0
    assert glm["pricing"]["output_price"] == 28.0
    assert glm["pricing"]["peak_input_price"] is None
    assert glm["pricing"]["currency"] == "CNY"
    assert glm["pricing"]["enabled"] is True

    glm45 = models["glm-4.5"]
    assert glm45["pricing"] is not None
    assert glm45["pricing"]["tier_threshold_tokens"] is not None


@pytest.mark.asyncio
async def test_pricing_update_affects_billing_and_stats(client):
    admin_token = await _admin_token(client)
    models = await _get_models(client, admin_token)
    glm_id = models["glm-5.3"]["id"]

    original_provider = provider_registry._providers["glm"]
    provider_registry._providers["glm"] = PricingProvider()
    try:
        patched = await client.patch(
            f"/api/admin/models/{glm_id}/pricing",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"input_price": 4},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["created"] is False
        assert patched.json()["pricing"]["input_price"] == 4.0

        api_headers = await _create_api_key(client, "pricing-billing-user")
        response = await client.post(
            "/v1/chat/completions",
            headers=api_headers,
            json={
                "model": "glm-5.3",
                "messages": [{"role": "user", "content": "你好"}],
            },
        )
        assert response.status_code == 200, response.text
        request_id = response.headers["x-request-id"]

        logs = await client.get(
            "/api/admin/usage-logs",
            headers={"Authorization": f"Bearer {admin_token}"},
            params={"request_id": request_id},
        )
        assert logs.status_code == 200, logs.text
        item = logs.json()["items"][0]
        assert item["input_tokens"] == 1000
        assert item["cached_input_tokens"] == 600
        assert item["reasoning_tokens"] == 80
        assert item["cost"] == pytest.approx(0.0084)
        assert item["cost_source"] == "realtime"
        assert item["price_detail"]["input_price"] == 4.0
        assert item["price_detail"]["tier"] == "base"

        stats = await client.get(
            "/api/admin/stats",
            headers={"Authorization": f"Bearer {admin_token}"},
            params={"username": "pricing-billing-user"},
        )
        assert stats.status_code == 200, stats.text
        body = stats.json()
        assert body["summary"]["cost"] == pytest.approx(0.0084)
        assert body["by_user"][0]["cost"] == pytest.approx(0.0084)
        model_row = next(r for r in body["by_model"] if r["model"] == "glm-5.3")
        assert model_row["cost"] == pytest.approx(0.0084)
        provider_row = next(r for r in body["by_provider"] if r["provider"] == "glm")
        assert provider_row["cost"] == pytest.approx(0.0084)
    finally:
        provider_registry._providers["glm"] = original_provider
        restored = await client.patch(
            f"/api/admin/models/{glm_id}/pricing",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"input_price": 8},
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["pricing"]["input_price"] == 8.0


@pytest.mark.asyncio
async def test_pricing_nullable_clear_and_rejection(client):
    admin_token = await _admin_token(client)
    models = await _get_models(client, admin_token)
    flash_id = models["deepseek-v4-flash"]["id"]
    assert models["deepseek-v4-flash"]["pricing"]["peak_input_price"] == 3.0

    try:
        cleared = await client.patch(
            f"/api/admin/models/{flash_id}/pricing",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"peak_input_price": None},
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["pricing"]["peak_input_price"] is None

        rejected = await client.patch(
            f"/api/admin/models/{flash_id}/pricing",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"input_price": None},
        )
        assert rejected.status_code == 400
        assert rejected.json()["error"]["code"] == "pricing_field_not_nullable"
    finally:
        await client.patch(
            f"/api/admin/models/{flash_id}/pricing",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"peak_input_price": 3},
        )


@pytest.mark.asyncio
async def test_pricing_create_for_unpriced_model(client):
    admin_token = await _admin_token(client)
    async with SessionLocal() as session:
        glm = await session.scalar(
            select(ProviderConfig).where(ProviderConfig.code == "glm")
        )
        model = ModelConfig(
            public_model="glm-pricing-create-test",
            provider_id=glm.id,
            upstream_model="glm-pricing-create-test",
            display_name="GLM Pricing Create Test",
            enabled=False,
            default_allowed=False,
        )
        session.add(model)
        await session.commit()
        await session.refresh(model)
        model_id = model.id

    try:
        models = await _get_models(client, admin_token)
        assert models["glm-pricing-create-test"]["pricing"] is None

        created = await client.patch(
            f"/api/admin/models/{model_id}/pricing",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "input_price": 1,
                "cached_input_price": 0.5,
                "output_price": 4,
                "note": "手工配置",
            },
        )
        assert created.status_code == 200, created.text
        assert created.json()["created"] is True
        pricing = created.json()["pricing"]
        assert pricing["input_price"] == 1.0
        assert pricing["cached_input_price"] == 0.5
        assert pricing["output_price"] == 4.0
        assert pricing["note"] == "手工配置"

        models_after = await _get_models(client, admin_token)
        assert models_after["glm-pricing-create-test"]["pricing"] is not None
        assert (
            models_after["glm-pricing-create-test"]["pricing"]["input_price"] == 1.0
        )
    finally:
        async with SessionLocal() as session:
            await session.execute(
                delete(ModelPricing).where(
                    ModelPricing.model_config_id == model_id
                )
            )
            await session.execute(
                delete(ModelConfig).where(ModelConfig.id == model_id)
            )
            await session.commit()
