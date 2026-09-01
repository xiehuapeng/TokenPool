import pytest
from sqlalchemy import select

from app.database.session import SessionLocal
from app.models import ModelConfig
from app.providers.base import BaseProvider, ProviderResult
from app.providers.registry import provider_registry
from app.services.model_router import payload_contains_images


class RecordingProvider(BaseProvider):
    def __init__(self, code: str) -> None:
        self.code = code
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
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 2,
                    "completion_tokens": 1,
                    "total_tokens": 3,
                },
            },
            http_status=200,
            upstream_request_id=f"{self.code}-upstream",
        )

    async def open_chat_stream(self, payload, *, upstream_model, timeout_seconds):
        raise NotImplementedError


async def login(client, username: str, password: str) -> str:
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def create_user(client, admin_headers: dict, username: str) -> str:
    created = await client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={"username": username, "password": "developer-password1"},
    )
    assert created.status_code in (201, 409), created.text
    return await login(client, username, "developer-password1")


async def create_key(client, headers: dict, name: str) -> dict:
    response = await client.post(
        "/api/me/api-keys", headers=headers, json={"name": name}
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_api_key_limit(client):
    admin_token = await login(client, "admin", "admin-password")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    user_token = await create_user(client, admin_headers, "key-limit-user")
    user_headers = {"Authorization": f"Bearer {user_token}"}

    config = await client.get("/api/me/config", headers=user_headers)
    assert config.status_code == 200
    assert config.json()["max_api_keys"] == 3

    created_ids = []
    for index in range(3):
        created = await create_key(client, user_headers, f"limit-{index}")
        assert created["preferred_model_id"] is None
        assert created["preferred_model"] is None
        created_ids.append(created["id"])

    blocked = await client.post(
        "/api/me/api-keys", headers=user_headers, json={"name": "one-too-many"}
    )
    assert blocked.status_code == 400
    assert blocked.json()["error"]["code"] == "api_key_limit_reached"

    revoked = await client.delete(
        f"/api/me/api-keys/{created_ids[0]}", headers=user_headers
    )
    assert revoked.status_code == 204

    retry = await create_key(client, user_headers, "after-revoke")
    assert retry["id"] not in created_ids

    listed = await client.get("/api/me/api-keys", headers=user_headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 3


@pytest.mark.asyncio
async def test_key_preferred_model_routing(client):
    original_deepseek = provider_registry._providers["deepseek"]
    original_qwen = provider_registry._providers["qwen"]
    deepseek_fake = RecordingProvider("deepseek")
    qwen_fake = RecordingProvider("qwen")
    provider_registry._providers["deepseek"] = deepseek_fake
    provider_registry._providers["qwen"] = qwen_fake
    try:
        admin_token = await login(client, "admin", "admin-password")
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        user_token = await create_user(client, admin_headers, "key-pref-user")
        user_headers = {"Authorization": f"Bearer {user_token}"}
        other_token = await create_user(client, admin_headers, "key-pref-other")
        other_headers = {"Authorization": f"Bearer {other_token}"}

        key_a = await create_key(client, user_headers, "default")
        key_b = await create_key(client, user_headers, "qwen-key")

        updated = await client.patch(
            f"/api/me/api-keys/{key_b['id']}/preferred-model",
            headers=user_headers,
            json={"model": "qwen3.7-plus"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["preferred_model"] == "qwen3.7-plus"
        assert updated.json()["preferred_model_id"] is not None

        listed = await client.get("/api/me/api-keys", headers=user_headers)
        listed_by_id = {item["id"]: item for item in listed.json()}
        assert listed_by_id[key_b["id"]]["preferred_model"] == "qwen3.7-plus"
        assert listed_by_id[key_a["id"]]["preferred_model"] is None

        routed_b = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {key_b['key']}"},
            json={
                "model": "team-coding",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert routed_b.status_code == 200, routed_b.text
        assert routed_b.json()["model"] == "team-coding"
        assert qwen_fake.upstream_models[-1] == "qwen3.7-plus"

        routed_a = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {key_a['key']}"},
            json={
                "model": "team-coding",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert routed_a.status_code == 200, routed_a.text
        assert deepseek_fake.upstream_models[-1] == "deepseek-v4-flash"

        explicit = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {key_b['key']}"},
            json={
                "model": "deepseek-v4-flash",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert explicit.status_code == 200, explicit.text
        assert deepseek_fake.upstream_models[-1] == "deepseek-v4-flash"

        cleared = await client.patch(
            f"/api/me/api-keys/{key_b['id']}/preferred-model",
            headers=user_headers,
            json={"model": None},
        )
        assert cleared.status_code == 200
        assert cleared.json()["preferred_model"] is None
        assert cleared.json()["preferred_model_id"] is None

        routed_cleared = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {key_b['key']}"},
            json={
                "model": "team-coding",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert routed_cleared.status_code == 200
        assert deepseek_fake.upstream_models[-1] == "deepseek-v4-flash"

        unknown = await client.patch(
            f"/api/me/api-keys/{key_b['id']}/preferred-model",
            headers=user_headers,
            json={"model": "not-a-real-model"},
        )
        assert unknown.status_code == 404
        assert unknown.json()["error"]["code"] == "model_not_found"

        foreign = await client.patch(
            f"/api/me/api-keys/{key_a['id']}/preferred-model",
            headers=other_headers,
            json={"model": "qwen3.7-plus"},
        )
        assert foreign.status_code == 404
        assert foreign.json()["error"]["code"] == "key_not_found"
    finally:
        provider_registry._providers["deepseek"] = original_deepseek
        provider_registry._providers["qwen"] = original_qwen


@pytest.mark.asyncio
async def test_vision_reroute_and_friendly_error(client):
    original_deepseek = provider_registry._providers["deepseek"]
    original_qwen = provider_registry._providers["qwen"]
    original_glm = provider_registry._providers["glm"]
    deepseek_fake = RecordingProvider("deepseek")
    qwen_fake = RecordingProvider("qwen")
    glm_fake = RecordingProvider("glm")
    provider_registry._providers["deepseek"] = deepseek_fake
    provider_registry._providers["qwen"] = qwen_fake
    provider_registry._providers["glm"] = glm_fake
    try:
        admin_token = await login(client, "admin", "admin-password")
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        user_token = await create_user(client, admin_headers, "vision-user")
        user_headers = {"Authorization": f"Bearer {user_token}"}
        key = await create_key(client, user_headers, "vision")
        api_headers = {"Authorization": f"Bearer {key['key']}"}

        image_payload = {
            "model": "deepseek-v4-flash",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "describe this"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "https://example.com/screenshot.png"
                            },
                        },
                    ],
                }
            ],
        }

        rerouted = await client.post(
            "/v1/chat/completions", headers=api_headers, json=image_payload
        )
        assert rerouted.status_code == 200, rerouted.text
        assert rerouted.json()["model"] == "deepseek-v4-flash"
        assert glm_fake.upstream_models[-1] == "glm-5.3-flash"
        assert qwen_fake.upstream_models == []
        assert deepseek_fake.upstream_models == []

        virtual_image = {**image_payload, "model": "team-coding"}
        virtual_rerouted = await client.post(
            "/v1/chat/completions", headers=api_headers, json=virtual_image
        )
        assert virtual_rerouted.status_code == 200, virtual_rerouted.text
        assert glm_fake.upstream_models[-1] == "glm-5.3-flash"

        text_only = await client.post(
            "/v1/chat/completions",
            headers=api_headers,
            json={
                "model": "deepseek-v4-flash",
                "messages": [{"role": "user", "content": "plain text"}],
            },
        )
        assert text_only.status_code == 200, text_only.text
        assert deepseek_fake.upstream_models[-1] == "deepseek-v4-flash"

        async with SessionLocal() as session:
            vision_models = list(
                await session.scalars(
                    select(ModelConfig).where(
                        ModelConfig.public_model.in_(
                            (
                                "glm-5.3-flash",
                                "qwen3.8-max",
                                "qwen3.8-flash",
                                "qwen3.7-plus",
                                "kimi-k3",
                                "kimi-k2.7-code",
                                "kimi-k2.7-code-highspeed",
                            )
                        )
                    )
                )
            )
            for model in vision_models:
                model.enabled = False
            await session.commit()
        try:
            blocked = await client.post(
                "/v1/chat/completions", headers=api_headers, json=image_payload
            )
            assert blocked.status_code == 400, blocked.text
            assert blocked.json()["error"]["code"] == "vision_not_supported"
        finally:
            async with SessionLocal() as session:
                vision_models = list(
                    await session.scalars(
                        select(ModelConfig).where(
                            ModelConfig.public_model.in_(
                                (
                                    "glm-5.3-flash",
                                    "qwen3.8-max",
                                    "qwen3.8-flash",
                                    "qwen3.7-plus",
                                    "kimi-k3",
                                    "kimi-k2.7-code",
                                    "kimi-k2.7-code-highspeed",
                                )
                            )
                        )
                    )
                )
                for model in vision_models:
                    model.enabled = True
                await session.commit()
    finally:
        provider_registry._providers["deepseek"] = original_deepseek
        provider_registry._providers["qwen"] = original_qwen
        provider_registry._providers["glm"] = original_glm


def test_payload_contains_images():
    image_payload = {
        "messages": [
            {"role": "user", "content": "text"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "a"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "https://example.com/a.png"},
                    },
                ],
            },
        ]
    }
    assert payload_contains_images(image_payload) is True

    text_payload = {"messages": [{"role": "user", "content": "text"}]}
    assert payload_contains_images(text_payload) is False
    assert payload_contains_images({}) is False

    legacy_image_part = {
        "messages": [
            {"role": "user", "content": [{"type": "image", "image": "data"}]}
        ]
    }
    assert payload_contains_images(legacy_image_part) is True
