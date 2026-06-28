"""Eval-facing adoption gate: delegates to the shared product gate in `repo_atlas.adoption`,
mapping a Task to its focused retrieval query. Thin wrapper so eval imports stay stable."""
from __future__ import annotations

from repo_atlas.adoption import _present_in_tree, gate_query_out_of_tree  # noqa: F401  (re-export)
from repo_atlas.eval.tasks import task_query


async def local_context_insufficient(task, work_dir, retriever, *, k: int = 5) -> bool:
    """True iff the task's needed helper is out of the local work-tree (uses the task's focused
    retrieval_query). Thin wrapper over repo_atlas.adoption.gate_query_out_of_tree."""
    return await gate_query_out_of_tree(task_query(task), work_dir, retriever, k=k)
