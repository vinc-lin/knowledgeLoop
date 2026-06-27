"""repo_atlas MCP server: cross-repo retrieval over existing knowledge (stdio)."""
from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from repo_atlas.config import load_config
from repo_atlas.store import Store
from repo_atlas.embed import GatewayEmbedder
from repo_atlas.registry import load_registry
from repo_atlas import tools

TOOL_NAMES = ["find_related", "prepare_change", "verify_grounding", "list_repos"]

# Legibility: tell the agent WHEN to reach for the tool, not just what it does. The high-value
# case is cross-repo — a helper/convention that lives in a related repo and is therefore absent
# from (and un-greppable in) the files in front of you.
APP_INSTRUCTIONS = (
    "Cross-repo knowledge. The code you need may live in a RELATED repository that is not in "
    "your working tree. When your own search of the local files (or your own knowledge) does not "
    "surface an existing helper, pattern, or convention, call find_related before writing it "
    "yourself."
)
FIND_RELATED_DESC = (
    "Find related code, building blocks, usage, and conventions across ALL indexed repos "
    "(including related repos NOT in your local working tree). Call this when local search or "
    "your own knowledge does not surface the answer — it is the only way to reach cross-repo "
    "helpers and prior art. Use it before writing or changing a function or fixing a bug."
)


def build_app() -> FastMCP:
    cfg = load_config(os.environ)
    store = Store(cfg.db_path)
    embedder = GatewayEmbedder(cfg.base_url, cfg.api_key, cfg.embed_model)
    registry_path = os.environ.get("REPO_ATLAS_REGISTRY", "atlas.toml")
    try:
        entries = load_registry(registry_path)
    except Exception:
        entries = []

    app = FastMCP("repo_atlas", instructions=APP_INSTRUCTIONS)

    @app.tool(name="find_related", description=FIND_RELATED_DESC)
    async def _find(query: str, repos: list = None, kinds: list = None, k: int = 20) -> dict:
        return await tools.find_related(store, embedder, query, repos=repos, kinds=kinds, k=k)

    @app.tool(name="prepare_change",
              description="Assemble a grounded context pack for a change to a symbol/file in one repo.")
    async def _prep(target: str, repo: str) -> dict:
        return await tools.prepare_change(store, embedder, target, repo)

    @app.tool(name="verify_grounding",
              description="Check that referenced symbols actually exist in a repo's graph "
                          "(anti-hallucination); returns nearest real matches for any that don't.")
    def _verify(symbols: list, repo: str) -> dict:
        return tools.verify_grounding(store, repo, symbols)

    @app.tool(name="list_repos",
              description="List indexed repos + their freshness (indexed commit vs HEAD).")
    def _list() -> dict:
        return tools.list_repos(entries, store)

    return app


def main() -> None:
    build_app().run(transport="stdio")
