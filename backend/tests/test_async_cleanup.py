import asyncio

import pytest

from app.utils.async_cleanup import drain_cleanup_tasks, run_cancellation_safe_cleanup


@pytest.mark.asyncio
async def test_cleanup_finishes_after_owner_is_cancelled():
    owner_started = asyncio.Event()
    cleanup_finished = asyncio.Event()

    async def cleanup() -> None:
        await asyncio.sleep(0.02)
        cleanup_finished.set()

    async def response_task() -> None:
        try:
            owner_started.set()
            await asyncio.Event().wait()
        finally:
            await run_cancellation_safe_cleanup(cleanup())

    owner = asyncio.create_task(response_task())
    await owner_started.wait()
    owner.cancel()

    with pytest.raises(asyncio.CancelledError):
        await owner

    await asyncio.wait_for(cleanup_finished.wait(), timeout=1)


@pytest.mark.asyncio
async def test_lifespan_drain_waits_for_detached_audits():
    started = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()

    async def cleanup():
        started.set()
        await release.wait()
        finished.set()

    owner = asyncio.create_task(run_cancellation_safe_cleanup(cleanup()))
    await started.wait()
    owner.cancel()
    await owner
    drain = asyncio.create_task(drain_cleanup_tasks())
    await asyncio.sleep(0)
    assert not drain.done()
    release.set()
    await asyncio.wait_for(drain, timeout=1)
    assert finished.is_set()
