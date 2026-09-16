import pytest

from app.database.session import SessionLocal
from app.models import ApiKey, User


async def login(client, username: str, password: str) -> str:
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def admin_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def make_invite(client, admin_token: str, code: str, max_uses: int | None = 10):
    response = await client.post(
        "/api/admin/invite-codes",
        headers=admin_headers(admin_token),
        json={"label": "test", "code": code, "max_uses": max_uses, "expires_at": None},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_reset_password_with_invite_code(client):
    admin_token = await login(client, "admin", "admin-password")
    headers = admin_headers(admin_token)

    created = await client.post(
        "/api/admin/users",
        headers=headers,
        json={"username": "reset-user", "password": "original-password1"},
    )
    assert created.status_code in (201, 409), created.text

    invite_code = "RESETCODE2026"
    await make_invite(client, admin_token, invite_code, max_uses=1)

    # Wrong invite code is rejected.
    bad = await client.post(
        "/api/auth/reset-password",
        json={
            "username": "reset-user",
            "password": "brand-new-password1",
            "invite_code": "WRONGCODE2026",
        },
    )
    assert bad.status_code == 400, bad.text
    assert bad.json()["error"]["code"] == "invalid_invite_code"

    # The old password still works after a failed attempt.
    await login(client, "reset-user", "original-password1")

    ok = await client.post(
        "/api/auth/reset-password",
        json={
            "username": "reset-user",
            "password": "brand-new-password1",
            "invite_code": invite_code,
        },
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["access_token"]

    # New password works, old one no longer does.
    await login(client, "reset-user", "brand-new-password1")
    stale = await client.post(
        "/api/auth/login",
        json={"username": "reset-user", "password": "original-password1"},
    )
    assert stale.status_code == 401

    # The reset must NOT consume the invite code's usage count.
    codes = await client.get("/api/admin/invite-codes", headers=headers)
    entry = next(
        item for item in codes.json() if item["code_prefix"].startswith(invite_code[:4])
    )
    assert entry["usage_count"] == 0


@pytest.mark.asyncio
async def test_reset_password_rejects_unknown_user(client):
    admin_token = await login(client, "admin", "admin-password")
    await make_invite(client, admin_token, "RESETCODE2X", max_uses=None)

    response = await client.post(
        "/api/auth/reset-password",
        json={
            "username": "no-such-person",
            "password": "whatever-password1",
            "invite_code": "RESETCODE2X",
        },
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


@pytest.mark.asyncio
async def test_reset_password_rejects_extra_field(client):
    admin_token = await login(client, "admin", "admin-password")
    await make_invite(client, admin_token, "RESETCODE3X", max_uses=None)

    response = await client.post(
        "/api/auth/reset-password",
        json={
            "username": "someone",
            "password": "whatever-password1",
            "invite_code": "RESETCODE3X",
            "is_admin": True,
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_delete_user_is_soft_and_preserves_usage(client):
    admin_token = await login(client, "admin", "admin-password")
    headers = admin_headers(admin_token)

    created = await client.post(
        "/api/admin/users",
        headers=headers,
        json={"username": "delete-me", "password": "delete-me-password1"},
    )
    assert created.status_code in (201, 409), created.text
    user_id = created.json()["id"]

    user_token = await login(client, "delete-me", "delete-me-password1")
    key = await client.post(
        "/api/me/api-keys",
        headers=admin_headers(user_token),
        json={"name": "to-revoke"},
    )
    assert key.status_code == 201, key.text

    deleted = await client.delete(f"/api/admin/users/{user_id}", headers=headers)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"] is True

    # Gone from the admin list.
    users = await client.get("/api/admin/users", headers=headers)
    assert all(item["id"] != user_id for item in users.json())

    # Cannot log in any more.
    relogin = await client.post(
        "/api/auth/login",
        json={"username": "delete-me", "password": "delete-me-password1"},
    )
    assert relogin.status_code == 401

    # The user row still exists so usage attribution survives; the key is revoked.
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        assert user is not None
        assert user.status == "deleted"
        assert not user.password_hash.startswith("scrypt$")
        key_row = await session.get(ApiKey, key.json()["id"])
        assert key_row.status == "revoked"
        assert key_row.secret_ciphertext is None

    # Deleting again reports not found.
    again = await client.delete(f"/api/admin/users/{user_id}", headers=headers)
    assert again.status_code == 404


@pytest.mark.asyncio
async def test_admin_cannot_delete_self(client):
    admin_token = await login(client, "admin", "admin-password")
    headers = admin_headers(admin_token)
    users = await client.get("/api/admin/users", headers=headers)
    admin_row = next(item for item in users.json() if item["username"] == "admin")

    response = await client.delete(
        f"/api/admin/users/{admin_row['id']}", headers=headers
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "cannot_delete_self"


@pytest.mark.asyncio
async def test_admin_actions_are_audited(client):
    admin_token = await login(client, "admin", "admin-password")
    headers = admin_headers(admin_token)

    created = await client.post(
        "/api/admin/users",
        headers=headers,
        json={"username": "audit-target", "password": "audit-target-pass1"},
    )
    assert created.status_code in (201, 409), created.text
    user_id = created.json()["id"]

    await client.patch(
        f"/api/admin/users/{user_id}/status", headers=headers, json={"status": "disabled"}
    )

    logs = await client.get("/api/admin/audit-logs", headers=headers)
    assert logs.status_code == 200, logs.text
    items = logs.json()["items"]
    actions = {item["action"] for item in items}
    assert "user.status" in actions

    status_entry = next(item for item in items if item["action"] == "user.status")
    assert status_entry["admin_username"] == "admin"
    assert status_entry["target_label"] == "audit-target"
    assert status_entry["detail"]["from"] == "active"
    assert status_entry["detail"]["to"] == "disabled"
    assert status_entry["created_at"]

    # Filtering by action returns only that action.
    filtered = await client.get(
        "/api/admin/audit-logs", headers=headers, params={"action": "user.status"}
    )
    assert filtered.status_code == 200
    assert all(
        item["action"] == "user.status" for item in filtered.json()["items"]
    )


@pytest.mark.asyncio
async def test_audit_log_records_pricing_change_without_secret_values(client):
    admin_token = await login(client, "admin", "admin-password")
    headers = admin_headers(admin_token)

    models = await client.get("/api/admin/models", headers=headers)
    target = next(m for m in models.json() if m["public_model"] == "glm-5.3")

    response = await client.patch(
        f"/api/admin/models/{target['id']}/pricing",
        headers=headers,
        json={"input_price": 9.5},
    )
    assert response.status_code == 200, response.text

    # Restore the seeded value so later tests are unaffected.
    await client.patch(
        f"/api/admin/models/{target['id']}/pricing",
        headers=headers,
        json={"input_price": 8},
    )

    logs = await client.get(
        "/api/admin/audit-logs", headers=headers, params={"action": "model.pricing"}
    )
    assert logs.status_code == 200
    entries = [
        item
        for item in logs.json()["items"]
        if item["target_label"] == "glm-5.3"
        and item["detail"]["changes"].get("input_price", {}).get("to") == 9.5
    ]
    assert entries, "the 9.5 pricing change must be audited"
    entry = entries[0]
    assert entry["target_label"] == "glm-5.3"
    assert entry["detail"]["changes"]["input_price"]["from"] == 8.0
    assert entry["admin_username"] == "admin"
