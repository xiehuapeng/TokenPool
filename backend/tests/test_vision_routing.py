import uuid

import pytest
from sqlalchemy import select

from app.database.session import SessionLocal
from app.models import ModelConfig, UsageLog
from app.providers.registry import provider_registry
from test_gateway import FakeProvider, login


@pytest.fixture
async def routing_client(client, monkeypatch):
    fake = FakeProvider()
    for code in ("deepseek", "glm", "qwen", "kimi"):
        monkeypatch.setitem(provider_registry._providers, code, fake)
    # Bootstrap tests intentionally preserve administrator-disabled models.
    # Establish this fixture's candidate and restore that shared state afterwards.
    async with SessionLocal() as session:
        vision = await session.scalar(select(ModelConfig).where(
            ModelConfig.public_model == "deepseek-v4-flash-vision-exp"))
        previous = (vision.enabled, vision.default_allowed, vision.sort_order)
        vision.enabled = True
        vision.default_allowed = True
        vision.sort_order = -1000
        await session.commit()
    token = await login(client, "admin", "admin-password")
    admin_headers = {"Authorization": f"Bearer {token}"}
    username = f"route-{uuid.uuid4().hex[:12]}"
    created = await client.post("/api/admin/users", headers=admin_headers,
                                json={"username": username, "password": "test-password123"})
    assert created.status_code == 201
    token = await login(client, username, "test-password123")
    user_headers = {"Authorization": f"Bearer {token}"}
    key = await client.post("/api/me/api-keys", headers=user_headers, json={"name": "routing"})
    assert key.status_code == 201
    # A conflicting Key preference must never override an explicit model.
    preference = await client.patch(f"/api/me/api-keys/{key.json()['id']}/preferred-model",
                                    headers=user_headers, json={"model": "deepseek-v4-flash"})
    assert preference.status_code == 200
    try:
        yield client, {"Authorization": f"Bearer {key.json()['key']}"}, admin_headers, fake
    finally:
        async with SessionLocal() as session:
            vision = await session.scalar(select(ModelConfig).where(
                ModelConfig.public_model == "deepseek-v4-flash-vision-exp"))
            vision.enabled, vision.default_allowed, vision.sort_order = previous
            await session.commit()


def image_messages(kind, historical):
    part = ({"type": "image_url", "image_url": {"url": "https://example.com/private-image.png"}}
            if kind == "image_url" else {"type": "image", "source": {"data": "private-image-data"}})
    messages = [{"role": "user", "content": [part]}]
    if historical:
        messages.extend([{"role": "assistant", "content": "seen"},
                         {"role": "user", "content": "Now answer in text"}])
    return messages


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("historical", [False, True])
@pytest.mark.parametrize("kind", ["image_url", "image"])
async def test_explicit_nonvision_rejects_before_any_upstream_call(routing_client, stream, historical, kind):
    client, headers, _, fake = routing_client
    response = await client.post("/v1/chat/completions", headers=headers, json={
        "model": "deepseek-v4-flash", "stream": stream,
        "messages": image_messages(kind, historical),
    })
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "vision_not_supported"
    assert response.json()["error"]["param"] == "model"
    assert "历史消息" in response.json()["error"]["message"]
    assert "team-coding" in response.json()["error"]["message"]
    assert response.headers["x-request-id"]
    assert fake.upstream_models == []
    assert fake.payloads == []
    assert "private-image" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("model,with_image,expected,reason", [
    ("team-coding", True, "deepseek-v4-flash-vision-exp", "vision_fallback"),
    ("team-coding", False, "deepseek-v4-flash", "preference"),
    ("deepseek-v4-flash", False, "deepseek-v4-flash", "explicit"),
    ("deepseek-v4-flash-vision-exp", True, "deepseek-v4-flash-vision-exp", "explicit"),
])
async def test_model_selection_headers_and_persistent_audit(routing_client, stream, model, with_image, expected, reason):
    client, headers, admin_headers, fake = routing_client
    messages = image_messages("image_url", True) if with_image else [{"role": "user", "content": "Hi"}]
    response = await client.post("/v1/chat/completions", headers=headers, json={
        "model": model, "stream": stream, "messages": messages,
    })
    assert response.status_code == 200, response.text
    assert fake.upstream_models == [expected]
    original = "deepseek-v4-flash" if model == "team-coding" else model
    assert response.headers["x-original-model"] == original
    assert response.headers["x-actual-model"] == expected
    assert response.headers["x-route-reason"] == reason
    if stream:
        assert "data: [DONE]" in response.text
        assert f'"model": "{model}"' in response.text
    else:
        assert response.json()["model"] == model
    request_id = response.headers["x-request-id"]
    async with SessionLocal() as session:
        log = await session.scalar(select(UsageLog).where(UsageLog.request_id == request_id))
        assert (log.requested_model, log.original_model, log.model, log.route_reason) == (model, original, expected, reason)
        assert log.status == "success"
    logs = await client.get("/api/admin/usage-logs", headers=admin_headers, params={"request_id": request_id})
    item = logs.json()["items"][0]
    assert item["original_model"] == original
    assert item["route_reason"] == reason
    assert "private-image" not in logs.text
