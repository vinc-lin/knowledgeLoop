# repo_atlas/eval/offline/retriever.py
from __future__ import annotations


class OfflineRetriever:
    """Adapter over the production retrieval code paths (no MCP server)."""

    def __init__(self, store, embedder):
        self._store = store
        self._embedder = embedder

    async def retrieve(self, query: str, repo, k: int, kinds=None) -> list:
        import repo_atlas.retrieve as _r          # late import so monkeypatch targets the module
        repos = [repo] if repo else None
        return await _r.find_related_units(self._store, self._embedder, query,
                                           repos=repos, k=k, kinds=kinds)

    def ground(self, repo: str, symbols: list) -> dict:
        import repo_atlas.tools as _t
        env = _t.verify_grounding(self._store, repo, list(symbols))
        # verify_grounding wraps the {sym: {...}} mapping in a contract envelope;
        # unwrap result so grounding_scores can look symbols up at the top level.
        return env.get("result", env) if isinstance(env, dict) else env


class StubRetriever:
    """Canned hits/grounding for tests (no store/embedder)."""

    def __init__(self, hits_by_query=None, grounding_by_repo=None):
        self._hits = hits_by_query or {}
        self._grounding = grounding_by_repo or {}

    async def retrieve(self, query: str, repo, k: int, kinds=None) -> list:
        return list(self._hits.get(query, []))[:k]

    def ground(self, repo: str, symbols: list) -> dict:
        known = self._grounding.get(repo, {})
        return {s: {"exists": bool(known.get(s, False)), "nearest": []} for s in symbols}
