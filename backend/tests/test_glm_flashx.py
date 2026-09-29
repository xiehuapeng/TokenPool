from decimal import Decimal
import uuid

import pytest
from sqlalchemy import select

from app.database.session import SessionLocal
from app.models import ModelConfig, ModelPricing, UsageLog
from app.providers.registry import provider_registry
from app.services.bootstrap import seed_initial_data
from app.services.model_router import model_supports_vision, resolve_model
from app.services.pricing_service import compute_cost
from app.utils.time import utc_now
from test_gateway import FakeProvider, login


@pytest.mark.asyncio
async def test_flashx_is_visual_and_priced(client):
    async with SessionLocal() as session:
        route = await resolve_model(
            session, user_id=1, public_model="glm-5.3-flashx"
        )
        model = route.model
        pricing = await session.scalar(
            select(ModelPricing).where(ModelPricing.model_config_id == model.id)
        )
        assert model.upstream_model == "glm-5.3-flashx"
        assert model_supports_vision(model)
        assert model.capabilities["stream"] is True
        assert model.capabilities["tools"] is True
        assert model.capabilities["thinking"] is True
        assert pricing is not None
        assert pricing.input_price == Decimal("2")
        assert pricing.cached_input_price == Decimal("0.57")
        assert pricing.output_price == Decimal("7")
        computed = compute_cost(
            pricing,
            input_tokens=1_000_000,
            cached_tokens=100_000,
            output_tokens=100_000,
            request_time_utc=utc_now(),
        )
        assert computed is not None
        assert computed[0] == Decimal("2.557")


@pytest.mark.asyncio
async def test_flashx_reseed_repairs_capabilities_without_overwriting_admin_choice(client):
    async with SessionLocal() as session:
        model = await session.scalar(
            select(ModelConfig).where(ModelConfig.public_model == "glm-5.3-flashx")
        )
        model_id = model.id
        model.enabled = False
        model.default_allowed = False
        model.capabilities = {"official_available": True}
        await session.commit()

    await seed_initial_data()

    async with SessionLocal() as session:
        model = await session.get(ModelConfig, model_id)
        assert model is not None
        assert model.enabled is False
        assert model.default_allowed is False
        assert model_supports_vision(model)
        assert model.capabilities["official_available"] is True
        pricing = await session.scalar(
            select(ModelPricing).where(ModelPricing.model_config_id == model.id)
        )
        assert pricing is not None

        # 不影响共享测试数据库中后续用例的默认可用状态。
        model.enabled = True
        model.default_allowed = True
        await session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "public_model,provider_code,expected_upstream,with_image",
    [
        ("glm-5.3-flashx", "glm", "glm-5.3-flashx", True),
        ("qwen3.8-max", "qwen", "qwen3.8-max-0902", False),
    ],
)
async def test_public_model_keeps_client_id_and_prices_actual_route(
    client, monkeypatch, stream, public_model, provider_code, expected_upstream, with_image
):
    fake = FakeProvider()
    monkeypatch.setitem(provider_registry._providers, provider_code, fake)
    admin_token = await login(client, "admin", "admin-password")
    username = f"model-route-{uuid.uuid4().hex[:12]}"
    created = await client.post(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"username": username, "password": "test-password123"},
    )
    assert created.status_code == 201
    user_token = await login(client, username, "test-password123")
    key = await client.post(
        "/api/me/api-keys",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"name": "model-route"},
    )
    assert key.status_code == 201
    messages = (
        [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "https://example.com/test.png"}}]}]
        if with_image
        else [{"role": "user", "content": "hello"}]
    )
    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.json()['key']}"},
        json={"model": public_model, "messages": messages, "stream": stream},
    )
    assert response.status_code == 200, response.text
    assert fake.upstream_models == [expected_upstream]
    assert response.headers["x-actual-model"] == public_model
    if stream:
        assert f'"model": "{public_model}"' in response.text
        assert "data: [DONE]" in response.text
    else:
        assert response.json()["model"] == public_model

    async with SessionLocal() as session:
        log = await session.scalar(
            select(UsageLog).where(UsageLog.request_id == response.headers["x-request-id"])
        )
        assert log.model == public_model
        assert log.upstream_model == expected_upstream
        assert log.billing_status == "usage_priced"
        assert log.cost > 0
