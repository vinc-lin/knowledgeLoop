"""Bounded refresh: re-index CBM + rebuild entity_map -> graph_commit==repo_head -> fresh."""

import pytest
from unittest.mock import AsyncMock

import repo_memory.refresh as R
from repo_memory.state import AppState
from repo_memory.wiki.loader import WikiData
from repo_memory.bridge.schema import EntityMap


def _state(cbm):
    wiki = WikiData({"m": {"path": "p", "components": [], "children": {}}}, {}, {}, "r", [])
    return AppState(wiki_dir="w", entity_map_path="e", repo_head="r", repo_path="/repo",
                    cbm=cbm, wiki=wiki, entity_map=None)


@pytest.mark.asyncio
async def test_refresh_reindexes_rebuilds_and_freshens(monkeypatch, tmp_path):
    cbm = AsyncMock()
    cbm.call_tool_with_restart = AsyncMock(return_value={"ok": 1})
    st = _state(cbm)
    st.entity_map_path = str(tmp_path / "entity_map.json")
    em = EntityMap("r", "r", "r", [])
    monkeypatch.setattr(R, "build_and_save", AsyncMock(return_value=em))
    monkeypatch.setattr(R.forward, "index_repository",
                        AsyncMock(return_value={"indexed": True, "project": "proj"}))
    e = await R.refresh(st)
    R.forward.index_repository.assert_awaited_once()
    assert e["result"]["reindexed"] is True
    assert e["result"]["graph_commit"] == "r"
    assert st.entity_map is em                # reloaded into state
    assert e["freshness"] == "fresh"


@pytest.mark.asyncio
async def test_refresh_degrades_without_cbm():
    st = _state(None)
    e = await R.refresh(st)
    assert e["result"] is None and any("CBM" in w for w in e["warnings"])
