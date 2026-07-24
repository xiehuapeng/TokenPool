import asyncio
import logging
from collections.abc import Awaitable


logger = logging.getLogger(__name__)
_active_cleanup_tasks: set[asyncio.Task[None]] = set()


def _cleanup_finished(task: asyncio.Task[None]) -> None:
    _active_cleanup_tasks.discard(task)
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.error(
            "Background stream cleanup failed: %s",
            type(error).__name__,
        )


async def run_cancellation_safe_cleanup(cleanup: Awaitable[None]) -> None:
    """Run cleanup independently from a cancelled SSE request task.

    Starlette cancels the response task when an SSE client disconnects. Any
    awaited database work in that task can be cancelled again by the enclosing
    cancel scope. A separately tracked task is allowed to finish even when the
    caller is already being cancelled.
    """

    task = asyncio.create_task(cleanup)
    _active_cleanup_tasks.add(task)
    task.add_done_callback(_cleanup_finished)
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        # The caller's cancellation continues after its finally block. The
        # tracked cleanup task remains alive and persists the terminal status.
        return
