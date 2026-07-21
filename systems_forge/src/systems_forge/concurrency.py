"""Structured concurrency helpers beyond what asyncio.TaskGroup gives you
out of the box: bounded fan-out (limit concurrency, don't launch 10,000
coroutines at once), and fan-out that collects partial results instead of
aborting everything on the first failure.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Generic, TypeVar

T = TypeVar("T")
R = TypeVar("R")


@dataclass
class TaskResult(Generic[R]):
    """Outcome of one item in a bounded_gather call. Exactly one of
    `result`/`error` is set — check `ok` rather than truthiness of either
    field, since a legitimate result can itself be falsy (0, "", None)."""

    item_index: int
    ok: bool
    result: R | None = None
    error: BaseException | None = None


async def bounded_gather(
    items: list[T],
    worker: Callable[[T], Awaitable[R]],
    max_concurrency: int = 10,
) -> list[TaskResult[R]]:
    """Run `worker` over every item with at most `max_concurrency` in
    flight at once, and — unlike asyncio.TaskGroup — collect every
    result/error rather than cancelling everything on the first failure.

    Use this for supervisor/worker fan-out where each item is independent
    and partial success is a legitimate, useful outcome (e.g. "47 of 50
    API calls succeeded, here are the 3 that failed and why"). Use
    TaskGroup instead when the operation is transactional and a single
    failure should abort the whole batch.
    """
    semaphore = asyncio.Semaphore(max_concurrency)

    async def run_one(index: int, item: T) -> TaskResult[R]:
        async with semaphore:
            try:
                result = await worker(item)
                return TaskResult(item_index=index, ok=True, result=result)
            except BaseException as exc:  # noqa: BLE001 — intentionally broad, see docstring
                return TaskResult(item_index=index, ok=False, error=exc)

    return await asyncio.gather(*(run_one(i, item) for i, item in enumerate(items)))


async def race(*coros: Awaitable[T]) -> T:
    """Return the first coroutine to complete successfully; cancels the
    rest. Different from asyncio.wait(FIRST_COMPLETED), which returns on
    the first to finish even if it raised — race() keeps waiting for a
    successful result unless every coroutine fails, in which case it
    re-raises the last error."""
    tasks = [asyncio.ensure_future(c) for c in coros]
    last_error: BaseException | None = None
    pending = set(tasks)
    try:
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task.exception() is None:
                    return task.result()
                last_error = task.exception()
        assert last_error is not None
        raise last_error
    finally:
        for task in pending:
            task.cancel()
