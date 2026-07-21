"""Production resilience primitives: circuit breaker, rate limiting, retry,
idempotency. Each is a small, dependency-free, fully typed implementation
meant to be imported directly, not retyped from a reference doc.
"""

from __future__ import annotations

import asyncio
import random
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, Generic, Hashable, TypeVar

T = TypeVar("T")

# ─────────────────────────────────────────────────────────────────────────
# Circuit breaker
# ─────────────────────────────────────────────────────────────────────────


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    """Raised when a call is rejected because the circuit is open."""


class CircuitBreaker:
    """Thread-safe circuit breaker.

    Trips OPEN after `failure_threshold` consecutive failures, rejects calls
    immediately while open, then allows exactly one HALF_OPEN probe after
    `recovery_timeout` seconds to test whether the dependency has recovered.

    The `release_probe()` method exists for a real, easy-to-miss bug: if
    something OTHER than the wrapped call denies the half-open probe request
    (a rate limiter, an auth check, a guardrail upstream of this breaker),
    `call()` never runs and never records an outcome — the breaker would
    stay wedged in HALF_OPEN forever with no path back to CLOSED. Call
    `release_probe()` from that denial path so the breaker knows the probe
    slot is free again, without counting it as a success or a failure (the
    dependency itself was never actually tested).
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failures = 0
        self._state = CircuitState.CLOSED
        self._opened_at: float | None = None
        self._probe_in_flight = False
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._maybe_transition_to_half_open()
            return self._state

    def _maybe_transition_to_half_open(self) -> None:
        if (
            self._state is CircuitState.OPEN
            and self._opened_at is not None
            and time.monotonic() - self._opened_at >= self.recovery_timeout
        ):
            self._state = CircuitState.HALF_OPEN

    def _acquire(self) -> None:
        with self._lock:
            self._maybe_transition_to_half_open()
            if self._state is CircuitState.OPEN:
                raise CircuitOpenError("circuit open, failing fast")
            if self._state is CircuitState.HALF_OPEN:
                if self._probe_in_flight:
                    raise CircuitOpenError("probe already in flight")
                self._probe_in_flight = True

    def _record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._state = CircuitState.CLOSED
            self._probe_in_flight = False

    def _record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            self._probe_in_flight = False
            if self._state is CircuitState.HALF_OPEN or self._failures >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()

    def release_probe(self) -> None:
        """Call when a half-open probe was denied by something other than
        the wrapped dependency (a rate limiter, guardrail, auth check) —
        frees the probe slot without recording success or failure."""
        with self._lock:
            self._probe_in_flight = False

    def call(self, fn: Callable[[], T]) -> T:
        self._acquire()
        try:
            result = fn()
        except Exception:
            self._record_failure()
            raise
        else:
            self._record_success()
            return result


# ─────────────────────────────────────────────────────────────────────────
# Token bucket rate limiter
# ─────────────────────────────────────────────────────────────────────────


class TokenBucket:
    """Thread-safe token bucket: allows bursts up to `capacity`, refills at
    `refill_rate` tokens/second. The RFC-standard shape used by most
    production rate limiters: tokens = min(capacity, tokens + elapsed * rate).
    """

    def __init__(self, capacity: float, refill_rate: float):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._tokens = capacity
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def allow(self, cost: float = 1.0) -> bool:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)
            self._last_refill = now
            if self._tokens >= cost:
                self._tokens -= cost
                return True
            return False

    def peek(self) -> float:
        """Read current token count WITHOUT consuming. Kept as a distinct
        method from allow() on purpose — a peek that accidentally consumed
        would be exactly the peek/consume conflation bug this skill warns
        about for agent tool design."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            return min(self.capacity, self._tokens + elapsed * self.refill_rate)


# ─────────────────────────────────────────────────────────────────────────
# Retry with backoff (sync + async)
# ─────────────────────────────────────────────────────────────────────────


def retry_with_backoff(
    fn: Callable[[], T],
    max_attempts: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retry_on: type[Exception] | tuple[type[Exception], ...] = Exception,
) -> T:
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    for attempt in range(max_attempts):
        try:
            return fn()
        except retry_on:
            if attempt == max_attempts - 1:
                raise
            delay = min(max_delay, base_delay * (2**attempt))
            delay *= 0.5 + random.random() * 0.5  # jitter: 50-100% of computed delay
            time.sleep(delay)
    raise AssertionError("unreachable: last attempt always returns or re-raises")


async def async_retry_with_backoff(
    fn: Callable[[], Awaitable[T]],
    max_attempts: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retry_on: type[Exception] | tuple[type[Exception], ...] = Exception,
) -> T:
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    for attempt in range(max_attempts):
        try:
            return await fn()
        except retry_on:
            if attempt == max_attempts - 1:
                raise
            delay = min(max_delay, base_delay * (2**attempt))
            delay *= 0.5 + random.random() * 0.5
            await asyncio.sleep(delay)
    raise AssertionError("unreachable: last attempt always returns or re-raises")


# ─────────────────────────────────────────────────────────────────────────
# Idempotency store
# ─────────────────────────────────────────────────────────────────────────

K = TypeVar("K", bound=Hashable)


@dataclass
class _Entry(Generic[T]):
    value: T
    expires_at: float


class IdempotencyStore(Generic[K, T]):
    """In-memory idempotency-key store: the same key returns the same
    cached result instead of re-running the side effect. A caller (an HTTP
    client retrying a timeout, or an LLM retrying a tool call after a
    timeout) sends the same key on every retry of the same logical
    operation; the server's job is to remember which keys it already
    handled. For multi-process use, back this with Redis/a real store using
    the same interface instead of the in-memory dict here.
    """

    def __init__(self, ttl_seconds: float = 86400.0):
        self.ttl_seconds = ttl_seconds
        self._entries: dict[K, _Entry[T]] = {}
        self._lock = threading.Lock()

    def get_or_compute(self, key: K, compute: Callable[[], T]) -> T:
        with self._lock:
            self._evict_expired()
            entry = self._entries.get(key)
            if entry is not None:
                return entry.value
        # compute outside the lock — side effect may be slow, don't block other keys
        result = compute()
        with self._lock:
            self._entries[key] = _Entry(value=result, expires_at=time.monotonic() + self.ttl_seconds)
        return result

    def _evict_expired(self) -> None:
        now = time.monotonic()
        expired = [k for k, e in self._entries.items() if e.expires_at < now]
        for k in expired:
            del self._entries[k]
