"""Adoption gate: decide whether to nudge the agent toward cross-repo retrieval.

The `assisted` arm fires a SOFT nudge only when the task's needed building block isn't in the
local work-tree. The signal is answer-agnostic: it never inspects `required_apis`. For a *local*
task the top all-repos retrieval hit is the in-tree prior art (present -> no nudge); for a
*cross-repo* task the helper lives in a sibling repo absent from the snapshot (absent -> nudge).
"""
from __future__ import annotations

import os

from repo_atlas.eval.tasks import task_query


def _present_in_tree(rel_or_name: str, work_dir: str) -> bool:
    """True iff a file with the same basename as `rel_or_name` exists anywhere under `work_dir`
    (the snapshot), skipping `.git`. Basename match because retrieval paths are repo-relative
    and won't line up with the snapshot's layout."""
    target = os.path.basename(rel_or_name)
    if not target:
        return False
    for root, dirs, files in os.walk(work_dir):
        dirs[:] = [d for d in dirs if d != ".git"]
        if target in files:
            return True
    return False


async def local_context_insufficient(task, work_dir, retriever, *, k: int = 5) -> bool:
    """True iff the single most-relevant all-repos hit for the task lives in a file ABSENT from
    the local snapshot — i.e. the needed building block isn't in the work-tree. False when no
    retriever, no hits, or the top hit is in-tree."""
    if retriever is None:
        return False
    units = await retriever.retrieve(task_query(task), None, k)
    if not units:
        return False
    f = units[0].get("file") or units[0].get("path") or ""
    return bool(f) and not _present_in_tree(f, work_dir)
