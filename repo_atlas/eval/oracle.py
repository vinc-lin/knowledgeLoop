from __future__ import annotations

from typing import Callable


def store_exists_fn(store, repo: str) -> Callable[[str], bool]:
    """An exists_fn(symbol)->bool backed by the repo_atlas store's indexed symbols.

    Caches the per-symbol lookups within a single eval run."""
    cache: dict[str, bool] = {}

    def exists(symbol: str) -> bool:
        if symbol not in cache:
            cache[symbol] = store.symbols_exist(repo, [symbol])[symbol]
        return cache[symbol]

    return exists
