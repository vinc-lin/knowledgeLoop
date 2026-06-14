"""Wiki tool logic (pure; take AppState, return the response envelope)."""

from __future__ import annotations

from typing import Optional

from repo_memory.contract import envelope
from repo_memory.wiki.search import WikiIndex


def provenance(state) -> dict:
    return {
        "repo_head": state.repo_head,
        "wiki_commit": state.wiki.wiki_commit if state.wiki else None,
        "graph_commit": state.entity_map.graph_commit if state.entity_map else None,
    }


def _no_wiki(state, empty):
    return envelope(empty, warnings=["wiki artifacts unavailable"],
                    provenance=provenance(state))


def _walk_modules(tree: dict):
    for name, node in tree.items():
        yield name, node
        yield from _walk_modules(node.get("children") or {})


def _find_module(tree: dict, module: str) -> Optional[dict]:
    for name, node in _walk_modules(tree):
        if name == module:
            return node
    return None


def get_repo_overview(state) -> dict:
    if not state.wiki:
        return _no_wiki(state, None)
    return envelope({"overview": state.wiki.docs.get("overview.md", ""),
                     "metadata": state.wiki.metadata}, provenance=provenance(state))


def list_modules(state) -> dict:
    if not state.wiki:
        return _no_wiki(state, [])
    return envelope([n for n, _ in _walk_modules(state.wiki.module_tree)],
                    provenance=provenance(state))


def search_wiki(state, query: str) -> dict:
    if not state.wiki:
        return _no_wiki(state, [])
    return envelope(WikiIndex(state.wiki).search(query), provenance=provenance(state))


def get_module_doc(state, module: str) -> dict:
    if not state.wiki:
        return _no_wiki(state, None)
    node = _find_module(state.wiki.module_tree, module)
    if node is None:
        return envelope(None, warnings=[f"module '{module}' not found"],
                        provenance=provenance(state))
    doc = state.wiki.docs.get(f"{module}.md", "")
    return envelope({"module": module, "path": node.get("path", ""),
                     "components": node.get("components", []), "doc": doc},
                    provenance=provenance(state))
