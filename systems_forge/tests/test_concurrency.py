import asyncio

import pytest

from systems_forge.concurrency import bounded_gather, race


@pytest.mark.asyncio
class TestBoundedGather:
    async def test_all_succeed(self):
        async def worker(x: int) -> int:
            return x * 2

        results = await bounded_gather([1, 2, 3], worker, max_concurrency=2)
        assert [r.result for r in results] == [2, 4, 6]
        assert all(r.ok for r in results)

    async def test_partial_failure_does_not_lose_other_results(self):
        async def worker(x: int) -> int:
            if x == 2:
                raise ValueError("bad item")
            return x * 10

        results = await bounded_gather([1, 2, 3], worker, max_concurrency=3)
        assert results[0].ok and results[0].result == 10
        assert not results[1].ok and isinstance(results[1].error, ValueError)
        assert results[2].ok and results[2].result == 30

    async def test_respects_concurrency_limit(self):
        in_flight = 0
        max_seen = 0

        async def worker(x: int) -> int:
            nonlocal in_flight, max_seen
            in_flight += 1
            max_seen = max(max_seen, in_flight)
            await asyncio.sleep(0.01)
            in_flight -= 1
            return x

        await bounded_gather(list(range(10)), worker, max_concurrency=3)
        assert max_seen <= 3

    async def test_falsy_result_is_not_confused_with_failure(self):
        async def worker(x: int) -> int:
            return 0  # a legitimate but falsy result

        results = await bounded_gather([1], worker)
        assert results[0].ok is True
        assert results[0].result == 0


@pytest.mark.asyncio
class TestRace:
    async def test_returns_first_success(self):
        async def fast():
            await asyncio.sleep(0.01)
            return "fast"

        async def slow():
            await asyncio.sleep(0.1)
            return "slow"

        result = await race(fast(), slow())
        assert result == "fast"

    async def test_skips_failures_and_returns_a_success(self):
        async def fails_fast():
            await asyncio.sleep(0.01)
            raise ValueError("nope")

        async def succeeds_slower():
            await asyncio.sleep(0.05)
            return "eventually"

        result = await race(fails_fast(), succeeds_slower())
        assert result == "eventually"

    async def test_raises_if_everything_fails(self):
        async def always_fails():
            raise ValueError("nope")

        with pytest.raises(ValueError):
            await race(always_fails(), always_fails())
