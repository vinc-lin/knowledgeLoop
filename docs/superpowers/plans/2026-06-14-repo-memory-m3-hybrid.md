# repo_memory M3: Hybrid Fusion Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the two hybrid fusion tools — `explain_with_sources` (read-only wiki narrative + graph-grounded evidence) and `assess_impact` (fail-closed, graph-verified change impact) — to the `repo_memory` facade.

**Architecture:** New `tools/hybrid_tools.py` composes existing M2 tool functions (`search_wiki`, `get_related_files`, `graph_tools.*`) and the bridge primitives (`CBMGraphProbe`, `verify_entries`); a small `grounding.py` provides the `graph_is_current` check for `assess_impact`'s fail-closed gate; `forward.py` gains a `detect_changes` wrapper (internal-only). The two tools register on the M2 FastMCP server (9 → 11 tools).

**Tech Stack:** Python 3.12, `mcp` SDK 1.27.2 (`FastMCP`), pytest + pytest-asyncio (STRICT → `@pytest.mark.asyncio`). Builds on `feat/repo-memory-m0-m1`.

**Spec:** `docs/superpowers/specs/2026-06-14-repo-memory-m3-hybrid-design.md`. Conventions: line-length 100; `tests/` gitignored → `git add -f`; unit tests offline (mock/monkeypatch the composed functions); do NOT stage the unrelated `CLAUDE.md` or untracked `.claude/`.

---

## File Structure

**Created:** `repo_memory/grounding.py` (`graph_is_current`), `repo_memory/tools/hybrid_tools.py` (`explain_with_sources`, `assess_impact` + helpers); tests `tests/test_rm_grounding.py`, `tests/test_rm_hybrid_explain.py`, `tests/test_rm_hybrid_impact.py`.
**Modified:** `repo_memory/graph/forward.py` (+`detect_changes`), `tests/test_rm_graph_forward.py`, `repo_memory/server.py` (TOOL_NAMES 9→11 + 2 registrations), `tests/test_rm_server.py` (9→11), `tests/test_rm_integration.py` (+assess_impact integration), `pyproject.toml` (none — marker already registered in M2).

**New signatures (locked):**
```python
# graph/forward.py
async def detect_changes(client, *, base_branch: str | None = None) -> Any
# grounding.py
def graph_is_current(state) -> bool
# tools/hybrid_tools.py
async def explain_with_sources(state, query: str, *, n: int = 3) -> dict
async def assess_impact(state, base_branch: str | None = None) -> dict
```
Reused (verified): `contract.envelope`, `wiki_tools.provenance/search_wiki/_find_module`, `bridge_tools.get_related_files`, `graph_tools.search_code_graph/get_code_snippet`, `graph.nodes.CBMGraphProbe`, `graph.client.CBMUnavailable`. `EntityEntry` fields: `symbol,file,cbm_node_id,lines,match_strategy,confidence,stale`. `AppState`: `wiki_dir,entity_map_path,repo_head,cbm,wiki,entity_map`.

---

## Task 1: `detect_changes` forward wrapper (internal)

**Files:** Modify `repo_memory/graph/forward.py`; Modify `tests/test_rm_graph_forward.py`

- [ ] **Step 1: Add failing test** — append to `tests/test_rm_graph_forward.py`:
```python
@pytest.mark.asyncio
async def test_detect_changes_args():
    c = _client({"changes": [], "impacted": []})
    await forward.detect_changes(c, base_branch="main")
    assert c.call_tool_with_restart.await_args.args == ("detect_changes", {"base_branch": "main"})
    await forward.detect_changes(c)
    assert c.call_tool_with_restart.await_args.args == ("detect_changes", {})
```

- [ ] **Step 2: Run to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_rm_graph_forward.py::test_detect_changes_args -p no:cacheprovider --no-cov -q`
Expected: FAIL — `AttributeError: module 'repo_memory.graph.forward' has no attribute 'detect_changes'`

- [ ] **Step 3: Add the wrapper** — append to `repo_memory/graph/forward.py`:
```python
async def detect_changes(client, *, base_branch: Optional[str] = None) -> Any:
    return await client.call_tool_with_restart(
        "detect_changes", _compact({"base_branch": base_branch}))
```

- [ ] **Step 4: Run to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_rm_graph_forward.py -p no:cacheprovider --no-cov -q`
Expected: PASS (all forward tests, incl. the new one).

- [ ] **Step 5: Commit**
```bash
git add -f tests/test_rm_graph_forward.py
git add repo_memory/graph/forward.py
git commit -m "feat(repo_memory): detect_changes forward wrapper (internal)"
```

---

## Task 2: `grounding.graph_is_current`

**Files:** Create `repo_memory/grounding.py`; Test `tests/test_rm_grounding.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_rm_grounding.py
"""graph_is_current: the fail-closed freshness gate for assess_impact."""

from repo_memory.state import AppState
from repo_memory.bridge.schema import EntityMap
from repo_memory.grounding import graph_is_current


def _state(cbm, repo_head, graph_commit, *, entity_map=True):
    em = EntityMap(repo_head, None, graph_commit, []) if entity_map else None
    return AppState(wiki_dir="w", entity_map_path="e", repo_head=repo_head, cbm=cbm, entity_map=em)


def test_current_when_cbm_and_commits_match():
    assert graph_is_current(_state(object(), "r1", "r1")) is True


def test_not_current_when_cbm_none():
    assert graph_is_current(_state(None, "r1", "r1")) is False


def test_not_current_when_graph_stale():
    assert graph_is_current(_state(object(), "r1", "rOLD")) is False


def test_not_current_when_no_entity_map():
    assert graph_is_current(_state(object(), "r1", "r1", entity_map=False)) is False


def test_not_current_when_graph_commit_none():
    assert graph_is_current(_state(object(), "r1", None)) is False
```

- [ ] **Step 2: Run to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_rm_grounding.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'repo_memory.grounding'`

- [ ] **Step 3: Write the implementation**
```python
# repo_memory/grounding.py
"""Fail-closed grounding helpers: is the graph current enough to ground against?"""

from __future__ import annotations


def graph_is_current(state) -> bool:
    """True only if CBM is available and the indexed graph matches the repo HEAD.

    Requires a CBM client, a known repo_head, and an entity_map whose graph_commit
    equals repo_head. Any unknown/mismatch returns False (fail closed).
    """
    if state.cbm is None or not state.repo_head:
        return False
    em = state.entity_map
    return bool(em and em.graph_commit and em.graph_commit == state.repo_head)
```

- [ ] **Step 4: Run to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_rm_grounding.py -p no:cacheprovider --no-cov -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**
```bash
git add -f tests/test_rm_grounding.py
git add repo_memory/grounding.py
git commit -m "feat(repo_memory): graph_is_current fail-closed grounding check"
```

---

## Task 3: `explain_with_sources` (read-only fusion)

**Files:** Create `repo_memory/tools/hybrid_tools.py`; Test `tests/test_rm_hybrid_explain.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_rm_hybrid_explain.py
"""explain_with_sources: narrative + multiple grounded evidence snippets."""

import pytest
from unittest.mock import AsyncMock

import repo_memory.tools.hybrid_tools as H
from repo_memory.state import AppState
from repo_memory.wiki.loader import WikiData


def _wiki():
    return WikiData(
        module_tree={"ingestion": {"path": "src/ingest", "components": [], "children": {}}},
        metadata={}, docs={"ingestion.md": "# Ingestion\n"}, wiki_commit="c",
        files_generated=["ingestion.md"])


def _state():
    return AppState(wiki_dir="w", entity_map_path="e", repo_head="r", cbm=object(), wiki=_wiki())


@pytest.mark.asyncio
async def test_entity_map_grounding(monkeypatch):
    monkeypatch.setattr(H, "search_wiki",
        lambda state, q: {"result": [{"doc": "ingestion.md", "snippet": "narrative text"}],
                          "warnings": []})
    monkeypatch.setattr(H.bridge_tools, "get_related_files", AsyncMock(return_value={
        "result": {"module": "ingestion", "files": ["src/ingest/p.py"],
                   "entries": [{"symbol": "Pipe", "file": "src/ingest/p.py",
                                "cbm_node_id": "ingest.Pipe", "lines": [1, 9],
                                "confidence": 1.0, "stale": False}]},
        "unmatched": [{"symbol": "Ghost"}], "warnings": []}))
    monkeypatch.setattr(H.graph_tools, "get_code_snippet",
        AsyncMock(return_value={"result": "class Pipe: ...", "warnings": []}))

    e = await H.explain_with_sources(_state(), "how does ingestion work")
    assert e["result"]["module"] == "ingestion"
    assert e["result"]["narrative"] == "narrative text"
    ev = e["result"]["evidence"]
    assert len(ev) == 1
    assert ev[0]["symbol"] == "Pipe" and ev[0]["grounding_method"] == "entity_map"
    assert ev[0]["snippet"] == "class Pipe: ..."
    assert e["unmatched"] == [{"symbol": "Ghost"}]
    assert e["confidence"] == 1.0


@pytest.mark.asyncio
async def test_graph_search_fallback(monkeypatch):
    # wiki hit whose doc does NOT map to a module -> fallback to graph search
    monkeypatch.setattr(H, "search_wiki",
        lambda state, q: {"result": [{"doc": "nomatch.md", "snippet": "n"}], "warnings": []})
    monkeypatch.setattr(H.graph_tools, "search_code_graph", AsyncMock(return_value={
        "result": {"results": [{"name": "Chunker", "qualified_name": "ingest.Chunker",
                                "file_path": "src/ingest/c.py", "start_line": 2, "end_line": 8}]},
        "warnings": []}))
    monkeypatch.setattr(H.graph_tools, "get_code_snippet",
        AsyncMock(return_value={"result": "def Chunker(): ...", "warnings": []}))

    e = await H.explain_with_sources(_state(), "chunker")
    assert e["result"]["module"] is None
    ev = e["result"]["evidence"]
    assert ev[0]["symbol"] == "Chunker" and ev[0]["grounding_method"] == "graph_search"


@pytest.mark.asyncio
async def test_degrades_without_wiki(monkeypatch):
    st = AppState(wiki_dir="w", entity_map_path="e", repo_head="r", cbm=object(), wiki=None)
    monkeypatch.setattr(H.graph_tools, "search_code_graph",
        AsyncMock(return_value={"result": {"results": []}, "warnings": []}))
    e = await H.explain_with_sources(st, "anything")
    assert e["result"]["narrative"] == "" and any("wiki" in w for w in e["warnings"])
```

- [ ] **Step 2: Run to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_rm_hybrid_explain.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'repo_memory.tools.hybrid_tools'`

- [ ] **Step 3: Write the implementation**
```python
# repo_memory/tools/hybrid_tools.py
"""Hybrid fusion tools: explain_with_sources (read-only) + assess_impact (fail-closed)."""

from __future__ import annotations

import re
from typing import Optional

from repo_memory.contract import envelope
from repo_memory.tools.wiki_tools import provenance, search_wiki, _find_module
from repo_memory.tools import bridge_tools, graph_tools

N_EVIDENCE = 3


def _terms_to_pattern(query: str) -> str:
    words = [re.escape(w) for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", query)]
    return "(" + "|".join(words) + ")" if words else ".*"


async def _snippet(state, qn: str) -> str:
    if not qn:
        return ""
    res = await graph_tools.get_code_snippet(state, qualified_name=qn)
    out = res.get("result")
    return out if isinstance(out, str) else ("" if out is None else str(out))


async def explain_with_sources(state, query: str, *, n: int = N_EVIDENCE) -> dict:
    warnings: list = []
    narrative, module = "", None

    if state.wiki:
        hits = search_wiki(state, query).get("result") or []
        if hits:
            narrative = hits[0].get("snippet", "")
            cand = hits[0]["doc"][:-3] if hits[0]["doc"].endswith(".md") else hits[0]["doc"]
            if _find_module(state.wiki.module_tree, cand) is not None:
                module = cand
    else:
        warnings.append("wiki artifacts unavailable")

    evidence: list = []
    unmatched: list = []
    if module is not None:
        rel = await bridge_tools.get_related_files(state, module)
        warnings.extend(rel.get("warnings") or [])
        unmatched = rel.get("unmatched") or []
        for entry in ((rel.get("result") or {}).get("entries") or [])[:n]:
            evidence.append({
                "symbol": entry.get("symbol", ""), "file": entry.get("file", ""),
                "lines": entry.get("lines"), "snippet": await _snippet(state, entry.get("cbm_node_id")),
                "grounding_method": "entity_map",
                "confidence": entry.get("confidence", 0.0), "stale": entry.get("stale", False)})
    else:
        sg = await graph_tools.search_code_graph(state, name_pattern=_terms_to_pattern(query), limit=n)
        warnings.extend(sg.get("warnings") or [])
        for row in ((sg.get("result") or {}).get("results") or [])[:n]:
            qn = row.get("qualified_name") or row.get("name", "")
            evidence.append({
                "symbol": row.get("name", ""), "file": row.get("file_path", ""),
                "lines": [row.get("start_line", 0), row.get("end_line", 0)],
                "snippet": await _snippet(state, qn), "grounding_method": "graph_search",
                "confidence": 0.85, "stale": False})

    conf = round(sum(e["confidence"] for e in evidence) / len(evidence), 3) if evidence else None
    fresh = "fresh" if evidence and not any(e["stale"] for e in evidence) else "unverified"
    return envelope({"narrative": narrative, "module": module, "evidence": evidence},
                    freshness=fresh, confidence=conf, warnings=warnings,
                    unmatched=unmatched, provenance=provenance(state))
```

- [ ] **Step 4: Run to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_rm_hybrid_explain.py -p no:cacheprovider --no-cov -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**
```bash
git add -f tests/test_rm_hybrid_explain.py
git add repo_memory/tools/hybrid_tools.py
git commit -m "feat(repo_memory): explain_with_sources (wiki narrative + grounded evidence)"
```

---

## Task 4: `assess_impact` (fail-closed)

**Files:** Modify `repo_memory/tools/hybrid_tools.py`; Test `tests/test_rm_hybrid_impact.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_rm_hybrid_impact.py
"""assess_impact: graph-grounding-only fail-closed gate + happy path."""

import pytest
from unittest.mock import AsyncMock

import repo_memory.tools.hybrid_tools as H
from repo_memory.state import AppState
from repo_memory.bridge.schema import EntityMap, ModuleMap, EntityEntry, NodeRecord


def _em(graph_commit="r", with_file=None):
    entries = []
    if with_file:
        entries = [EntityEntry("Sym", with_file, "m.Sym", [1, 9], "exact", 1.0)]
    return EntityMap("r", "w", graph_commit, [ModuleMap("mod", None, "p", entries, [])])


def _state(*, cbm=True, graph_commit="r", with_file=None):
    return AppState(wiki_dir="w", entity_map_path="e", repo_head="r",
                    cbm=(object() if cbm else None), entity_map=_em(graph_commit, with_file))


class _Probe:
    def __init__(self, present):
        self._p = present

    async def prefetch(self, qns):
        return None

    def lookup(self, qn):
        return self._p.get(qn)


def test_blocks_when_cbm_none():
    import asyncio
    e = asyncio.run(H.assess_impact(_state(cbm=False)))
    assert e["result"] is None and any("CBM" in w for w in e["warnings"])


def test_blocks_when_graph_stale():
    import asyncio
    e = asyncio.run(H.assess_impact(_state(graph_commit="OLD")))
    assert e["result"] is None and any("not current" in w for w in e["warnings"])


@pytest.mark.asyncio
async def test_blocks_when_detect_changes_fails(monkeypatch):
    from repo_memory.graph.client import CBMUnavailable
    monkeypatch.setattr(H.forward, "detect_changes", AsyncMock(side_effect=CBMUnavailable("boom")))
    e = await H.assess_impact(_state())
    assert e["result"] is None and any("boom" in w for w in e["warnings"])


@pytest.mark.asyncio
async def test_blocks_when_detect_changes_error_shape(monkeypatch):
    monkeypatch.setattr(H.forward, "detect_changes",
        AsyncMock(return_value={"error": "base 'nope' unresolved"}))
    e = await H.assess_impact(_state(), base_branch="nope")
    assert e["result"] is None and any("unresolved" in w for w in e["warnings"])


@pytest.mark.asyncio
async def test_blocks_when_symbol_unverifiable(monkeypatch):
    monkeypatch.setattr(H.forward, "detect_changes", AsyncMock(return_value={
        "changes": ["a.py"], "impacted": [{"qualified_name": "m.Gone", "risk": "high"}]}))
    monkeypatch.setattr(H, "CBMGraphProbe", lambda cbm: _Probe({}))  # nothing verifiable
    e = await H.assess_impact(_state())
    assert e["result"] is None and any("not verifiable" in w for w in e["warnings"])


@pytest.mark.asyncio
async def test_happy_path_with_and_without_module(monkeypatch):
    monkeypatch.setattr(H.forward, "detect_changes", AsyncMock(return_value={
        "changes": ["src/p.py", "src/x.py"],
        "impacted": [{"qualified_name": "m.Sym", "risk": "high"},
                     {"qualified_name": "m.Other", "risk": "low"}]}))
    nodes = {"m.Sym": NodeRecord("m.Sym", "Sym", "m.Sym", "src/p.py", 1, 9),
             "m.Other": NodeRecord("m.Other", "Other", "m.Other", "src/x.py", 1, 4)}
    monkeypatch.setattr(H, "CBMGraphProbe", lambda cbm: _Probe(nodes))
    # entity_map maps src/p.py -> module "mod"; src/x.py -> no module
    e = await H.assess_impact(_state(with_file="src/p.py"))
    assert e["freshness"] == "fresh"
    imp = {i["symbol"]: i for i in e["result"]["impacted"]}
    assert imp["Sym"]["module"] == "mod" and imp["Sym"]["verified"] is True
    assert imp["Other"]["module"] is None
    assert e["result"]["blast_radius"] == 2
    assert any("no wiki module" in w for w in e["warnings"])
```

- [ ] **Step 2: Run to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_rm_hybrid_impact.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `AttributeError: module 'repo_memory.tools.hybrid_tools' has no attribute 'assess_impact'`

- [ ] **Step 3: Add to `repo_memory/tools/hybrid_tools.py`**
Add these imports to the existing import block:
```python
from repo_memory.grounding import graph_is_current
from repo_memory.graph.nodes import CBMGraphProbe
from repo_memory.graph import forward
from repo_memory.graph.client import CBMUnavailable
```
Append the function + helper:
```python
def _module_for_file(state, file_path: str) -> Optional[str]:
    em = state.entity_map
    if not em:
        return None
    for m in em.modules:
        if any(e.file == file_path for e in m.entries):
            return m.module
    return None


async def assess_impact(state, base_branch: Optional[str] = None) -> dict:
    prov = provenance(state)

    def _blocked(reason, freshness="stale-graph"):
        return envelope(None, freshness=freshness, warnings=[f"cannot assess impact: {reason}"],
                        provenance=prov)

    # --- fail-closed gate (graph-grounding only) ---
    if state.cbm is None:
        return _blocked("CBM unavailable", freshness="unverified")
    if not graph_is_current(state):
        return _blocked("graph not current (re-index first)")
    try:
        changes = await forward.detect_changes(state.cbm, base_branch=base_branch)
    except CBMUnavailable as exc:
        return _blocked(str(exc))
    if not isinstance(changes, dict) or changes.get("error"):
        reason = (changes or {}).get("error", "detect_changes returned no usable result") \
            if isinstance(changes, dict) else "detect_changes returned no usable result"
        return _blocked(reason)

    impacted_in = changes.get("impacted") or []
    probe = CBMGraphProbe(state.cbm)
    qns = [i.get("qualified_name") or i.get("name") for i in impacted_in
           if (i.get("qualified_name") or i.get("name"))]
    await probe.prefetch(qns)

    impacted_out, no_module = [], []
    for item in impacted_in:
        qn = item.get("qualified_name") or item.get("name")
        node = probe.lookup(qn) if qn else None
        if node is None:
            return _blocked(f"symbol '{qn}' not verifiable in current graph")
        module = _module_for_file(state, node.file_path)
        if module is None:
            no_module.append(node.name)
        impacted_out.append({"symbol": node.name, "file": node.file_path,
                             "risk": item.get("risk"), "module": module, "verified": True})

    warnings = [f"{len(no_module)} impacted symbol(s) have no wiki module mapping"] if no_module else []
    return envelope({"base_branch": base_branch, "changes": changes.get("changes") or [],
                     "impacted": impacted_out, "blast_radius": len(impacted_out)},
                    freshness="fresh", confidence=(1.0 if impacted_out else None),
                    warnings=warnings, provenance=prov)
```

- [ ] **Step 4: Run to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_rm_hybrid_impact.py -p no:cacheprovider --no-cov -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**
```bash
git add -f tests/test_rm_hybrid_impact.py
git add repo_memory/tools/hybrid_tools.py
git commit -m "feat(repo_memory): assess_impact (fail-closed, graph-grounded change impact)"
```

---

## Task 5: Register the 2 hybrid tools on the server (9 → 11)

**Files:** Modify `repo_memory/server.py`; Modify `tests/test_rm_server.py`

- [ ] **Step 1: Update the server test for 11 tools** — in `tests/test_rm_server.py`, change the assertion `assert len(TOOL_NAMES) == 9` to:
```python
    assert len(TOOL_NAMES) == 11
```
(Leave the rest — `names == set(TOOL_NAMES)` and the description-length check — unchanged.)

- [ ] **Step 2: Run to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_rm_server.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `assert 9 == 11` (and names mismatch once you add to TOOL_NAMES it flips; run after Step 3 to confirm pass).

- [ ] **Step 3: Register the tools in `repo_memory/server.py`**
Add the import alongside the existing tool imports:
```python
from repo_memory.tools import wiki_tools, bridge_tools, graph_tools, hybrid_tools
```
Add the two names to `TOOL_NAMES` (after `"get_architecture"`):
```python
    "get_architecture",
    "explain_with_sources", "assess_impact",
]
```
Register the two tools inside `build_app` (after the `get_architecture` tool, before `return app`):
```python
    @app.tool(name="explain_with_sources",
              description="Explain how something works with GRAPH-VERIFIED source evidence "
                          "(wiki narrative + real files/symbols/snippets). Use for 'how does X "
                          "work / why' questions that need proof, not just narrative.")
    async def _explain(query: str) -> dict:
        return await hybrid_tools.explain_with_sources(state, query)

    @app.tool(name="assess_impact",
              description="Assess the blast radius of current changes — FAIL-CLOSED and "
                          "graph-verified (blocks if the graph isn't current). Use before "
                          "modifying/refactoring or for 'what does this change affect' questions.")
    async def _impact(base_branch: str = None) -> dict:
        return await hybrid_tools.assess_impact(state, base_branch=base_branch)
```

- [ ] **Step 4: Run to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_rm_server.py -p no:cacheprovider --no-cov -q`
Expected: PASS (1 passed — now 11 tools, all with descriptions).

- [ ] **Step 5: Commit**
```bash
git add -f tests/test_rm_server.py
git add repo_memory/server.py
git commit -m "feat(repo_memory): register explain_with_sources + assess_impact (9->11 tools)"
```

---

## Task 6: Integration test + milestone gate

**Files:** Modify `tests/test_rm_integration.py`

- [ ] **Step 1: Append a gated assess_impact integration test** to `tests/test_rm_integration.py`:
```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_assess_impact_blocks_when_graph_absent():
    """With no built entity_map (graph not current), assess_impact must fail closed."""
    import shutil
    from repo_memory.state import AppState
    from repo_memory.graph.client import CBMClient
    from repo_memory.tools.hybrid_tools import assess_impact
    if shutil.which("uvx") is None:
        pytest.skip("uvx not available")
    client = CBMClient()
    try:
        await client.start()
    except Exception as exc:
        pytest.skip(f"CBM unavailable: {exc}")
    try:
        # repo_head set but no entity_map -> graph_is_current False -> blocked
        st = AppState(wiki_dir="docs", entity_map_path="missing.json",
                      repo_head=_repo_head(), cbm=client, entity_map=None)
        e = await assess_impact(st)
        assert e["result"] is None
        assert any("not current" in w or "CBM" in w for w in e["warnings"])
    finally:
        await client.aclose()
```

- [ ] **Step 2: Run the M3 offline unit suite**
Run:
```bash
.venv/bin/python -m pytest tests/test_rm_graph_forward.py tests/test_rm_grounding.py \
  tests/test_rm_hybrid_explain.py tests/test_rm_hybrid_impact.py tests/test_rm_server.py \
  -p no:cacheprovider --no-cov -q
```
Expected: all PASS.

- [ ] **Step 3: Regression — full offline suite**
Run: `.venv/bin/python -m pytest tests/ -p no:cacheprovider --no-cov -q -m "not integration"`
Expected: all PASS. NOTE: if the pre-existing pytest capture-teardown error appears ("I/O operation on closed file"), re-run with `-s` and confirm "N passed, 0 failed".

- [ ] **Step 4: (Optional, manual) gated integration**
Run: `.venv/bin/python -m pytest tests/test_rm_integration.py -m integration -p no:cacheprovider --no-cov -q`
Expected: PASS or SKIP. **If real CBM `detect_changes` differs** from the mocked contract (arg name, result keys, error signaling for unresolved base / unsupported worktree), adjust `graph/forward.py::detect_changes` and `tools/hybrid_tools.py::assess_impact` (block-condition detection), update the affected unit tests, and re-commit.

- [ ] **Step 5: Commit**
```bash
git add -f tests/test_rm_integration.py
git commit -m "test(repo_memory): gated assess_impact integration + M3 offline gate"
```

---

## Self-Review (completed by plan author)

- **Spec coverage:** `detect_changes` wrapper (T1) · fail-closed gate helper (T2) · `explain_with_sources` with multiple grounded evidence + `grounding_method` + unmatched + entity_map/graph_search paths + degradation (T3) · `assess_impact` graph-grounding-only gate (6 block conditions) + happy path + best-effort module (`module=null` never blocks) (T4) · 11-tool surface + routing descriptions (T5) · integration + gate (T6). The spec's *optional* `trace_path` callers enrichment is intentionally **omitted** in M3 (deferred until the trace result shape is confirmed) — consistent with "optionally add" in §5.
- **Placeholder scan:** none — complete code in every step; commands have expected outcomes. The walrus shorthand in T3's first test is flagged with a plain-`e=` fallback.
- **Type consistency:** `envelope`, `provenance`, `search_wiki`, `_find_module`, `get_related_files`, `graph_tools.{search_code_graph,get_code_snippet}`, `CBMGraphProbe`, `graph_is_current`, `detect_changes`, `_module_for_file`, `TOOL_NAMES` are used with the exact signatures verified against the M2 code. `EntityEntry.file`/`.cbm_node_id`/`.confidence`/`.stale` and `NodeRecord.name`/`.file_path` match schema. Block-condition detection for base-unresolved/unsupported-worktree (spec conditions 3–4) is modeled via `detect_changes` raising or returning an `{"error": ...}` shape, with the real signaling confirmed in T6 (open question, per spec §12).
