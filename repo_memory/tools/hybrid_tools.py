"""Hybrid fusion tools: explain_with_sources (read-only) + assess_impact (fail-closed)."""

from __future__ import annotations

import re
from typing import Optional

from repo_memory.contract import envelope
from repo_memory.tools.wiki_tools import provenance, search_wiki, _find_module
from repo_memory.tools import bridge_tools, graph_tools
from repo_memory.grounding import graph_is_current
from repo_memory.graph.nodes import CBMGraphProbe
from repo_memory.graph import forward
from repo_memory.graph.client import CBMUnavailable

N_EVIDENCE = 3


def _terms_to_pattern(query: str) -> str:
    words = [re.escape(w) for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", query)]
    return "(" + "|".join(words) + ")" if words else ".*"


async def _snippet(state, qn: str) -> str:
    if not qn:
        return ""
    res = await graph_tools.get_code_snippet(state, qualified_name=qn)
    out = res.get("result")
    return out if isinstance(out, str) else ("" if out is None else str(out))


async def explain_with_sources(state, query: str, *, n: int = N_EVIDENCE) -> dict:
    warnings: list = []
    narrative, module = "", None

    if state.wiki:
        hits = search_wiki(state, query).get("result") or []
        if hits:
            narrative = hits[0].get("snippet", "")
            cand = hits[0]["doc"][:-3] if hits[0]["doc"].endswith(".md") else hits[0]["doc"]
            if _find_module(state.wiki.module_tree, cand) is not None:
                module = cand
    else:
        warnings.append("wiki artifacts unavailable")

    evidence: list = []
    unmatched: list = []
    if module is not None:
        rel = await bridge_tools.get_related_files(state, module)
        warnings.extend(rel.get("warnings") or [])
        unmatched = rel.get("unmatched") or []
        for entry in ((rel.get("result") or {}).get("entries") or [])[:n]:
            evidence.append({
                "symbol": entry.get("symbol", ""), "file": entry.get("file", ""),
                "lines": entry.get("lines"), "snippet": await _snippet(state, entry.get("cbm_node_id")),
                "grounding_method": "entity_map",
                "confidence": entry.get("confidence", 0.0), "stale": entry.get("stale", False)})
    else:
        sg = await graph_tools.search_code_graph(state, name_pattern=_terms_to_pattern(query), limit=n)
        warnings.extend(sg.get("warnings") or [])
        for row in ((sg.get("result") or {}).get("results") or [])[:n]:
            qn = row.get("qualified_name") or row.get("name", "")
            evidence.append({
                "symbol": row.get("name", ""), "file": row.get("file_path", ""),
                "lines": [row.get("start_line", 0), row.get("end_line", 0)],
                "snippet": await _snippet(state, qn), "grounding_method": "graph_search",
                "confidence": 0.85, "stale": False})

    conf = round(sum(e["confidence"] for e in evidence) / len(evidence), 3) if evidence else None
    fresh = "fresh" if evidence and not any(e["stale"] for e in evidence) else "unverified"
    return envelope({"narrative": narrative, "module": module, "evidence": evidence},
                    freshness=fresh, confidence=conf, warnings=warnings,
                    unmatched=unmatched, provenance=provenance(state))


def _module_for_file(state, file_path: str) -> Optional[str]:
    em = state.entity_map
    if not em:
        return None
    for m in em.modules:
        if any(e.file == file_path for e in m.entries):
            return m.module
    return None


async def assess_impact(state, base_branch: Optional[str] = None) -> dict:
    prov = provenance(state)

    def _blocked(reason, freshness="stale-graph"):
        return envelope(None, freshness=freshness, warnings=[f"cannot assess impact: {reason}"],
                        provenance=prov)

    # --- fail-closed gate (graph-grounding only) ---
    if state.cbm is None:
        return _blocked("CBM unavailable", freshness="unverified")
    if not graph_is_current(state):
        return _blocked("graph not current (re-index first)")
    try:
        changes = await forward.detect_changes(state.cbm, base_branch=base_branch)
    except CBMUnavailable as exc:
        return _blocked(str(exc))
    if not isinstance(changes, dict) or changes.get("error"):
        reason = (changes or {}).get("error", "detect_changes returned no usable result") \
            if isinstance(changes, dict) else "detect_changes returned no usable result"
        return _blocked(reason)

    impacted_in = changes.get("impacted") or []
    probe = CBMGraphProbe(state.cbm)
    qns = [i.get("qualified_name") or i.get("name") for i in impacted_in
           if (i.get("qualified_name") or i.get("name"))]
    await probe.prefetch(qns)

    impacted_out, no_module = [], []
    for item in impacted_in:
        qn = item.get("qualified_name") or item.get("name")
        node = probe.lookup(qn) if qn else None
        if node is None:
            return _blocked(f"symbol '{qn}' not verifiable in current graph")
        module = _module_for_file(state, node.file_path)
        if module is None:
            no_module.append(node.name)
        impacted_out.append({"symbol": node.name, "file": node.file_path,
                             "risk": item.get("risk"), "module": module, "verified": True})

    warnings = [f"{len(no_module)} impacted symbol(s) have no wiki module mapping"] if no_module else []
    return envelope({"base_branch": base_branch, "changes": changes.get("changes") or [],
                     "impacted": impacted_out, "blast_radius": len(impacted_out)},
                    freshness="fresh", confidence=(1.0 if impacted_out else None),
                    warnings=warnings, provenance=prov)
