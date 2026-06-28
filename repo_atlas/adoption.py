"""Adoption gate + nudge — the productized `assisted` mechanism, shared by the eval and the
`repo-atlas gate` hook. Answer-agnostic: it asks only "is the most-relevant thing for this prompt
absent from the local work-tree?" (i.e. plausibly in a related repo)."""
from __future__ import annotations

import os
import re

# Soft, conditional nudge injected when the gate fires. NOT imperative (no "MUST"/"FIRST" — that is
# the mandatory STEER): it suggests the cross-repo tool when local search comes up empty.
NUDGE = (
    "Note: this task may depend on a helper or convention that is NOT present in your local "
    "files — it may live in a related repository. If your own search of this codebase does not "
    "surface one, consider calling mcp__repo-atlas__find_related to look across related repos "
    "before implementing it yourself.\n\nTask:\n"
)


_CODING_INTENT = re.compile(
    r"\b(implement|add|fix|use the existing|wire up|refactor|create|write|hook up|"
    r"call the|integrate|support)\b", re.IGNORECASE)


def is_coding_intent(prompt: str) -> bool:
    """Cheap pre-filter: does the prompt look like an implementation/change request? Keeps the gate
    from running a retrieval on Q&A / explanation prompts."""
    return bool(_CODING_INTENT.search(prompt or ""))


def _present_in_tree(rel_or_name: str, work_dir: str) -> bool:
    """True iff a file with the same basename as `rel_or_name` exists anywhere under `work_dir`
    (skipping `.git`). Basename match: retrieval paths are repo-relative and won't line up with the
    work-tree's layout."""
    target = os.path.basename(rel_or_name)
    if not target:
        return False
    for _root, dirs, files in os.walk(work_dir):
        dirs[:] = [d for d in dirs if d != ".git"]
        if target in files:
            return True
    return False


async def gate_query_out_of_tree(query: str, work_dir: str, retriever, *, k: int = 5) -> bool:
    """True iff the top all-repos retrieval hit for `query` lives in a file ABSENT from `work_dir`.
    False when no retriever, no hits, or the top hit is in-tree."""
    if retriever is None:
        return False
    units = await retriever.retrieve(query, None, k)
    if not units:
        return False
    f = units[0].get("file") or units[0].get("path") or ""
    return bool(f) and not _present_in_tree(f, work_dir)


async def nudge_for(prompt: str, work_dir: str, retriever, *, k: int = 5) -> str | None:
    """Return the NUDGE text iff the gate judges the prompt's need to be out of the local work-tree."""
    return NUDGE if await gate_query_out_of_tree(prompt, work_dir, retriever, k=k) else None
