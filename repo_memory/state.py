"""Shared application state for the facade tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from repo_memory.wiki.loader import load_wiki, WikiData
from repo_memory.bridge.schema import load_entity_map, EntityMap


@dataclass
class AppState:
    wiki_dir: str
    entity_map_path: str
    repo_head: Optional[str] = None
    repo_path: Optional[str] = None       # source repo to re-index (refresh)
    cbm: Optional[object] = None          # CBMClient | None (set by server lifespan)
    wiki: Optional[WikiData] = None
    entity_map: Optional[EntityMap] = None


def load_app_state(*, wiki_dir: str, entity_map_path: str,
                   repo_head: Optional[str] = None, repo_path: Optional[str] = None,
                   cbm=None) -> AppState:
    """Load wiki + entity_map from disk; missing/unreadable artifacts degrade to None."""
    try:
        wiki = load_wiki(wiki_dir)
    except Exception:
        wiki = None
    try:
        entity_map = load_entity_map(entity_map_path)
    except Exception:
        entity_map = None
    return AppState(wiki_dir=wiki_dir, entity_map_path=entity_map_path,
                    repo_head=repo_head, repo_path=repo_path, cbm=cbm,
                    wiki=wiki, entity_map=entity_map)
