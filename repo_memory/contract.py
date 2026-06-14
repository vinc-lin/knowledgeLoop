"""The unified response envelope returned by every repo_memory tool."""

from __future__ import annotations

from typing import Any, Optional

FRESHNESS = ("fresh", "stale-wiki", "stale-graph", "unverified")


def envelope(result: Any, *, freshness: str = "unverified",
             provenance: Optional[dict] = None, confidence: Optional[float] = None,
             warnings: Optional[list] = None, unmatched: Optional[list] = None) -> dict:
    return {
        "result": result,
        "freshness": freshness,
        "provenance": provenance or {"repo_head": None, "wiki_commit": None,
                                     "graph_commit": None},
        "confidence": confidence,
        "warnings": list(warnings or []),
        "unmatched": list(unmatched or []),
    }
