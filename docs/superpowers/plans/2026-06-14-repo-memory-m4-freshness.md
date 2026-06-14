# repo_memory M4: Freshness, Two-Tier Policy & Bounded Refresh — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make response `freshness` real and centrally computed, generalize the warn-vs-fail-closed policy, fix the `graph_commit` recording gap, and add a bounded `refresh` (re-index + rebuild) exposed as a 12th tool.

**Architecture:** A pure `grounding.compute_freshness` (graph>wiki precedence) + `require_fresh` (returns the blocking freshness string or None — Tier-B tools build their own blocked envelope, so `grounding` stays import-light and cycle-free). Tier-A tools route freshness through `compute_freshness`; `build_and_save` records `graph_commit=repo_head`; `refresh.py` re-indexes CBM + rebuilds the entity_map.

**Tech Stack:** Python 3.12, pytest + pytest-asyncio (STRICT → `@pytest.mark.asyncio`), `mcp` SDK 1.27.2. Builds on `feat/repo-memory-m0-m1`.

**Spec:** `docs/superpowers/specs/2026-06-14-repo-memory-m4-freshness-design.md`. Conventions: line-length 100; `tests/` gitignored → `git add -f`; unit tests offline (mock state/CBM with AsyncMock); transient `.git/index.lock` on commit → retry; do NOT stage `CLAUDE.md` or `.claude/`.

---

## File Structure

**Modify:** `repo_memory/grounding.py` (+`compute_freshness`, `require_fresh`), `repo_memory/entity_map_build.py` (graph_commit fix), `repo_memory/tools/{bridge_tools,graph_tools,wiki_tools}.py` (use `compute_freshness`), `repo_memory/tools/hybrid_tools.py` (`require_fresh` + `require_verification`), `repo_memory/graph/forward.py` (+`index_repository`), `repo_memory/state.py` (`repo_path`), `repo_memory/server.py` (register `refresh_index` → 12; pass `repo_path`).
**Create:** `repo_memory/refresh.py`; tests `tests/test_rm_freshness.py`, `tests/test_rm_refresh.py`.
**Test churn (existing files):** `tests/test_rm_bridge_tools.py`, `tests/test_rm_hybrid_impact.py`, `tests/test_rm_entity_map_build.py`, `tests/test_rm_server.py`.

**Locked signatures:**
```python
# grounding.py (no new imports — stays pure)
def compute_freshness(state, *, entries_stale: bool = False) -> str  # "fresh"|"stale-wiki"|"stale-graph"|"unverified"
def require_fresh(state) -> "str | None"   # blocking freshness if NOT graph-current, else None
# entity_map_build.build_and_save -> also passes graph_commit=repo_head
# graph/forward.py
async def index_repository(client, *, path: str) -> Any
# refresh.py
async def refresh(state) -> dict
# state.AppState: + repo_path: Optional[str] = None ; load_app_state(..., repo_path=None)
```

---

## Task 1: `compute_freshness` + `require_fresh`

**Files:** Modify `repo_memory/grounding.py`; Test `tests/test_rm_freshness.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_rm_freshness.py
"""Central freshness enum (graph>wiki precedence) + require_fresh gate."""

from repo_memory.state import AppState
from repo_memory.bridge.schema import EntityMap
from repo_memory.wiki.loader import WikiData
from repo_memory.grounding import compute_freshness, require_fresh


def _state(*, cbm=True, repo_head="r", graph_commit="r", wiki_commit=None, em=True):
    entity_map = EntityMap(repo_head, wiki_commit, graph_commit, []) if em else None
    wiki = WikiData({}, {}, {}, wiki_commit, []) if wiki_commit is not None else None
    return AppState(wiki_dir="w", entity_map_path="e", repo_head=repo_head,
                    cbm=(object() if cbm else None), wiki=wiki, entity_map=entity_map)


def test_unverified_when_no_cbm_or_missing_commit():
    assert compute_freshness(_state(cbm=False)) == "unverified"
    assert compute_freshness(_state(graph_commit=None)) == "unverified"
    assert compute_freshness(_state(em=False)) == "unverified"


def test_stale_graph_beats_wiki():
    # both graph and wiki behind HEAD -> graph wins
    assert compute_freshness(_state(graph_commit="OLD", wiki_commit="OLD")) == "stale-graph"


def test_entries_stale_forces_stale_graph():
    assert compute_freshness(_state(graph_commit="r"), entries_stale=True) == "stale-graph"


def test_stale_wiki_when_only_wiki_behind():
    assert compute_freshness(_state(graph_commit="r", wiki_commit="OLD")) == "stale-wiki"


def test_fresh_when_all_aligned():
    assert compute_freshness(_state(graph_commit="r", wiki_commit="r")) == "fresh"


def test_require_fresh_none_when_current():
    assert require_fresh(_state(graph_commit="r")) is None


def test_require_fresh_returns_blocking_freshness():
    assert require_fresh(_state(cbm=False)) == "unverified"
    assert require_fresh(_state(graph_commit="OLD")) == "stale-graph"


def test_require_fresh_does_not_block_on_stale_wiki():
    # graph current, wiki behind -> NOT blocked (graph-only gate)
    assert require_fresh(_state(graph_commit="r", wiki_commit="OLD")) is None
```

- [ ] **Step 2: Run to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_rm_freshness.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ImportError: cannot import name 'compute_freshness'`

- [ ] **Step 3: Add to `repo_memory/grounding.py`** (append after `graph_is_current`; no new imports):
```python
def compute_freshness(state, *, entries_stale: bool = False) -> str:
    """Reporting enum, precedence graph > wiki.

    unverified: can't tell (no CBM / missing commits). stale-graph: graph behind
    HEAD or a returned entry failed verify-on-access. stale-wiki: only docs behind
    HEAD. fresh: all aligned.
    """
    rh = state.repo_head
    em = state.entity_map
    if state.cbm is None or not rh or em is None or not em.graph_commit:
        return "unverified"
    if em.graph_commit != rh or entries_stale:
        return "stale-graph"
    wiki_commit = state.wiki.wiki_commit if state.wiki else em.wiki_commit
    if wiki_commit and wiki_commit != rh:
        return "stale-wiki"
    return "fresh"


def require_fresh(state):
    """Tier-B gate: return the blocking freshness ('unverified'/'stale-graph') when
    the graph is NOT current, else None. Graph-only — a stale wiki never blocks.
    Callers build their own blocked envelope from the returned string."""
    if graph_is_current(state):
        return None
    return compute_freshness(state)
```

- [ ] **Step 4: Run to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_rm_freshness.py -p no:cacheprovider --no-cov -q`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**
```bash
git add -f tests/test_rm_freshness.py
git add repo_memory/grounding.py
git commit -m "feat(repo_memory): compute_freshness + require_fresh (graph>wiki, graph-only gate)"
```

---

## Task 2: Fix the `graph_commit` recording gap

**Files:** Modify `repo_memory/entity_map_build.py`; Modify `tests/test_rm_entity_map_build.py`

- [ ] **Step 1: Add a failing assertion** — in `tests/test_rm_entity_map_build.py`, inside `test_build_and_save_grounds_known_symbol`, after `assert saved.wiki_commit == "wsha"` add:
```python
    assert saved.graph_commit == "rsha"   # recorded = repo_head (M4 fix)
```

- [ ] **Step 2: Run to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_rm_entity_map_build.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `assert None == 'rsha'` (graph_commit currently unset).

- [ ] **Step 3: Pass `graph_commit` in `build_and_save`** — in `repo_memory/entity_map_build.py`, change the `build_entity_map(...)` call (currently lines 29–30):
```python
    em = build_entity_map(wiki.module_tree, nodes, repo_root=repo_root,
                          repo_head=repo_head, wiki_commit=wiki.wiki_commit)
```
to:
```python
    em = build_entity_map(wiki.module_tree, nodes, repo_root=repo_root,
                          repo_head=repo_head, wiki_commit=wiki.wiki_commit,
                          graph_commit=repo_head)   # graph was just enumerated at repo_head
```

- [ ] **Step 4: Run to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_rm_entity_map_build.py -p no:cacheprovider --no-cov -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**
```bash
git add -f tests/test_rm_entity_map_build.py
git add repo_memory/entity_map_build.py
git commit -m "fix(repo_memory): build_and_save records graph_commit=repo_head"
```

---

## Task 3: Tier-A freshness — bridge_tools + graph_tools

**Files:** Modify `repo_memory/tools/bridge_tools.py`, `repo_memory/tools/graph_tools.py`; Modify `tests/test_rm_bridge_tools.py`

- [ ] **Step 1: Update bridge fixtures + add freshness assertions** — in `tests/test_rm_bridge_tools.py`:
  - Change `_state` (line ~21) to give a CBM sentinel (so freshness can be computed):
    ```python
    def _state(entity_map):
        return AppState(wiki_dir="w", entity_map_path="e", repo_head="r",
                        cbm=object(), entity_map=entity_map)
    ```
  - Change `_em` (line ~25) so `graph_commit` matches repo_head:
    ```python
        return EntityMap("r", "w", "r", [ModuleMap("mod", None, "p", [entry], [])])
    ```
  - In `test_returns_entries_and_confidence_when_fresh`, add: `assert e["freshness"] == "fresh"`
  - In `test_marks_stale_when_node_gone`, add: `assert e["freshness"] == "stale-graph"`
  (Leave `test_degrades_when_cbm_down` — it builds `AppState(... entity_map=_em())` with no cbm, so it stays `"unverified"`.)

- [ ] **Step 2: Run to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_rm_bridge_tools.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — the new freshness assertions fail (current code computes `"fresh"`/`"stale-graph"` inline only via `any_stale`, but the new `"fresh"` assert may pass while `stale` still works; the real failure appears once Step 3 swaps to `compute_freshness`). If both new asserts already pass, proceed to Step 3 anyway to centralize.

- [ ] **Step 3: Use `compute_freshness` in bridge_tools** — in `repo_memory/tools/bridge_tools.py`:
  - Add import: `from repo_memory.grounding import compute_freshness`
  - In the CBM-unavailable branch (the early `return envelope(...)` ~lines 34–39), add `freshness=compute_freshness(state),` to that envelope call.
  - Change the final return's `freshness=("stale-graph" if any_stale else "fresh")` (line ~49) to:
    ```python
        freshness=compute_freshness(state, entries_stale=any_stale),
    ```

- [ ] **Step 4: Use `compute_freshness` in graph_tools** — replace `_run` in `repo_memory/tools/graph_tools.py`:
  - Add import: `from repo_memory.grounding import compute_freshness`
  - Replace the `_run` body:
    ```python
    async def _run(state, coro_factory):
        f = compute_freshness(state)
        if state.cbm is None:
            return envelope(None, freshness=f, warnings=["CBM unavailable"],
                            provenance=provenance(state))
        try:
            result = await coro_factory(state.cbm)
        except CBMUnavailable as exc:
            return envelope(None, freshness=f, warnings=[f"CBM error: {exc}"],
                            provenance=provenance(state))
        return envelope(result, freshness=f, provenance=provenance(state))
    ```

- [ ] **Step 5: Run to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_rm_bridge_tools.py tests/test_rm_graph_tools.py -p no:cacheprovider --no-cov -q`
Expected: PASS (bridge 5 + graph 3).

- [ ] **Step 6: Commit**
```bash
git add -f tests/test_rm_bridge_tools.py
git add repo_memory/tools/bridge_tools.py repo_memory/tools/graph_tools.py
git commit -m "refactor(repo_memory): bridge+graph tools report freshness via compute_freshness"
```

---

## Task 4: Tier-A freshness — wiki_tools

**Files:** Modify `repo_memory/tools/wiki_tools.py`; Test `tests/test_rm_wiki_tools.py`

- [ ] **Step 1: Add a failing test** — append to `tests/test_rm_wiki_tools.py`:
```python
def test_wiki_tools_report_freshness():
    # cbm + aligned graph_commit -> fresh; wiki tools carry the freshness field
    from repo_memory.bridge.schema import EntityMap
    st = _state_with_wiki()
    st.cbm = object()
    st.entity_map = EntityMap("r", "c", "r", [])   # graph_commit==repo_head, wiki_commit==repo_head
    assert wiki_tools.get_repo_overview(st)["freshness"] == "fresh"
    assert wiki_tools.list_modules(st)["freshness"] == "fresh"
```
(`_state_with_wiki()` already sets `repo_head="r"` and a wiki with `wiki_commit="c"`; here we set `entity_map.wiki_commit="c"`... note repo_head is "r" so for `fresh` the wiki_commit must equal repo_head — set the wiki/em commits to "r". Adjust the fixture commits to "r": ensure `_state_with_wiki`'s wiki `wiki_commit` is "r" OR override `st.wiki.wiki_commit = "r"` in this test.)

  To keep it unambiguous, write the test body as:
```python
def test_wiki_tools_report_freshness():
    from repo_memory.bridge.schema import EntityMap
    st = _state_with_wiki()
    st.cbm = object()
    st.wiki.wiki_commit = "r"
    st.entity_map = EntityMap("r", "r", "r", [])
    assert wiki_tools.get_repo_overview(st)["freshness"] == "fresh"
    assert wiki_tools.list_modules(st)["freshness"] == "fresh"
    assert wiki_tools.search_wiki(st, "x")["freshness"] == "fresh"
```

- [ ] **Step 2: Run to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_rm_wiki_tools.py::test_wiki_tools_report_freshness -p no:cacheprovider --no-cov -q`
Expected: FAIL — `assert 'unverified' == 'fresh'` (wiki tools currently default `"unverified"`).

- [ ] **Step 3: Route wiki envelopes through a freshness-aware helper** — in `repo_memory/tools/wiki_tools.py`:
  - Add import: `from repo_memory.grounding import compute_freshness`
  - Add a helper after `provenance`:
    ```python
    def _env(state, result, **kw):
        return envelope(result, freshness=compute_freshness(state),
                        provenance=provenance(state), **kw)
    ```
  - Replace every `envelope(... provenance=provenance(state))` return in this file with `_env(state, ...)` carrying the same `result`/`warnings` (drop the now-redundant `provenance=` arg). Specifically:
    - `_no_wiki`: `return _env(state, empty, warnings=["wiki artifacts unavailable"])`
    - `get_repo_overview` success: `return _env(state, {"overview": ..., "metadata": ...})`
    - `list_modules` success: `return _env(state, [n for n, _ in _walk_modules(state.wiki.module_tree)])`
    - `search_wiki` success: `return _env(state, WikiIndex(state.wiki).search(query))`
    - `get_module_doc` not-found: `return _env(state, None, warnings=[f"module '{module}' not found"])`
    - `get_module_doc` success: `return _env(state, {"module": module, "path": ..., "components": ..., "doc": doc})`

- [ ] **Step 4: Run to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_rm_wiki_tools.py -p no:cacheprovider --no-cov -q`
Expected: PASS (existing 5 + the new one). The existing tests don't assert freshness, so they remain green.

- [ ] **Step 5: Commit**
```bash
git add -f tests/test_rm_wiki_tools.py
git add repo_memory/tools/wiki_tools.py
git commit -m "refactor(repo_memory): wiki tools report freshness via compute_freshness"
```

---

## Task 5: Two-tier policy in hybrid_tools

**Files:** Modify `repo_memory/tools/hybrid_tools.py`; Modify `tests/test_rm_hybrid_impact.py`; Test `tests/test_rm_hybrid_explain.py`

- [ ] **Step 1: Update assess_impact block-message assertions + add explain verification test**
  - In `tests/test_rm_hybrid_impact.py`: in `test_blocks_when_cbm_none` change `any("CBM" in w ...)` to `any("unverified" in w for w in e["warnings"])`; in `test_blocks_when_graph_stale` change `any("not current" in w ...)` to `any("stale-graph" in w for w in e["warnings"])`.
  - In `tests/test_rm_hybrid_explain.py`, append:
    ```python
    @pytest.mark.asyncio
    async def test_explain_require_verification_blocks_when_stale(monkeypatch):
        # cbm present but no entity_map -> graph not current -> require_verification blocks
        st = AppState(wiki_dir="w", entity_map_path="e", repo_head="r", cbm=object(), wiki=_wiki())
        e = await H.explain_with_sources(st, "Ingestion", require_verification=True)
        assert e["result"] is None
        assert any("verification required" in w for w in e["warnings"])
    ```

- [ ] **Step 2: Run to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_rm_hybrid_impact.py tests/test_rm_hybrid_explain.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — explain has no `require_verification` kwarg; impact assertions mismatch.

- [ ] **Step 3: Edit `repo_memory/tools/hybrid_tools.py`**
  - Change the grounding import (line ~11) from `from repo_memory.grounding import graph_is_current` to:
    ```python
    from repo_memory.grounding import require_fresh, compute_freshness
    ```
  - `explain_with_sources`: add `require_verification: bool = False` to the signature, and at the very top of the body insert:
    ```python
    if require_verification:
        blocked = require_fresh(state)
        if blocked is not None:
            return envelope(None, freshness=blocked,
                            warnings=[f"verification required but graph is {blocked} "
                                      f"(run refresh_index)"], provenance=provenance(state))
    ```
  - `explain_with_sources` freshness line (currently `fresh = "fresh" if evidence and not any(...) else "unverified"`): replace with
    ```python
    fresh = compute_freshness(state, entries_stale=any(e["stale"] for e in evidence))
    ```
  - `assess_impact`: replace the inline gate (the `if state.cbm is None: ...` and `if not graph_is_current(state): ...` block, ~lines 94–97) with:
    ```python
    blocked = require_fresh(state)
    if blocked is not None:
        return _blocked(f"graph is {blocked}", freshness=blocked)
    ```
    (Keep the rest of `assess_impact` — `detect_changes` try/except, error-shape block, per-symbol verify, `_module_for_file`, the happy-path envelope with `freshness="fresh"` — unchanged.)

- [ ] **Step 4: Run to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_rm_hybrid_impact.py tests/test_rm_hybrid_explain.py -p no:cacheprovider --no-cov -q`
Expected: PASS (impact 6 + explain 5).

- [ ] **Step 5: Commit**
```bash
git add -f tests/test_rm_hybrid_impact.py tests/test_rm_hybrid_explain.py
git add repo_memory/tools/hybrid_tools.py
git commit -m "feat(repo_memory): generalize two-tier policy via require_fresh (+explain require_verification)"
```

---

## Task 6: `index_repository` wrapper + `refresh.py` + `AppState.repo_path`

**Files:** Modify `repo_memory/graph/forward.py`, `repo_memory/state.py`; Create `repo_memory/refresh.py`; Test `tests/test_rm_refresh.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_rm_refresh.py
"""Bounded refresh: re-index CBM + rebuild entity_map -> graph_commit==repo_head -> fresh."""

import pytest
from unittest.mock import AsyncMock

import repo_memory.refresh as R
from repo_memory.state import AppState
from repo_memory.wiki.loader import WikiData
from repo_memory.bridge.schema import EntityMap


def _state(cbm):
    wiki = WikiData({"m": {"path": "p", "components": [], "children": {}}}, {}, {}, "r", [])
    return AppState(wiki_dir="w", entity_map_path="e", repo_head="r", repo_path="/repo",
                    cbm=cbm, wiki=wiki, entity_map=None)


@pytest.mark.asyncio
async def test_refresh_reindexes_rebuilds_and_freshens(monkeypatch, tmp_path):
    cbm = AsyncMock()
    cbm.call_tool_with_restart = AsyncMock(return_value={"ok": 1})  # index_repository + search_graph
    st = _state(cbm)
    st.entity_map_path = str(tmp_path / "entity_map.json")
    # stub the rebuild to return a current entity_map
    em = EntityMap("r", "r", "r", [])
    monkeypatch.setattr(R, "build_and_save", AsyncMock(return_value=em))
    monkeypatch.setattr(R.forward, "index_repository", AsyncMock(return_value={"indexed": True}))
    e = await R.refresh(st)
    R.forward.index_repository.assert_awaited_once()
    assert e["result"]["reindexed"] is True
    assert e["result"]["graph_commit"] == "r"
    assert st.entity_map is em                # reloaded into state
    assert e["freshness"] == "fresh"


@pytest.mark.asyncio
async def test_refresh_degrades_without_cbm():
    st = _state(None)
    e = await R.refresh(st)
    assert e["result"] is None and any("CBM" in w for w in e["warnings"])
```

- [ ] **Step 2: Run to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_rm_refresh.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'repo_memory.refresh'` (and `AppState` has no `repo_path`).

- [ ] **Step 3: Add `repo_path` to `AppState`** — in `repo_memory/state.py`:
  - Add field after `entity_map_path`: `repo_path: Optional[str] = None`
  - Add `repo_path=None` param to `load_app_state` and pass it into the returned `AppState(...)`.

- [ ] **Step 4: Add the `index_repository` wrapper** — append to `repo_memory/graph/forward.py`:
```python
async def index_repository(client, *, path: str) -> Any:
    return await client.call_tool_with_restart("index_repository", {"path": path})
```

- [ ] **Step 5: Create `repo_memory/refresh.py`**
```python
# repo_memory/refresh.py
"""Bounded refresh: re-index CBM at HEAD + rebuild the entity_map (no LLM wiki-regen)."""

from __future__ import annotations

from repo_memory.contract import envelope
from repo_memory.grounding import compute_freshness
from repo_memory.graph import forward
from repo_memory.entity_map_build import build_and_save
from repo_memory.tools.wiki_tools import provenance


async def refresh(state) -> dict:
    if state.cbm is None:
        return envelope(None, warnings=["CBM unavailable; cannot refresh"],
                        provenance=provenance(state))
    if state.wiki is None:
        return envelope(None, warnings=["wiki artifacts unavailable; cannot rebuild entity_map"],
                        provenance=provenance(state))
    await forward.index_repository(state.cbm, path=state.repo_path or ".")
    em = await build_and_save(state.wiki, state.cbm, state.entity_map_path,
                              repo_head=state.repo_head)
    state.entity_map = em
    return envelope({"reindexed": True, "graph_commit": em.graph_commit,
                     "modules": len(em.modules)},
                    freshness=compute_freshness(state), provenance=provenance(state))
```

- [ ] **Step 6: Run to verify it passes**
Run: `.venv/bin/python -m pytest tests/test_rm_refresh.py tests/test_rm_state.py -p no:cacheprovider --no-cov -q`
Expected: PASS (refresh 2 + state 2).

- [ ] **Step 7: Commit**
```bash
git add -f tests/test_rm_refresh.py
git add repo_memory/refresh.py repo_memory/graph/forward.py repo_memory/state.py
git commit -m "feat(repo_memory): bounded refresh (index_repository + rebuild) + AppState.repo_path"
```

---

## Task 7: Register `refresh_index` (→ 12) + integration + gate

**Files:** Modify `repo_memory/server.py`, `tests/test_rm_server.py`, `tests/test_rm_integration.py`

- [ ] **Step 1: Update the server test for 12 tools** — in `tests/test_rm_server.py` change `assert len(TOOL_NAMES) == 11` to `assert len(TOOL_NAMES) == 12`.

- [ ] **Step 2: Run to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_rm_server.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `assert 11 == 12`.

- [ ] **Step 3: Register `refresh_index` in `repo_memory/server.py`**
  - Add import: `from repo_memory.refresh import refresh as _do_refresh`
  - Add `"refresh_index"` to the end of `TOOL_NAMES`.
  - Thread `repo_path`: change `build_app` signature to add `repo_path: Optional[str] = None`, pass it into `load_app_state(... repo_path=repo_path)`; in `main()` read `repo_path = os.environ.get("REPO_MEMORY_REPO_PATH", os.getcwd())` and pass `repo_path=repo_path` to `build_app`.
  - Register the tool (after `assess_impact`, before `return app`):
    ```python
    @app.tool(name="refresh_index",
              description="Re-index the code graph and rebuild the Wiki<->Graph map to restore "
                          "freshness. Call this when a tool reports stale-graph or a verified "
                          "tool blocks. (Does NOT regenerate the wiki docs.)")
    async def _refresh() -> dict:
        return await _do_refresh(state)
    ```

- [ ] **Step 4: Append a gated integration test** to `tests/test_rm_integration.py`:
```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_refresh_then_assess_impact_is_current(tmp_path):
    """Real refresh indexes + rebuilds so the graph is current; assess_impact no longer blocks
    on staleness (it may still block on detect_changes specifics, but not on 'not current')."""
    import shutil
    from repo_memory.state import AppState
    from repo_memory.graph.client import CBMClient
    from repo_memory.wiki.loader import load_wiki
    from repo_memory.refresh import refresh
    from repo_memory.grounding import graph_is_current
    if shutil.which("uvx") is None:
        pytest.skip("uvx not available")
    client = CBMClient()
    try:
        await client.start()
    except Exception as exc:
        pytest.skip(f"CBM unavailable: {exc}")
    try:
        wiki = load_wiki("docs")
        st = AppState(wiki_dir="docs", entity_map_path=str(tmp_path / "em.json"),
                      repo_head=_repo_head(), repo_path=REPO_ROOT, cbm=client, wiki=wiki)
        e = await refresh(st)
        assert e["result"]["reindexed"] is True
        assert graph_is_current(st)            # graph_commit now == repo_head
    finally:
        await client.aclose()
```

- [ ] **Step 5: Run the M4 offline suite + regression**
Run:
```bash
.venv/bin/python -m pytest tests/test_rm_freshness.py tests/test_rm_refresh.py \
  tests/test_rm_server.py tests/test_rm_bridge_tools.py tests/test_rm_graph_tools.py \
  tests/test_rm_wiki_tools.py tests/test_rm_hybrid_impact.py tests/test_rm_hybrid_explain.py \
  tests/test_rm_entity_map_build.py -p no:cacheprovider --no-cov -q
```
Then regression: `.venv/bin/python -m pytest tests/ -p no:cacheprovider --no-cov -q -m "not integration"`
Expected: all PASS. (If the pre-existing capture-teardown error mangles the summary, re-run with `-s` and confirm "0 failed".)

- [ ] **Step 6: Commit**
```bash
git add -f tests/test_rm_server.py tests/test_rm_integration.py
git add repo_memory/server.py
git commit -m "feat(repo_memory): register refresh_index (->12 tools) + integration + M4 gate"
```

---

## Self-Review (completed by plan author)

- **Spec coverage:** central `compute_freshness` graph>wiki (T1) · `require_fresh` graph-only gate (T1) · `graph_commit` fix (T2) · Tier-A freshness across bridge/graph/wiki (T3, T4) · `assess_impact`→`require_fresh` + `explain_with_sources(require_verification)` (T5) · `index_repository` + bounded `refresh` + `AppState.repo_path` (T6) · `refresh_index` tool → 12 + integration (T7). No spec item unassigned. (`callers`/LLM-wiki-regen remain deferred per spec.)
- **Import-cycle check:** `require_fresh` returns a string (not an envelope), so `grounding` imports nothing from `tools` → `wiki_tools`/`bridge_tools`/`graph_tools` can import `grounding.compute_freshness` with no cycle.
- **Test churn (called out explicitly):** bridge `_state` gains a `cbm` sentinel + `_em` `graph_commit="r"` (T3); `entity_map_build` test asserts `graph_commit` (T2); hybrid block-message assertions change (`CBM`→`unverified`, `not current`→`stale-graph`) (T5); server count 11→12 (T7). These reflect freshness centralization (the old fixtures under-specified `cbm`/`graph_commit`).
- **Placeholder scan:** none — complete code/edits in every step with exact current-code anchors; commands have expected outcomes.
- **Type consistency:** `compute_freshness(state, *, entries_stale=False)`, `require_fresh(state)->str|None`, `index_repository(client, *, path)`, `refresh(state)`, `AppState.repo_path`, `TOOL_NAMES` (12) used consistently; `EntityMap(built_at_repo_head, wiki_commit, graph_commit, modules)` positional order matches `bridge/schema.py`.
