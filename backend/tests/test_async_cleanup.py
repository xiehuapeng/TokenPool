import asyncio

import pytest

from app.utils.async_cleanup import run_cancellation_safe_cleanup


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
