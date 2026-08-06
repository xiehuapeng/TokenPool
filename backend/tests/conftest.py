import asyncio
import os
import sys
import uuid
from pathlib import Path


TEST_DATABASE = (
    Path(__file__).resolve().parents[1] / "data" / f"test_{uuid.uuid4().hex}.db"
)
TEST_DATABASE.parent.mkdir(parents=True, exist_ok=True)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

os.environ.update(
    {
        "APP_ENV": "test",
        "DATABASE_URL": f"sqlite+aiosqlite:///{TEST_DATABASE.as_posix()}",
        "JWT_SECRET": "test-jwt-secret-that-is-long-enough",
        "API_KEY_PEPPER": "test-api-key-pepper-that-is-long-enough",
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD": "admin-password",
        "DEEPSEEK_API_KEY": "test-upstream-key",
        "GLM_API_KEY": "test-zhipu-key",
        "GLM_BASE_URL": "https://open.bigmodel.cn/api/coding/paas/v4",
        "KIMI_API_KEY": "test-kimi-key",
        "QWEN_API_KEY": "test-qwen-key",
        "MODEL_SYNC_ENABLED": "false",
    }
)

import httpx
import pytest
import pytest_asyncio

from app.main import app


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_database():
    yield
    for suffix in ("", "-shm", "-wal"):
        candidate = Path(f"{TEST_DATABASE}{suffix}")
        if candidate.exists():
            candidate.unlink()


@pytest.fixture(scope="session")
def event_loop_policy():
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture
async def client():
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as test_client:
            yield test_client
