"""repo_memory unified MCP facade (FastMCP). Sole endpoint the agent calls."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Optional

from mcp.server.fastmcp import FastMCP

from repo_memory.state import load_app_state
from repo_memory.graph.client import CBMClient
from repo_memory.tools import wiki_tools, bridge_tools, graph_tools, hybrid_tools

TOOL_NAMES = [
    "get_repo_overview", "list_modules", "search_wiki", "get_module_doc",
    "get_related_files",
    "search_code_graph", "trace_symbol", "get_code_snippet", "get_architecture",
    "explain_with_sources", "assess_impact",
]


def build_app(*, wiki_dir: str, entity_map_path: str,
              repo_head: Optional[str] = None,
              cbm_command: Optional[list] = None) -> FastMCP:
    state = load_app_state(wiki_dir=wiki_dir, entity_map_path=entity_map_path,
                           repo_head=repo_head)

    @asynccontextmanager
    async def lifespan(_app):
        client = CBMClient(cbm_command)
        try:
            await client.start()
            state.cbm = client
        except Exception:
            state.cbm = None  # degrade: wiki tools still work
        try:
            yield {}
        finally:
            await client.aclose()

    app = FastMCP("repo_memory",
                  instructions="Grounded code intelligence: CodeWiki docs + CBM graph.",
                  lifespan=lifespan)

    @app.tool(name="get_repo_overview",
              description="High-level repo overview from the generated wiki. Use FIRST for "
                          "'what is this project / overall architecture' questions.")
    def _overview() -> dict:
        return wiki_tools.get_repo_overview(state)

    @app.tool(name="list_modules",
              description="List the wiki module names. Use to discover module boundaries.")
    def _list() -> dict:
        return wiki_tools.list_modules(state)

    @app.tool(name="search_wiki",
              description="Search the generated module docs by keyword. Use for "
                          "conceptual 'how does X work / which module does Y' questions.")
    def _search_wiki(query: str) -> dict:
        return wiki_tools.search_wiki(state, query)

    @app.tool(name="get_module_doc",
              description="Get one module's generated doc, path, and components.")
    def _module_doc(module: str) -> dict:
        return wiki_tools.get_module_doc(state, module)

    @app.tool(name="get_related_files",
              description="Map a wiki module to its real source files + symbols (graph-"
                          "verified). Use to go from understanding a module to its code.")
    async def _related(module: str) -> dict:
        return await bridge_tools.get_related_files(state, module)

    @app.tool(name="search_code_graph",
              description="Structural code search over the CBM graph (name/label/file). "
                          "Use to locate exact symbols.")
    async def _search_graph(name_pattern: str = None, label: str = None,
                            file_pattern: str = None, limit: int = 200) -> dict:
        return await graph_tools.search_code_graph(
            state, name_pattern=name_pattern, label=label,
            file_pattern=file_pattern, limit=limit)

    @app.tool(name="trace_symbol",
              description="Trace a function's call paths (callers/callees) via the graph. "
                          "Use for call-chain questions.")
    async def _trace(function_name: str, direction: str = "both", depth: int = 3) -> dict:
        return await graph_tools.trace_symbol(
            state, function_name=function_name, direction=direction, depth=depth)

    @app.tool(name="get_code_snippet",
              description="Fetch source for a symbol by qualified name from the graph.")
    async def _snippet(qualified_name: str) -> dict:
        return await graph_tools.get_code_snippet(state, qualified_name=qualified_name)

    @app.tool(name="get_architecture",
              description="Graph-level architecture summary (languages, entry points, "
                          "hotspots) from CBM.")
    async def _arch() -> dict:
        return await graph_tools.get_architecture(state)

    @app.tool(name="explain_with_sources",
              description="Explain how something works with GRAPH-VERIFIED source evidence "
                          "(wiki narrative + real files/symbols/snippets). Use for 'how does X "
                          "work / why' questions that need proof, not just narrative.")
    async def _explain(query: str) -> dict:
        return await hybrid_tools.explain_with_sources(state, query)

    @app.tool(name="assess_impact",
              description="Assess the blast radius of current changes — FAIL-CLOSED and "
                          "graph-verified (blocks if the graph isn't current). Use before "
                          "modifying/refactoring or for 'what does this change affect' questions.")
    async def _impact(base_branch: str = None) -> dict:
        return await hybrid_tools.assess_impact(state, base_branch=base_branch)

    return app


def main() -> None:  # pragma: no cover - process entry point
    wiki_dir = os.environ.get("REPO_MEMORY_WIKI_DIR", "docs")
    entity_map_path = os.environ.get("REPO_MEMORY_ENTITY_MAP", "entity_map.json")
    build_app(wiki_dir=wiki_dir, entity_map_path=entity_map_path).run(transport="stdio")
