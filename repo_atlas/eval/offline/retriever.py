# repo_atlas/eval/offline/retriever.py
from __future__ import annotations


class OfflineRetriever:
    """Adapter over the production retrieval code paths (no MCP server)."""

    def __init__(self, store, embedder):
        self._store = store
        self._embedder = embedder

    async def retrieve(self, query: str, repo, k: int) -> list:
        import repo_atlas.retrieve as _r          # late import so monkeypatch targets the module
        repos = [repo] if repo else None
        return await _r.find_related_units(self._store, self._embedder, query, repos=repos, k=k)

    def ground(self, repo: str, symbols: list) -> dict:
        import repo_atlas.tools as _t
        return _t.verify_grounding(self._store, repo, list(symbols))


class StubRetriever:
    """Canned hits/grounding for tests (no store/embedder)."""

    def __init__(self, hits_by_query=None, grounding_by_repo=None):
        self._hits = hits_by_query or {}
        self._grounding = grounding_by_repo or {}

    async def retrieve(self, query: str, repo, k: int) -> list:
        return list(self._hits.get(query, []))[:k]

    def ground(self, repo: str, symbols: list) -> dict:
        known = self._grounding.get(repo, {})
        return {s: {"exists": bool(known.get(s, False)), "nearest": []} for s in symbols}
