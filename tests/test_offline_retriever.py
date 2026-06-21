# tests/test_offline_retriever.py
import pytest
from repo_atlas.eval.offline.retriever import OfflineRetriever, StubRetriever


@pytest.mark.asyncio
async def test_stub_retriever():
    s = StubRetriever(
        hits_by_query={"q": [{"file": "a.h", "name": "A", "qualified_name": None}]},
        grounding_by_repo={"r": {"Real": True}})
    assert (await s.retrieve("q", "r", k=5))[0]["file"] == "a.h"
    assert await s.retrieve("missing", "r", k=5) == []
    g = s.ground("r", ["Real", "Nope"])
    assert g["Real"]["exists"] is True and g["Nope"]["exists"] is False


@pytest.mark.asyncio
async def test_offline_retriever_delegates(monkeypatch):
    captured = {}

    async def fake_find(store, embedder, query, *, repos=None, kinds=None, k=20):
        captured.update(query=query, repos=repos, k=k)
        return [{"file": "z.cpp", "name": "Z", "qualified_name": None}]

    def fake_verify(store, repo, symbols):
        captured.update(grepo=repo, syms=symbols)
        return {s: {"exists": True, "nearest": []} for s in symbols}

    monkeypatch.setattr("repo_atlas.retrieve.find_related_units", fake_find)
    monkeypatch.setattr("repo_atlas.tools.verify_grounding", fake_verify)
    r = OfflineRetriever(store=object(), embedder=object())
    hits = await r.retrieve("hello", "myrepo", k=7)
    assert hits[0]["file"] == "z.cpp"
    assert captured["repos"] == ["myrepo"] and captured["k"] == 7
    g = r.ground("myrepo", ["S"])
    assert g["S"]["exists"] is True and captured["grepo"] == "myrepo"
