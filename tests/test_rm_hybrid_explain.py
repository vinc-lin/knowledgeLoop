"""explain_with_sources: narrative + multiple grounded evidence snippets."""

import pytest
from unittest.mock import AsyncMock

import repo_memory.tools.hybrid_tools as H
from repo_memory.state import AppState
from repo_memory.wiki.loader import WikiData


def _wiki():
    return WikiData(
        module_tree={"ingestion": {"path": "src/ingest", "components": [], "children": {}}},
        metadata={}, docs={"ingestion.md": "# Ingestion\n"}, wiki_commit="c",
        files_generated=["ingestion.md"])


def _state():
    return AppState(wiki_dir="w", entity_map_path="e", repo_head="r", cbm=object(), wiki=_wiki())


@pytest.mark.asyncio
async def test_entity_map_grounding(monkeypatch):
    monkeypatch.setattr(H, "search_wiki",
        lambda state, q: {"result": [{"doc": "ingestion.md", "snippet": "narrative text"}],
                          "warnings": []})
    monkeypatch.setattr(H.bridge_tools, "get_related_files", AsyncMock(return_value={
        "result": {"module": "ingestion", "files": ["src/ingest/p.py"],
                   "entries": [{"symbol": "Pipe", "file": "src/ingest/p.py",
                                "cbm_node_id": "ingest.Pipe", "lines": [1, 9],
                                "confidence": 1.0, "stale": False}]},
        "unmatched": [{"symbol": "Ghost"}], "warnings": []}))
    monkeypatch.setattr(H.graph_tools, "get_code_snippet",
        AsyncMock(return_value={"result": "class Pipe: ...", "warnings": []}))

    e = await H.explain_with_sources(_state(), "how does ingestion work")
    assert e["result"]["module"] == "ingestion"
    assert e["result"]["narrative"] == "narrative text"
    ev = e["result"]["evidence"]
    assert len(ev) == 1
    assert ev[0]["symbol"] == "Pipe" and ev[0]["grounding_method"] == "entity_map"
    assert ev[0]["snippet"] == "class Pipe: ..."
    assert e["unmatched"] == [{"symbol": "Ghost"}]
    assert e["confidence"] == 1.0


@pytest.mark.asyncio
async def test_graph_search_fallback(monkeypatch):
    # wiki hit whose doc does NOT map to a module -> fallback to graph search
    monkeypatch.setattr(H, "search_wiki",
        lambda state, q: {"result": [{"doc": "nomatch.md", "snippet": "n"}], "warnings": []})
    monkeypatch.setattr(H.graph_tools, "search_code_graph", AsyncMock(return_value={
        "result": {"results": [{"name": "Chunker", "qualified_name": "ingest.Chunker",
                                "file_path": "src/ingest/c.py", "start_line": 2, "end_line": 8}]},
        "warnings": []}))
    monkeypatch.setattr(H.graph_tools, "get_code_snippet",
        AsyncMock(return_value={"result": "def Chunker(): ...", "warnings": []}))

    e = await H.explain_with_sources(_state(), "chunker")
    assert e["result"]["module"] is None
    ev = e["result"]["evidence"]
    assert ev[0]["symbol"] == "Chunker" and ev[0]["grounding_method"] == "graph_search"


@pytest.mark.asyncio
async def test_degrades_without_wiki(monkeypatch):
    st = AppState(wiki_dir="w", entity_map_path="e", repo_head="r", cbm=object(), wiki=None)
    monkeypatch.setattr(H.graph_tools, "search_code_graph",
        AsyncMock(return_value={"result": {"results": []}, "warnings": []}))
    e = await H.explain_with_sources(st, "anything")
    assert e["result"]["narrative"] == "" and any("wiki" in w for w in e["warnings"])


@pytest.mark.asyncio
async def test_degrades_when_cbm_down_but_wiki_present():
    # No monkeypatch: real composition. cbm=None -> get_related_files serves the
    # precomputed entity_map entries (unverified) and snippets come back empty.
    from repo_memory.bridge.schema import EntityMap, ModuleMap, EntityEntry
    em = EntityMap("r", "c", "r", [ModuleMap("ingestion", None, "src/ingest",
            [EntityEntry("Pipe", "src/ingest/p.py", "ingest.Pipe", [1, 9], "exact", 1.0)], [])])
    st = AppState(wiki_dir="w", entity_map_path="e", repo_head="r", cbm=None,
                  wiki=_wiki(), entity_map=em)
    e = await H.explain_with_sources(st, "Ingestion")   # matches "# Ingestion" -> module resolves
    assert e["result"]["module"] == "ingestion"
    assert e["result"]["evidence"]                       # entity-map evidence still served
    assert e["result"]["evidence"][0]["snippet"] == ""   # no live snippet (CBM down)
    assert any("CBM" in w for w in e["warnings"])         # degradation warning surfaced


@pytest.mark.asyncio
async def test_explain_require_verification_blocks_when_stale():
    # cbm present, no entity_map -> graph not current -> require_verification blocks
    st = AppState(wiki_dir="w", entity_map_path="e", repo_head="r", cbm=object(), wiki=_wiki())
    e = await H.explain_with_sources(st, "Ingestion", require_verification=True)
    assert e["result"] is None
    assert any("verification required" in w for w in e["warnings"])
