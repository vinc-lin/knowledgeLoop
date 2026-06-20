from __future__ import annotations

from typing import Callable


def hallucination_rate(referenced_symbols: list[str],
                       exists_fn: Callable[[str], bool]) -> float:
    """Fraction of referenced symbols that do NOT exist in the graph. 0.0 if none referenced."""
    if not referenced_symbols:
        return 0.0
    missing = sum(0 if exists_fn(s) else 1 for s in referenced_symbols)
    return missing / len(referenced_symbols)


def reuse_recall(referenced_symbols: list[str], touched_files: list[str], *,
                 expected_symbols: list[str], expected_files: list[str]) -> float:
    """Recall of the ground-truth key (expected symbols+files) by the solution. 1.0 if key empty."""
    key = [("sym", s) for s in expected_symbols] + [("file", f) for f in expected_files]
    if not key:
        return 1.0
    got_syms, got_files = set(referenced_symbols), set(touched_files)
    hit = sum(1 for kind, v in key
              if (v in got_syms if kind == "sym" else v in got_files))
    return hit / len(key)


def exploration_cost(tool_calls: int) -> int:
    """Lower is better. Proxy = agent tool calls (or num_turns, per the spike decision)."""
    return tool_calls
