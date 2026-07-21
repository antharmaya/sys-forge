"""A real supervisor/worker multi-agent orchestrator: dispatches independent
subtasks to a bounded pool of workers, retries failed subtasks individually,
and returns a per-subtask result instead of losing everything on one
failure. This is the orchestration shape that fits genuinely independent,
parallelizable work — a broad research sweep, a refactor across many files,
fanning a question out across N agents.

For work that's transactional (a single failure should abort the whole
batch), use asyncio.TaskGroup directly instead — this module is deliberately
for the opposite case.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Generic, TypeVar

from systems_forge.concurrency import bounded_gather
from systems_forge.resilience import async_retry_with_backoff

T = TypeVar("T")
R = TypeVar("R")


@dataclass
class SubtaskResult(Generic[T, R]):
    subtask: T
    ok: bool
    output: R | None = None
    error: str | None = None
    attempts: int = 0


class Orchestrator(Generic[T, R]):
    """Supervisor over a pool of workers executing independent subtasks.

    `worker` is your agent-calling coroutine — e.g. a function that spawns
    a subagent with a task-specific prompt and returns its structured
    output. This class owns the orchestration (concurrency limits, retry,
    result collection); it does not know or care what the worker actually
    does, which is what lets the same orchestrator serve a code-review
    fan-out, a research sweep, or a batch of independent API calls alike.
    """

    def __init__(
        self,
        worker: Callable[[T], Awaitable[R]],
        max_concurrency: int = 5,
        max_retries_per_subtask: int = 1,
    ):
        self.worker = worker
        self.max_concurrency = max_concurrency
        self.max_retries_per_subtask = max_retries_per_subtask

    async def run(self, subtasks: list[T]) -> list[SubtaskResult[T, R]]:
        async def run_with_retry(subtask: T) -> SubtaskResult[T, R]:
            attempts = 0

            async def attempt() -> R:
                nonlocal attempts
                attempts += 1
                return await self.worker(subtask)

            try:
                output = await async_retry_with_backoff(
                    attempt,
                    max_attempts=self.max_retries_per_subtask + 1,
                    base_delay=0.5,
                )
                return SubtaskResult(subtask=subtask, ok=True, output=output, attempts=attempts)
            except Exception as exc:
                return SubtaskResult(subtask=subtask, ok=False, error=str(exc), attempts=attempts)

        results = await bounded_gather(subtasks, run_with_retry, max_concurrency=self.max_concurrency)
        # bounded_gather wraps in TaskResult even though run_with_retry never
        # raises (it catches internally) — unwrap the always-ok outer layer.
        return [r.result for r in results if r.result is not None]

    @staticmethod
    def summarize(results: list[SubtaskResult[T, R]]) -> str:
        succeeded = sum(1 for r in results if r.ok)
        failed = [r for r in results if not r.ok]
        lines = [f"{succeeded}/{len(results)} subtasks succeeded"]
        for r in failed:
            lines.append(f"  FAILED after {r.attempts} attempt(s): {r.subtask!r} — {r.error}")
        return "\n".join(lines)
