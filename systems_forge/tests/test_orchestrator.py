import pytest

from systems_forge.agents.orchestrator import Orchestrator


@pytest.mark.asyncio
class TestOrchestrator:
    async def test_all_subtasks_succeed(self):
        async def worker(task: str) -> str:
            return f"done: {task}"

        orch = Orchestrator(worker, max_concurrency=2)
        results = await orch.run(["a", "b", "c"])
        assert [r.ok for r in results] == [True, True, True]
        assert [r.output for r in results] == ["done: a", "done: b", "done: c"]
        assert all(r.attempts == 1 for r in results)  # no retries needed

    async def test_one_subtask_fails_others_still_reported(self):
        async def worker(task: str) -> str:
            if task == "b":
                raise RuntimeError("b always fails")
            return f"done: {task}"

        orch = Orchestrator(worker, max_concurrency=3, max_retries_per_subtask=0)
        results = await orch.run(["a", "b", "c"])
        by_task = {r.subtask: r for r in results}
        assert by_task["a"].ok and by_task["a"].output == "done: a"
        assert not by_task["b"].ok and "b always fails" in (by_task["b"].error or "")
        assert by_task["c"].ok and by_task["c"].output == "done: c"

    async def test_retries_a_flaky_subtask_before_giving_up(self):
        calls: dict[str, int] = {}

        async def worker(task: str) -> str:
            calls[task] = calls.get(task, 0) + 1
            if task == "flaky" and calls[task] < 3:
                raise RuntimeError("transient")
            return f"done: {task}"

        orch = Orchestrator(worker, max_concurrency=1, max_retries_per_subtask=3)
        results = await orch.run(["flaky"])
        assert results[0].ok
        assert results[0].output == "done: flaky"
        assert results[0].attempts == 3

    async def test_summarize_reports_failures_with_reason(self):
        async def worker(task: str) -> str:
            if task == "bad":
                raise RuntimeError("boom")
            return "ok"

        orch = Orchestrator(worker, max_retries_per_subtask=0)
        results = await orch.run(["good", "bad"])
        summary = Orchestrator.summarize(results)
        assert "1/2 subtasks succeeded" in summary
        assert "'bad'" in summary
        assert "boom" in summary
