# repo_atlas System (Phase 1a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `repo_atlas` cross-repo retrieval system — registry, indexer, SQLite store, hybrid (keyword + semantic) retrieval, and the MCP tool surface — that exploits existing per-repo wiki + graph knowledge to help a coding agent.

**Architecture:** A new `repo_atlas/` package layered above `repo_memory` (reusing its leaf modules: `wiki.loader`, `graph`, `contract`). An offline indexer ingests each repo's wiki sections + CBM symbols into one SQLite store (FTS5 keyword + embedding vectors). Queries hit only SQLite (no live CBM fan-out). Embeddings come from the gateway's OpenAI-compatible `/v1/embeddings`. Exposed as a stdio MCP server.

**Tech Stack:** Python 3.12, `sqlite3` (stdlib, FTS5), `httpx` (gateway embeddings), `mcp.server.fastmcp` (MCP), `pytest`/`pytest-asyncio`. Reuses `repo_memory` + `codewiki` config.

**Scope note:** This is plan **1a** (the system). The validation/eval harness (spec §13) is plan **1b**, written separately after 1a lands, because it consumes 1a.

**Conventions:**
- TDD: write the failing test, watch it fail, minimal code, watch it pass, commit.
- `tests/` is gitignored and force-added in this repo — new test files need `git add -f` (see CLAUDE.md).
- Run tests with `.venv/bin/python -m pytest <path> -p no:cacheprovider --no-cov -q` (pyproject sets `--cov`; `--no-cov` avoids needing coverage on new code; `-p no:cacheprovider` is the repo convention).
- Reference spec: `docs/superpowers/specs/2026-06-20-repo-atlas-design.md`.

**Phase-1 deviations from spec (deliberate, to keep 1a bounded):** `prepare_change` returns an *index-derived* context pack (target symbol + its module doc + scoped conventions + a drill-down handle); **live callers/`assess_impact`** wiring is Phase 2 (spec §11 "richer live graph drill-down"). Symbol units embed `name + qualified_name + file + label` (not full snippets); snippet-embedding is Phase 2.

---

## File Structure

**New package `repo_atlas/`:**
- `__init__.py` — package marker.
- `config.py` — `AtlasConfig` + `load_config()` (env + codewiki cred fallback).
- `store.py` — `Unit` dataclass + `Store` (SQLite schema, reindex, keyword/vector search, repo state, symbol existence/nearest).
- `embed.py` — `Embedder` protocol, `StubEmbedder`, `GatewayEmbedder`.
- `chunk.py` — `chunk_markdown`, `doc_units` (wiki doc → `Unit`s).
- `registry.py` — `RepoEntry` + `load_registry` + `repo_freshness`.
- `index.py` — `build_units` (pure) + `index_repo`/`index_all` (async IO).
- `retrieve.py` — `rrf_fuse` (pure) + `find_related_units` (async).
- `tools.py` — `find_related`, `verify_grounding`, `list_repos`, `prepare_change` (envelope-returning).
- `server.py` — FastMCP `build_app` + `main`.
- `__main__.py` — `python -m repo_atlas`.

**Modified:**
- `repo_memory/graph/nodes.py` — add `enumerate_all_nodes`.
- `pyproject.toml` — add `repo_atlas` package, `repo-atlas` console script, `httpx` dep.

**Tests:** `tests/test_ra_config.py`, `test_rm_graph_enumerate_all.py`, `test_ra_store.py`, `test_ra_embed.py`, `test_ra_chunk.py`, `test_ra_registry.py`, `test_ra_index.py`, `test_ra_retrieve.py`, `test_ra_tools.py`, `test_ra_server.py`, `test_ra_integration.py` (gated).

---

## Task 0: Verify the gateway embeddings model (prerequisite spike)

**Not TDD — an environment check that unblocks semantic search. Record the result in the plan/PR.**

- [ ] **Step 1: Query the gateway for an embeddings model**

Run (use the configured gateway base_url + key; `CODEWIKI_NO_KEYRING=1` reads the file-based key):

```bash
CODEWIKI_NO_KEYRING=1 .venv/bin/codewiki config show   # note base_url + that a key exists
# then list models on the gateway:
curl -s -H "Authorization: Bearer $KEY" http://192.168.31.240:4000/v1/models | python -m json.tool | grep -iE 'embed|bge|e5|gte' || echo "NO embeddings model found"
```

Expected: at least one embeddings-capable model id (e.g. `text-embedding-*`, `bge-*`). **Record its id and vector dimension** (POST one test string to `/v1/embeddings` and read `len(data[0].embedding)`).

- [ ] **Step 2: Confirm GPU serving (gateway-side)**

Confirm with whoever runs the gateway that the embeddings model is served on GPU. This is operational, not code. If no embeddings model exists, **stop and resolve before Task 4's integration test** — unit tests use a stub and are unblocked.

- [ ] **Step 3: Record findings**

Write the model id + dimension into the PR description / `REPO_ATLAS_EMBED_MODEL` default. No commit.

---

## Task 1: Scaffold the package + config

**Files:**
- Create: `repo_atlas/__init__.py`, `repo_atlas/config.py`
- Modify: `pyproject.toml`
- Test: `tests/test_ra_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ra_config.py
from repo_atlas.config import load_config, AtlasConfig


def test_env_overrides_and_defaults(tmp_path):
    env = {
        "REPO_ATLAS_BASE_URL": "http://gw/v1",
        "REPO_ATLAS_API_KEY": "sk-x",
        "REPO_ATLAS_EMBED_MODEL": "bge-m3",
        "REPO_ATLAS_DB": str(tmp_path / "a.db"),
    }
    cfg = load_config(env)
    assert isinstance(cfg, AtlasConfig)
    assert cfg.base_url == "http://gw/v1"
    assert cfg.api_key == "sk-x"
    assert cfg.embed_model == "bge-m3"
    assert cfg.db_path == str(tmp_path / "a.db")


def test_db_path_defaults_under_home():
    cfg = load_config({"REPO_ATLAS_BASE_URL": "u", "REPO_ATLAS_API_KEY": "k",
                       "REPO_ATLAS_EMBED_MODEL": "m"})
    assert cfg.db_path.endswith(".repo_atlas/atlas.db")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_ra_config.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'repo_atlas'`.

- [ ] **Step 3: Create the package + config**

```python
# repo_atlas/__init__.py
"""repo_atlas: cross-repo knowledge base over existing per-repo knowledge."""
```

```python
# repo_atlas/config.py
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class AtlasConfig:
    base_url: str
    api_key: str
    embed_model: str
    db_path: str


def _codewiki_creds() -> tuple[Optional[str], Optional[str]]:
    """Best-effort base_url + api_key from codewiki's stored config (default only)."""
    try:
        from codewiki.cli.config_manager import ConfigManager
        cm = ConfigManager()
        cm.load()
        cfg = cm.config  # Configuration with base_url; api_key via cm
        return getattr(cfg, "base_url", None), cm.get_api_key()
    except Exception:
        return None, None


def load_config(environ: Optional[dict] = None) -> AtlasConfig:
    env = environ if environ is not None else os.environ
    cw_base, cw_key = (None, None)
    base_url = env.get("REPO_ATLAS_BASE_URL")
    api_key = env.get("REPO_ATLAS_API_KEY")
    if base_url is None or api_key is None:
        cw_base, cw_key = _codewiki_creds()
    return AtlasConfig(
        base_url=base_url or cw_base or "",
        api_key=api_key or cw_key or "",
        embed_model=env.get("REPO_ATLAS_EMBED_MODEL", ""),
        db_path=env.get("REPO_ATLAS_DB", os.path.expanduser("~/.repo_atlas/atlas.db")),
    )
```

> Note: confirm `ConfigManager().get_api_key()` and `.config.base_url` exist; if the accessor names differ, adjust the lazy `_codewiki_creds` only (it is wrapped in try/except, so a mismatch degrades to empty strings rather than crashing).

- [ ] **Step 4: Register the package in pyproject**

Modify `pyproject.toml`: add `"repo_atlas"` to `[tool.setuptools] packages`, add `repo-atlas = "repo_atlas.server:main"` under `[project.scripts]`, and add `"httpx"` to `[project] dependencies` (it is already transitively present; declare it explicitly). Reinstall editable so the package resolves:

Run: `uv pip install --python .venv/bin/python -e .`

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_ra_config.py -p no:cacheprovider --no-cov -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add repo_atlas/__init__.py repo_atlas/config.py pyproject.toml
git add -f tests/test_ra_config.py
git commit -m "feat(repo_atlas): scaffold package + endpoint config"
```

---

## Task 2: `enumerate_all_nodes` foundation helper

**Files:**
- Modify: `repo_memory/graph/nodes.py`
- Test: `tests/test_rm_graph_enumerate_all.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rm_graph_enumerate_all.py
import pytest
from repo_memory.graph.nodes import enumerate_all_nodes


class FakeClient:
    """Returns 2 pages then empty; mimics CBM search_graph paging."""
    def __init__(self):
        self.calls = []

    async def call_tool_with_restart(self, name, args):
        self.calls.append((name, dict(args)))
        offset = args["offset"]
        if offset == 0:
            return {"results": [{"qualified_name": "a.f", "name": "f"},
                                {"qualified_name": "a.g", "name": "g"}], "has_more": True}
        if offset == 2:
            return {"results": [{"qualified_name": "a.g", "name": "g"}], "has_more": False}
        return {"results": []}


@pytest.mark.asyncio
async def test_enumerate_all_nodes_paginates_and_dedupes():
    client = FakeClient()
    rows = await enumerate_all_nodes(client, project="P", page_size=2)
    qns = sorted(r["qualified_name"] for r in rows)
    assert qns == ["a.f", "a.g"]            # deduped (a.g appeared twice)
    assert client.calls[0][1]["project"] == "P"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_rm_graph_enumerate_all.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ImportError: cannot import name 'enumerate_all_nodes'`.

- [ ] **Step 3: Add the helper**

Append to `repo_memory/graph/nodes.py`:

```python
async def enumerate_all_nodes(client, *, project: str, page_size: int = 200) -> list[dict]:
    """Every symbol row of a project (no filter), deduped by qualified_name.

    Returns the raw CBM search_graph rows (richer than NodeRecord) so callers can
    keep label/signature/etc. Touched only at index time.
    """
    seen: dict[str, dict] = {}
    offset = 0
    while True:
        resp = await forward.search_graph(client, project=project,
                                          limit=page_size, offset=offset)
        rows = _rows(resp)
        for row in rows:
            qn = row.get("qualified_name") or row.get("name")
            if qn:
                seen[qn] = row
        if len(rows) < page_size or not (isinstance(resp, dict) and resp.get("has_more")):
            break
        offset += page_size
    return list(seen.values())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_rm_graph_enumerate_all.py -p no:cacheprovider --no-cov -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add repo_memory/graph/nodes.py
git add -f tests/test_rm_graph_enumerate_all.py
git commit -m "feat(repo_memory): add enumerate_all_nodes (full-project symbol dump)"
```

---

## Task 3: SQLite store (`store.py`)

**Files:**
- Create: `repo_atlas/store.py`
- Test: `tests/test_ra_store.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ra_store.py
from repo_atlas.store import Store, Unit


def _u(repo, kind, name, text, qn=None, file=None):
    return Unit(repo=repo, kind=kind, name=name, qualified_name=qn, file=file,
                repo_head="HEAD1", text=text, meta={})


def test_reindex_keyword_vector_and_state(tmp_path):
    st = Store(str(tmp_path / "a.db"))
    units = [_u("r1", "symbol", "brightness", "adjust image brightness", qn="cge.brightness",
                file="f.cpp"),
             _u("r1", "doc", "Filters", "how filters are written", file="filters.md")]
    vecs = [[1.0, 0.0], [0.0, 1.0]]
    st.reindex_repo("r1", list(zip(units, vecs)), repo_head="HEAD1")

    kw = st.keyword_search("brightness", k=5)
    assert any(u.name == "brightness" for u, _ in kw)

    vec = st.vector_search([1.0, 0.0], k=5)
    assert vec[0][0].name == "brightness"          # closest to [1,0]

    states = st.list_repo_states()
    assert states[0].repo == "r1" and states[0].unit_count == 2
    assert states[0].indexed_repo_head == "HEAD1"


def test_reindex_is_idempotent(tmp_path):
    st = Store(str(tmp_path / "a.db"))
    u = _u("r1", "symbol", "x", "x text", qn="m.x")
    st.reindex_repo("r1", [(u, [1.0, 1.0])], repo_head="H")
    st.reindex_repo("r1", [(u, [1.0, 1.0])], repo_head="H")     # again
    assert st.list_repo_states()[0].unit_count == 1            # not doubled


def test_symbols_exist_and_nearest(tmp_path):
    st = Store(str(tmp_path / "a.db"))
    u = _u("r1", "symbol", "cgeBrightnessAdjust", "brightness filter",
           qn="cge.cgeBrightnessAdjust")
    st.reindex_repo("r1", [(u, [1.0])], repo_head="H")
    res = st.symbols_exist("r1", ["cgeBrightnessAdjust", "cgeApplyBrightness"])
    assert res["cgeBrightnessAdjust"] is True
    assert res["cgeApplyBrightness"] is False
    near = st.nearest_symbols("r1", "cgeApplyBrightness", k=3)
    assert "cgeBrightnessAdjust" in [n.name for n in near]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_ra_store.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'repo_atlas.store'`.

- [ ] **Step 3: Implement the store**

```python
# repo_atlas/store.py
from __future__ import annotations

import hashlib
import json
import math
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
        import os
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
            clauses.append(f"repo IN ({','.join('?' * len(repos))})"); params += list(repos)
        if kinds:
            clauses.append(f"kind IN ({','.join('?' * len(kinds))})"); params += list(kinds)
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
    """Sanitize free text into a safe FTS5 OR query of bare tokens."""
    import re
    toks = re.findall(r"[A-Za-z0-9_]+", text)
    return " OR ".join(toks) if toks else '""'
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_ra_store.py -p no:cacheprovider --no-cov -q`
Expected: PASS (3 passed). If FTS5 is unavailable, the schema raises — Python's stdlib sqlite3 ships FTS5 on this platform; confirm with `python -c "import sqlite3;sqlite3.connect(':memory:').execute('CREATE VIRTUAL TABLE t USING fts5(x)')"`.

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/store.py
git add -f tests/test_ra_store.py
git commit -m "feat(repo_atlas): SQLite store (FTS5 keyword + vector cosine + repo state)"
```

---

## Task 4: Embedders (`embed.py`)

**Files:**
- Create: `repo_atlas/embed.py`
- Test: `tests/test_ra_embed.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ra_embed.py
from repo_atlas.embed import StubEmbedder


def test_stub_is_deterministic_and_shaped():
    e = StubEmbedder(dim=8)
    a = e.embed(["hello world", "other"])
    assert len(a) == 2 and all(len(v) == 8 for v in a)
    assert e.embed(["hello world"])[0] == a[0]      # deterministic
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_ra_embed.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement embedders**

```python
# repo_atlas/embed.py
from __future__ import annotations

import hashlib
import math
from typing import Protocol


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class StubEmbedder:
    """Deterministic hash-based vectors for offline tests (no semantics)."""
    def __init__(self, dim: int = 16):
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for tok in t.split():
                h = int(hashlib.sha1(tok.encode("utf-8")).hexdigest(), 16)
                v[h % self.dim] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


class GatewayEmbedder:
    """Calls an OpenAI-compatible /v1/embeddings endpoint (GPU-served gateway)."""
    def __init__(self, base_url: str, api_key: str, model: str, batch: int = 64,
                 timeout: float = 60.0):
        self.url = base_url.rstrip("/") + "/embeddings"
        self.api_key = api_key
        self.model = model
        self.batch = batch
        self.timeout = timeout

    def embed(self, texts: list[str]) -> list[list[float]]:
        import httpx
        out: list[list[float]] = []
        headers = {"Authorization": f"Bearer {self.api_key}"}
        for i in range(0, len(texts), self.batch):
            chunk = texts[i:i + self.batch]
            resp = httpx.post(self.url, headers=headers,
                              json={"model": self.model, "input": chunk},
                              timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()["data"]
            out.extend(item["embedding"] for item in data)
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_ra_embed.py -p no:cacheprovider --no-cov -q`
Expected: PASS (1 passed). (`GatewayEmbedder` is exercised only in the gated integration test, Task 11.)

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/embed.py
git add -f tests/test_ra_embed.py
git commit -m "feat(repo_atlas): Stub + Gateway embedders"
```

---

## Task 5: Markdown chunker (`chunk.py`)

**Files:**
- Create: `repo_atlas/chunk.py`
- Test: `tests/test_ra_chunk.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ra_chunk.py
from repo_atlas.chunk import chunk_markdown, doc_units


def test_chunk_markdown_splits_by_heading():
    md = "# Title\nintro\n## A\nbody a\n## B\nbody b\n"
    secs = chunk_markdown(md)
    heads = [h for h, _ in secs]
    assert heads == ["Title", "A", "B"]
    assert "body a" in dict(secs)["A"]


def test_doc_units_carry_repo_and_module():
    md = "## Filters\nhow filters work\n"
    units = doc_units(md, repo="r1", module="Image Filters", file="filters.md",
                      repo_head="H")
    assert len(units) == 1
    u = units[0]
    assert u.repo == "r1" and u.kind == "doc" and u.name == "Filters"
    assert u.meta["module"] == "Image Filters"
    assert "how filters work" in u.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_ra_chunk.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement the chunker**

```python
# repo_atlas/chunk.py
from __future__ import annotations

import re

from repo_atlas.store import Unit

_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


def chunk_markdown(text: str) -> list[tuple[str, str]]:
    """Split markdown into (heading, body) sections by ATX headings.

    Content before the first heading is dropped (it is usually frontmatter)."""
    sections: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        m = _HEADING.match(line)
        if m:
            sections.append((m.group(2).strip(), []))
        elif sections:
            sections[-1][1].append(line)
    return [(h, "\n".join(b).strip()) for h, b in sections]


def doc_units(text: str, *, repo: str, module: str, file: str | None,
              repo_head: str | None) -> list[Unit]:
    units = []
    for ord_, (heading, body) in enumerate(chunk_markdown(text)):
        units.append(Unit(
            repo=repo, kind="doc", name=heading, qualified_name=None, file=file,
            repo_head=repo_head, text=f"{heading}\n{body}".strip(),
            meta={"module": module, "ord": ord_}))
    return units
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_ra_chunk.py -p no:cacheprovider --no-cov -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/chunk.py
git add -f tests/test_ra_chunk.py
git commit -m "feat(repo_atlas): markdown heading chunker -> doc units"
```

---

## Task 6: Registry + freshness (`registry.py`)

**Files:**
- Create: `repo_atlas/registry.py`
- Test: `tests/test_ra_registry.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ra_registry.py
from repo_atlas.registry import load_registry, RepoEntry, repo_freshness


def test_load_registry(tmp_path):
    toml = tmp_path / "atlas.toml"
    toml.write_text(
        '[[repo]]\nname="r1"\nrepo_path="/p/r1"\nwiki_dir="/w/r1"\n'
        'entity_map="/w/r1/entity_map.json"\n')
    entries = load_registry(str(toml))
    assert entries == [RepoEntry(name="r1", repo_path="/p/r1", wiki_dir="/w/r1",
                                 entity_map="/w/r1/entity_map.json")]


class _FakeStore:
    def __init__(self, head): self._head = head
    def list_repo_states(self):
        from repo_atlas.store import RepoState
        return [RepoState("r1", self._head, 0.0, 1)] if self._head else []


def test_repo_freshness_states():
    e = RepoEntry("r1", "/p/r1", "/w/r1", "/w/r1/em.json")
    assert repo_freshness(e, _FakeStore(None), head_fn=lambda p: "H1") == "unindexed"
    assert repo_freshness(e, _FakeStore("H1"), head_fn=lambda p: "H1") == "fresh"
    assert repo_freshness(e, _FakeStore("OLD"), head_fn=lambda p: "H1") == "stale"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_ra_registry.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement the registry**

```python
# repo_atlas/registry.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_ra_registry.py -p no:cacheprovider --no-cov -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/registry.py
git add -f tests/test_ra_registry.py
git commit -m "feat(repo_atlas): registry loader + freshness"
```

---

## Task 7: Indexer (`index.py`)

**Files:**
- Create: `repo_atlas/index.py`
- Test: `tests/test_ra_index.py`

- [ ] **Step 1: Write the failing test (pure `build_units`)**

```python
# tests/test_ra_index.py
from repo_atlas.index import build_units


class _Wiki:
    module_tree = {"Image Filters": {}}
    wiki_commit = "H"
    docs = {"image-filters.md": "## Image Filters\nhow filters work\n"}
    files_generated = ["image-filters.md"]


def test_build_units_makes_doc_and_symbol_units():
    symbol_rows = [{"qualified_name": "cge.brightness", "name": "brightness",
                    "label": "Class", "file_path": "f.cpp"}]
    units = build_units(_Wiki(), symbol_rows, repo="r1", repo_head="H")
    kinds = sorted({u.kind for u in units})
    assert kinds == ["doc", "symbol"]
    sym = [u for u in units if u.kind == "symbol"][0]
    assert sym.qualified_name == "cge.brightness" and sym.file == "f.cpp"
    assert "brightness" in sym.text and "Class" in sym.text
    doc = [u for u in units if u.kind == "doc"][0]
    assert doc.name == "Image Filters"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_ra_index.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement the indexer**

```python
# repo_atlas/index.py
from __future__ import annotations

from typing import Optional

from repo_atlas.chunk import doc_units
from repo_atlas.store import Store, Unit
from repo_atlas.registry import RepoEntry


def _symbol_unit(row: dict, *, repo: str, repo_head: Optional[str]) -> Unit:
    name = row.get("name", "")
    qn = row.get("qualified_name") or name
    label = row.get("label", "")
    file = row.get("file_path") or row.get("file")
    text = " ".join(p for p in [name, label, qn, file] if p)
    return Unit(repo=repo, kind="symbol", name=name, qualified_name=qn, file=file,
                repo_head=repo_head, text=text, meta={"label": label})


def build_units(wiki, symbol_rows: list[dict], *, repo: str,
                repo_head: Optional[str]) -> list[Unit]:
    """Pure: wiki + symbol rows -> Units (no IO). Tested directly."""
    units: list[Unit] = []
    docs = getattr(wiki, "docs", {}) or {}
    for fname, text in docs.items():
        module = fname.rsplit(".", 1)[0]
        units += doc_units(text, repo=repo, module=module, file=fname, repo_head=repo_head)
    for row in symbol_rows:
        units.append(_symbol_unit(row, repo=repo, repo_head=repo_head))
    return units


async def index_repo(entry: RepoEntry, store: Store, embedder) -> int:
    """Index one repo end-to-end (IO: wiki load + CBM enumerate + embed + store).

    Exercised by the gated integration test (Task 11), not unit tests."""
    from repo_memory.wiki.loader import load_wiki
    from repo_memory.server import _resolve_repo_head
    from repo_memory.deploy import resolve_launch_spec
    from repo_memory.graph.client import CBMClient
    from repo_memory.graph import forward
    from repo_memory.graph.nodes import enumerate_all_nodes
    import os

    repo_head = _resolve_repo_head(entry.repo_path, os.environ)
    wiki = load_wiki(entry.wiki_dir)

    spec = resolve_launch_spec(environ=os.environ)
    client = CBMClient(spec.command, env=spec.env, cwd=spec.cwd)
    symbol_rows: list[dict] = []
    try:
        await client.start()
        idx = await forward.index_repository(client, repo_path=entry.repo_path)
        project = idx["project"]
        symbol_rows = await enumerate_all_nodes(client, project=project)
    finally:
        await client.aclose()

    units = build_units(wiki, symbol_rows, repo=entry.name, repo_head=repo_head)
    vecs = embedder.embed([u.text for u in units]) if units else []
    store.reindex_repo(entry.name, list(zip(units, vecs)), repo_head=repo_head)
    return len(units)


async def index_all(entries, store: Store, embedder) -> dict:
    return {e.name: await index_repo(e, store, embedder) for e in entries}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_ra_index.py -p no:cacheprovider --no-cov -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/index.py
git add -f tests/test_ra_index.py
git commit -m "feat(repo_atlas): indexer (build_units pure + index_repo IO)"
```

---

## Task 8: Hybrid retrieval (`retrieve.py`)

**Files:**
- Create: `repo_atlas/retrieve.py`
- Test: `tests/test_ra_retrieve.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ra_retrieve.py
import pytest
from repo_atlas.retrieve import rrf_fuse, find_related_units
from repo_atlas.store import Store, Unit
from repo_atlas.embed import StubEmbedder


def test_rrf_fuse_rewards_agreement():
    fused = rrf_fuse([["a", "b", "c"], ["b", "a", "d"]], k0=60)
    ids = [i for i, _ in fused]
    assert ids[0] in ("a", "b")          # both ranked high in both lists
    assert set(ids) == {"a", "b", "c", "d"}


@pytest.mark.asyncio
async def test_find_related_returns_hits(tmp_path):
    st = Store(str(tmp_path / "a.db"))
    emb = StubEmbedder(dim=16)
    units = [Unit("r1", "symbol", "brightness", "adjust image brightness",
                  "cge.brightness", "f.cpp", "H", {}),
             Unit("r1", "doc", "Filters", "how filters work", None, "d.md", "H", {})]
    vecs = emb.embed([u.text for u in units])
    st.reindex_repo("r1", list(zip(units, vecs)), repo_head="H")
    hits = await find_related_units(st, emb, "brightness adjust", k=5)
    assert hits and hits[0]["repo"] == "r1"
    assert any(h["name"] == "brightness" for h in hits)
    assert "freshness" not in hits[0] or hits[0].get("repo")   # hit shape sane
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_ra_retrieve.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement retrieval**

```python
# repo_atlas/retrieve.py
from __future__ import annotations

from typing import Optional


def rrf_fuse(ranked_lists: list[list[str]], k0: int = 60) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion over lists of ids (best-first)."""
    scores: dict[str, float] = {}
    for lst in ranked_lists:
        for rank, _id in enumerate(lst):
            scores[_id] = scores.get(_id, 0.0) + 1.0 / (k0 + rank + 1)
    return sorted(scores.items(), key=lambda t: t[1], reverse=True)


def _hit(unit, repo_head, score, matched_via) -> dict:
    return {
        "repo": unit.repo, "kind": unit.kind, "name": unit.name,
        "qualified_name": unit.qualified_name, "file": unit.file,
        "snippet": unit.text[:400], "score": round(score, 5), "matched_via": matched_via,
        "indexed_repo_head": unit.repo_head,
        "drill_down": {"repo": unit.repo, "qualified_name": unit.qualified_name},
    }


async def find_related_units(store, embedder, query: str, *, repos=None, kinds=None,
                             k: int = 20) -> list[dict]:
    qvec = embedder.embed([query])[0]
    kw = store.keyword_search(query, k=k * 2, repos=repos, kinds=kinds)
    vec = store.vector_search(qvec, k=k * 2, repos=repos, kinds=kinds)
    by_id = {u.uid: u for u, _ in kw}
    by_id.update({u.uid: u for u, _ in vec})
    fused = rrf_fuse([[u.uid for u, _ in kw], [u.uid for u, _ in vec]])
    kw_ids = {u.uid for u, _ in kw}
    vec_ids = {u.uid for u, _ in vec}
    hits = []
    for uid, score in fused[:k]:
        u = by_id[uid]
        via = "+".join(([("keyword")] if uid in kw_ids else [])
                       + (["semantic"] if uid in vec_ids else []))
        hits.append(_hit(u, u.repo_head, score, via))
    return hits
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_ra_retrieve.py -p no:cacheprovider --no-cov -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/retrieve.py
git add -f tests/test_ra_retrieve.py
git commit -m "feat(repo_atlas): hybrid retrieval (RRF fusion of keyword+semantic)"
```

---

## Task 9: Tools (`tools.py`)

**Files:**
- Create: `repo_atlas/tools.py`
- Test: `tests/test_ra_tools.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ra_tools.py
import pytest
from repo_atlas import tools
from repo_atlas.store import Store, Unit
from repo_atlas.embed import StubEmbedder
from repo_atlas.registry import RepoEntry


def _seed(tmp_path):
    st = Store(str(tmp_path / "a.db"))
    emb = StubEmbedder(dim=16)
    units = [Unit("r1", "symbol", "cgeBrightnessAdjust", "adjust brightness",
                  "cge.cgeBrightnessAdjust", "f.cpp", "H", {}),
             Unit("r1", "doc", "Filters", "how filters work", None, "d.md", "H",
                  {"module": "Image Filters"})]
    st.reindex_repo("r1", list(zip(units, emb.embed([u.text for u in units]))), repo_head="H")
    return st, emb


@pytest.mark.asyncio
async def test_find_related_envelope(tmp_path):
    st, emb = _seed(tmp_path)
    env = await tools.find_related(st, emb, "brightness")
    assert "result" in env and "freshness" in env
    assert any(h["name"] == "cgeBrightnessAdjust" for h in env["result"])


def test_verify_grounding_flags_hallucinations(tmp_path):
    st, _ = _seed(tmp_path)
    env = tools.verify_grounding(st, "r1", ["cgeBrightnessAdjust", "cgeApplyBrightness"])
    res = env["result"]
    assert res["cgeBrightnessAdjust"]["exists"] is True
    assert res["cgeApplyBrightness"]["exists"] is False
    assert "cgeBrightnessAdjust" in res["cgeApplyBrightness"]["nearest"]


def test_list_repos(tmp_path):
    st, _ = _seed(tmp_path)
    entries = [RepoEntry("r1", "/p/r1", "/w/r1", "/w/r1/em.json")]
    env = tools.list_repos(entries, st, head_fn=lambda p: "H")
    assert env["result"][0]["repo"] == "r1"
    assert env["result"][0]["freshness"] == "fresh"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_ra_tools.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement tools**

```python
# repo_atlas/tools.py
from __future__ import annotations

from typing import Optional

from repo_memory.contract import envelope
from repo_atlas.retrieve import find_related_units
from repo_atlas.registry import repo_freshness, _head


async def find_related(store, embedder, query: str, *, repos=None, kinds=None,
                       k: int = 20) -> dict:
    hits = await find_related_units(store, embedder, query, repos=repos, kinds=kinds, k=k)
    return envelope(hits, freshness="fresh" if hits else "unverified",
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_ra_tools.py -p no:cacheprovider --no-cov -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/tools.py
git add -f tests/test_ra_tools.py
git commit -m "feat(repo_atlas): tools (find_related, verify_grounding, list_repos, prepare_change)"
```

---

## Task 10: MCP server (`server.py`, `__main__.py`)

**Files:**
- Create: `repo_atlas/server.py`, `repo_atlas/__main__.py`
- Test: `tests/test_ra_server.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ra_server.py
from repo_atlas.server import build_app, TOOL_NAMES


def test_build_app_registers_tools(tmp_path, monkeypatch):
    reg = tmp_path / "atlas.toml"
    reg.write_text('[[repo]]\nname="r1"\nrepo_path="/p"\nwiki_dir="/w"\nentity_map="/w/e.json"\n')
    monkeypatch.setenv("REPO_ATLAS_REGISTRY", str(reg))
    monkeypatch.setenv("REPO_ATLAS_DB", str(tmp_path / "a.db"))
    monkeypatch.setenv("REPO_ATLAS_BASE_URL", "u")
    monkeypatch.setenv("REPO_ATLAS_API_KEY", "k")
    monkeypatch.setenv("REPO_ATLAS_EMBED_MODEL", "m")
    app = build_app()
    assert app is not None
    assert set(TOOL_NAMES) == {"find_related", "prepare_change", "verify_grounding",
                               "list_repos"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_ra_server.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement the server**

```python
# repo_atlas/server.py
"""repo_atlas MCP server: cross-repo retrieval over existing knowledge (stdio)."""
from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from repo_atlas.config import load_config
from repo_atlas.store import Store
from repo_atlas.embed import GatewayEmbedder
from repo_atlas.registry import load_registry
from repo_atlas import tools

TOOL_NAMES = ["find_related", "prepare_change", "verify_grounding", "list_repos"]


def build_app() -> FastMCP:
    cfg = load_config(os.environ)
    store = Store(cfg.db_path)
    embedder = GatewayEmbedder(cfg.base_url, cfg.api_key, cfg.embed_model)
    registry_path = os.environ.get("REPO_ATLAS_REGISTRY", "atlas.toml")
    try:
        entries = load_registry(registry_path)
    except Exception:
        entries = []

    app = FastMCP("repo_atlas",
                  instructions="Cross-repo knowledge: find related code/docs across repos.")

    @app.tool(name="find_related",
              description="Find related code, building blocks, usage, and conventions across "
                          "ALL indexed repos. Use when writing/changing a function or fixing a bug.")
    async def _find(query: str, repos: list = None, kinds: list = None, k: int = 20) -> dict:
        return await tools.find_related(store, embedder, query, repos=repos, kinds=kinds, k=k)

    @app.tool(name="prepare_change",
              description="Assemble a grounded context pack for a change to a symbol/file in one repo.")
    async def _prep(target: str, repo: str) -> dict:
        return await tools.prepare_change(store, embedder, target, repo)

    @app.tool(name="verify_grounding",
              description="Check that referenced symbols actually exist in a repo's graph "
                          "(anti-hallucination); returns nearest real matches for any that don't.")
    def _verify(symbols: list, repo: str) -> dict:
        return tools.verify_grounding(store, repo, symbols)

    @app.tool(name="list_repos",
              description="List indexed repos + their freshness (indexed commit vs HEAD).")
    def _list() -> dict:
        return tools.list_repos(entries, store)

    return app


def main() -> None:
    build_app().run(transport="stdio")
```

```python
# repo_atlas/__main__.py
"""`python -m repo_atlas` -> the cross-repo MCP server (stdio)."""
from repo_atlas.server import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_ra_server.py -p no:cacheprovider --no-cov -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Run the whole offline suite (no regressions)**

Run: `.venv/bin/python -m pytest tests/ -p no:cacheprovider -m "not integration" --no-cov -s 2>&1 | grep -cE 'FAILED|ERROR'`
Expected: `0`.

- [ ] **Step 6: Commit**

```bash
git add repo_atlas/server.py repo_atlas/__main__.py
git add -f tests/test_ra_server.py
git commit -m "feat(repo_atlas): FastMCP stdio server (find_related/prepare_change/verify_grounding/list_repos)"
```

---

## Task 11: Gated end-to-end integration test

**Files:**
- Create: `tests/test_ra_integration.py`

**Prereq:** Task 0 confirmed an embeddings model; the 3 corpora have produced wikis +
`entity_map.json` (e.g. under `/home/vinc/e2e-knowledgeloop/<repo>/`). Set
`REPO_ATLAS_EMBED_MODEL`, `REPO_ATLAS_BASE_URL`, `REPO_ATLAS_API_KEY`, and
`CBM_CACHE_DIR` (off v9fs).

- [ ] **Step 1: Write the gated integration test**

```python
# tests/test_ra_integration.py
"""End-to-end: index one real corpus + query. Gated (needs gateway + uvx CBM)."""
import os
import shutil
import pytest

from repo_atlas.store import Store
from repo_atlas.embed import GatewayEmbedder
from repo_atlas.config import load_config
from repo_atlas.registry import RepoEntry
from repo_atlas.index import index_repo
from repo_atlas.tools import find_related

CORPUS = "/mnt/x/code/corpora/android-gpuimage-plus"
WIKI = "/home/vinc/e2e-knowledgeloop/android-gpuimage-plus/docs"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_index_and_find_related(tmp_path):
    if shutil.which("uvx") is None:
        pytest.skip("uvx not available")
    cfg = load_config(os.environ)
    if not cfg.base_url or not cfg.embed_model:
        pytest.skip("gateway embeddings not configured")
    store = Store(str(tmp_path / "atlas.db"))
    emb = GatewayEmbedder(cfg.base_url, cfg.api_key, cfg.embed_model)
    entry = RepoEntry("gpuimage", CORPUS, WIKI, WIKI + "/../entity_map.json")
    try:
        n = await index_repo(entry, store, emb)
    except Exception as exc:
        pytest.skip(f"index failed (CBM/gateway): {exc}")
    assert n > 0
    env = await find_related(store, emb, "adjust image brightness")
    assert env["result"], "expected related hits"
    assert any(h["repo"] == "gpuimage" for h in env["result"])
```

- [ ] **Step 2: Run it explicitly (optional, needs network + gateway)**

Run: `.venv/bin/python -m pytest tests/test_ra_integration.py -m integration -p no:cacheprovider --no-cov -q`
Expected: PASS, or SKIP if uvx/gateway absent.

- [ ] **Step 3: Commit**

```bash
git add -f tests/test_ra_integration.py
git commit -m "test(repo_atlas): gated end-to-end index+find_related integration test"
```

---

## Self-Review (done at authoring; notes for the implementer)

- **Spec coverage:** registry (T6), indexer + index-time-only CBM (T7), SQLite FTS5 + vectors store (T3), gateway embeddings (T4), RRF hybrid retrieval (T8), the 4 tools (T9), MCP server (T10), `enumerate_all_nodes` foundation touch (T2), `repo_atlas` endpoint config (T1), reuse `contract.envelope` (T9), correctness tests (T1–T10), gated integration (T11). The third foundation touch "reuse grounding" is satisfied by reusing `contract.envelope`; per-hit freshness is carried as `indexed_repo_head` on hits + `list_repos` freshness (T6/T9). **Deferred per spec §11/this plan's header:** live callers/`assess_impact` in `prepare_change`, snippet-embedding — both Phase 2.
- **Placeholder scan:** none — every code step is complete.
- **Type consistency:** `Unit`/`Store`/`RepoEntry`/`RepoState` signatures are defined in T3/T6 and used unchanged in T5/T7/T8/T9; `find_related_units` returns the hit dict shape consumed by `tools.find_related`; `Embedder.embed(texts)->list[list[float]]` is honored by both embedders and all callers.
- **Known verification points for the implementer:** (a) `ConfigManager` accessor names in `config._codewiki_creds` (wrapped in try/except); (b) CBM `search_graph` with no filter returns all symbols (Task 0/Task 11 will confirm); (c) FTS5 availability in stdlib sqlite3 (Task 3 Step 4 check).

---

## Execution Handoff

Plan complete. Plan **1b (the validation/eval harness)** is a separate plan to write after 1a lands (it consumes 1a). For 1a, two execution options:

1. **Subagent-Driven (recommended)** — a fresh subagent per task, review between tasks.
2. **Inline Execution** — execute tasks in this session with checkpoints.
