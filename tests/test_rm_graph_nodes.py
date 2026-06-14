"""CBM row -> NodeRecord and per-file enumeration with pagination."""

import pytest
from unittest.mock import AsyncMock

from repo_memory.bridge.schema import NodeRecord
from repo_memory.graph.nodes import row_to_node, enumerate_nodes_for_files


def test_row_to_node_uses_qn_as_id():
    n = row_to_node({"name": "Cfg", "qualified_name": "p.m.Cfg",
                     "file_path": "p/m.py", "start_line": 3, "end_line": 9})
    assert n == NodeRecord("p.m.Cfg", "Cfg", "p.m.Cfg", "p/m.py", 3, 9)


def test_row_to_node_defaults_missing_lines():
    n = row_to_node({"name": "X", "qualified_name": "X", "file_path": "x.py"})
    assert n.start_line == 0 and n.end_line == 0


@pytest.mark.asyncio
async def test_enumerate_paginates_and_dedups():
    pages = [
        {"results": [{"name": "A", "qualified_name": "m.A", "file_path": "m.py",
                      "start_line": 1, "end_line": 2}], "has_more": True},
        {"results": [{"name": "A", "qualified_name": "m.A", "file_path": "m.py",
                      "start_line": 1, "end_line": 2},
                     {"name": "B", "qualified_name": "m.B", "file_path": "m.py",
                      "start_line": 3, "end_line": 4}], "has_more": False},
    ]
    c = AsyncMock()
    c.call_tool_with_restart = AsyncMock(side_effect=pages)
    nodes = await enumerate_nodes_for_files(c, ["m.py"], project="p", page_size=1)
    qns = sorted(n.qualified_name for n in nodes)
    assert qns == ["m.A", "m.B"]  # deduped by qualified_name
    assert c.call_tool_with_restart.await_count == 2


from repo_memory.graph.nodes import CBMGraphProbe


@pytest.mark.asyncio
async def test_probe_prefetch_then_sync_lookup():
    found = {"results": [{"name": "Cfg", "qualified_name": "p.m.Cfg",
                          "file_path": "p/m.py", "start_line": 1, "end_line": 5}]}
    c = AsyncMock()
    c.call_tool_with_restart = AsyncMock(return_value=found)
    probe = CBMGraphProbe(c, project="p")
    await probe.prefetch(["p.m.Cfg"])
    node = probe.lookup("p.m.Cfg")
    assert node is not None and node.start_line == 1
    assert probe.lookup("p.m.Missing") is None  # not prefetched/found -> None


@pytest.mark.asyncio
async def test_probe_absent_node_not_cached():
    c = AsyncMock()
    c.call_tool_with_restart = AsyncMock(return_value={"results": []})
    probe = CBMGraphProbe(c, project="p")
    await probe.prefetch(["p.m.Gone"])
    assert probe.lookup("p.m.Gone") is None
