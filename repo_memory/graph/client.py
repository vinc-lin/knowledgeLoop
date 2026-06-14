"""Stdio MCP client for the Codebase-Memory-MCP backend."""

from __future__ import annotations

import json
from typing import Any, Optional


class CBMUnavailable(RuntimeError):
    """CBM is unreachable or returned an error."""


def parse_tool_result(result) -> Any:
    """Extract a CBM tool's payload from an mcp CallToolResult.

    Prefers structuredContent; else JSON-parses the first text block; else raw text.
    Raises CBMUnavailable if the result is flagged isError.
    """
    if getattr(result, "isError", False):
        raise CBMUnavailable(f"CBM tool error: {_first_text(result)}")
    structured = getattr(result, "structuredContent", None)
    if structured:
        return structured
    text = _first_text(result)
    if text is None:
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text


def _first_text(result) -> Optional[str]:
    for block in getattr(result, "content", None) or []:
        if getattr(block, "type", None) == "text":
            return block.text
    return None


def backoff_delays(n: int, base: float = 0.5, cap: float = 8.0) -> list[float]:
    """Exponential backoff schedule: base, 2*base, 4*base, ... capped at `cap`."""
    return [min(cap, base * (2 ** i)) for i in range(n)]
