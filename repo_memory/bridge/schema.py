"""Entity-map data model and JSON (de)serialization."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Optional

CONFIDENCE = {"exact": 1.0, "qualified_suffix": 0.85, "file_only": 0.5, "unmatched": 0.0}


@dataclass(frozen=True)
class NodeRecord:
    """A code node as supplied by CBM (or a test fixture)."""
    node_id: str
    name: str
    qualified_name: str
    file_path: str
    start_line: int
    end_line: int


@dataclass
class EntityEntry:
    symbol: str
    file: str
    cbm_node_id: Optional[str]
    lines: Optional[list]          # [start, end] or None
    match_strategy: str            # exact | qualified_suffix | file_only | unmatched
    confidence: float
    stale: bool = False


@dataclass
class ModuleMap:
    module: str
    wiki_page: Optional[str]
    path: str
    entries: list = field(default_factory=list)      # list[EntityEntry]
    unmatched: list = field(default_factory=list)     # list[EntityEntry]


@dataclass
class EntityMap:
    built_at_repo_head: Optional[str]
    wiki_commit: Optional[str]
    graph_commit: Optional[str]
    modules: list = field(default_factory=list)       # list[ModuleMap]


def to_dict(em: EntityMap) -> dict:
    return asdict(em)


def _entry(d: dict) -> EntityEntry:
    return EntityEntry(
        symbol=d["symbol"], file=d["file"], cbm_node_id=d["cbm_node_id"],
        lines=d["lines"], match_strategy=d["match_strategy"],
        confidence=d["confidence"], stale=d.get("stale", False),
    )


def from_dict(d: dict) -> EntityMap:
    modules = [
        ModuleMap(
            module=m["module"], wiki_page=m["wiki_page"], path=m["path"],
            entries=[_entry(e) for e in m["entries"]],
            unmatched=[_entry(e) for e in m["unmatched"]],
        )
        for m in d["modules"]
    ]
    return EntityMap(
        built_at_repo_head=d["built_at_repo_head"],
        wiki_commit=d["wiki_commit"], graph_commit=d["graph_commit"],
        modules=modules,
    )


def save_entity_map(em: EntityMap, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(to_dict(em), fh, indent=2)


def load_entity_map(path: str) -> EntityMap:
    with open(path, encoding="utf-8") as fh:
        return from_dict(json.load(fh))
