"""Thin pass-through wrappers for the CBM tools we use. Single place that knows
CBM's tool names + argument keys, so schema drift is contained here.

CBM 0.8.1 addresses every indexed graph by a `project` id and marks it REQUIRED on
all query tools; `index_repository` takes `repo_path` and returns the canonical
project name. The `project` is resolved (not guessed) in repo_memory.graph.project."""

from __future__ import annotations

from typing import Any, Optional


def _compact(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


async def list_projects(client) -> Any:
    """All indexed projects ({"projects": [{name, root_path, ...}]}) — used to resolve the project id."""
    return await client.call_tool_with_restart("list_projects", {})


async def search_graph(client, *, project: str, name_pattern: Optional[str] = None,
                       label: Optional[str] = None, file_pattern: Optional[str] = None,
                       limit: int = 200, offset: int = 0) -> Any:
    args = _compact({"name_pattern": name_pattern, "label": label,
                     "file_pattern": file_pattern})
    args.update({"project": project, "limit": limit, "offset": offset})
    return await client.call_tool_with_restart("search_graph", args)


async def trace_path(client, *, project: str, function_name: str, direction: str = "both",
                     depth: int = 3) -> Any:
    return await client.call_tool_with_restart(
        "trace_path", {"project": project, "function_name": function_name,
                       "direction": direction, "depth": depth})


async def get_code_snippet(client, *, project: str, qualified_name: str) -> Any:
    return await client.call_tool_with_restart(
        "get_code_snippet", {"project": project, "qualified_name": qualified_name})


async def get_architecture(client, *, project: str) -> Any:
    return await client.call_tool_with_restart("get_architecture", {"project": project})


async def get_graph_schema(client, *, project: str) -> Any:
    return await client.call_tool_with_restart("get_graph_schema", {"project": project})


async def index_status(client, *, project: str) -> Any:
    return await client.call_tool_with_restart("index_status", {"project": project})


async def index_repository(client, *, repo_path: str) -> Any:
    """Index a repo. CBM derives + RETURNS the canonical project name in the result."""
    return await client.call_tool_with_restart("index_repository", {"repo_path": repo_path})


async def detect_changes(client, *, project: str, base_branch: Optional[str] = None) -> Any:
    return await client.call_tool_with_restart(
        "detect_changes", _compact({"project": project, "base_branch": base_branch}))
