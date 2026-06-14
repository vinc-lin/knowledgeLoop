"""Hybrid fusion tools: explain_with_sources (read-only) + assess_impact (fail-closed)."""

from __future__ import annotations

import re
from typing import Optional

from repo_memory.contract import envelope
from repo_memory.tools.wiki_tools import provenance, search_wiki, _find_module
from repo_memory.tools import bridge_tools, graph_tools

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
