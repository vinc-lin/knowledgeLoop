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
