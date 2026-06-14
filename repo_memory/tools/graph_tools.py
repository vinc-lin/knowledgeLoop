"""Forwarded CBM graph tools, wrapped in the response envelope with degradation."""

from __future__ import annotations

from repo_memory.contract import envelope
from repo_memory.graph import forward
from repo_memory.graph.client import CBMUnavailable
from repo_memory.grounding import compute_freshness
from repo_memory.tools.wiki_tools import provenance


async def _run(state, coro_factory):
    f = compute_freshness(state)
    if state.cbm is None:
        return envelope(None, freshness=f, warnings=["CBM unavailable"],
                        provenance=provenance(state))
    try:
        result = await coro_factory(state.cbm)
    except CBMUnavailable as exc:
        return envelope(None, freshness=f, warnings=[f"CBM error: {exc}"],
                        provenance=provenance(state))
    return envelope(result, freshness=f, provenance=provenance(state))


async def search_code_graph(state, *, name_pattern=None, label=None,
                            file_pattern=None, limit=200, offset=0) -> dict:
    return await _run(state, lambda c: forward.search_graph(
        c, name_pattern=name_pattern, label=label, file_pattern=file_pattern,
        limit=limit, offset=offset))


async def trace_symbol(state, *, function_name, direction="both", depth=3) -> dict:
    return await _run(state, lambda c: forward.trace_path(
        c, function_name=function_name, direction=direction, depth=depth))


async def get_code_snippet(state, *, qualified_name) -> dict:
    return await _run(state, lambda c: forward.get_code_snippet(c, qualified_name=qualified_name))


async def get_architecture(state) -> dict:
    return await _run(state, lambda c: forward.get_architecture(c))
