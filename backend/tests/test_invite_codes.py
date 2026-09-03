import pytest
from sqlalchemy import select

from app.database.session import SessionLocal
from app.models import User


async def login(client, username: str, password: str) -> str:
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def admin_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def create_invite(
    client, admin_token: str, code: str, label: str
) -> dict:
    response = await client.post(
        "/api/admin/invite-codes",
        headers=admin_headers(admin_token),
        json={"label": label, "code": code, "max_uses": 10, "expires_at": None},
    )
    assert response.status_code == 201
    return response.json()


async def register_user(client, username: str, invite_code: str) -> None:
    response = await client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": "secure-password1",
            "invite_code": invite_code,
        },
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_register_binds_invite_code_and_listing_reports_it(client):
    admin_token = await login(client, "admin", "admin-password")
    created = await create_invite(
        client, admin_token, "bind-test-code", "绑定测试"
    )
    await register_user(client, "invite-bound-user", "bind-test-code")

    listing = await client.get(
        "/api/admin/invite-codes", headers=admin_headers(admin_token)
    )
    assert listing.status_code == 200
    row = next(
        item for item in listing.json() if item["id"] == created["id"]
    )
    assert row["bound_users"] == 1
    assert row["bound_usernames"] == ["invite-bound-user"]

    async with SessionLocal() as session:
        user = await session.scalar(
            select(User).where(User.username == "invite-bound-user")
        )
        assert user is not None
        assert user.invite_code_id == created["id"]


@pytest.mark.asyncio
async def test_delete_invite_code_blocked_while_users_bound(client):
    admin_token = await login(client, "admin", "admin-password")
    created = await create_invite(
        client, admin_token, "block-delete-code", "删除保护"
    )
    await register_user(client, "block-delete-user", "block-delete-code")

    blocked = await client.delete(
        f"/api/admin/invite-codes/{created['id']}",
        headers=admin_headers(admin_token),
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "invite_code_in_use"


@pytest.mark.asyncio
async def test_delete_invite_code_without_bindings(client):
    admin_token = await login(client, "admin", "admin-password")
    created = await create_invite(
        client, admin_token, "free-delete-code", "可删除"
    )

    deleted = await client.delete(
        f"/api/admin/invite-codes/{created['id']}",
        headers=admin_headers(admin_token),
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    missing = await client.delete(
        f"/api/admin/invite-codes/{created['id']}",
        headers=admin_headers(admin_token),
    )
    assert missing.status_code == 404
