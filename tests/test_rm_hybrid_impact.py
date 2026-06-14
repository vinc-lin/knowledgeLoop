"""assess_impact: graph-grounding-only fail-closed gate + happy path."""

import pytest
from unittest.mock import AsyncMock

import repo_memory.tools.hybrid_tools as H
from repo_memory.state import AppState
from repo_memory.bridge.schema import EntityMap, ModuleMap, EntityEntry, NodeRecord


def _em(graph_commit="r", with_file=None):
    entries = []
    if with_file:
        entries = [EntityEntry("Sym", with_file, "m.Sym", [1, 9], "exact", 1.0)]
    return EntityMap("r", "w", graph_commit, [ModuleMap("mod", None, "p", entries, [])])


def _state(*, cbm=True, graph_commit="r", with_file=None):
    return AppState(wiki_dir="w", entity_map_path="e", repo_head="r",
                    cbm=(object() if cbm else None), entity_map=_em(graph_commit, with_file))


class _Probe:
    def __init__(self, present):
        self._p = present

    async def prefetch(self, qns):
        return None

    def lookup(self, qn):
        return self._p.get(qn)


def test_blocks_when_cbm_none():
    import asyncio
    e = asyncio.run(H.assess_impact(_state(cbm=False)))
    assert e["result"] is None and any("CBM" in w for w in e["warnings"])


def test_blocks_when_graph_stale():
    import asyncio
    e = asyncio.run(H.assess_impact(_state(graph_commit="OLD")))
    assert e["result"] is None and any("not current" in w for w in e["warnings"])


@pytest.mark.asyncio
async def test_blocks_when_detect_changes_fails(monkeypatch):
    from repo_memory.graph.client import CBMUnavailable
    monkeypatch.setattr(H.forward, "detect_changes", AsyncMock(side_effect=CBMUnavailable("boom")))
    e = await H.assess_impact(_state())
    assert e["result"] is None and any("boom" in w for w in e["warnings"])


@pytest.mark.asyncio
async def test_blocks_when_detect_changes_error_shape(monkeypatch):
    monkeypatch.setattr(H.forward, "detect_changes",
        AsyncMock(return_value={"error": "base 'nope' unresolved"}))
    e = await H.assess_impact(_state(), base_branch="nope")
    assert e["result"] is None and any("unresolved" in w for w in e["warnings"])


@pytest.mark.asyncio
async def test_blocks_when_symbol_unverifiable(monkeypatch):
    monkeypatch.setattr(H.forward, "detect_changes", AsyncMock(return_value={
        "changes": ["a.py"], "impacted": [{"qualified_name": "m.Gone", "risk": "high"}]}))
    monkeypatch.setattr(H, "CBMGraphProbe", lambda cbm: _Probe({}))  # nothing verifiable
    e = await H.assess_impact(_state())
    assert e["result"] is None and any("not verifiable" in w for w in e["warnings"])


@pytest.mark.asyncio
async def test_happy_path_with_and_without_module(monkeypatch):
    monkeypatch.setattr(H.forward, "detect_changes", AsyncMock(return_value={
        "changes": ["src/p.py", "src/x.py"],
        "impacted": [{"qualified_name": "m.Sym", "risk": "high"},
                     {"qualified_name": "m.Other", "risk": "low"}]}))
    nodes = {"m.Sym": NodeRecord("m.Sym", "Sym", "m.Sym", "src/p.py", 1, 9),
             "m.Other": NodeRecord("m.Other", "Other", "m.Other", "src/x.py", 1, 4)}
    monkeypatch.setattr(H, "CBMGraphProbe", lambda cbm: _Probe(nodes))
    e = await H.assess_impact(_state(with_file="src/p.py"))
    assert e["freshness"] == "fresh"
    imp = {i["symbol"]: i for i in e["result"]["impacted"]}
    assert imp["Sym"]["module"] == "mod" and imp["Sym"]["verified"] is True
    assert imp["Other"]["module"] is None
    assert e["result"]["blast_radius"] == 2
    assert any("no wiki module" in w for w in e["warnings"])
