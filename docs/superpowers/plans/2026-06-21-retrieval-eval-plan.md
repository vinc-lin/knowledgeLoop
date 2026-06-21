# Offline Retrieval + Grounding Eval — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, agent-free eval that measures `find_related` (Recall@k / MRR / nDCG, file-level primary) and `verify_grounding` (sensitivity / specificity) against curated + auto-generated ground truth.

**Architecture:** Pure-function metrics → frozen-dataclass cases (TOML) → a retriever adapter over the *real* `find_related_units` / `verify_grounding` → a resilient harness → a markdown report → a `repo-atlas eval-offline` CLI command. No agent, no judge, no MCP server.

**Tech Stack:** Python 3.12 (stdlib `tomllib`, `math`), pytest (+pytest-asyncio), the existing `repo_atlas` package (`retrieve.find_related_units`, `tools.verify_grounding`, `store.Store`, `embed.GatewayEmbedder`, `config.load_config`).

**Conventions:**
- Run tests: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest <file> -m "not integration" -p no:cacheprovider --no-cov -q`
- `tests/` is gitignored → new test files need `git add -f`.
- Line length 100; `from __future__ import annotations` at top of each module.
- The eval is run against the existing setup at `/home/vinc/repo-atlas-eval-full/` (`atlas.db` indexed with local Ollama `bge-m3`, `atlas.toml`, env vars `REPO_ATLAS_DB/REGISTRY/BASE_URL/API_KEY/EMBED_MODEL`).

---

## Verified API surfaces (do not re-derive — use exactly these)

```python
# repo_atlas/retrieve.py
async def find_related_units(store, embedder, query, *, repos=None, kinds=None, k=20) -> list[dict]
#   hit dict keys: repo, kind, name, qualified_name, file, snippet, score, matched_via,
#                  indexed_repo_head, drill_down
# repo_atlas/tools.py
def verify_grounding(store, repo: str, symbols: list[str]) -> dict
#   returns {sym: {"exists": bool, "nearest": list[str]}}   (SYNC, not async)
# repo_atlas/store.py
class Store:  def __init__(self, path: str)
# repo_atlas/embed.py
class GatewayEmbedder:  def __init__(self, base_url, api_key, embed_model)   # .embed(list[str]) -> list[list[float]]
# repo_atlas/config.py
@dataclass class AtlasConfig: base_url; api_key; embed_model; db_path
def load_config(environ=None) -> AtlasConfig
# repo_atlas/registry.py
@dataclass class RepoEntry: name; repo_path; wiki_dir; entity_map
def load_registry(path) -> list[RepoEntry]
```

---

## Task 1: Metrics (pure functions)

**Files:**
- Create: `repo_atlas/eval/offline/__init__.py` (empty)
- Create: `repo_atlas/eval/offline/metrics.py`
- Test: `tests/test_offline_metrics.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_offline_metrics.py
import math
from repo_atlas.eval.offline import metrics as m


def test_recall_at_k_file_level():
    ranked = ["a.h", "x.cpp", "b.h", "y.cpp"]
    gold = {"a.h", "b.h", "z.h"}
    assert m.recall_at_k(ranked, gold, k=2) == 1 / 3          # only a.h in top-2
    assert m.recall_at_k(ranked, gold, k=4) == 2 / 3          # a.h + b.h
    assert m.recall_at_k(ranked, set(), k=4) == 0.0           # empty gold guarded
    assert m.recall_at_k([], {"a.h"}, k=4) == 0.0


def test_hit_rate_at_k():
    assert m.hit_rate_at_k(["x", "a.h"], {"a.h"}, k=2) == 1.0
    assert m.hit_rate_at_k(["x", "a.h"], {"a.h"}, k=1) == 0.0


def test_mrr_uses_full_list():
    assert m.mrr(["x", "y", "a.h"], {"a.h"}) == 1 / 3
    assert m.mrr(["a.h", "y"], {"a.h"}) == 1.0
    assert m.mrr(["x", "y"], {"a.h"}) == 0.0


def test_ndcg_dedup_and_ideal():
    # one gold file at rank 1 (ideal) -> 1.0
    assert m.ndcg_at_k(["a.h", "x"], {"a.h"}, k=2) == 1.0
    # gold at rank 2 only: DCG = 1/log2(3); IDCG = 1/log2(2)=1
    got = m.ndcg_at_k(["x", "a.h"], {"a.h"}, k=2)
    assert math.isclose(got, (1 / math.log2(3)) / 1.0)
    # duplicate gold file counted once (dedup): second a.h contributes 0
    g2 = m.ndcg_at_k(["a.h", "a.h"], {"a.h"}, k=2)
    assert g2 == 1.0


def test_symbol_recall_at_k():
    hits = [{"name": "Foo", "qualified_name": "ns.Foo"},
            {"name": "Bar", "qualified_name": None}]
    assert m.symbol_recall_at_k(hits, ["Foo", "Bar", "Baz"], k=2) == 2 / 3
    assert m.symbol_recall_at_k(hits, ["ns.Foo"], k=2) == 1.0     # matches qualified_name
    assert m.symbol_recall_at_k(hits, [], k=2) == 0.0


def test_grounding_scores():
    v = {"Real1": {"exists": True}, "Real2": {"exists": False},   # Real2 = false negative
         "Fake1": {"exists": False}, "Fake2": {"exists": True}}   # Fake2 = false positive
    sc = m.grounding_scores(v, ["Real1", "Real2"], ["Fake1", "Fake2"])
    assert sc["sensitivity"] == 0.5
    assert sc["specificity"] == 0.5
    assert sc["false_negatives"] == ["Real2"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_offline_metrics.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ModuleNotFoundError: repo_atlas.eval.offline`.

- [ ] **Step 3: Create the package + implement**

```python
# repo_atlas/eval/offline/__init__.py
```
(empty file)

```python
# repo_atlas/eval/offline/metrics.py
from __future__ import annotations

import math


def recall_at_k(ranked_files: list, gold: set, k: int) -> float:
    """Fraction of gold files present among the top-k ranked files. 0.0 if gold empty."""
    if not gold:
        return 0.0
    topk = set(ranked_files[:k])
    return len(gold & topk) / len(gold)


def hit_rate_at_k(ranked_files: list, gold: set, k: int) -> float:
    """1.0 if any of the top-k ranked files is gold, else 0.0."""
    return 1.0 if (gold & set(ranked_files[:k])) else 0.0


def mrr(ranked_files: list, gold: set) -> float:
    """Reciprocal rank (1-indexed) of the first gold file in the FULL list. 0.0 if none."""
    for i, f in enumerate(ranked_files):
        if f in gold:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(ranked_files: list, gold: set, k: int) -> float:
    """Binary, file-level, dedup nDCG@k (each gold file rewarded once)."""
    if not gold:
        return 0.0
    dcg, seen = 0.0, set()
    for i, f in enumerate(ranked_files[:k]):
        if f in gold and f not in seen:
            seen.add(f)
            dcg += 1.0 / math.log2(i + 2)        # position p=i+1 -> 1/log2(p+1)
    ideal_hits = min(k, len(gold))
    idcg = sum(1.0 / math.log2(p + 1) for p in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def symbol_recall_at_k(hits: list, gold_symbols, k: int) -> float:
    """Fraction of gold symbols whose name or qualified_name appears in the top-k hits."""
    gold = set(gold_symbols)
    if not gold:
        return 0.0
    seen = set()
    for h in hits[:k]:
        for key in (h.get("name"), h.get("qualified_name")):
            if key in gold:
                seen.add(key)
    return len(seen) / len(gold)


def grounding_scores(verify_result: dict, real: list, fake: list) -> dict:
    """sensitivity = recall over real (source-verified) symbols; specificity over fakes."""
    def _exists(s):
        return bool(verify_result.get(s, {}).get("exists"))
    sens = (sum(1 for s in real if _exists(s)) / len(real)) if real else 0.0
    spec = (sum(1 for s in fake if not _exists(s)) / len(fake)) if fake else 0.0
    fn = [s for s in real if not _exists(s)]
    return {"sensitivity": sens, "specificity": spec, "false_negatives": fn}
```

- [ ] **Step 4: Run to verify it passes**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_offline_metrics.py -p no:cacheprovider --no-cov -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
cd /mnt/x/code/knowledgeLoop/.claude/worktrees/cm
git add repo_atlas/eval/offline/__init__.py repo_atlas/eval/offline/metrics.py
git add -f tests/test_offline_metrics.py
git commit -m "feat(repo_atlas/offline): retrieval + grounding metric functions"
```

---

## Task 2: Cases (dataclasses + TOML loaders)

**Files:**
- Create: `repo_atlas/eval/offline/cases.py`
- Test: `tests/test_offline_cases.py`

A `.toml` file holds either one case (top-level fields) or many (`[[case]]` array). Retrieval and grounding have separate loaders.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_offline_cases.py
import pytest
from repo_atlas.eval.offline.cases import (RetrievalCase, GroundingCase,
                                           load_retrieval_cases, load_grounding_cases)

RET_SINGLE = """
id = "c1"
repo = "r"
query = "find the filter base"
gold_files = ["a/b.h"]
gold_symbols = ["Base"]
"""

RET_ARRAY = """
[[case]]
id = "c2"
repo = "r"
query = "q2"
gold_files = ["x.cpp"]

[[case]]
id = "c3"
repo = "r"
query = "q3"
gold_files = ["y.cpp"]
"""

GND = """
id = "g1"
repo = "r"
real_symbols = ["Real1", "Real2"]
fake_symbols = ["FakeX"]
"""


def test_load_retrieval_single_and_array(tmp_path):
    (tmp_path / "a.toml").write_text(RET_SINGLE)
    (tmp_path / "b.toml").write_text(RET_ARRAY)
    cases = load_retrieval_cases(str(tmp_path))
    by_id = {c.id: c for c in cases}
    assert set(by_id) == {"c1", "c2", "c3"}
    assert by_id["c1"].gold_files == ("a/b.h",)
    assert by_id["c1"].gold_symbols == ("Base",)
    assert by_id["c2"].gold_symbols == ()           # default
    assert by_id["c2"].source == "curated"          # default


def test_load_grounding(tmp_path):
    (tmp_path / "g.toml").write_text(GND)
    cases = load_grounding_cases(str(tmp_path))
    assert len(cases) == 1 and isinstance(cases[0], GroundingCase)
    assert cases[0].real_symbols == ("Real1", "Real2")


def test_retrieval_missing_gold_files_errors(tmp_path):
    (tmp_path / "bad.toml").write_text('id="x"\nrepo="r"\nquery="q"\n')
    with pytest.raises(ValueError):
        load_retrieval_cases(str(tmp_path))


def test_duplicate_id_errors(tmp_path):
    # the same case id appears in two files -> loader must reject it
    (tmp_path / "e.toml").write_text(RET_SINGLE)
    (tmp_path / "f.toml").write_text(RET_SINGLE)
    with pytest.raises(ValueError):
        load_retrieval_cases(str(tmp_path))
```

- [ ] **Step 2: Run to verify it fails**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_offline_cases.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement**

```python
# repo_atlas/eval/offline/cases.py
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
    """Yield each case table from a dir of .toml (or a single .toml). A file is either a
    single case (top-level keys) or an array of cases under [[case]]."""
    files = (sorted(glob.glob(os.path.join(path, "*.toml")))
             if os.path.isdir(path) else [path])
    for f in files:
        with open(f, "rb") as fh:
            data = tomllib.load(fh)
        if "case" in data:
            yield from data["case"]
        else:
            yield data


def _require(tbl: dict, keys: tuple, where: str):
    for k in keys:
        if not tbl.get(k):
            raise ValueError(f"offline case in {where}: missing/empty required field {k!r}")


def load_retrieval_cases(path: str) -> list:
    out, seen = [], set()
    for tbl in _iter_tables(path):
        _require(tbl, ("id", "repo", "query", "gold_files"), path)
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
    for tbl in _iter_tables(path):
        _require(tbl, ("id", "repo", "real_symbols", "fake_symbols"), path)
        if tbl["id"] in seen:
            raise ValueError(f"duplicate grounding case id {tbl['id']!r}")
        seen.add(tbl["id"])
        out.append(GroundingCase(
            id=tbl["id"], repo=tbl["repo"],
            real_symbols=tuple(tbl["real_symbols"]),
            fake_symbols=tuple(tbl["fake_symbols"])))
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_offline_cases.py -p no:cacheprovider --no-cov -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/eval/offline/cases.py
git add -f tests/test_offline_cases.py
git commit -m "feat(repo_atlas/offline): RetrievalCase/GroundingCase + TOML loaders"
```

---

## Task 3: Retriever adapter

**Files:**
- Create: `repo_atlas/eval/offline/retriever.py`
- Test: `tests/test_offline_retriever.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_offline_retriever.py
import pytest
from repo_atlas.eval.offline.retriever import OfflineRetriever, StubRetriever


@pytest.mark.asyncio
async def test_stub_retriever():
    s = StubRetriever(
        hits_by_query={"q": [{"file": "a.h", "name": "A", "qualified_name": None}]},
        grounding_by_repo={"r": {"Real": True}})
    assert (await s.retrieve("q", "r", k=5))[0]["file"] == "a.h"
    assert await s.retrieve("missing", "r", k=5) == []
    g = s.ground("r", ["Real", "Nope"])
    assert g["Real"]["exists"] is True and g["Nope"]["exists"] is False


@pytest.mark.asyncio
async def test_offline_retriever_delegates(monkeypatch):
    captured = {}

    async def fake_find(store, embedder, query, *, repos=None, kinds=None, k=20):
        captured.update(query=query, repos=repos, k=k)
        return [{"file": "z.cpp", "name": "Z", "qualified_name": None}]

    def fake_verify(store, repo, symbols):
        captured.update(grepo=repo, syms=symbols)
        return {s: {"exists": True, "nearest": []} for s in symbols}

    monkeypatch.setattr("repo_atlas.retrieve.find_related_units", fake_find)
    monkeypatch.setattr("repo_atlas.tools.verify_grounding", fake_verify)
    r = OfflineRetriever(store=object(), embedder=object())
    hits = await r.retrieve("hello", "myrepo", k=7)
    assert hits[0]["file"] == "z.cpp"
    assert captured["repos"] == ["myrepo"] and captured["k"] == 7
    g = r.ground("myrepo", ["S"])
    assert g["S"]["exists"] is True and captured["grepo"] == "myrepo"
```

- [ ] **Step 2: Run to verify it fails**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_offline_retriever.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement**

```python
# repo_atlas/eval/offline/retriever.py
from __future__ import annotations


class OfflineRetriever:
    """Adapter over the production retrieval code paths (no MCP server)."""

    def __init__(self, store, embedder):
        self._store = store
        self._embedder = embedder

    async def retrieve(self, query: str, repo, k: int) -> list:
        import repo_atlas.retrieve as _r          # late import so monkeypatch targets the module
        repos = [repo] if repo else None
        return await _r.find_related_units(self._store, self._embedder, query, repos=repos, k=k)

    def ground(self, repo: str, symbols: list) -> dict:
        import repo_atlas.tools as _t
        return _t.verify_grounding(self._store, repo, list(symbols))


class StubRetriever:
    """Canned hits/grounding for tests (no store/embedder)."""

    def __init__(self, hits_by_query=None, grounding_by_repo=None):
        self._hits = hits_by_query or {}
        self._grounding = grounding_by_repo or {}

    async def retrieve(self, query: str, repo, k: int) -> list:
        return list(self._hits.get(query, []))[:k]

    def ground(self, repo: str, symbols: list) -> dict:
        known = self._grounding.get(repo, {})
        return {s: {"exists": bool(known.get(s, False)), "nearest": []} for s in symbols}
```

- [ ] **Step 4: Run to verify it passes**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_offline_retriever.py -p no:cacheprovider --no-cov -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/eval/offline/retriever.py
git add -f tests/test_offline_retriever.py
git commit -m "feat(repo_atlas/offline): OfflineRetriever adapter + StubRetriever"
```

---

## Task 4: Harness

**Files:**
- Create: `repo_atlas/eval/offline/harness.py`
- Test: `tests/test_offline_harness.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_offline_harness.py
import pytest
from repo_atlas.eval.offline.cases import RetrievalCase, GroundingCase
from repo_atlas.eval.offline.retriever import StubRetriever
from repo_atlas.eval.offline.harness import run_retrieval, run_grounding


@pytest.mark.asyncio
async def test_run_retrieval_aggregates_and_perrepo():
    cases = [
        RetrievalCase("c1", "r1", "q1", ("a.h",), ("A",)),
        RetrievalCase("c2", "r2", "q2", ("b.h",)),
    ]
    stub = StubRetriever(hits_by_query={
        "q1": [{"file": "a.h", "name": "A", "qualified_name": None}],     # rank-1 hit
        "q2": [{"file": "x.h", "name": "X", "qualified_name": None}],     # miss
    })
    rep = await run_retrieval(cases, stub, ks=(5,))
    assert rep.overall["n"] == 2
    assert rep.overall["recall@5"] == 0.5            # c1 hit, c2 miss
    assert rep.per_repo["r1"]["recall@5"] == 1.0
    assert rep.per_repo["r2"]["recall@5"] == 0.0
    assert rep.overall["sym_recall@5"] == 1.0        # only c1 has gold_symbols, and it hit


@pytest.mark.asyncio
async def test_run_retrieval_skips_failing_case():
    class Boom(StubRetriever):
        async def retrieve(self, query, repo, k):
            raise RuntimeError("retrieval died")
    cases = [RetrievalCase("c1", "r1", "q1", ("a.h",))]
    rep = await run_retrieval(cases, Boom(), ks=(5,))
    assert rep.overall["n"] == 0                      # skipped, not crashed


def test_run_grounding():
    cases = [GroundingCase("g1", "r1", ("Real1", "Real2"), ("Fake1",))]
    stub = StubRetriever(grounding_by_repo={"r1": {"Real1": True}})  # Real2 missing -> FN
    rep = run_grounding(cases, stub)
    assert rep.overall["sensitivity"] == 0.5
    assert rep.overall["specificity"] == 1.0
    assert rep.false_negatives["r1"] == ["Real2"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_offline_harness.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement**

```python
# repo_atlas/eval/offline/harness.py
from __future__ import annotations

from dataclasses import dataclass

from repo_atlas.eval.offline import metrics


@dataclass
class RetrievalReport:
    per_case: list
    overall: dict
    per_repo: dict


@dataclass
class GroundingReport:
    per_case: list
    overall: dict
    per_repo: dict
    false_negatives: dict


def _agg_retrieval(rows: list, ks) -> dict:
    out = {"n": len(rows)}
    keys = ([f"recall@{k}" for k in ks] + [f"hit@{k}" for k in ks]
            + [f"ndcg@{k}" for k in ks] + ["mrr"])
    for key in keys:
        vals = [r[key] for r in rows if key in r]
        out[key] = sum(vals) / len(vals) if vals else 0.0
    sym_key = f"sym_recall@{max(ks)}"
    sym_vals = [r[sym_key] for r in rows if sym_key in r]
    if sym_vals:
        out[sym_key] = sum(sym_vals) / len(sym_vals)
    return out


async def run_retrieval(cases: list, retriever, ks=(5, 10, 20)) -> RetrievalReport:
    kmax = max(ks)
    per_case = []
    for c in cases:
        try:
            hits = await retriever.retrieve(c.query, c.repo, kmax)
        except Exception as exc:                       # noqa: BLE001 - resilience boundary
            print(f"[offline-eval] case {c.id} failed: {type(exc).__name__}: {exc}")
            continue
        ranked_files = [h.get("file") for h in hits]
        gold_f = set(c.gold_files)
        row = {"id": c.id, "repo": c.repo, "source": c.source}
        for k in ks:
            row[f"recall@{k}"] = metrics.recall_at_k(ranked_files, gold_f, k)
            row[f"hit@{k}"] = metrics.hit_rate_at_k(ranked_files, gold_f, k)
            row[f"ndcg@{k}"] = metrics.ndcg_at_k(ranked_files, gold_f, k)
        row["mrr"] = metrics.mrr(ranked_files, gold_f)
        if c.gold_symbols:
            row[f"sym_recall@{kmax}"] = metrics.symbol_recall_at_k(hits, c.gold_symbols, kmax)
        per_case.append(row)
    repos = sorted({r["repo"] for r in per_case})
    per_repo = {rp: _agg_retrieval([r for r in per_case if r["repo"] == rp], ks) for rp in repos}
    return RetrievalReport(per_case, _agg_retrieval(per_case, ks), per_repo)


def _agg_grounding(rows: list) -> dict:
    out = {"n": len(rows)}
    for key in ("sensitivity", "specificity"):
        vals = [r[key] for r in rows]
        out[key] = sum(vals) / len(vals) if vals else 0.0
    return out


def run_grounding(cases: list, retriever) -> GroundingReport:
    per_case, fn_by_repo = [], {}
    for c in cases:
        v = retriever.ground(c.repo, list(c.real_symbols) + list(c.fake_symbols))
        sc = metrics.grounding_scores(v, list(c.real_symbols), list(c.fake_symbols))
        per_case.append({"id": c.id, "repo": c.repo,
                         "sensitivity": sc["sensitivity"], "specificity": sc["specificity"]})
        if sc["false_negatives"]:
            fn_by_repo.setdefault(c.repo, []).extend(sc["false_negatives"])
    repos = sorted({r["repo"] for r in per_case})
    per_repo = {rp: _agg_grounding([r for r in per_case if r["repo"] == rp]) for rp in repos}
    return GroundingReport(per_case, _agg_grounding(per_case), per_repo, fn_by_repo)
```

- [ ] **Step 4: Run to verify it passes**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_offline_harness.py -p no:cacheprovider --no-cov -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/eval/offline/harness.py
git add -f tests/test_offline_harness.py
git commit -m "feat(repo_atlas/offline): resilient retrieval+grounding harness with per-repo aggregation"
```

---

## Task 5: Report renderer

**Files:**
- Create: `repo_atlas/eval/offline/report.py`
- Test: `tests/test_offline_report.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_offline_report.py
import pytest
from repo_atlas.eval.offline.cases import RetrievalCase, GroundingCase
from repo_atlas.eval.offline.retriever import StubRetriever
from repo_atlas.eval.offline.harness import run_retrieval, run_grounding
from repo_atlas.eval.offline.report import render_offline_scorecard


@pytest.mark.asyncio
async def test_render_both_sections():
    rc = [RetrievalCase("c1", "r1", "q1", ("a.h",))]
    rret = await run_retrieval(rc, StubRetriever(
        hits_by_query={"q1": [{"file": "a.h", "name": "A", "qualified_name": None}]}), ks=(5,))
    gc = [GroundingCase("g1", "r1", ("Real",), ("Fake",))]
    gret = run_grounding(gc, StubRetriever(grounding_by_repo={"r1": {"Real": True}}))
    md = render_offline_scorecard(rret, gret, embed_model="bge-m3", db_path="/x/atlas.db")
    assert "Retrieval" in md and "Grounding" in md
    assert "Recall@5" in md
    assert "sensitivity" in md.lower()
    assert "bge-m3" in md                       # provenance recorded
    assert "r1" in md                           # per-repo row


def test_render_handles_skipped_layer():
    md = render_offline_scorecard(None, None)
    assert "no retrieval" in md.lower() or "skipped" in md.lower()
```

- [ ] **Step 2: Run to verify it fails**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_offline_report.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement**

```python
# repo_atlas/eval/offline/report.py
from __future__ import annotations


def _f(x) -> str:
    return f"{x:.3f}" if isinstance(x, (int, float)) else str(x)


def _retrieval_section(rep, ks=(5, 10, 20)) -> list:
    if rep is None:
        return ["## Retrieval (find_related)\n_no retrieval layer run._\n"]
    lines = [f"## Retrieval (find_related) — cases: {rep.overall['n']}\n",
             "| scope | Recall@5 | Recall@10 | Recall@20 | Hit@10 | MRR | nDCG@10 |",
             "|---|---|---|---|---|---|---|"]

    def row(name, agg):
        return (f"| {name} | {_f(agg.get('recall@5', 0))} | {_f(agg.get('recall@10', 0))} | "
                f"{_f(agg.get('recall@20', 0))} | {_f(agg.get('hit@10', 0))} | "
                f"{_f(agg.get('mrr', 0))} | {_f(agg.get('ndcg@10', 0))} |")

    lines.append(row("overall", rep.overall))
    for repo in sorted(rep.per_repo):
        lines.append(row(repo, rep.per_repo[repo]))
    sym = rep.overall.get(f"sym_recall@{max(ks)}")
    if sym is not None:
        lines.append(f"\n(secondary) symbol-level Recall@{max(ks)} overall: {_f(sym)}")
    return lines


def _grounding_section(rep) -> list:
    if rep is None:
        return ["## Grounding (verify_grounding)\n_no grounding layer run._\n"]
    lines = [f"## Grounding (verify_grounding) — cases: {rep.overall['n']}\n",
             "| scope | sensitivity | specificity |", "|---|---|---|",
             f"| overall | {_f(rep.overall['sensitivity'])} | {_f(rep.overall['specificity'])} |"]
    for repo in sorted(rep.per_repo):
        a = rep.per_repo[repo]
        lines.append(f"| {repo} | {_f(a['sensitivity'])} | {_f(a['specificity'])} |")
    if rep.false_negatives:
        lines.append("\n**Worst false-negatives (real symbols reported missing):**")
        for repo in sorted(rep.false_negatives):
            fns = rep.false_negatives[repo]
            lines.append(f"- {repo}: {', '.join(fns[:20])}" + (" …" if len(fns) > 20 else ""))
    return lines


def render_offline_scorecard(retrieval_report, grounding_report, *,
                             embed_model: str = "", db_path: str = "") -> str:
    head = ["# repo_atlas offline eval — retrieval + grounding\n"]
    if embed_model or db_path:
        head.append(f"_embed_model={embed_model or '?'} · db={db_path or '?'}_\n")
    return "\n".join(head + _retrieval_section(retrieval_report)
                     + ["\n"] + _grounding_section(grounding_report)) + "\n"
```

- [ ] **Step 4: Run to verify it passes**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_offline_report.py -p no:cacheprovider --no-cov -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/eval/offline/report.py
git add -f tests/test_offline_report.py
git commit -m "feat(repo_atlas/offline): markdown scorecard renderer (retrieval + grounding)"
```

---

## Task 6: Seed retrieval cases + gold-file verification

**Files:**
- Create: `repo_atlas/eval/offline/cases/retrieval/tasks.toml` (6 task-derived)
- Create: `repo_atlas/eval/offline/cases/retrieval/curated.toml` (≥9 curated)
- Create: `scripts/verify_offline_gold.py` (asserts every gold file exists under the repo's `repo_path`)

All gold files below are confirmed to exist in the corpora checkouts.

- [ ] **Step 1: Write the 6 task-derived cases**

```toml
# repo_atlas/eval/offline/cases/retrieval/tasks.toml
[[case]]
id = "task-gpuimage-add-sepia"
repo = "android-gpuimage-plus"
query = "Add a sepia-tone image filter to the CGE native filter library, following the existing filter pattern used by the other cge*Adjust filters."
gold_files = ["library/src/main/jni/cge/common/cgeImageFilter.h"]
gold_symbols = ["CGEImageFilterInterface"]
source = "task:gpuimage-add-sepia"

[[case]]
id = "task-gpuimage-fix-jni"
repo = "android-gpuimage-plus"
query = "A native method is failing to bind from Java to C++. Fix the JNI registration in the CGE native bridge so the Java layer can call into the native filter code."
gold_files = ["library/src/main/jni/cge/common/cgeGlobal.h"]
source = "task:gpuimage-fix-jni-registration"

[[case]]
id = "task-libxcam-add-handler"
repo = "libxcam"
query = "Add a new OpenCL image handler to libxcam that applies a simple gamma adjustment, following the existing CLImageHandler pattern in the ocl module."
gold_files = ["modules/ocl/cl_image_handler.h"]
gold_symbols = ["CLImageHandler"]
source = "task:libxcam-add-handler"

[[case]]
id = "task-libxcam-fix-csc"
repo = "libxcam"
query = "The color-space-conversion handler in libxcam produces incorrect output for a specific input format. Fix the CSC image handler."
gold_files = ["modules/ocl/cl_3a_image_processor.h"]
gold_symbols = ["CLCscImageHandler"]
source = "task:libxcam-fix-csc"

[[case]]
id = "task-ndk-add-native-method"
repo = "ndk-samples"
query = "Add a second native method to the hello-jni sample that returns the device's ABI string, registered the same way as the existing native method."
gold_files = ["hello-jni/app/src/main/cpp/hello-jni.cpp"]
gold_symbols = ["JNI_OnLoad"]
source = "task:ndk-add-native-method"

[[case]]
id = "task-ndk-fix-codec-crash"
repo = "ndk-samples"
query = "The native-codec sample crashes when the media format changes mid-stream. Fix the native codec handling so a format change is handled safely."
gold_files = ["native-codec/app/src/main/cpp/native-codec-jni.cpp"]
source = "task:ndk-fix-codec-crash"
```

- [ ] **Step 2: Write ≥9 curated cases**

```toml
# repo_atlas/eval/offline/cases/retrieval/curated.toml
[[case]]
id = "cur-gpuimage-filter-base"
repo = "android-gpuimage-plus"
query = "base class / interface that all CGE image filters implement"
gold_files = ["library/src/main/jni/cge/common/cgeImageFilter.h"]
gold_symbols = ["CGEImageFilterInterface"]

[[case]]
id = "cur-gpuimage-image-handler"
repo = "android-gpuimage-plus"
query = "CGE image handler that owns the filter chain and framebuffers"
gold_files = ["library/src/main/jni/cge/common/cgeImageHandler.h"]

[[case]]
id = "cur-gpuimage-jni-bridge"
repo = "android-gpuimage-plus"
query = "extern C JNI entry points exporting the CGE native library to Java"
gold_files = ["library/src/main/jni/cge/common/cgeGlobal.h"]

[[case]]
id = "cur-libxcam-image-handler-base"
repo = "libxcam"
query = "base class for OpenCL image handlers in the ocl module"
gold_files = ["modules/ocl/cl_image_handler.h"]
gold_symbols = ["CLImageHandler"]

[[case]]
id = "cur-libxcam-3a-processor"
repo = "libxcam"
query = "OpenCL 3A image processor pipeline that chains color conversion and adjustment handlers"
gold_files = ["modules/ocl/cl_3a_image_processor.h"]

[[case]]
id = "cur-libxcam-context"
repo = "libxcam"
query = "OpenCL context wrapper used to create kernels and command queues"
gold_files = ["modules/ocl/cl_context.h"]

[[case]]
id = "cur-ndk-hello-jni"
repo = "ndk-samples"
query = "hello-jni native method registration via JNI_OnLoad / RegisterNatives"
gold_files = ["hello-jni/app/src/main/cpp/hello-jni.cpp"]
gold_symbols = ["JNI_OnLoad"]

[[case]]
id = "cur-ndk-native-codec"
repo = "ndk-samples"
query = "native AMediaCodec decode loop handling output buffers and format changes"
gold_files = ["native-codec/app/src/main/cpp/native-codec-jni.cpp"]

[[case]]
id = "cur-ndk-native-audio"
repo = "ndk-samples"
query = "OpenSL ES native audio engine creation and buffer queue playback"
gold_files = ["native-audio/app/src/main/cpp/native-audio-jni.cpp"]
```

- [ ] **Step 3: Write the gold-file verifier**

```python
# scripts/verify_offline_gold.py
"""Assert every gold_files entry in the offline retrieval cases exists under its repo's
repo_path (from the registry). Exit non-zero on any missing file. Usage:
  REPO_ATLAS_REGISTRY=/path/atlas.toml python scripts/verify_offline_gold.py [CASES_DIR]
"""
import os
import sys

from repo_atlas.eval.offline.cases import load_retrieval_cases
from repo_atlas.registry import load_registry


def main() -> int:
    cases_dir = sys.argv[1] if len(sys.argv) > 1 else "repo_atlas/eval/offline/cases/retrieval"
    reg = {e.name: e.repo_path
           for e in load_registry(os.environ.get("REPO_ATLAS_REGISTRY", "atlas.toml"))}
    missing = []
    for c in load_retrieval_cases(cases_dir):
        base = reg.get(c.repo)
        if not base:
            missing.append(f"{c.id}: repo {c.repo!r} not in registry")
            continue
        for gf in c.gold_files:
            if not os.path.exists(os.path.join(base, gf)):
                missing.append(f"{c.id}: missing {gf}")
    if missing:
        print("GOLD FILE PROBLEMS:")
        for m in missing:
            print("  -", m)
        return 1
    print(f"OK: all gold files exist across the cases in {cases_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the verifier against the real registry**

Run:
```bash
cd /mnt/x/code/knowledgeLoop/.claude/worktrees/cm
CODEWIKI_NO_KEYRING=1 REPO_ATLAS_REGISTRY=/home/vinc/repo-atlas-eval-full/atlas.toml \
  /home/vinc/code/knowledgeLoop/.venv/bin/python scripts/verify_offline_gold.py
```
Expected: `OK: all gold files exist across the cases ...`. If any file is missing, fix the path in the `.toml` (grep the corpus under `/mnt/x/code/corpora/<repo>` for the correct location) and re-run until OK.

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/eval/offline/cases/retrieval/tasks.toml \
        repo_atlas/eval/offline/cases/retrieval/curated.toml scripts/verify_offline_gold.py
git commit -m "feat(repo_atlas/offline): seed retrieval cases (6 task-derived + 9 curated) + gold verifier"
```

---

## Task 7: Auto-generate grounding cases

**Files:**
- Create: `repo_atlas/eval/offline/gen_grounding.py`
- Create (generated, then committed): `repo_atlas/eval/offline/cases/grounding/<repo>.toml`
- Test: `tests/test_offline_gen_grounding.py`

The generator extracts **real** symbols from repo *source* (so the grounding metric can expose store under-indexing) and builds **fake** symbols by perturbation, verifying fakes are absent from source.

- [ ] **Step 1: Write the failing test (pure helpers)**

```python
# tests/test_offline_gen_grounding.py
from repo_atlas.eval.offline.gen_grounding import extract_symbols, make_fakes


def test_extract_symbols_cpp():
    src = ("class CGEImageFilterInterface {};\n"
           "struct CLImageHandler { };\n"
           "typedef const char* CGEConstString;\n"
           "#define CGE_SHADER_STRING_PRECISION_M 1\n"
           "int plain_function() { return 0; }\n")
    syms = extract_symbols(src)
    assert "CGEImageFilterInterface" in syms
    assert "CLImageHandler" in syms
    assert "CGEConstString" in syms                 # typedef name (the under-indexing target)
    assert "CGE_SHADER_STRING_PRECISION_M" in syms  # macro


def test_make_fakes_are_absent():
    real = ["CGEImageFilterInterface", "CLImageHandler"]
    corpus_text = "\n".join(real)
    fakes = make_fakes(real, corpus_text, n=2)
    assert len(fakes) == 2
    for f in fakes:
        assert f not in corpus_text                 # guaranteed absent
        assert f not in real
```

- [ ] **Step 2: Run to verify it fails**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_offline_gen_grounding.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement**

```python
# repo_atlas/eval/offline/gen_grounding.py
"""Generate grounding cases: real symbols grep-extracted from repo source (so the grounding
metric measures the store against reality), plus perturbed fakes verified absent from source.

CLI:  REPO_ATLAS_REGISTRY=.../atlas.toml \\
      python -m repo_atlas.eval.offline.gen_grounding --out repo_atlas/eval/offline/cases/grounding \\
      [--per-repo 40]
"""
from __future__ import annotations

import argparse
import os
import re

_SRC_EXT = (".h", ".hpp", ".hxx", ".c", ".cc", ".cpp", ".cxx", ".java", ".kt")
_CLASS = re.compile(r"\b(?:class|struct|interface)\s+([A-Za-z_][A-Za-z0-9_]{2,})")
_TYPEDEF = re.compile(r"\btypedef\b[^;{]*?\b([A-Za-z_][A-Za-z0-9_]{2,})\s*;")
_MACRO = re.compile(r"^\s*#\s*define\s+([A-Za-z_][A-Za-z0-9_]{2,})", re.M)


def extract_symbols(src: str) -> list:
    """Class/struct/interface names, typedef names, and macro names (order-preserving dedup)."""
    found = {}
    for rx in (_CLASS, _TYPEDEF, _MACRO):
        for name in rx.findall(src):
            found[name] = None
    return list(found)


def make_fakes(real: list, corpus_text: str, n: int) -> list:
    """Perturb real names into plausible-but-absent symbols (verified not in corpus_text)."""
    fakes, i = [], 0
    suffixes = ("Xyz", "FooBar", "2", "Impl9", "Nonexistent")
    while len(fakes) < n and i < len(real) * len(suffixes):
        base = real[i % len(real)]
        suf = suffixes[(i // len(real)) % len(suffixes)]
        cand = base + suf
        if cand not in corpus_text and cand not in real and cand not in fakes:
            fakes.append(cand)
        i += 1
    return fakes


def _read_source(repo_path: str) -> str:
    chunks = []
    for root, _dirs, files in os.walk(repo_path):
        if "/.git" in root:
            continue
        for fn in files:
            if fn.endswith(_SRC_EXT):
                try:
                    with open(os.path.join(root, fn), errors="ignore") as fh:
                        chunks.append(fh.read())
                except OSError:
                    pass
    return "\n".join(chunks)


def _toml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def generate(name: str, repo_path: str, per_repo: int) -> str:
    src = _read_source(repo_path)
    real = extract_symbols(src)[:per_repo]
    fakes = make_fakes(real, src, n=min(per_repo, len(real)))
    rl = ", ".join(f'"{_toml_escape(s)}"' for s in real)
    fl = ", ".join(f'"{_toml_escape(s)}"' for s in fakes)
    return (f'id = "{name}-symbols"\nrepo = "{name}"\n'
            f"real_symbols = [{rl}]\nfake_symbols = [{fl}]\n")


def main(argv=None) -> int:
    from repo_atlas.registry import load_registry
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--per-repo", type=int, default=40)
    ap.add_argument("--registry", default=os.environ.get("REPO_ATLAS_REGISTRY", "atlas.toml"))
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    for e in load_registry(args.registry):
        toml = generate(e.name, e.repo_path, args.per_repo)
        with open(os.path.join(args.out, f"{e.name}.toml"), "w") as fh:
            fh.write(toml)
        print(f"wrote {e.name}.toml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_offline_gen_grounding.py -p no:cacheprovider --no-cov -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Generate the real grounding cases + sanity-check**

Run:
```bash
cd /mnt/x/code/knowledgeLoop/.claude/worktrees/cm
CODEWIKI_NO_KEYRING=1 REPO_ATLAS_REGISTRY=/home/vinc/repo-atlas-eval-full/atlas.toml \
  /home/vinc/code/knowledgeLoop/.venv/bin/python -m repo_atlas.eval.offline.gen_grounding \
  --out repo_atlas/eval/offline/cases/grounding --per-repo 40
/home/vinc/code/knowledgeLoop/.venv/bin/python -c "from repo_atlas.eval.offline.cases import load_grounding_cases as L; cs=L('repo_atlas/eval/offline/cases/grounding'); print('repos:', [(c.repo, len(c.real_symbols), len(c.fake_symbols)) for c in cs])"
```
Expected: three `.toml` written; each case has ~40 real + up to 40 fake symbols.

- [ ] **Step 6: Commit**

```bash
git add repo_atlas/eval/offline/gen_grounding.py repo_atlas/eval/offline/cases/grounding/
git add -f tests/test_offline_gen_grounding.py
git commit -m "feat(repo_atlas/offline): grounding-case generator (source-grep reals + perturbed fakes) + generated cases"
```

---

## Task 8: CLI wiring + integration test

**Files:**
- Modify: `repo_atlas/cli.py` (add `eval-offline` subcommand + `_run_eval_offline`)
- Test: `tests/test_offline_integration.py` (gated `@pytest.mark.integration`)

- [ ] **Step 1: Add the subcommand to `build_parser`**

In `repo_atlas/cli.py`, after the `ev = sub.add_parser("eval", …)` block and before `return p`, add:

```python
    eo = sub.add_parser("eval-offline",
                        help="deterministic retrieval+grounding eval (no agent)")
    eo.add_argument("--cases", default="repo_atlas/eval/offline/cases",
                    help="dir with retrieval/ and grounding/ subdirs of case .toml")
    eo.add_argument("--layer", choices=["retrieval", "grounding", "all"], default="all")
    eo.add_argument("--k", default="5,10,20", help="comma-separated cutoffs")
    eo.add_argument("--out", default="offline-scorecard.md")
```

- [ ] **Step 2: Add the handler**

In `repo_atlas/cli.py`, add this function (after `_run_eval`):

```python
def _run_eval_offline(args) -> int:
    import asyncio as _aio

    from repo_atlas.config import load_config
    from repo_atlas.store import Store
    from repo_atlas.embed import GatewayEmbedder
    from repo_atlas.eval.offline.cases import load_retrieval_cases, load_grounding_cases
    from repo_atlas.eval.offline.retriever import OfflineRetriever
    from repo_atlas.eval.offline.harness import run_retrieval, run_grounding
    from repo_atlas.eval.offline.report import render_offline_scorecard

    cfg = load_config(os.environ)
    ks = tuple(int(x) for x in args.k.split(","))
    store = Store(cfg.db_path)
    embedder = GatewayEmbedder(cfg.base_url, cfg.api_key, cfg.embed_model)
    retriever = OfflineRetriever(store, embedder)

    rret = gret = None
    if args.layer in ("retrieval", "all"):
        rcases = load_retrieval_cases(os.path.join(args.cases, "retrieval"))
        rret = _aio.run(run_retrieval(rcases, retriever, ks=ks))
    if args.layer in ("grounding", "all"):
        gcases = load_grounding_cases(os.path.join(args.cases, "grounding"))
        gret = run_grounding(gcases, retriever)

    md = render_offline_scorecard(rret, gret, embed_model=cfg.embed_model, db_path=cfg.db_path)
    with open(args.out, "w") as fh:
        fh.write(md)
    print(md)
    print(f"\nwrote {args.out}")
    return 0
```

- [ ] **Step 3: Dispatch it in `main`**

In `repo_atlas/cli.py`, in `main()`, after the `if args.cmd == "eval": return _run_eval(args)` line add:

```python
    if args.cmd == "eval-offline":
        return _run_eval_offline(args)
```

- [ ] **Step 4: Write the gated integration test**

```python
# tests/test_offline_integration.py
import os
import pytest

pytestmark = pytest.mark.integration

DB = "/home/vinc/repo-atlas-eval-full/atlas.db"


@pytest.mark.asyncio
@pytest.mark.skipif(not os.path.exists(DB), reason="real atlas.db not present")
async def test_offline_eval_runs_against_real_store():
    from repo_atlas.store import Store
    from repo_atlas.embed import GatewayEmbedder
    from repo_atlas.eval.offline.cases import load_retrieval_cases
    from repo_atlas.eval.offline.retriever import OfflineRetriever
    from repo_atlas.eval.offline.harness import run_retrieval

    store = Store(DB)
    embedder = GatewayEmbedder(os.environ.get("REPO_ATLAS_BASE_URL", "http://127.0.0.1:11434/v1"),
                               os.environ.get("REPO_ATLAS_API_KEY", "local"),
                               os.environ.get("REPO_ATLAS_EMBED_MODEL", "bge-m3"))
    cases = load_retrieval_cases("repo_atlas/eval/offline/cases/retrieval")
    rep = await run_retrieval(cases, OfflineRetriever(store, embedder), ks=(5, 10, 20))
    assert rep.overall["n"] >= 1
    assert 0.0 <= rep.overall["recall@20"] <= 1.0
```

- [ ] **Step 5: Run the unit suite (integration deselected)**

Run:
```bash
cd /mnt/x/code/knowledgeLoop/.claude/worktrees/cm
/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_offline_*.py \
  -m "not integration" -p no:cacheprovider --no-cov -q
```
Expected: all offline unit tests pass; `test_offline_integration.py` deselected.

- [ ] **Step 6: Lint + commit**

```bash
/home/vinc/code/knowledgeLoop/.venv/bin/ruff check repo_atlas/cli.py repo_atlas/eval/offline/
git add repo_atlas/cli.py
git add -f tests/test_offline_integration.py
git commit -m "feat(repo_atlas/offline): eval-offline CLI command + gated integration test"
```

---

## Task 9: First real run + sanity check

**Files:** none (operational).

- [ ] **Step 1: Verify Ollama is up**

Run: `curl -s -m 5 http://127.0.0.1:11434/api/tags | grep -o bge-m3` → expect `bge-m3`. If absent, start Ollama / the embedding backend before continuing.

- [ ] **Step 2: Run the full offline eval against the real store**

Run:
```bash
cd /mnt/x/code/knowledgeLoop/.claude/worktrees/cm
FULL=/home/vinc/repo-atlas-eval-full
CODEWIKI_NO_KEYRING=1 REPO_ATLAS_DB=$FULL/atlas.db REPO_ATLAS_REGISTRY=$FULL/atlas.toml \
  REPO_ATLAS_BASE_URL=http://127.0.0.1:11434/v1 REPO_ATLAS_API_KEY=local \
  REPO_ATLAS_EMBED_MODEL=bge-m3 \
  /home/vinc/code/knowledgeLoop/.venv/bin/python -m repo_atlas eval-offline \
  --cases repo_atlas/eval/offline/cases --layer all --out $FULL/offline-scorecard.md
```
Expected: a scorecard with a Retrieval table (overall + 3 per-repo rows, Recall@5/10/20, MRR, nDCG) and a Grounding table (sensitivity/specificity + a false-negatives list). Runtime: seconds to ~1 min.

- [ ] **Step 3: Sanity-check the numbers**

Confirm: retrieval `n` ≥ 15, every metric ∈ [0,1]; grounding sensitivity < 1.0 on at least one repo (it should expose the known under-indexing — e.g. typedef/macro reals reported missing) and specificity ≈ 1.0 (fakes correctly rejected). Read the false-negative list — it is the actionable index-gap report.

- [ ] **Step 4: Run the integration test explicitly (optional confirmation)**

Run:
```bash
FULL=/home/vinc/repo-atlas-eval-full
CODEWIKI_NO_KEYRING=1 REPO_ATLAS_BASE_URL=http://127.0.0.1:11434/v1 REPO_ATLAS_API_KEY=local \
  REPO_ATLAS_EMBED_MODEL=bge-m3 \
  /home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_offline_integration.py \
  -m integration -p no:cacheprovider --no-cov -q -s
```
Expected: PASS.

- [ ] **Step 5: Final full unit-suite regression + merge**

Run the whole suite (capture-safe per the known CBM-stdout teardown artifact):
```bash
/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/ \
  --ignore=tests/test_eval_integration.py --ignore=tests/test_offline_integration.py \
  -p no:cacheprovider --no-cov -s -o addopts="" > /tmp/offline_suite.log 2>&1; echo "exit=$?"
```
Expected: `exit=0`. Then merge to master:
```bash
git -C /home/vinc/code/knowledgeLoop merge --ff-only worktree-cm
git -C /home/vinc/code/knowledgeLoop push origin master
```

---

## Self-review checklist (done while writing)

- **Spec coverage:** metrics (T1), cases+loaders (T2), retriever adapter over real code paths (T3), resilient harness w/ per-repo agg (T4), scorecard incl. provenance + false-negatives (T5), hybrid seed: 6 task-derived + 9 curated retrieval (T6) + auto grounding (T7), `eval-offline` CLI + integration test (T8), first run + index-gap read (T9). Commit-mining left as the documented future hook (spec §Extensibility) — intentionally out of scope.
- **Type consistency:** `RetrievalCase`/`GroundingCase` fields, `run_retrieval(cases, retriever, ks)`, report dataclasses (`per_case/overall/per_repo[/false_negatives]`), and metric signatures match across tasks.
- **No placeholders:** every code step has complete code; every run step has an exact command + expected output. (T2 Step 1 carries an explicit correction note for the `test_duplicate_id_errors` body — apply it before running.)
