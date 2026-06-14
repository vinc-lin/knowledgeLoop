"""Fail-closed grounding helpers: is the graph current enough to ground against?"""

from __future__ import annotations


def graph_is_current(state) -> bool:
    """True only if CBM is available and the indexed graph matches the repo HEAD.

    Requires a CBM client, a known repo_head, and an entity_map whose graph_commit
    equals repo_head. Any unknown/mismatch returns False (fail closed).
    """
    if state.cbm is None or not state.repo_head:
        return False
    em = state.entity_map
    return bool(em and em.graph_commit and em.graph_commit == state.repo_head)


def compute_freshness(state, *, entries_stale: bool = False) -> str:
    """Reporting enum, precedence graph > wiki.

    unverified: can't tell (no CBM / missing commits). stale-graph: graph behind
    HEAD or a returned entry failed verify-on-access. stale-wiki: only docs behind
    HEAD. fresh: all aligned.
    """
    rh = state.repo_head
    em = state.entity_map
    if state.cbm is None or not rh or em is None or not em.graph_commit:
        return "unverified"
    if em.graph_commit != rh or entries_stale:
        return "stale-graph"
    wiki_commit = state.wiki.wiki_commit if state.wiki else em.wiki_commit
    if wiki_commit and wiki_commit != rh:
        return "stale-wiki"
    return "fresh"


def require_fresh(state):
    """Tier-B gate: return the blocking freshness ('unverified'/'stale-graph') when
    the graph is NOT current, else None. Graph-only — a stale wiki never blocks.
    Callers build their own blocked envelope from the returned string."""
    if graph_is_current(state):
        return None
    return compute_freshness(state)
