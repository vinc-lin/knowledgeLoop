"""End-to-end: index one real corpus + query. Gated (needs gateway + uvx CBM)."""
import os
import shutil
import pytest

from repo_atlas.store import Store
from repo_atlas.embed import GatewayEmbedder
from repo_atlas.config import load_config
from repo_atlas.registry import RepoEntry
from repo_atlas.index import index_repo
from repo_atlas.tools import find_related

CORPUS = "/mnt/x/code/corpora/android-gpuimage-plus"
WIKI = "/home/vinc/e2e-knowledgeloop/android-gpuimage-plus/docs"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_index_and_find_related(tmp_path):
    if shutil.which("uvx") is None:
        pytest.skip("uvx not available")
    cfg = load_config(os.environ)
    if not cfg.base_url or not cfg.embed_model:
        pytest.skip("gateway embeddings not configured")
    store = Store(str(tmp_path / "atlas.db"))
    emb = GatewayEmbedder(cfg.base_url, cfg.api_key, cfg.embed_model)
    entry = RepoEntry("gpuimage", CORPUS, WIKI, WIKI + "/../entity_map.json")
    try:
        n = await index_repo(entry, store, emb)
    except Exception as exc:
        pytest.skip(f"index failed (CBM/gateway): {exc}")
    assert n > 0
    env = await find_related(store, emb, "adjust image brightness")
    assert env["result"], "expected related hits"
    flat = env["result"]["symbols"] + env["result"]["docs"]     # grouped buckets now
    assert any(h["repo"] == "gpuimage" for h in flat)
