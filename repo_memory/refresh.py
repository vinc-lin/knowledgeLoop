"""Bounded refresh: re-index CBM at HEAD + rebuild the entity_map (no LLM wiki-regen)."""

from __future__ import annotations

from repo_memory.contract import envelope
from repo_memory.grounding import compute_freshness
from repo_memory.graph import forward
from repo_memory.graph.project import ensure_project
from repo_memory.entity_map_build import build_and_save
from repo_memory.tools.wiki_tools import provenance


async def refresh(state) -> dict:
    if state.cbm is None:
        return envelope(None, warnings=["CBM unavailable; cannot refresh"],
                        provenance=provenance(state))
    if state.wiki is None:
        return envelope(None, warnings=["wiki artifacts unavailable; cannot rebuild entity_map"],
                        provenance=provenance(state))
    idx = await forward.index_repository(state.cbm, repo_path=state.repo_path or ".")
    proj = idx.get("project") if isinstance(idx, dict) else None
    if proj:
        state.project = proj                       # CBM returns the canonical project on index
    elif state.project is None:
        state.project = await ensure_project(state)
    if state.project is None:
        return envelope(None, warnings=["could not resolve CBM project after indexing"],
                        provenance=provenance(state))
    em = await build_and_save(state.wiki, state.cbm, state.entity_map_path,
                              project=state.project, repo_head=state.repo_head)
    state.entity_map = em
    return envelope({"reindexed": True, "graph_commit": em.graph_commit,
                     "modules": len(em.modules)},
                    freshness=compute_freshness(state), provenance=provenance(state))
