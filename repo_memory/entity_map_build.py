"""Offline step: build the Wiki<->Graph entity_map.json from a wiki + CBM."""

from __future__ import annotations

from typing import Optional

from repo_memory.bridge.builder import _walk, _split_component, build_entity_map
from repo_memory.bridge.schema import save_entity_map, EntityMap, NodeRecord
from repo_memory.graph.nodes import enumerate_nodes_for_files


def _module_files(node: dict) -> list[str]:
    files = set()
    for component in node.get("components") or []:
        file, _symbol = _split_component(component)
        if file:
            files.add(file)
    return sorted(files)


async def build_and_save(wiki, client, out_path: str, *,
                         repo_root: Optional[str] = None,
                         repo_head: Optional[str] = None) -> EntityMap:
    # Collect the union of files referenced across all modules, enumerate once.
    all_files = set()
    for _name, node in _walk(wiki.module_tree):
        all_files.update(_module_files(node))
    nodes: list[NodeRecord] = await enumerate_nodes_for_files(client, sorted(all_files))
    em = build_entity_map(wiki.module_tree, nodes, repo_root=repo_root,
                          repo_head=repo_head, wiki_commit=wiki.wiki_commit)
    save_entity_map(em, out_path)
    return em
