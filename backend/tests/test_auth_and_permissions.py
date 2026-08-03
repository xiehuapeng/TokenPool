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
        json={"username": username, "password": "secure-password1"},
    )
    assert response.status_code == 201
    user_id = response.json()["id"]
    token = await login(client, username, "secure-password1")
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
        models = await session.scalars(
            select(ModelConfig).where(ModelConfig.enabled.is_(True))
        )
        session.add_all(
            [
                UserModelPermission(
                    user_id=denied_user_id,
                    model_config_id=model.id,
                    allowed=False,
                )
                for model in models
            ]
        )
        await session.commit()

    allowed = await client.get(
        "/v1/models", headers={"Authorization": f"Bearer {allowed_key}"}
    )
    denied = await client.get(
        "/v1/models", headers={"Authorization": f"Bearer {denied_key}"}
    )
    assert [item["id"] for item in allowed.json()["data"]] == ["team-coding"]
    assert denied.json()["data"] == []

    denied_preference = await client.put(
        "/api/me/model-preference",
        headers={
            "Authorization": f"Bearer {await login(client, 'denied-user', 'secure-password1')}"
        },
        json={"model": "deepseek-chat"},
    )
    assert denied_preference.status_code == 403
    assert denied_preference.json()["error"]["code"] == "model_permission_denied"

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

    denied_virtual_chat = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {denied_key}"},
        json={
            "model": "team-coding",
            "messages": [{"role": "user", "content": "should not be sent"}],
        },
    )
    assert denied_virtual_chat.status_code == 403
    assert denied_virtual_chat.json()["error"]["code"] == "no_permitted_model"


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
async def test_public_registration_creates_only_normal_user(client):
    admin_token = await login(client, "admin", "admin-password")
    invite_response = await client.post(
        "/api/admin/invite-codes",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "label": "registration-test",
            "code": "team-register-2026",
            "max_uses": 2,
        },
    )
    assert invite_response.status_code == 201
    assert invite_response.json()["code"] == "team-register-2026"
    invite_id = invite_response.json()["id"]

    revealed_invite = await client.get(
        f"/api/admin/invite-codes/{invite_id}/secret",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert revealed_invite.status_code == 200
    assert revealed_invite.json()["value"] == "team-register-2026"
    assert revealed_invite.headers["cache-control"] == "no-store"

    privilege_attempt = await client.post(
        "/api/auth/register",
        json={
            "username": "self-user",
            "password": "external-password1",
            "invite_code": "team-register-2026",
            "is_admin": True,
        },
    )
    assert privilege_attempt.status_code == 422

    response = await client.post(
        "/api/auth/register",
        json={
            "username": "self-user",
            "password": "external-password1",
            "invite_code": "team-register-2026",
        },
    )
    assert response.status_code == 201
    assert response.json()["user"]["username"] == "self-user"
    assert response.json()["user"]["status"] == "active"
    assert response.json()["user"]["is_admin"] is False
    assert response.json()["access_token"]

    duplicate = await client.post(
        "/api/auth/register",
        json={
            "username": "SELF-USER",
            "password": "external-password1",
            "invite_code": "team-register-2026",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "username_exists"

    forbidden = await client.get(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {response.json()['access_token']}"},
    )
    assert forbidden.status_code == 403

    invalid_invite = await client.post(
        "/api/auth/register",
        json={
            "username": "another-user",
            "password": "external-password1",
            "invite_code": "wrong-invite",
        },
    )
    assert invalid_invite.status_code == 400
    assert invalid_invite.json()["error"]["code"] == "invalid_invite_code"

    invite_list = await client.get(
        "/api/admin/invite-codes",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert invite_list.status_code == 200
    assert invite_list.json()[0]["usage_count"] == 1
    assert invite_list.json()[0]["can_reveal"] is True
    assert "code" not in invite_list.json()[0]

    forbidden_reveal = await client.get(
        f"/api/admin/invite-codes/{invite_id}/secret",
        headers={"Authorization": f"Bearer {response.json()['access_token']}"},
    )
    assert forbidden_reveal.status_code == 403
