from __future__ import annotations

import os

from repo_memory.contract import envelope
from repo_atlas.retrieve import find_related_units
from repo_atlas.registry import repo_freshness, _head


def _symbol_ratio() -> float:
    from repo_atlas.config import load_config
    return load_config(os.environ).symbol_ratio


async def find_related(store, embedder, query: str, *, repos=None, kinds=None,
                       k: int = 20) -> dict:
    hits = await find_related_units(store, embedder, query, repos=repos, kinds=kinds, k=k,
                                    symbol_ratio=_symbol_ratio())
    if kinds is None:                              # grouped buckets for the default mixed call
        payload = {"docs": [h for h in hits if h["kind"] == "doc"],
                   "symbols": [h for h in hits if h["kind"] == "symbol"]}
    else:                                          # explicit kinds -> flat (back-compat)
        payload = hits
    return envelope(payload, freshness="fresh" if hits else "unverified",
                    warnings=[] if hits else ["no matches in index"])


def verify_grounding(store, repo: str, symbols: list[str]) -> dict:
    exists = store.symbols_exist(repo, symbols)
    result = {}
    unmatched = []
    for name in symbols:
        ok = exists[name]
        nearest = [] if ok else [u.name for u in store.nearest_symbols(repo, name, k=5)]
        result[name] = {"exists": ok, "nearest": nearest}
        if not ok:
            unmatched.append(name)
    return envelope(result, freshness="fresh", unmatched=unmatched,
                    warnings=[f"{len(unmatched)} symbol(s) not found in {repo}"]
                    if unmatched else [])


def list_repos(entries, store, *, head_fn=_head) -> dict:
    states = {s.repo: s for s in store.list_repo_states()}
    rows = []
    for e in entries:
        s = states.get(e.name)
        rows.append({"repo": e.name, "indexed_units": s.unit_count if s else 0,
                     "freshness": repo_freshness(e, store, head_fn=head_fn)})
    return envelope(rows, freshness="fresh")


async def prepare_change(store, embedder, target: str, repo: str) -> dict:
    """Index-derived context pack (Phase 1: no live graph; impact = Phase 2)."""
    sym = store.nearest_symbols(repo, target, k=1)
    conventions = await find_related_units(store, embedder, target, repos=[repo],
                                           kinds=["doc"], k=5)
    related = await find_related_units(store, embedder, target, repos=[repo], k=8)
    result = {
        "target": target,
        "symbol": ({"name": sym[0].name, "qualified_name": sym[0].qualified_name,
                    "file": sym[0].file} if sym else None),
        "conventions": conventions,
        "related": related,
        "note": "live callers/impact via assess_impact is Phase 2",
        "drill_down": {"repo": repo, "qualified_name": sym[0].qualified_name if sym else None},
    }
    return envelope(result, freshness="fresh" if sym else "unverified")
