from __future__ import annotations

import os
import re
from typing import Callable

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SRC_EXT = (".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".hh", ".java", ".kt",
            ".js", ".ts", ".jsx", ".tsx", ".py", ".go", ".rs", ".m", ".mm")
_SKIP_DIRS = {".git", "node_modules", "build", ".venv", "__pycache__", "dist"}


def _repo_tokens(repo_path: str) -> set:
    """Every identifier token in the repo's source files (one walk). Authoritative existence
    fallback for symbols the atlas index under-indexed. Unreadable files are skipped."""
    toks: set = set()
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fn in files:
            if fn.endswith(_SRC_EXT):
                try:
                    with open(os.path.join(root, fn), errors="ignore") as fh:
                        toks.update(_IDENT.findall(fh.read()))
                except OSError:
                    pass
    return toks


def store_exists_fn(store, repo: str, repo_path: str | None = None) -> Callable[[str], bool]:
    """An exists_fn(symbol)->bool: the repo_atlas index, then (if `repo_path` given) the repo
    source token set as an authoritative fallback. Per-symbol results and the token set (built
    lazily, once) are cached for the eval run."""
    cache: dict[str, bool] = {}
    tokens: dict[str, set] = {}

    def exists(symbol: str) -> bool:
        if symbol not in cache:
            ok = store.symbols_exist(repo, [symbol])[symbol]
            if not ok and repo_path:
                if "t" not in tokens:
                    tokens["t"] = _repo_tokens(repo_path)
                ok = symbol.split("::")[-1] in tokens["t"]
            cache[symbol] = ok
        return cache[symbol]

    return exists
