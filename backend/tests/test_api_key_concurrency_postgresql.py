"""Opt-in PostgreSQL locking regression using an isolated random schema.

TOKENPOOL_TEST_POSTGRES_URL must point to a disposable local test database and
use postgresql+asyncpg. The normal SQLite suite skips this database-specific test.
"""

import asyncio
import os
import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.models import ApiKey, User
from app.routers.me import create_api_key
from app.schemas.api_key import ApiKeyCreate
from app.utils.errors import GatewayError


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("TOKENPOOL_TEST_POSTGRES_URL"),
    reason="requires an explicitly configured disposable PostgreSQL database",
)
async def test_postgresql_concurrent_key_creation_obeys_owner_limit():
    url = os.environ["TOKENPOOL_TEST_POSTGRES_URL"]
    assert url.startswith("postgresql+asyncpg://")
    schema = f"tokenpool_key_test_{uuid.uuid4().hex}"
    admin_engine = create_async_engine(url)
    scoped_engine = create_async_engine(
        url, connect_args={"server_settings": {"search_path": schema}},
    )
    sessions = async_sessionmaker(scoped_engine, expire_on_commit=False)
    try:
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        async with scoped_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            user = User(username="pg-key-race", password_hash="unused", status="active")
            session.add(user)
            await session.flush()
            user_id = user.id
            for index in range(2):
                session.add(ApiKey(
                    user_id=user_id, name=f"existing-{index}", key_prefix="test",
                    key_hash=f"not-a-real-key-{index}", status="active",
                ))
            await session.commit()

        barrier = asyncio.Barrier(6)

        async def attempt(index: int) -> str:
            async with sessions() as session:
                current_user = await session.get(User, user_id)
                await barrier.wait()
                try:
                    await create_api_key(
                        ApiKeyCreate(name=f"concurrent-{index}"), current_user, session,
                    )
                    return "created"
                except GatewayError as exc:
                    return exc.code

        results = await asyncio.wait_for(
            asyncio.gather(*(attempt(index) for index in range(6))), timeout=30,
        )
        assert results.count("created") == 1
        assert results.count("api_key_limit_reached") == 5
        async with sessions() as session:
            assert await session.scalar(select(func.count(ApiKey.id))) == 3
    finally:
        await scoped_engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()
