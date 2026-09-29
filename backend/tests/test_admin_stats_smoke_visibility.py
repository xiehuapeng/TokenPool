from decimal import Decimal
from uuid import uuid4

import pytest

from app.database.session import SessionLocal
from app.models import ApiKey, UsageLog, User
from app.utils.time import utc_now


@pytest.mark.asyncio
async def test_release_smoke_calls_stay_in_logs_but_not_token_stats(client):
    login = await client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin-password"}
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    before = await client.get("/api/admin/stats", headers=headers, params={"days": 0})
    assert before.status_code == 200
    baseline = before.json()["summary"]

    smoke_usernames = [
        f"release-smoke-{uuid4().hex[:10]}",
        f"releaseui{uuid4().hex[:10]}",
    ]
    real_username = f"stats-member-{uuid4().hex[:10]}"
    entries = [
        (smoke_usernames[0], "smoke-only-model", "smoke-provider"),
        (smoke_usernames[1], "smoke-only-model", "smoke-provider"),
        (real_username, "real-only-model", "deepseek"),
    ]
    async with SessionLocal() as session:
        for username, model, provider in entries:
            user = User(username=username, password_hash="unused", status="deleted")
            session.add(user)
            await session.flush()
            key = ApiKey(
                user_id=user.id,
                name="audit",
                key_prefix="sk-test",
                key_hash=uuid4().hex,
                status="revoked",
            )
            session.add(key)
            await session.flush()
            session.add(
                UsageLog(
                    request_id=uuid4().hex,
                    user_id=user.id,
                    api_key_id=key.id,
                    model=model,
                    provider=provider,
                    upstream_model=model,
                    stream=False,
                    request_time=utc_now(),
                    status="success",
                    input_tokens=4,
                    output_tokens=2,
                    total_tokens=6,
                    cost=Decimal("0.000123"),
                    usage_source="provider",
                )
            )
        await session.commit()

    response = await client.get("/api/admin/stats", headers=headers, params={"days": 0})
    assert response.status_code == 200, response.text
    stats = response.json()
    assert stats["summary"]["requests"] == baseline["requests"] + 1
    assert stats["summary"]["total_tokens"] == baseline["total_tokens"] + 6
    assert real_username in {entry["username"] for entry in stats["by_user"]}
    assert not set(smoke_usernames) & {entry["username"] for entry in stats["by_user"]}
    assert "smoke-only-model" not in stats["filter_options"]["models"]
    assert "smoke-provider" not in stats["filter_options"]["providers"]
    assert "smoke-only-model" not in {entry["model"] for entry in stats["by_model"]}
    assert "smoke-provider" not in {entry["provider"] for entry in stats["by_provider"]}

    for username in smoke_usernames:
        filtered = await client.get(
            "/api/admin/stats",
            headers=headers,
            params={"days": 0, "username": username},
        )
        assert filtered.status_code == 200
        assert filtered.json()["summary"]["requests"] == 0
        assert filtered.json()["by_user"] == []

        audit = await client.get(
            "/api/admin/usage-logs",
            headers=headers,
            params={"days": 0, "username": username},
        )
        assert audit.status_code == 200
        assert audit.json()["total"] == 1
        assert audit.json()["items"][0]["username"] == username
