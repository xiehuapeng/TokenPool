import pytest
from sqlalchemy import select

from app.database.session import SessionLocal
from app.models import ModelConfig, User, UserModelPermission


async def login(client, username: str, password: str) -> str:
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200
    return response.json()["access_token"]


async def create_user_and_key(
    client, admin_token: str, username: str
) -> tuple[int, str]:
    response = await client.post(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"username": username, "password": "secure-password"},
    )
    assert response.status_code == 201
    user_id = response.json()["id"]
    token = await login(client, username, "secure-password")
    key_response = await client.post(
        "/api/me/api-keys",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "permission-test"},
    )
    assert key_response.status_code == 201
    return user_id, key_response.json()["key"]


@pytest.mark.asyncio
async def test_models_are_filtered_per_user_permission(client):
    admin_token = await login(client, "admin", "admin-password")
    _, allowed_key = await create_user_and_key(client, admin_token, "allowed-user")
    denied_user_id, denied_key = await create_user_and_key(
        client, admin_token, "denied-user"
    )

    async with SessionLocal() as session:
        model = await session.scalar(
            select(ModelConfig).where(ModelConfig.public_model == "deepseek-chat")
        )
        session.add(
            UserModelPermission(
                user_id=denied_user_id,
                model_config_id=model.id,
                allowed=False,
            )
        )
        await session.commit()

    allowed = await client.get(
        "/v1/models", headers={"Authorization": f"Bearer {allowed_key}"}
    )
    denied = await client.get(
        "/v1/models", headers={"Authorization": f"Bearer {denied_key}"}
    )
    assert [item["id"] for item in allowed.json()["data"]] == ["deepseek-chat"]
    assert denied.json()["data"] == []

    denied_chat = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {denied_key}"},
        json={
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": "should not be sent"}],
        },
    )
    assert denied_chat.status_code == 403
    assert denied_chat.json()["error"]["code"] == "model_permission_denied"


@pytest.mark.asyncio
async def test_missing_and_invalid_api_keys_are_rejected(client):
    missing = await client.get("/v1/models")
    invalid = await client.get(
        "/v1/models", headers={"Authorization": "Bearer sk-team-invalid-key"}
    )
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "missing_api_key"
    assert invalid.status_code == 401
    assert invalid.json()["error"]["code"] == "invalid_api_key"


@pytest.mark.asyncio
async def test_no_public_registration_endpoint(client):
    response = await client.post(
        "/api/auth/register",
        json={"username": "external", "password": "external-password"},
    )
    assert response.status_code == 404
