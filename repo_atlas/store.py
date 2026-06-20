from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Unit:
    repo: str
    kind: str                       # 'doc' | 'symbol'
    name: str
    qualified_name: Optional[str]
    file: Optional[str]
    repo_head: Optional[str]
    text: str
    meta: dict = field(default_factory=dict)

    @property
    def uid(self) -> str:
        key = f"{self.repo}\0{self.kind}\0{self.qualified_name or self.name}\0{self.text}"
        return hashlib.sha1(key.encode("utf-8")).hexdigest()


@dataclass
class RepoState:
    repo: str
    indexed_repo_head: Optional[str]
    indexed_at: float
    unit_count: int


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else -1.0


class Store:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self._schema()

    def _schema(self):
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS units(
              id TEXT PRIMARY KEY, repo TEXT, kind TEXT, name TEXT,
              qualified_name TEXT, file TEXT, repo_head TEXT, text TEXT, meta TEXT);
            CREATE VIRTUAL TABLE IF NOT EXISTS units_fts
              USING fts5(id UNINDEXED, name, qualified_name, text);
            CREATE TABLE IF NOT EXISTS vectors(id TEXT PRIMARY KEY, vec TEXT);
            CREATE TABLE IF NOT EXISTS repos(
              repo TEXT PRIMARY KEY, indexed_repo_head TEXT, indexed_at REAL,
              unit_count INTEGER);
            CREATE INDEX IF NOT EXISTS idx_units_repo ON units(repo);
            """
        )
        self.db.commit()

    def reindex_repo(self, repo: str, units_with_vecs, *, repo_head: Optional[str]):
        """Replace all rows for `repo`. `units_with_vecs` = iterable of (Unit, vec)."""
        cur = self.db.cursor()
        ids = [r["id"] for r in cur.execute("SELECT id FROM units WHERE repo=?", (repo,))]
        for uid in ids:
            cur.execute("DELETE FROM units_fts WHERE id=?", (uid,))
            cur.execute("DELETE FROM vectors WHERE id=?", (uid,))
        cur.execute("DELETE FROM units WHERE repo=?", (repo,))
        seen = set()
        for unit, vec in units_with_vecs:
            uid = unit.uid
            if uid in seen:
                continue
            seen.add(uid)
            cur.execute(
                "INSERT INTO units(id,repo,kind,name,qualified_name,file,repo_head,text,meta)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (uid, unit.repo, unit.kind, unit.name, unit.qualified_name, unit.file,
                 unit.repo_head, unit.text, json.dumps(unit.meta)))
            cur.execute("INSERT INTO units_fts(id,name,qualified_name,text) VALUES(?,?,?,?)",
                        (uid, unit.name, unit.qualified_name or "", unit.text))
            cur.execute("INSERT INTO vectors(id,vec) VALUES(?,?)", (uid, json.dumps(vec)))
        cur.execute(
            "INSERT OR REPLACE INTO repos(repo,indexed_repo_head,indexed_at,unit_count)"
            " VALUES(?,?,?,?)", (repo, repo_head, time.time(), len(seen)))
        self.db.commit()

    def _row_to_unit(self, row) -> Unit:
        return Unit(repo=row["repo"], kind=row["kind"], name=row["name"],
                    qualified_name=row["qualified_name"], file=row["file"],
                    repo_head=row["repo_head"], text=row["text"],
                    meta=json.loads(row["meta"] or "{}"))

    def _filter_sql(self, repos, kinds):
        clauses, params = [], []
        if repos:
            clauses.append(f"u.repo IN ({','.join('?' * len(repos))})"); params += list(repos)
        if kinds:
            clauses.append(f"u.kind IN ({','.join('?' * len(kinds))})"); params += list(kinds)
        return (" AND " + " AND ".join(clauses) if clauses else ""), params

    def keyword_search(self, query, k=20, repos=None, kinds=None):
        flt, params = self._filter_sql(repos, kinds)
        sql = ("SELECT u.* , bm25(units_fts) AS rank FROM units_fts "
               "JOIN units u ON u.id = units_fts.id "
               "WHERE units_fts MATCH ?" + flt + " ORDER BY rank LIMIT ?")
        rows = self.db.execute(sql, [_fts_query(query)] + params + [k]).fetchall()
        return [(self._row_to_unit(r), r["rank"]) for r in rows]

    def vector_search(self, qvec, k=20, repos=None, kinds=None):
        flt, params = self._filter_sql(repos, kinds)
        sql = ("SELECT u.*, v.vec AS vec FROM vectors v JOIN units u ON u.id=v.id "
               "WHERE 1=1" + flt)
        scored = []
        for r in self.db.execute(sql, params):
            scored.append((self._row_to_unit(r), _cosine(qvec, json.loads(r["vec"]))))
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:k]

    def list_repo_states(self):
        rows = self.db.execute(
            "SELECT repo,indexed_repo_head,indexed_at,unit_count FROM repos ORDER BY repo")
        return [RepoState(r["repo"], r["indexed_repo_head"], r["indexed_at"], r["unit_count"])
                for r in rows]

    def symbols_exist(self, repo, names):
        out = {}
        for n in names:
            row = self.db.execute(
                "SELECT 1 FROM units WHERE repo=? AND kind='symbol' AND (name=? OR "
                "qualified_name=?) LIMIT 1", (repo, n, n)).fetchone()
            out[n] = row is not None
        return out

    def nearest_symbols(self, repo, name, k=5):
        rows = self.db.execute(
            "SELECT u.* FROM units_fts JOIN units u ON u.id=units_fts.id "
            "WHERE units_fts MATCH ? AND u.repo=? AND u.kind='symbol' "
            "ORDER BY bm25(units_fts) LIMIT ?", (_fts_query(name), repo, k)).fetchall()
        return [self._row_to_unit(r) for r in rows]


def _fts_query(text: str) -> str:
    """Sanitize free text into a safe FTS5 OR query of bare tokens.

    Splits on non-alphanumeric boundaries AND on camelCase/PascalCase word
    boundaries so that e.g. ``cgeApplyBrightness`` also emits the sub-words
    ``cge``, ``Apply``, ``Brightness`` for fuzzy nearest-symbol matching.
    """
    # First split on non-alphanumeric separators
    raw = re.findall(r"[A-Za-z0-9]+", text)
    toks: list[str] = []
    for tok in raw:
        # Emit the whole token as-is
        toks.append(tok)
        # Also split camelCase/PascalCase into sub-words
        parts = re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?=[A-Z]|$)", tok)
        for p in parts:
            if p.lower() != tok.lower():
                toks.append(p)
    seen: set[str] = set()
    unique = [t for t in toks if not (t.lower() in seen or seen.add(t.lower()))]  # type: ignore[func-returns-value]
    return " OR ".join(unique) if unique else '""'
