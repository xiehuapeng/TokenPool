import asyncio
from contextlib import asynccontextmanager
import json
import os

import httpx
from sqlalchemy import select

from app.config.settings import get_settings
from app.database.session import SessionLocal
from app.main import app
from app.models import UsageLog, User


TARGET_MODELS = ("qwen3.8-max", "qwen3.7-plus", "qwen3.7-max")


@asynccontextmanager
async def gateway_client():
    external_base_url = os.getenv("VERIFY_BASE_URL")
    if external_base_url:
        async with httpx.AsyncClient(
            base_url=external_base_url,
            timeout=httpx.Timeout(180),
        ) as client:
            yield client
        return

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            timeout=httpx.Timeout(180),
        ) as client:
            yield client


async def main() -> None:
    settings = get_settings()
    admin_password = settings.admin_password.get_secret_value()
    if not admin_password:
        raise RuntimeError("ADMIN_PASSWORD is required for live verification")

    async with gateway_client() as client:
        async def verify() -> None:
            login = await client.post(
                "/api/auth/login",
                json={
                    "username": settings.admin_username,
                    "password": admin_password,
                },
            )
            login.raise_for_status()
            bearer = {"Authorization": f"Bearer {login.json()['access_token']}"}
            admin_id = login.json()["user"]["id"]

            async with SessionLocal() as session:
                admin = await session.get(User, admin_id)
                original_preference = admin.preferred_model_id

            created_key_id: int | None = None
            request_ids: list[str] = []
            results: list[dict] = []
            try:
                created = await client.post(
                    "/api/me/api-keys",
                    headers=bearer,
                    json={"name": "Qwen live verification"},
                )
                created.raise_for_status()
                created_key_id = created.json()["id"]
                api_key = created.json()["key"]
                api_headers = {"Authorization": f"Bearer {api_key}"}

                models = await client.get("/v1/models", headers=api_headers)
                models.raise_for_status()
                assert [item["id"] for item in models.json()["data"]] == [
                    "team-coding"
                ]

                for model in TARGET_MODELS:
                    preference = await client.put(
                        "/api/me/model-preference",
                        headers=bearer,
                        json={"model": model},
                    )
                    preference.raise_for_status()
                    assert preference.json()["selected_model"] == model

                    response = await client.post(
                        "/v1/chat/completions",
                        headers=api_headers,
                        json={
                            "model": "team-coding",
                            "messages": [
                                {"role": "user", "content": "只回复 OK"}
                            ],
                            "stream": False,
                            "max_tokens": 16,
                        },
                    )
                    response.raise_for_status()
                    request_ids.append(response.headers["x-request-id"])
                    usage = response.json().get("usage") or {}
                    results.append(
                        {
                            "model": model,
                            "mode": "non_stream",
                            "status": response.status_code,
                            "total_tokens": usage.get("total_tokens"),
                        }
                    )

                preference = await client.put(
                    "/api/me/model-preference",
                    headers=bearer,
                    json={"model": "qwen3.7-plus"},
                )
                preference.raise_for_status()
                stream_usage = None
                saw_done = False
                async with client.stream(
                    "POST",
                    "/v1/chat/completions",
                    headers=api_headers,
                    json={
                        "model": "team-coding",
                        "messages": [{"role": "user", "content": "只回复 OK"}],
                        "stream": True,
                        "max_tokens": 16,
                    },
                ) as response:
                    response.raise_for_status()
                    request_ids.append(response.headers["x-request-id"])
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        value = line[5:].strip()
                        if value == "[DONE]":
                            saw_done = True
                            continue
                        payload = json.loads(value)
                        if payload.get("usage"):
                            stream_usage = payload["usage"]
                results.append(
                    {
                        "model": "qwen3.7-plus",
                        "mode": "stream",
                        "status": response.status_code,
                        "done": saw_done,
                        "total_tokens": (stream_usage or {}).get("total_tokens"),
                    }
                )

                async with SessionLocal() as session:
                    logs = list(
                        await session.scalars(
                            select(UsageLog).where(
                                UsageLog.request_id.in_(request_ids)
                            )
                        )
                    )
                assert len(logs) == len(request_ids)
                assert all(log.status == "success" for log in logs)
                assert all(log.provider == "qwen" for log in logs)
                assert all(log.total_tokens > 0 for log in logs)
                print(
                    json.dumps(
                        {
                            "models_endpoint": "ok",
                            "calls": results,
                            "usage_logs": len(logs),
                            "usage_status": "ok",
                        },
                        ensure_ascii=False,
                    )
                )
            finally:
                if created_key_id is not None:
                    await client.delete(
                        f"/api/me/api-keys/{created_key_id}", headers=bearer
                    )
                async with SessionLocal() as session:
                    admin = await session.get(User, admin_id)
                    admin.preferred_model_id = original_preference
                    await session.commit()

        await verify()


if __name__ == "__main__":
    asyncio.run(main())
