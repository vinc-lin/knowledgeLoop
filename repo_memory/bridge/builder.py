"""Build an EntityMap by joining a CodeWiki module_tree against CBM nodes."""

from __future__ import annotations

from typing import Iterable, Optional

from repo_memory.bridge.paths import normalize_path, path_suffix_match
from repo_memory.bridge.schema import (
    CONFIDENCE, NodeRecord, EntityEntry, ModuleMap, EntityMap,
)


def _walk(tree: dict):
    """Yield (module_name, node) for every module in the tree, depth-first."""
    for name, node in tree.items():
        yield name, node
        for pair in _walk(node.get("children") or {}):
            yield pair


def _split_component(component: str) -> tuple[str, str]:
    """'path/to/file.py::Symbol' -> ('path/to/file.py', 'Symbol')."""
    if "::" in component:
        file, symbol = component.rsplit("::", 1)
        return file, symbol
    return component, ""


def _match(file: str, symbol: str, nodes: list[NodeRecord],
           repo_root: Optional[str]) -> EntityEntry:
    nf = normalize_path(file, repo_root)
    by_name = [n for n in nodes if n.name == symbol]
    # 1. exact: same normalized file + same name
    for n in by_name:
        if normalize_path(n.file_path, repo_root) == nf:
            return EntityEntry(symbol, nf, n.node_id, [n.start_line, n.end_line],
                               "exact", CONFIDENCE["exact"])
    # 2. qualified_suffix: same name, shared path tail (handles differing roots)
    for n in by_name:
        if path_suffix_match(nf, normalize_path(n.file_path, repo_root)):
            return EntityEntry(symbol, nf, n.node_id, [n.start_line, n.end_line],
                               "qualified_suffix", CONFIDENCE["qualified_suffix"])
    # 3. file_only: the file exists in the graph but the symbol does not
    for n in nodes:
        nfp = normalize_path(n.file_path, repo_root)
        if nfp == nf or path_suffix_match(nf, nfp):
            return EntityEntry(symbol, nf, None, None,
                               "file_only", CONFIDENCE["file_only"])
    # 4. unmatched
    return EntityEntry(symbol, nf, None, None, "unmatched", CONFIDENCE["unmatched"])


def build_entity_map(module_tree: dict, nodes: Iterable[NodeRecord], *,
                     repo_root: Optional[str] = None,
                     repo_head: Optional[str] = None,
                     wiki_commit: Optional[str] = None,
                     graph_commit: Optional[str] = None) -> EntityMap:
    node_list = list(nodes)
    modules: list[ModuleMap] = []
    for name, node in _walk(module_tree):
        mod = ModuleMap(module=name, wiki_page=None, path=node.get("path", ""))
        for component in node.get("components") or []:
            file, symbol = _split_component(component)
            if not symbol:
                continue
            entry = _match(file, symbol, node_list, repo_root)
            if entry.match_strategy == "unmatched":
                mod.unmatched.append(entry)
            else:
                mod.entries.append(entry)
        modules.append(mod)
    return EntityMap(built_at_repo_head=repo_head, wiki_commit=wiki_commit,
                     graph_commit=graph_commit, modules=modules)
