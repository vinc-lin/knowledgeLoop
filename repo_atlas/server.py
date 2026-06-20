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


def build_app() -> FastMCP:
    cfg = load_config(os.environ)
    store = Store(cfg.db_path)
    embedder = GatewayEmbedder(cfg.base_url, cfg.api_key, cfg.embed_model)
    registry_path = os.environ.get("REPO_ATLAS_REGISTRY", "atlas.toml")
    try:
        entries = load_registry(registry_path)
    except Exception:
        entries = []

    app = FastMCP("repo_atlas",
                  instructions="Cross-repo knowledge: find related code/docs across repos.")

    @app.tool(name="find_related",
              description="Find related code, building blocks, usage, and conventions across "
                          "ALL indexed repos. Use when writing/changing a function or fixing a bug.")
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
