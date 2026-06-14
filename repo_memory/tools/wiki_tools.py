"""Wiki tool logic (pure; take AppState, return the response envelope)."""

from __future__ import annotations

from typing import Optional

from repo_memory.contract import envelope
from repo_memory.grounding import compute_freshness
from repo_memory.wiki.search import WikiIndex


def provenance(state) -> dict:
    return {
        "repo_head": state.repo_head,
        "wiki_commit": state.wiki.wiki_commit if state.wiki else None,
        "graph_commit": state.entity_map.graph_commit if state.entity_map else None,
    }


def _env(state, result, **kw):
    return envelope(result, freshness=compute_freshness(state),
                    provenance=provenance(state), **kw)


def _no_wiki(state, empty):
    return _env(state, empty, warnings=["wiki artifacts unavailable"])


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
    return _env(state, {"overview": state.wiki.docs.get("overview.md", ""),
                        "metadata": state.wiki.metadata})


def list_modules(state) -> dict:
    if not state.wiki:
        return _no_wiki(state, [])
    return _env(state, [n for n, _ in _walk_modules(state.wiki.module_tree)])


def search_wiki(state, query: str) -> dict:
    if not state.wiki:
        return _no_wiki(state, [])
    return _env(state, WikiIndex(state.wiki).search(query))


def get_module_doc(state, module: str) -> dict:
    if not state.wiki:
        return _no_wiki(state, None)
    node = _find_module(state.wiki.module_tree, module)
    if node is None:
        return _env(state, None, warnings=[f"module '{module}' not found"])
    doc = state.wiki.docs.get(f"{module}.md", "")
    return _env(state, {"module": module, "path": node.get("path", ""),
                        "components": node.get("components", []), "doc": doc})
