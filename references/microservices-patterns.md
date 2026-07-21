# Microservices Resilience Patterns

A service that only handles the happy path works in the demo and pages someone in production. Every pattern here
exists to answer one question: what happens when the thing you depend on is slow, down, or half-failed?

## Circuit breaker

**Problem:** a dependency is down, and every caller keeps hitting it anyway, each one waiting out a full timeout,
piling up latency and exhausting connection pools across the whole system for a dependency that was never going
to answer.

```python
import time
from enum import Enum

class State(Enum):
    CLOSED = "closed"      # normal operation
    OPEN = "open"           # failing, reject immediately
    HALF_OPEN = "half_open"  # probing to see if it recovered

class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.state = State.CLOSED
        self.opened_at: float | None = None

    def call(self, fn, *args, **kwargs):
        if self.state == State.OPEN:
            if time.monotonic() - self.opened_at >= self.recovery_timeout:
                self.state = State.HALF_OPEN
            else:
                raise RuntimeError("circuit open, failing fast")
        try:
            result = fn(*args, **kwargs)
        except Exception:
            self.failures += 1
            if self.failures >= self.failure_threshold:
                self.state = State.OPEN
                self.opened_at = time.monotonic()
            raise
        else:
            self.failures = 0
            self.state = State.CLOSED
            return result
```
**The subtle bug to watch for** (a real one, not hypothetical): the half-open state allows exactly one probe
request through. If something *else* denies that same request before it reaches the dependency (a rate limiter,
a guardrail, an auth check), the breaker never finds out whether the probe succeeded or failed — because
`RecordOutcome`/its equivalent never gets called. Left unhandled, this wedges the breaker in half-open forever,
serving failures to everything with no path back to closed short of a process restart. The fix is a neutral
"release" path for exactly this case: a denial by something *other* than the dependency itself must release the
probe slot without counting as success or failure, since the probe never actually tested the upstream.

## Retry with exponential backoff + jitter

**Problem:** naive retries (`sleep(1)`, `sleep(2)`, `sleep(4)`, same schedule for every client) cause every
retrying client to converge on the same retry moment — a thundering herd that looks exactly like the outage that
caused the retries in the first place, just delayed.

```python
import random
import time

def retry_with_backoff(fn, max_attempts=5, base_delay=1.0, max_delay=30.0):
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception:
            if attempt == max_attempts - 1:
                raise
            delay = min(max_delay, base_delay * (2 ** attempt))
            delay = delay * (0.5 + random.random() * 0.5)  # jitter: 50-100% of computed delay
            time.sleep(delay)
```
The jitter line is the part naive implementations skip — without it, "exponential backoff" just makes the herd
converge less often but no less severely when it does.

## Idempotency keys

**Problem:** a client's request times out, it retries, but the first request actually succeeded server-side — a
payment gets charged twice, a job gets enqueued twice.

```python
def handle_request(idempotency_key: str, payload: dict) -> dict:
    existing = idempotency_store.get(idempotency_key)
    if existing is not None:
        return existing  # already processed, return the prior result, don't redo the side effect
    result = do_the_actual_work(payload)
    idempotency_store.set(idempotency_key, result, ttl=86400)
    return result
```
The client generates the key (usually a UUID) once per logical operation and sends the same key on every retry
of that same operation — the server's job is just to remember which keys it's already handled and return the
cached result instead of repeating the side effect. This is the same discipline an agentic tool-call loop needs:
an LLM retrying a tool call after a timeout has no idea whether the first call completed.

## Saga pattern — distributed transactions without a shared database transaction

**Problem:** a logical operation spans multiple services (charge a payment, reserve inventory, schedule a
shipment) and there's no single database transaction that can wrap all three atomically.

Two shapes: **orchestrated** (a central coordinator calls each step in order and calls compensating actions on
failure) or **choreographed** (each service listens for events and reacts, no central coordinator). Orchestrated
is easier to reason about and debug (one place to look); choreographed scales better with fewer services coupled
to a central point, at the cost of the overall flow being implicit, scattered across event handlers.

```python
class PaymentSaga:
    def execute(self, order):
        completed_steps = []
        try:
            charge_id = self.charge_payment(order)
            completed_steps.append(("payment", charge_id))
            reservation_id = self.reserve_inventory(order)
            completed_steps.append(("inventory", reservation_id))
            self.schedule_shipment(order)
        except Exception:
            for step, ref_id in reversed(completed_steps):
                self.compensate(step, ref_id)  # refund, release reservation, etc — in REVERSE order
            raise
```
Compensating actions run in reverse order of the original steps — this matters when later steps assumed earlier
ones succeeded (releasing an inventory reservation before refunding a payment that reservation depended on can
leave a window where inventory looks free but the payment hasn't actually been reversed yet).

## Bulkhead — isolate failure domains

**Problem:** one slow dependency exhausts a shared connection pool or thread pool, starving requests to every
*other* dependency that would otherwise be healthy.

```python
from concurrent.futures import ThreadPoolExecutor

pools = {
    "payments": ThreadPoolExecutor(max_workers=10),
    "inventory": ThreadPoolExecutor(max_workers=10),
    "notifications": ThreadPoolExecutor(max_workers=5),
}
# a hung "notifications" call can exhaust its own 5-worker pool, but payments/inventory keep working
```
Named after ship bulkheads: a hull breach in one compartment doesn't sink the whole ship. The pattern is the
same at any granularity — separate connection pools, separate thread pools, or separate deployed instances per
dependency, so one dependency's outage is contained to its own slice of capacity.

## Outbox pattern — atomic write + publish across systems

**Problem:** you need to both write to your database *and* publish an event to a message queue as one atomic
unit, but the database and the queue are different systems with no shared transaction.

Write the event into a table in the *same* database transaction as the actual data change; a separate poller (or
change-data-capture stream) reads unpublished rows from that table and publishes them to the real queue,
marking them published once the publish succeeds. The event write can never "succeed but the publish get lost"
because the event write is part of the same transaction as the data change it describes — it either both commit
or neither does.

## Backpressure — explicit is better than silent degradation

**Problem:** load exceeds capacity, and without an explicit policy, the system degrades implicitly — everything
just gets slower and slower until every request times out, which is a worse failure mode than a clean, fast
rejection.

Pick one, explicitly, rather than defaulting into the first by accident:
- **Reject immediately** (HTTP 429, a specific error) once queued work exceeds a threshold — the caller finds
  out fast and can retry elsewhere or back off.
- **Bounded queue** — accept up to a limit, reject beyond it, rather than an unbounded queue that just grows
  until the process runs out of memory.
- **Load shedding by priority** — under pressure, drop low-priority work first (background jobs, best-effort
  analytics) to keep capacity for the requests that actually matter.

## Health checks vs readiness checks — a distinction that matters

A **liveness/health check** answers "is this process alive at all" (should it be restarted?). A **readiness
check** answers "can this instance currently serve traffic" (should the load balancer route to it right now?).
Conflating them is a real production bug: a service that's alive but still warming up its cache, or draining
in-flight requests before shutdown, should fail readiness (stop receiving *new* traffic) without failing
liveness (getting killed and restarted mid-drain, which is worse than just waiting).
