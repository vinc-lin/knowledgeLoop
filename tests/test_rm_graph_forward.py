"""Thin async wrappers map to CBM tool names + args (CBM 0.8.1: project required)."""

import pytest
from unittest.mock import AsyncMock

from repo_memory.graph import forward


def _client(ret):
    c = AsyncMock()
    c.call_tool_with_restart = AsyncMock(return_value=ret)
    return c


@pytest.mark.asyncio
async def test_search_graph_args_include_project():
    c = _client({"results": [], "total": 0, "has_more": False})
    out = await forward.search_graph(c, project="proj", name_pattern=".*X", label="Function",
                                     file_pattern="a/b.py", limit=50, offset=10)
    assert out["total"] == 0
    name, args = c.call_tool_with_restart.await_args.args
    assert name == "search_graph"
    assert args == {"name_pattern": ".*X", "label": "Function", "file_pattern": "a/b.py",
                    "project": "proj", "limit": 50, "offset": 10}


@pytest.mark.asyncio
async def test_search_graph_omits_none_filters_keeps_project():
    c = _client({"results": []})
    await forward.search_graph(c, project="proj", label="Class")
    _, args = c.call_tool_with_restart.await_args.args
    assert args == {"label": "Class", "project": "proj", "limit": 200, "offset": 0}


@pytest.mark.asyncio
async def test_trace_snippet_arch_pass_project():
    c = _client({"r": 1})
    await forward.trace_path(c, project="p", function_name="main", direction="inbound", depth=2)
    assert c.call_tool_with_restart.await_args.args == (
        "trace_path", {"project": "p", "function_name": "main", "direction": "inbound", "depth": 2})
    await forward.get_code_snippet(c, project="p", qualified_name="proj.mod.Cls")
    assert c.call_tool_with_restart.await_args.args == (
        "get_code_snippet", {"project": "p", "qualified_name": "proj.mod.Cls"})
    await forward.get_architecture(c, project="p")
    assert c.call_tool_with_restart.await_args.args == ("get_architecture", {"project": "p"})


@pytest.mark.asyncio
async def test_schema_status_and_detect_pass_project():
    c = _client({"ok": 1})
    await forward.get_graph_schema(c, project="p")
    assert c.call_tool_with_restart.await_args.args == ("get_graph_schema", {"project": "p"})
    await forward.index_status(c, project="p")
    assert c.call_tool_with_restart.await_args.args == ("index_status", {"project": "p"})
    await forward.detect_changes(c, project="p", base_branch="main")
    assert c.call_tool_with_restart.await_args.args == (
        "detect_changes", {"project": "p", "base_branch": "main"})
    await forward.detect_changes(c, project="p")
    assert c.call_tool_with_restart.await_args.args == ("detect_changes", {"project": "p"})


@pytest.mark.asyncio
async def test_index_repository_uses_repo_path_and_returns_project():
    c = _client({"project": "derived-name", "status": "indexed"})
    out = await forward.index_repository(c, repo_path="/abs/repo")
    assert out["project"] == "derived-name"
    assert c.call_tool_with_restart.await_args.args == (
        "index_repository", {"repo_path": "/abs/repo"})


@pytest.mark.asyncio
async def test_list_projects():
    c = _client({"projects": [{"name": "n", "root_path": "/r"}]})
    out = await forward.list_projects(c)
    assert out["projects"][0]["name"] == "n"
    assert c.call_tool_with_restart.await_args.args == ("list_projects", {})
