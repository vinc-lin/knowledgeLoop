"""Thin async wrappers map to CBM tool names + args."""

import pytest
from unittest.mock import AsyncMock

from repo_memory.graph import forward


def _client(ret):
    c = AsyncMock()
    c.call_tool_with_restart = AsyncMock(return_value=ret)
    return c


@pytest.mark.asyncio
async def test_search_graph_args():
    c = _client({"results": [], "total": 0, "has_more": False})
    out = await forward.search_graph(c, name_pattern=".*X", label="Function",
                                     file_pattern="a/b.py", limit=50, offset=10)
    assert out["total"] == 0
    name, args = c.call_tool_with_restart.await_args.args
    assert name == "search_graph"
    assert args == {"name_pattern": ".*X", "label": "Function",
                    "file_pattern": "a/b.py", "limit": 50, "offset": 10}


@pytest.mark.asyncio
async def test_search_graph_omits_none_filters():
    c = _client({"results": []})
    await forward.search_graph(c, label="Class")
    _, args = c.call_tool_with_restart.await_args.args
    assert args == {"label": "Class", "limit": 200, "offset": 0}


@pytest.mark.asyncio
async def test_trace_and_snippet_and_arch():
    c = _client({"r": 1})
    await forward.trace_path(c, function_name="main", direction="inbound", depth=2)
    assert c.call_tool_with_restart.await_args.args == (
        "trace_path", {"function_name": "main", "direction": "inbound", "depth": 2})
    await forward.get_code_snippet(c, qualified_name="proj.mod.Cls")
    assert c.call_tool_with_restart.await_args.args == (
        "get_code_snippet", {"qualified_name": "proj.mod.Cls"})
    await forward.get_architecture(c)
    assert c.call_tool_with_restart.await_args.args == ("get_architecture", {})


@pytest.mark.asyncio
async def test_graph_schema_and_index_status():
    c = _client({"ok": 1})
    await forward.get_graph_schema(c)
    assert c.call_tool_with_restart.await_args.args == ("get_graph_schema", {})
    await forward.index_status(c)
    assert c.call_tool_with_restart.await_args.args == ("index_status", {})
    await forward.index_status(c, project="p")
    assert c.call_tool_with_restart.await_args.args == ("index_status", {"project": "p"})
