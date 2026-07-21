"""Tests the MCP server through the real FastMCP call_tool path (not by
importing the nested functions directly) — this exercises the actual
protocol boundary an agent calling this server would go through, including
argument validation and result serialization.
"""

import json

import pytest

from systems_forge.agents import mcp_server


def _unwrap(result: object) -> dict[str, object]:
    """call_tool's actual return shape in this SDK version is a tuple of
    (content_blocks, structured_output_dict) — verified by running it and
    reading the real result rather than assuming the type signature's
    `Sequence[ContentBlock] | dict[str, Any]` meant exactly one or the
    other. Handle the tuple first, then fall back for other shapes."""
    if isinstance(result, tuple):
        _, structured = result
        assert isinstance(structured, dict)
        return structured
    if isinstance(result, dict):
        return result
    block = result[0]  # type: ignore[index]
    text = getattr(block, "text", None)
    assert text is not None, f"unexpected content block shape: {block!r}"
    parsed = json.loads(text)
    assert isinstance(parsed, dict)
    return parsed


@pytest.fixture
def server():
    # build_server() module-level _budget/_spend_idempotency are shared
    # across the whole test module — reset them so tests don't leak state.
    mcp_server._budget.__init__(capacity=100.0, refill_rate=1.0)  # type: ignore[misc]
    mcp_server._spend_idempotency._entries.clear()
    return mcp_server.build_server()


@pytest.mark.asyncio
class TestMCPServer:
    async def test_check_budget_does_not_spend(self, server):
        first = _unwrap(await server.call_tool("check_budget", {}))
        second = _unwrap(await server.call_tool("check_budget", {}))
        assert first["remaining"] == second["remaining"]  # peek never consumes

    async def test_spend_budget_actually_decrements(self, server):
        before = _unwrap(await server.call_tool("check_budget", {}))
        await server.call_tool("spend_budget", {"amount": 10.0, "idempotency_key": "op-1"})
        after = _unwrap(await server.call_tool("check_budget", {}))
        assert after["remaining"] < before["remaining"]

    async def test_retrying_same_idempotency_key_does_not_double_spend(self, server):
        before = _unwrap(await server.call_tool("check_budget", {}))
        await server.call_tool("spend_budget", {"amount": 10.0, "idempotency_key": "retry-key"})
        mid = _unwrap(await server.call_tool("check_budget", {}))
        # simulate the caller retrying after a timeout with the SAME key
        await server.call_tool("spend_budget", {"amount": 10.0, "idempotency_key": "retry-key"})
        after = _unwrap(await server.call_tool("check_budget", {}))
        # The bucket refills continuously (refill_rate=1/sec), so `after` can
        # be a hair ABOVE `mid` just from elapsed wall-clock time between
        # calls — that's correct refill behavior, not a bug. What actually
        # proves no double-spend: `after` must NOT be ~10 lower than `mid`,
        # which is what a second real spend would produce.
        assert after["remaining"] >= mid["remaining"] - 0.5
        assert before["remaining"] - mid["remaining"] == pytest.approx(10.0, abs=0.5)

    async def test_different_idempotency_keys_each_spend(self, server):
        before = _unwrap(await server.call_tool("check_budget", {}))
        await server.call_tool("spend_budget", {"amount": 10.0, "idempotency_key": "key-a"})
        await server.call_tool("spend_budget", {"amount": 10.0, "idempotency_key": "key-b"})
        after = _unwrap(await server.call_tool("check_budget", {}))
        assert before["remaining"] - after["remaining"] == pytest.approx(20.0, abs=0.5)

    async def test_tools_are_registered_with_expected_names(self, server):
        tools = await server.list_tools()
        names = {t.name for t in tools}
        assert {"check_budget", "spend_budget"} <= names
