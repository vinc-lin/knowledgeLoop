"""Resolve the CBM `project` id for the repo and cache it on AppState.

CBM 0.8.1 names each indexed graph by a project (derived from the repo path) and
requires that id on every query. We get the name FROM CBM — the value
`index_repository` returns, or `list_projects` matched by `root_path` — rather
than replicating CBM's path→name scheme, so this stays correct across CBM versions.
"""

from __future__ import annotations

import os
from typing import Optional

from repo_memory.graph import forward
from repo_memory.graph.client import CBMUnavailable


def _norm(p: str) -> str:
    return os.path.realpath(os.path.abspath(p))


async def resolve_project(client, repo_path: Optional[str]) -> Optional[str]:
    """The CBM project whose root_path matches repo_path; None if not indexed/unavailable."""
    if not repo_path:
        return None
    try:
        resp = await forward.list_projects(client)
    except CBMUnavailable:
        return None
    target = _norm(repo_path)
    projects = resp.get("projects", []) if isinstance(resp, dict) else []
    for p in projects:
        root = p.get("root_path")
        if root and _norm(root) == target:
            name = p.get("name")
            return name if isinstance(name, str) else None
    return None


async def ensure_project(state) -> Optional[str]:
    """Return the cached CBM project for this repo, resolving + caching on first use."""
    cached = getattr(state, "project", None)
    if isinstance(cached, str) and cached:
        return cached
    if state.cbm is None or not state.repo_path:
        return None
    name = await resolve_project(state.cbm, state.repo_path)
    state.project = name
    return name
