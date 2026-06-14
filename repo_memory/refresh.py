"""Bounded refresh: re-index CBM at HEAD + rebuild the entity_map (no LLM wiki-regen)."""

from __future__ import annotations

from repo_memory.contract import envelope
from repo_memory.grounding import compute_freshness
from repo_memory.graph import forward
from repo_memory.entity_map_build import build_and_save
from repo_memory.tools.wiki_tools import provenance


async def refresh(state) -> dict:
    if state.cbm is None:
        return envelope(None, warnings=["CBM unavailable; cannot refresh"],
                        provenance=provenance(state))
    if state.wiki is None:
        return envelope(None, warnings=["wiki artifacts unavailable; cannot rebuild entity_map"],
                        provenance=provenance(state))
    await forward.index_repository(state.cbm, path=state.repo_path or ".")
    em = await build_and_save(state.wiki, state.cbm, state.entity_map_path,
                              repo_head=state.repo_head)
    state.entity_map = em
    return envelope({"reindexed": True, "graph_commit": em.graph_commit,
                     "modules": len(em.modules)},
                    freshness=compute_freshness(state), provenance=provenance(state))
