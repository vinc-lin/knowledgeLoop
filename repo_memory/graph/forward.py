"""Thin pass-through wrappers for the CBM tools we use. Single place that knows
CBM's tool names + argument keys, so schema drift is contained here."""

from __future__ import annotations

from typing import Any, Optional


def _compact(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


async def search_graph(client, *, name_pattern: Optional[str] = None,
                       label: Optional[str] = None, file_pattern: Optional[str] = None,
                       limit: int = 200, offset: int = 0) -> Any:
    args = _compact({"name_pattern": name_pattern, "label": label,
                     "file_pattern": file_pattern})
    args.update({"limit": limit, "offset": offset})
    return await client.call_tool_with_restart("search_graph", args)


async def trace_path(client, *, function_name: str, direction: str = "both",
                     depth: int = 3) -> Any:
    return await client.call_tool_with_restart(
        "trace_path", {"function_name": function_name, "direction": direction, "depth": depth})


async def get_code_snippet(client, *, qualified_name: str) -> Any:
    return await client.call_tool_with_restart(
        "get_code_snippet", {"qualified_name": qualified_name})


async def get_architecture(client) -> Any:
    return await client.call_tool_with_restart("get_architecture", {})


async def get_graph_schema(client) -> Any:
    return await client.call_tool_with_restart("get_graph_schema", {})


async def index_status(client, *, project: Optional[str] = None) -> Any:
    return await client.call_tool_with_restart("index_status", _compact({"project": project}))


async def index_repository(client, *, path: str) -> Any:
    return await client.call_tool_with_restart("index_repository", {"path": path})


async def detect_changes(client, *, base_branch: Optional[str] = None) -> Any:
    return await client.call_tool_with_restart(
        "detect_changes", _compact({"base_branch": base_branch}))
