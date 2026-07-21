import time

import pytest

from systems_forge.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    IdempotencyStore,
    TokenBucket,
    async_retry_with_backoff,
    retry_with_backoff,
)


class TestTokenBucket:
    def test_allows_burst_up_to_capacity(self):
        bucket = TokenBucket(capacity=3, refill_rate=1000)  # fast refill irrelevant to burst check
        results = [bucket.allow() for _ in range(5)]
        assert results == [True, True, True, False, False]

    def test_refills_over_time(self):
        bucket = TokenBucket(capacity=1, refill_rate=1000)  # ~1 token/ms
        assert bucket.allow() is True
        assert bucket.allow() is False
        time.sleep(0.01)
        assert bucket.allow() is True

    def test_peek_does_not_consume(self):
        bucket = TokenBucket(capacity=5, refill_rate=1)
        before = bucket.peek()
        bucket.peek()
        bucket.peek()
        after = bucket.peek()
        assert before == after  # multiple peeks never change the count
        assert bucket.allow() is True  # a token is still there to consume


class TestCircuitBreaker:
    def test_stays_closed_under_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10)
        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(lambda: (_ for _ in ()).throw(ValueError()))
        assert cb.state == CircuitState.CLOSED

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10)
        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(lambda: (_ for _ in ()).throw(ValueError()))
        assert cb.state == CircuitState.OPEN
        with pytest.raises(CircuitOpenError):
            cb.call(lambda: "should not run")

    def test_half_open_probe_recovers_on_success(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError()))
        assert cb.state == CircuitState.OPEN
        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN
        result = cb.call(lambda: "recovered")
        assert result == "recovered"
        assert cb.state == CircuitState.CLOSED

    def test_half_open_probe_reopens_on_failure(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError()))
        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError()))
        assert cb.state == CircuitState.OPEN

    def test_release_probe_does_not_count_as_failure(self):
        """The bug this guards against: something upstream (a rate limiter,
        an auth check) denies the half-open probe before the dependency is
        ever called. Without release_probe(), the breaker stays wedged in
        HALF_OPEN forever with no path back to CLOSED."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError()))
        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN
        cb.release_probe()  # simulates: upstream denied the probe, not the dependency
        assert cb.state == CircuitState.HALF_OPEN  # still recoverable, not stuck open
        result = cb.call(lambda: "recovered")
        assert result == "recovered"
        assert cb.state == CircuitState.CLOSED


class TestRetryWithBackoff:
    def test_succeeds_after_transient_failures(self):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("transient")
            return "success"

        result = retry_with_backoff(flaky, max_attempts=5, base_delay=0.001)
        assert result == "success"
        assert calls["n"] == 3

    def test_raises_after_exhausting_attempts(self):
        def always_fails():
            raise RuntimeError("permanent")

        with pytest.raises(RuntimeError, match="permanent"):
            retry_with_backoff(always_fails, max_attempts=3, base_delay=0.001)

    def test_rejects_zero_attempts(self):
        with pytest.raises(ValueError):
            retry_with_backoff(lambda: "x", max_attempts=0)

    def test_only_retries_specified_exception_type(self):
        def raises_type_error():
            raise TypeError("not retryable here")

        with pytest.raises(TypeError):
            retry_with_backoff(raises_type_error, max_attempts=3, base_delay=0.001, retry_on=ValueError)


class TestAsyncRetryWithBackoff:
    @pytest.mark.asyncio
    async def test_succeeds_after_transient_failures(self):
        calls = {"n": 0}

        async def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("transient")
            return "success"

        result = await async_retry_with_backoff(flaky, max_attempts=5, base_delay=0.001)
        assert result == "success"
        assert calls["n"] == 3


class TestIdempotencyStore:
    def test_same_key_returns_cached_result_without_recomputing(self):
        store: IdempotencyStore[str, int] = IdempotencyStore()
        calls = {"n": 0}

        def compute():
            calls["n"] += 1
            return 42

        first = store.get_or_compute("key-1", compute)
        second = store.get_or_compute("key-1", compute)
        assert first == second == 42
        assert calls["n"] == 1  # NOT recomputed on the second call

    def test_different_keys_compute_independently(self):
        store: IdempotencyStore[str, str] = IdempotencyStore()
        assert store.get_or_compute("a", lambda: "result-a") == "result-a"
        assert store.get_or_compute("b", lambda: "result-b") == "result-b"

    def test_expired_entry_is_recomputed(self):
        store: IdempotencyStore[str, int] = IdempotencyStore(ttl_seconds=0.01)
        calls = {"n": 0}

        def compute():
            calls["n"] += 1
            return calls["n"]

        first = store.get_or_compute("key", compute)
        time.sleep(0.02)
        second = store.get_or_compute("key", compute)
        assert first == 1
        assert second == 2  # recomputed after TTL expiry
