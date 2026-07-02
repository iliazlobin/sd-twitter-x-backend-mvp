"""Trending worker — background asyncio task: compute velocity scores every 60s."""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

StopFn = Callable[[], Coroutine[Any, Any, None]]


async def trending_worker_lifespan() -> StopFn:
    """Start the trending background task. Returns a stop callback."""

    stop_event = asyncio.Event()

    async def _run() -> None:
        while not stop_event.is_set():
            try:
                # TODO: staff task — implement trending computation
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                break

    task = asyncio.create_task(_run())

    async def _stop() -> None:
        stop_event.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    return _stop
