from typing import AsyncIterator

import pytest
from sqlalchemy import select

from app.database.session import SessionLocal
from app.models import ModelConfig, ProviderConfig
from app.providers.base import (
    BaseProvider,
    ProviderResult,
    ProviderStream,
    StreamEvent,
)
from app.providers.registry import provider_registry
from app.services.model_router import (
    ensure_reasoning_content,
    model_requires_reasoning_content,
)


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
        self.payloads: list[dict] = []

    async def chat_completion(
        self, payload, *, upstream_model, timeout_seconds
    ) -> ProviderResult:
        self.upstream_models.append(upstream_model)
        self.payloads.append(payload)
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
        self.payloads.append(payload)
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
            "selected_model": "deepseek-v4-flash",
            "selection_source": "default",
        }
        updated_preference = await client.put(
            "/api/me/model-preference",
            headers=user_headers,
            json={"model": "deepseek-v4-flash"},
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
        assert fake_provider.upstream_models[-1] == "deepseek-v4-flash"

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
        assert fake_provider.upstream_models[-1] == "deepseek-v4-flash"

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
        assert admin_logs.json()["items"][0]["model"] == "deepseek-v4-flash"
        assert admin_logs.json()["items"][0]["input_tokens"] == 4
        assert admin_logs.json()["items"][0]["output_tokens"] == 2
        assert admin_logs.json()["items"][0]["usage_source"] == "upstream"

        filtered_stats = await client.get(
            "/api/admin/stats",
            headers={"Authorization": f"Bearer {admin_token}"},
            params={
                "days": 30,
                "username": "chat-user",
                "model": "deepseek-v4-flash",
                "provider": "deepseek",
            },
        )
        assert filtered_stats.status_code == 200
        stats_summary = filtered_stats.json()["summary"]
        assert isinstance(stats_summary["cost"], float)
        # 峰时/谷时单价不同，cost 随运行时段在 0.00003~0.00006 之间
        assert 0 < stats_summary["cost"] <= 0.0001
        del stats_summary["cost"]
        assert stats_summary == {
            "requests": 2,
            "success_requests": 2,
            "failed_requests": 0,
            "non_success_requests": 0,
            "success_rate": 100.0,
            "input_tokens": 8,
            "output_tokens": 4,
            "total_tokens": 12,
            "active_users": 1,
            "models_used": 1,
        }
        chat_user_stats = filtered_stats.json()["by_user"][0]
        assert chat_user_stats["username"] == "chat-user"
        assert chat_user_stats["requests"] == 2
        assert chat_user_stats["total_tokens"] == 12
        assert chat_user_stats["last_request_time"].endswith("+08:00")
        assert filtered_stats.json()["by_model"][0]["users"] == 1
        assert filtered_stats.json()["by_provider"][0]["provider"] == "deepseek"
        assert "deepseek-v4-flash" in filtered_stats.json()["filter_options"][
            "models"
        ]

        filtered_logs = await client.get(
            "/api/admin/usage-logs",
            headers={"Authorization": f"Bearer {admin_token}"},
            params={
                "days": 30,
                "username": "chat-user",
                "model": "deepseek-v4-flash",
                "provider": "deepseek",
                "status": "success",
                "limit": 1,
                "offset": 1,
            },
        )
        assert filtered_logs.status_code == 200
        assert filtered_logs.json()["total"] == 2
        assert len(filtered_logs.json()["items"]) == 1
        assert filtered_logs.json()["items"][0]["username"] == "chat-user"

        empty_logs = await client.get(
            "/api/admin/usage-logs",
            headers={"Authorization": f"Bearer {admin_token}"},
            params={"username": "chat-user", "model": "not-a-model"},
        )
        assert empty_logs.status_code == 200
        assert empty_logs.json() == {"total": 0, "items": []}

        explicit_model = await client.post(
            "/v1/chat/completions",
            headers=api_headers,
            json={
                "model": "deepseek-v4-flash",
                "messages": [{"role": "user", "content": "compatibility"}],
            },
        )
        assert explicit_model.status_code == 200
        assert explicit_model.json()["model"] == "deepseek-v4-flash"
    finally:
        provider_registry._providers["deepseek"] = original_provider


def test_reasoning_content_helpers():
    thinking = ModelConfig(
        public_model="t1",
        provider_id=1,
        upstream_model="deepseek-v3.2-thinking",
        display_name="t1",
    )
    assert model_requires_reasoning_content(thinking) is True

    reasoner = ModelConfig(
        public_model="t2",
        provider_id=1,
        upstream_model="deepseek-reasoner",
        display_name="t2",
    )
    assert model_requires_reasoning_content(reasoner) is True

    plain = ModelConfig(
        public_model="t3",
        provider_id=1,
        upstream_model="deepseek-v4-flash",
        display_name="t3",
    )
    assert model_requires_reasoning_content(plain) is False

    forced = ModelConfig(
        public_model="t4",
        provider_id=1,
        upstream_model="deepseek-v4-flash",
        display_name="t4",
        capabilities={"thinking": True},
    )
    assert model_requires_reasoning_content(forced) is True

    disabled = ModelConfig(
        public_model="t5",
        provider_id=1,
        upstream_model="deepseek-reasoner",
        display_name="t5",
        capabilities={"thinking": False},
    )
    assert model_requires_reasoning_content(disabled) is False

    payload = {
        "messages": [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "assistant", "content": "c", "reasoning_content": "keep"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call_1"}],
            },
            {"role": "tool", "content": "result"},
        ]
    }
    patched = ensure_reasoning_content(payload)
    assert "reasoning_content" not in patched["messages"][0]
    assert patched["messages"][1]["reasoning_content"] == ""
    assert patched["messages"][2]["reasoning_content"] == "keep"
    assert patched["messages"][3]["reasoning_content"] == ""
    assert "reasoning_content" not in patched["messages"][4]
    assert "reasoning_content" not in payload["messages"][1]

    untouched = {"messages": [{"role": "user", "content": "a"}]}
    assert ensure_reasoning_content(untouched) is untouched


@pytest.mark.asyncio
async def test_thinking_model_patches_reasoning_content(client):
    original_provider = provider_registry._providers["deepseek"]
    fake_provider = FakeProvider()
    provider_registry._providers["deepseek"] = fake_provider
    try:
        admin_token = await login(client, "admin", "admin-password")
        create_user = await client.post(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"username": "think-user", "password": "developer-password1"},
        )
        assert create_user.status_code in (201, 409)
        user_token = await login(client, "think-user", "developer-password1")
        user_headers = {"Authorization": f"Bearer {user_token}"}
        created = await client.post(
            "/api/me/api-keys",
            headers=user_headers,
            json={"name": "think-test"},
        )
        assert created.status_code == 201
        api_headers = {"Authorization": f"Bearer {created.json()['key']}"}

        async with SessionLocal() as session:
            provider_id = await session.scalar(
                select(ProviderConfig.id).where(ProviderConfig.code == "deepseek")
            )
            for public_model, capabilities in (
                ("deepseek-v4-think", None),
                ("deepseek-v4-lite", {"chat": True, "stream": True}),
            ):
                existing = await session.scalar(
                    select(ModelConfig.id).where(
                        ModelConfig.public_model == public_model
                    )
                )
                if existing is None:
                    session.add(
                        ModelConfig(
                            public_model=public_model,
                            provider_id=provider_id,
                            upstream_model=public_model,
                            display_name=public_model,
                            enabled=True,
                            default_allowed=True,
                            capabilities=capabilities or {},
                        )
                    )
            await session.commit()

        response = await client.post(
            "/v1/chat/completions",
            headers=api_headers,
            json={
                "model": "deepseek-v4-think",
                "messages": [
                    {"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "hello"},
                    {
                        "role": "assistant",
                        "content": "with-cot",
                        "reasoning_content": "existing-cot",
                    },
                    {"role": "user", "content": "again"},
                ],
            },
        )
        assert response.status_code == 200, response.text
        sent_messages = fake_provider.payloads[-1]["messages"]
        assert sent_messages[1]["reasoning_content"] == ""
        assert sent_messages[2]["reasoning_content"] == "existing-cot"
        assert "reasoning_content" not in sent_messages[0]
        assert "reasoning_content" not in sent_messages[3]

        plain = await client.post(
            "/v1/chat/completions",
            headers=api_headers,
            json={
                "model": "deepseek-v4-lite",
                "messages": [
                    {"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "hello"},
                    {"role": "user", "content": "again"},
                ],
            },
        )
        assert plain.status_code == 200, plain.text
        plain_messages = fake_provider.payloads[-1]["messages"]
        assert all("reasoning_content" not in m for m in plain_messages)
    finally:
        provider_registry._providers["deepseek"] = original_provider


@pytest.mark.asyncio
async def test_user_usage_detail_breakdown(client):
    original_provider = provider_registry._providers["deepseek"]
    fake_provider = FakeProvider()
    provider_registry._providers["deepseek"] = fake_provider
    try:
        admin_token = await login(client, "admin", "admin-password")
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        create_user = await client.post(
            "/api/admin/users",
            headers=admin_headers,
            json={
                "username": "usage-detail-user",
                "password": "developer-password1",
            },
        )
        assert create_user.status_code in (201, 409), create_user.text

        users_list = (
            await client.get("/api/admin/users", headers=admin_headers)
        ).json()
        user_id = next(
            item["id"]
            for item in users_list
            if item["username"] == "usage-detail-user"
        )

        user_token = await login(client, "usage-detail-user", "developer-password1")
        user_headers = {"Authorization": f"Bearer {user_token}"}
        key = (
            await client.post(
                "/api/me/api-keys",
                headers=user_headers,
                json={"name": "usage-detail"},
            )
        ).json()["key"]

        response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": "team-coding",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert response.status_code == 200, response.text

        detail = await client.get(
            f"/api/admin/users/{user_id}/usage",
            headers=admin_headers,
            params={"days": 30},
        )
        assert detail.status_code == 200, detail.text
        data = detail.json()
        assert data["user"]["username"] == "usage-detail-user"
        assert data["summary"]["requests"] >= 1
        assert data["summary"]["total_tokens"] >= 6
        assert data["summary"]["active_days"] >= 1
        assert any(
            item["model"] == "deepseek-v4-flash" for item in data["by_model"]
        )
        deepseek_row = next(
            item for item in data["by_model"] if item["model"] == "deepseek-v4-flash"
        )
        assert deepseek_row["provider"] == "deepseek"
        assert deepseek_row["total_tokens"] >= 6
        assert isinstance(deepseek_row["cost"], (int, float))
        assert data["by_day"]
        assert all("date" in item for item in data["by_day"])

        today_detail = await client.get(
            f"/api/admin/users/{user_id}/usage",
            headers=admin_headers,
            params={"today": "true"},
        )
        assert today_detail.status_code == 200, today_detail.text
        today_data = today_detail.json()
        assert today_data["today"] is True
        assert today_data["summary"]["requests"] >= 1
        assert today_data["by_day"]

        today_logs = await client.get(
            "/api/admin/usage-logs",
            headers=admin_headers,
            params={"today": "true", "username": "usage-detail-user"},
        )
        assert today_logs.status_code == 200, today_logs.text
        assert today_logs.json()["total"] >= 1

        today_stats = await client.get(
            "/api/admin/stats",
            headers=admin_headers,
            params={"today": "true"},
        )
        assert today_stats.status_code == 200, today_stats.text
        assert today_stats.json()["summary"]["requests"] >= 1

        missing = await client.get(
            "/api/admin/users/999999/usage",
            headers=admin_headers,
        )
        assert missing.status_code == 404
    finally:
        provider_registry._providers["deepseek"] = original_provider
