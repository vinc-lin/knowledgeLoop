"""Bridge tool: get_related_files from the precomputed entity_map + verify-on-access."""

from __future__ import annotations

from dataclasses import asdict
from typing import Optional

from repo_memory.contract import envelope
from repo_memory.bridge.verify import verify_entries
from repo_memory.graph.nodes import CBMGraphProbe
from repo_memory.tools.wiki_tools import provenance


def _find_module(entity_map, module: str):
    for m in entity_map.modules:
        if m.module == module:
            return m
    return None


async def get_related_files(state, module: str, *, probe=None) -> dict:
    if state.entity_map is None:
        return envelope(None, warnings=["entity_map unavailable; run the build step"],
                        provenance=provenance(state))
    mod = _find_module(state.entity_map, module)
    if mod is None:
        return envelope(None, warnings=[f"module '{module}' not in entity_map"],
                        provenance=provenance(state))

    if probe is None:
        if state.cbm is None:
            # No graph to verify against: serve unverified, warn.
            files = sorted({e.file for e in mod.entries})
            return envelope(
                {"module": module, "files": files,
                 "entries": [asdict(e) for e in mod.entries]},
                warnings=["CBM unavailable; entries not verified"],
                confidence=_avg_conf(mod.entries), unmatched=[asdict(u) for u in mod.unmatched],
                provenance=provenance(state))
        probe = CBMGraphProbe(state.cbm)

    qns = [e.cbm_node_id for e in mod.entries if e.cbm_node_id]
    await probe.prefetch(qns)
    verify_entries(mod.entries, probe)
    any_stale = any(e.stale for e in mod.entries)
    files = sorted({e.file for e in mod.entries})
    return envelope(
        {"module": module, "files": files, "entries": [asdict(e) for e in mod.entries]},
        freshness=("stale-graph" if any_stale else "fresh"),
        confidence=_avg_conf(mod.entries),
        unmatched=[asdict(u) for u in mod.unmatched],
        provenance=provenance(state))


def _avg_conf(entries) -> Optional[float]:
    if not entries:
        return None
    return round(sum(e.confidence for e in entries) / len(entries), 3)
