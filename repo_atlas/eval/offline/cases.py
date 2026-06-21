from __future__ import annotations

import glob
import os
import tomllib
from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalCase:
    id: str
    repo: str
    query: str
    gold_files: tuple
    gold_symbols: tuple = ()
    source: str = "curated"


@dataclass(frozen=True)
class GroundingCase:
    id: str
    repo: str
    real_symbols: tuple
    fake_symbols: tuple


def _iter_tables(path: str):
    """Yield (file, case table) from a dir of .toml (or a single .toml). A file is either a
    single case (top-level keys) or an array of cases under [[case]]."""
    files = (sorted(glob.glob(os.path.join(path, "*.toml")))
             if os.path.isdir(path) else [path])
    for f in files:
        with open(f, "rb") as fh:
            data = tomllib.load(fh)
        if "case" in data:
            for tbl in data["case"]:
                yield f, tbl
        else:
            yield f, data


def _require(tbl: dict, keys: tuple, where: str):
    for k in keys:
        if not tbl.get(k):
            raise ValueError(f"offline case in {where}: missing/empty required field {k!r}")


def load_retrieval_cases(path: str) -> list:
    out, seen = [], set()
    for f, tbl in _iter_tables(path):
        _require(tbl, ("id", "repo", "query", "gold_files"), f)
        if tbl["id"] in seen:
            raise ValueError(f"duplicate retrieval case id {tbl['id']!r}")
        seen.add(tbl["id"])
        out.append(RetrievalCase(
            id=tbl["id"], repo=tbl["repo"], query=tbl["query"],
            gold_files=tuple(tbl["gold_files"]),
            gold_symbols=tuple(tbl.get("gold_symbols", ())),
            source=tbl.get("source", "curated")))
    return out


def load_grounding_cases(path: str) -> list:
    out, seen = [], set()
    for f, tbl in _iter_tables(path):
        _require(tbl, ("id", "repo", "real_symbols", "fake_symbols"), f)
        if tbl["id"] in seen:
            raise ValueError(f"duplicate grounding case id {tbl['id']!r}")
        seen.add(tbl["id"])
        out.append(GroundingCase(
            id=tbl["id"], repo=tbl["repo"],
            real_symbols=tuple(tbl["real_symbols"]),
            fake_symbols=tuple(tbl["fake_symbols"])))
    return out
