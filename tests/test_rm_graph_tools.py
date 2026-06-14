"""Forwarded graph tools wrap CBM results in the envelope; degrade when CBM is down."""

import pytest
from unittest.mock import AsyncMock

from repo_memory.state import AppState
from repo_memory.graph.client import CBMUnavailable
from repo_memory.tools import graph_tools


def _state(cbm):
    return AppState(wiki_dir="w", entity_map_path="e", repo_head="r", project="p", cbm=cbm)


@pytest.mark.asyncio
async def test_search_code_graph_wraps_result():
    cbm = AsyncMock()
    cbm.call_tool_with_restart = AsyncMock(return_value={"results": [{"name": "X"}], "total": 1})
    e = await graph_tools.search_code_graph(_state(cbm), name_pattern=".*X")
    assert e["result"]["total"] == 1
    assert e["provenance"]["repo_head"] == "r"


@pytest.mark.asyncio
async def test_degrades_when_cbm_none():
    e = await graph_tools.search_code_graph(_state(None), name_pattern=".*")
    assert e["result"] is None and e["warnings"]


@pytest.mark.asyncio
async def test_degrades_on_cbm_error():
    cbm = AsyncMock()
    cbm.call_tool_with_restart = AsyncMock(side_effect=CBMUnavailable("down"))
    e = await graph_tools.trace_symbol(_state(cbm), function_name="main")
    assert e["result"] is None and any("CBM" in w for w in e["warnings"])
