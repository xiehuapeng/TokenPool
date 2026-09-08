import asyncio
from contextlib import suppress
from datetime import timedelta
import os
import signal
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import select, update

from app.database.session import SessionLocal
from app.models import ApiKey, UsageLog, User
from app.services import usage_runtime
from app.services import usage_service
from app.services.usage_runtime import UsageRuntime, release_lock
from app.services.usage_service import (
    create_usage_log,
    recover_abandoned_usage_logs,
    recover_stale_usage_logs,
    usage_recovery_loop,
)
from app.utils.time import utc_now


def test_runtime_lock_is_held_until_owner_exits(tmp_path):
    runtime = UsageRuntime(tmp_path)
    # Separate OS process: exercise crash/exit semantics, not just a Python flag.
    source = (
        "import sys, os; from pathlib import Path; "
        "from app.services.usage_runtime import UsageRuntime; "
        "r=UsageRuntime(Path(sys.argv[1])); r.start(); "
        "print(r.id, os.getpid(), flush=True); sys.stdin.readline()"
    )
    child = subprocess.Popen(
        [sys.executable, "-u", "-c", source, str(tmp_path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        owner, actual_pid = child.stdout.readline().strip().split()
        assert owner.startswith(runtime.namespace), child.stderr.read() if child.poll() else ""
        assert runtime.try_claim_abandoned(owner) is None
        # A Windows venv launcher can be a wrapper around the real Python PID.
        os.kill(int(actual_pid), signal.SIGTERM)
        child.wait(timeout=5)
        claim = runtime.try_claim_abandoned(owner)
        assert claim is not None
        release_lock(claim)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        for handle in (child.stdin, child.stdout, child.stderr):
            handle.close()


def test_runtime_refuses_other_hosts_directories_and_invalid_ids(tmp_path):
    runtime = UsageRuntime(tmp_path)
    other_scope = UsageRuntime(tmp_path / "other")
    assert runtime.try_claim_abandoned(other_scope.id) is None
    assert runtime.try_claim_abandoned("../outside") is None
    assert runtime.try_claim_abandoned(runtime.id) is None


async def _identities():
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.username == "admin"))
        key = ApiKey(
            user_id=user.id, name="runtime-test", key_prefix="test",
            key_hash=uuid.uuid4().hex, status="active",
        )
        session.add(key)
        await session.commit()
        return user.id, key.id


async def _insert(user_id, key_id, owner, age_seconds):
    request_id = f"runtime-test-{uuid.uuid4().hex}"
    async with SessionLocal() as session:
        session.add(UsageLog(
            request_id=request_id, runtime_id=owner,
            user_id=user_id, api_key_id=key_id,
            model="deepseek-v4-flash", provider="deepseek", upstream_model="fake",
            status="pending", stream=True,
            request_time=utc_now()-timedelta(seconds=age_seconds),
        ))
        await session.commit()
    return request_id


async def _status(request_id):
    async with SessionLocal() as session:
        return await session.scalar(select(UsageLog.status).where(UsageLog.request_id == request_id))


@pytest.mark.asyncio
async def test_recovery_uses_owner_not_request_age(client, tmp_path, monkeypatch):
    current_id = usage_runtime.current_runtime_id()
    monkeypatch.setattr(usage_runtime, "_current_runtime_id", current_id)
    user_id, key_id = await _identities()
    living = UsageRuntime(tmp_path)
    living.start()
    stopped = UsageRuntime(tmp_path)
    stopped.start()
    stopped.stop()
    observer = UsageRuntime(tmp_path)
    observer.start()
    try:
        young_orphan = await _insert(user_id, key_id, stopped.id, 1)
        old_live = await _insert(user_id, key_id, living.id, 7200)
        old_legacy = await _insert(user_id, key_id, None, 7200)
        foreign = await _insert(user_id, key_id, UsageRuntime(tmp_path / "foreign").id, 7200)
        assert await recover_abandoned_usage_logs(observer) == 1
        assert await _status(young_orphan) == "interrupted"
        assert await _status(old_live) == "pending"
        assert await _status(old_legacy) == "pending"
        assert await _status(foreign) == "pending"
        assert await recover_abandoned_usage_logs(observer) == 0
        living.stop()
        assert await recover_abandoned_usage_logs(observer) == 1
        assert await _status(old_live) == "interrupted"
    finally:
        living.stop()
        observer.stop()


@pytest.mark.asyncio
async def test_new_usage_records_owner_and_periodic_recovery(client, tmp_path, monkeypatch):
    monkeypatch.setattr(usage_runtime, "_current_runtime_id", usage_runtime.current_runtime_id())
    user_id, key_id = await _identities()
    owner = UsageRuntime(tmp_path)
    owner.start()
    request_id = f"runtime-test-{uuid.uuid4().hex}"
    await create_usage_log(
        request_id=request_id, user_id=user_id, api_key_id=key_id,
        requested_model="team-coding", model="deepseek-v4-flash", provider="deepseek",
        upstream_model="fake", stream=True,
    )
    async with SessionLocal() as session:
        assert await session.scalar(select(UsageLog.runtime_id).where(UsageLog.request_id == request_id)) == owner.id
    observer = UsageRuntime(tmp_path)
    observer.start()
    task = asyncio.create_task(usage_recovery_loop(observer, interval_seconds=0.01))
    try:
        await asyncio.sleep(0.03)
        assert await _status(request_id) == "pending"
        owner.stop()
        async def wait_recovered():
            while await _status(request_id) == "pending":
                await asyncio.sleep(0.01)
        await asyncio.wait_for(wait_recovered(), timeout=2)
        assert await _status(request_id) == "interrupted"
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        owner.stop()
        observer.stop()


@pytest.mark.asyncio
async def test_manual_legacy_recovery_never_touches_owned_requests(client, tmp_path):
    user_id, key_id = await _identities()
    owned = await _insert(user_id, key_id, UsageRuntime(tmp_path).id, 7200)
    legacy = await _insert(user_id, key_id, None, 7200)
    await recover_stale_usage_logs()
    assert await _status(legacy) == "interrupted"
    assert await _status(owned) == "pending"


@pytest.mark.asyncio
async def test_two_recovery_processes_only_finalize_once(client, tmp_path):
    user_id, key_id = await _identities()
    owner = UsageRuntime(tmp_path)
    request_id = await _insert(user_id, key_id, owner.id, 1)
    results = await asyncio.gather(
        recover_abandoned_usage_logs(UsageRuntime(tmp_path)),
        recover_abandoned_usage_logs(UsageRuntime(tmp_path)),
    )
    assert sum(results) == 1
    assert await _status(request_id) == "interrupted"


@pytest.mark.asyncio
async def test_recovery_does_not_overwrite_a_late_terminal_commit(client, tmp_path, monkeypatch):
    user_id, key_id = await _identities()
    request_id = await _insert(user_id, key_id, UsageRuntime(tmp_path).id, 1)
    original_factory = usage_service.SessionLocal
    committed = False

    class InterleavedSession:
        def __init__(self):
            self.session = original_factory()

        async def __aenter__(self):
            await self.session.__aenter__()
            return self

        async def __aexit__(self, *args):
            return await self.session.__aexit__(*args)

        def __getattr__(self, name):
            return getattr(self.session, name)

        async def execute(self, statement):
            nonlocal committed
            if statement.is_update and not committed:
                committed = True
                async with original_factory() as finisher:
                    await finisher.execute(update(UsageLog).where(
                        UsageLog.request_id == request_id,
                    ).values(status="success"))
                    await finisher.commit()
            return await self.session.execute(statement)

    monkeypatch.setattr(usage_service, "SessionLocal", InterleavedSession)
    assert await recover_abandoned_usage_logs(UsageRuntime(tmp_path)) == 0
    assert committed
    assert await _status(request_id) == "success"
