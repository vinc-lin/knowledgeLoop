"""CBM client helpers + CBMClient behavior."""

import json
import pytest
from mcp.types import CallToolResult, TextContent

from repo_memory.graph.client import (
    CBMUnavailable, parse_tool_result, backoff_delays,
)


def _result(payload, is_error=False, structured=None):
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload))],
        isError=is_error, structuredContent=structured,
    )


def test_parse_prefers_structured_content():
    r = _result({"a": 1}, structured={"b": 2})
    assert parse_tool_result(r) == {"b": 2}


def test_parse_json_text():
    assert parse_tool_result(_result({"results": [1, 2]})) == {"results": [1, 2]}


def test_parse_raises_on_error():
    with pytest.raises(CBMUnavailable):
        parse_tool_result(_result({"msg": "boom"}, is_error=True))


def test_backoff_grows_and_caps():
    assert backoff_delays(1) == [0.5]
    assert backoff_delays(4) == [0.5, 1.0, 2.0, 4.0]
    assert backoff_delays(6, cap=4.0)[-1] == 4.0


from unittest.mock import AsyncMock
from repo_memory.graph.client import CBMClient


@pytest.mark.asyncio
async def test_call_tool_parses_and_passes_timeout():
    c = CBMClient(call_timeout=12.0)
    c._session = AsyncMock()
    c._session.call_tool = AsyncMock(return_value=_result({"ok": 1}))
    out = await c.call_tool("search_graph", {"label": "Function"})
    assert out == {"ok": 1}
    name, args = c._session.call_tool.await_args.args
    assert name == "search_graph"
    assert args == {"label": "Function"}
    kwargs = c._session.call_tool.await_args.kwargs
    assert kwargs["read_timeout_seconds"].total_seconds() == 12.0


@pytest.mark.asyncio
async def test_call_tool_without_session_raises():
    with pytest.raises(CBMUnavailable):
        await CBMClient().call_tool("x")


def test_default_command_is_uvx_cbm():
    c = CBMClient()
    assert c._params.command == "uvx"
    assert c._params.args == ["codebase-memory-mcp"]
