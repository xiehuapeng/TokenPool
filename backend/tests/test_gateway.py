from typing import AsyncIterator

import pytest

from app.providers.base import (
    BaseProvider,
    ProviderResult,
    ProviderStream,
    StreamEvent,
)
from app.providers.registry import provider_registry


class FakeStream(ProviderStream):
    http_status = 200
    upstream_request_id = "upstream-stream-1"

    async def events(self) -> AsyncIterator[StreamEvent]:
        yield StreamEvent(
            data={
                "id": "chatcmpl-stream",
                "object": "chat.completion.chunk",
                "model": "upstream",
                "choices": [{"index": 0, "delta": {"content": "你好"}}],
            }
        )
        yield StreamEvent(
            data={
                "id": "chatcmpl-stream",
                "object": "chat.completion.chunk",
                "model": "upstream",
                "choices": [],
                "usage": {
                    "prompt_tokens": 4,
                    "completion_tokens": 2,
                    "total_tokens": 6,
                },
            }
        )
        yield StreamEvent(done=True)

    async def close(self) -> None:
        pass


class FakeProvider(BaseProvider):
    code = "deepseek"

    def __init__(self) -> None:
        self.upstream_models: list[str] = []

    async def chat_completion(
        self, payload, *, upstream_model, timeout_seconds
    ) -> ProviderResult:
        self.upstream_models.append(upstream_model)
        return ProviderResult(
            data={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "model": upstream_model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "你好"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 4,
                    "completion_tokens": 2,
                    "total_tokens": 6,
                },
            },
            http_status=200,
            upstream_request_id="upstream-1",
        )

    async def open_chat_stream(
        self, payload, *, upstream_model, timeout_seconds
    ) -> ProviderStream:
        self.upstream_models.append(upstream_model)
        return FakeStream()


async def login(client, username: str, password: str) -> str:
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.mark.asyncio
async def test_health_and_user_key_flow(client):
    admin_token = await login(client, "admin", "admin-password")
    headers = {"Authorization": f"Bearer {admin_token}"}

    create_user = await client.post(
        "/api/admin/users",
        headers=headers,
        json={"username": "developer", "password": "developer-password1"},
    )
    assert create_user.status_code in (201, 409)

    user_token = await login(client, "developer", "developer-password1")
    user_headers = {"Authorization": f"Bearer {user_token}"}
    created = await client.post(
        "/api/me/api-keys", headers=user_headers, json={"name": "test"}
    )
    assert created.status_code == 201
    assert created.json()["created_at"].endswith("+08:00")
    assert created.json()["can_reveal"] is True
    full_key = created.json()["key"]
    assert full_key.startswith("sk-team-")

    revealed = await client.get(
        f"/api/me/api-keys/{created.json()['id']}/secret",
        headers=user_headers,
    )
    assert revealed.status_code == 200
    assert revealed.json()["value"] == full_key
    assert revealed.headers["cache-control"] == "no-store"

    reveal_as_other_user = await client.get(
        f"/api/me/api-keys/{created.json()['id']}/secret",
        headers=headers,
    )
    assert reveal_as_other_user.status_code == 404

    listed = await client.get("/api/me/api-keys", headers=user_headers)
    assert listed.status_code == 200
    assert "key" not in listed.json()[0]
    assert listed.json()[0]["key_prefix"].endswith("...")
    assert listed.json()[0]["can_reveal"] is True

    revoked = await client.delete(
        f"/api/me/api-keys/{created.json()['id']}",
        headers=user_headers,
    )
    assert revoked.status_code == 204

    reveal_after_revoke = await client.get(
        f"/api/me/api-keys/{created.json()['id']}/secret",
        headers=user_headers,
    )
    assert reveal_after_revoke.status_code == 404

    listed_after_revoke = await client.get(
        "/api/me/api-keys", headers=user_headers
    )
    assert listed_after_revoke.status_code == 200
    assert listed_after_revoke.json() == []

    revoked_key_access = await client.get(
        "/v1/models",
        headers={"Authorization": f"Bearer {full_key}"},
    )
    assert revoked_key_access.status_code == 401

    audit_keys = await client.get("/api/admin/api-keys", headers=headers)
    assert audit_keys.status_code == 200
    audit_key = next(
        item for item in audit_keys.json() if item["id"] == created.json()["id"]
    )
    assert audit_key["status"] == "revoked"

    reactivate = await client.patch(
        f"/api/admin/api-keys/{created.json()['id']}/status",
        headers=headers,
        json={"status": "active"},
    )
    assert reactivate.status_code == 422

    health = await client.get("/health")
    assert health.status_code == 200
    assert health.json()["providers"]["deepseek"] == "available"


@pytest.mark.asyncio
async def test_openai_compatible_non_stream_and_stream(client):
    original_provider = provider_registry._providers["deepseek"]
    fake_provider = FakeProvider()
    provider_registry._providers["deepseek"] = fake_provider
    try:
        admin_token = await login(client, "admin", "admin-password")
        create_user = await client.post(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"username": "chat-user", "password": "developer-password1"},
        )
        assert create_user.status_code in (201, 409)
        user_token = await login(client, "chat-user", "developer-password1")
        user_headers = {"Authorization": f"Bearer {user_token}"}
        key = (
            await client.post(
                "/api/me/api-keys",
                headers=user_headers,
                json={"name": "openai-test"},
            )
        ).json()["key"]
        api_headers = {"Authorization": f"Bearer {key}"}

        models = await client.get("/v1/models", headers=api_headers)
        assert models.status_code == 200
        assert [item["id"] for item in models.json()["data"]] == ["team-coding"]

        preference = await client.get(
            "/api/me/model-preference", headers=user_headers
        )
        assert preference.status_code == 200
        assert preference.json() == {
            "gateway_model": "team-coding",
            "selected_model": "deepseek-chat",
            "selection_source": "default",
        }
        updated_preference = await client.put(
            "/api/me/model-preference",
            headers=user_headers,
            json={"model": "deepseek-chat"},
        )
        assert updated_preference.status_code == 200
        assert updated_preference.json()["selection_source"] == "user"

        response = await client.post(
            "/v1/chat/completions",
            headers=api_headers,
            json={
                "model": "team-coding",
                "messages": [{"role": "user", "content": "你好"}],
            },
        )
        assert response.status_code == 200
        assert response.headers["x-request-id"].startswith("req_")
        assert response.json()["model"] == "team-coding"
        assert response.json()["usage"]["total_tokens"] == 6
        assert fake_provider.upstream_models[-1] == "deepseek-chat"

        async with client.stream(
            "POST",
            "/v1/chat/completions",
            headers=api_headers,
            json={
                "model": "team-coding",
                "messages": [{"role": "user", "content": "你好"}],
                "stream": True,
            },
        ) as stream:
            assert stream.headers["x-request-id"].startswith("req_")
            text = "".join([chunk async for chunk in stream.aiter_text()])
        assert '"content": "你好"' in text
        assert '"model": "team-coding"' in text
        assert "data: [DONE]" in text
        assert fake_provider.upstream_models[-1] == "deepseek-chat"

        usage = await client.get("/api/me/usage/summary", headers=user_headers)
        assert usage.status_code == 200
        assert usage.json()["today_tokens"] == 12

        admin_logs = await client.get(
            "/api/admin/usage-logs",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert admin_logs.status_code == 200
        assert admin_logs.json()["items"][0]["request_time"].endswith("+08:00")
        assert admin_logs.json()["items"][0]["requested_model"] == "team-coding"
        assert admin_logs.json()["items"][0]["model"] == "deepseek-chat"

        explicit_model = await client.post(
            "/v1/chat/completions",
            headers=api_headers,
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": "compatibility"}],
            },
        )
        assert explicit_model.status_code == 200
        assert explicit_model.json()["model"] == "deepseek-chat"
    finally:
        provider_registry._providers["deepseek"] = original_provider
