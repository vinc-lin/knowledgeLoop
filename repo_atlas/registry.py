from __future__ import annotations

import tomllib
from dataclasses import dataclass
from typing import Callable, Optional

from repo_memory.server import _resolve_repo_head


@dataclass(frozen=True)
class RepoEntry:
    name: str
    repo_path: str
    wiki_dir: str
    entity_map: str


def load_registry(path: str) -> list[RepoEntry]:
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    return [RepoEntry(name=r["name"], repo_path=r["repo_path"], wiki_dir=r["wiki_dir"],
                      entity_map=r.get("entity_map", "")) for r in data.get("repo", [])]


def _head(repo_path: str) -> Optional[str]:
    return _resolve_repo_head(repo_path, {})


def repo_freshness(entry: RepoEntry, store, *,
                   head_fn: Callable[[str], Optional[str]] = _head) -> str:
    indexed = {s.repo: s.indexed_repo_head for s in store.list_repo_states()}
    if entry.name not in indexed:
        return "unindexed"
    return "fresh" if indexed[entry.name] == head_fn(entry.repo_path) else "stale"
