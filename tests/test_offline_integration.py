# tests/test_offline_integration.py
import os
import pytest

pytestmark = pytest.mark.integration

DB = "/home/vinc/repo-atlas-eval-full/atlas.db"


@pytest.mark.asyncio
@pytest.mark.skipif(not os.path.exists(DB), reason="real atlas.db not present")
async def test_offline_eval_runs_against_real_store():
    from repo_atlas.store import Store
    from repo_atlas.embed import GatewayEmbedder
    from repo_atlas.eval.offline.cases import load_retrieval_cases
    from repo_atlas.eval.offline.retriever import OfflineRetriever
    from repo_atlas.eval.offline.harness import run_retrieval

    store = Store(DB)
    embedder = GatewayEmbedder(os.environ.get("REPO_ATLAS_BASE_URL", "http://127.0.0.1:11434/v1"),
                               os.environ.get("REPO_ATLAS_API_KEY", "local"),
                               os.environ.get("REPO_ATLAS_EMBED_MODEL", "bge-m3"))
    cases = load_retrieval_cases("repo_atlas/eval/offline/cases/retrieval")
    rep = await run_retrieval(cases, OfflineRetriever(store, embedder), ks=(5, 10, 20))
    assert rep.overall["n"] >= 1
    assert 0.0 <= rep.overall["recall@20"] <= 1.0
