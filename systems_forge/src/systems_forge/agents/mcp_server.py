"""A real, runnable MCP server demonstrating the two rules from
references/agentic-patterns.md that most MCP tool designs get wrong:

1. Peek and consume are different tools, never conflated in one — a tool
   that only checks state must never have the side effect of a tool that
   consumes it.
2. Every side-effecting tool needs an idempotency story — the calling
   agent will retry a timed-out call without knowing whether it completed.

Run it directly to smoke-test over stdio:
    uv run python -m systems_forge.agents.mcp_server

Or import `build_server()` and mount it inside a larger application.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from systems_forge.resilience import IdempotencyStore, TokenBucket

# A shared budget the two tools below both operate on — swap this for a
# real store (Redis, a database row) in a multi-process deployment; the
# peek/consume contract is what matters, not the storage backend.
_budget = TokenBucket(capacity=100.0, refill_rate=1.0)  # 100 burst, 1/sec refill
_spend_idempotency: IdempotencyStore[str, dict[str, object]] = IdempotencyStore(ttl_seconds=3600)


def build_server() -> FastMCP:
    mcp = FastMCP(
        name="systems-forge-budget-demo",
        instructions=(
            "Demonstrates peek-vs-consume tool separation and idempotent "
            "side-effecting tools for agent budget enforcement."
        ),
    )

    @mcp.tool()
    def check_budget() -> dict[str, float]:
        """PEEK — read-only. Returns remaining budget WITHOUT spending
        anything. Safe to call as often as needed before deciding whether
        to proceed with an action."""
        return {"remaining": _budget.peek(), "capacity": _budget.capacity}

    @mcp.tool()
    def spend_budget(amount: float, idempotency_key: str) -> dict[str, object]:
        """CONSUME — has a side effect. Spends `amount` from the budget.
        Pass the SAME idempotency_key on every retry of the same logical
        action (e.g. a UUID generated once per action, not once per HTTP
        call) — a retried call with a key already seen returns the
        original result instead of spending twice."""

        def do_spend() -> dict[str, object]:
            allowed = _budget.allow(cost=amount)
            return {"allowed": allowed, "remaining": _budget.peek()}

        return _spend_idempotency.get_or_compute(idempotency_key, do_spend)

    return mcp


if __name__ == "__main__":
    build_server().run()
