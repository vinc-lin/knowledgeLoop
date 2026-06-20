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
    exp_syms = list(dict.fromkeys(expected_symbols))      # dedup, order-preserving
    exp_files = list(dict.fromkeys(expected_files))
    total = len(exp_syms) + len(exp_files)
    if total == 0:
        return 1.0
    got_syms, got_files = set(referenced_symbols), set(touched_files)
    hit = (sum(1 for s in exp_syms if s in got_syms)
           + sum(1 for f in exp_files if f in got_files))
    return hit / total


def exploration_cost(tool_calls: int) -> int:
    """Lower is better. Proxy = agent tool calls (or num_turns, per the spike decision)."""
    return tool_calls
