# Kind-Balanced Retrieval (find_related rebalance) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebalance retrieval so `find_related` surfaces source symbols alongside docs — balance in the core `find_related_units` (flat, default-on when `kinds` unset, fixed quota + interleave, `symbol_ratio` knob), group into `{docs, symbols}` buckets at the `find_related` tool.

**Architecture:** Per `docs/superpowers/specs/2026-06-21-retrieval-rebalance-design.md`. The store's existing `kinds` filter is the enabler; no store/schema changes.

**Tech Stack:** Python 3.12, the existing `repo_atlas` package, pytest (+pytest-asyncio).

**Conventions:**
- Run tests: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest <file> -m "not integration" -p no:cacheprovider --no-cov -q`
- `tests/` is gitignored → new test files need `git add -f`.
- `from __future__ import annotations` at top of each module; line length 100.

---

## Breakage map (already analyzed — handle in the named tasks)

- `test_ra_retrieve.py` — uses the flat **core** `find_related_units`; symbol-first interleave keeps `brightness` first → **survives** (Task 2 re-runs it to confirm).
- `test_ra_server.py` — only asserts `TOOL_NAMES` → **survives**.
- `test_ra_tools.py::test_find_related_envelope` — iterates `env["result"]` (now a `{docs,symbols}` dict) → **must update** (Task 3).
- `test_ra_integration.py::test_index_and_find_related` (`@pytest.mark.integration`, GatewayEmbedder) — same dict-iteration → **must update** (Task 3).

---

## Task 1: `symbol_ratio` config knob

**Files:**
- Modify: `repo_atlas/config.py`
- Test: `tests/test_ra_symbol_ratio.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ra_symbol_ratio.py
from repo_atlas.config import load_config

_BASE = {"REPO_ATLAS_BASE_URL": "x", "REPO_ATLAS_API_KEY": "y"}   # avoid codewiki fallback


def test_symbol_ratio_default():
    assert load_config(_BASE).symbol_ratio == 0.5


def test_symbol_ratio_parsed_and_clamped():
    assert load_config({**_BASE, "REPO_ATLAS_SYMBOL_RATIO": "0.7"}).symbol_ratio == 0.7
    assert load_config({**_BASE, "REPO_ATLAS_SYMBOL_RATIO": "1.5"}).symbol_ratio == 1.0
    assert load_config({**_BASE, "REPO_ATLAS_SYMBOL_RATIO": "-0.2"}).symbol_ratio == 0.0
    assert load_config({**_BASE, "REPO_ATLAS_SYMBOL_RATIO": "abc"}).symbol_ratio == 0.5
```

- [ ] **Step 2: Run to verify it fails**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_ra_symbol_ratio.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `AttributeError: 'AtlasConfig' object has no attribute 'symbol_ratio'`.

- [ ] **Step 3: Implement**

In `repo_atlas/config.py`, add the field to the dataclass:

```python
@dataclass
class AtlasConfig:
    base_url: str
    api_key: str
    embed_model: str
    db_path: str
    symbol_ratio: float = 0.5
```

Add a parse helper before `load_config`:

```python
def _parse_ratio(raw) -> float:
    """Clamp REPO_ATLAS_SYMBOL_RATIO to [0,1]; fall back to 0.5 on missing/garbage."""
    try:
        return min(1.0, max(0.0, float(raw)))
    except (TypeError, ValueError):
        return 0.5
```

In `load_config`'s returned `AtlasConfig(...)`, add the new kwarg (after `db_path=...`):

```python
        symbol_ratio=_parse_ratio(env.get("REPO_ATLAS_SYMBOL_RATIO")),
```

- [ ] **Step 4: Run to verify it passes**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_ra_symbol_ratio.py -p no:cacheprovider --no-cov -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
cd /mnt/x/code/knowledgeLoop/.claude/worktrees/cm
git add repo_atlas/config.py
git add -f tests/test_ra_symbol_ratio.py
git commit -m "feat(repo_atlas): REPO_ATLAS_SYMBOL_RATIO config knob (default 0.5, clamped)"
```

---

## Task 2: Kind-balanced core retrieval

**Files:**
- Modify: `repo_atlas/retrieve.py`
- Test: `tests/test_ra_merge_quota.py` (pure `_merge_quota`)
- Test: `tests/test_ra_retrieve.py` (add a balanced-behavior test; existing tests must still pass)

- [ ] **Step 1: Write the failing pure-logic tests**

```python
# tests/test_ra_merge_quota.py
from repo_atlas.retrieve import _merge_quota

S = [{"kind": "symbol", "i": i} for i in range(6)]
D = [{"kind": "doc", "i": i} for i in range(6)]


def _kinds(xs):
    return [x["kind"] for x in xs]


def test_exact_quota_interleaves_symbol_first():
    out = _merge_quota(S, D, n_sym=2, n_doc=2, k=4)
    assert _kinds(out) == ["symbol", "doc", "symbol", "doc"]


def test_backfill_when_docs_short():
    out = _merge_quota(S, D[:1], n_sym=3, n_doc=3, k=6)
    assert len(out) == 6
    assert _kinds(out).count("symbol") == 5 and _kinds(out).count("doc") == 1


def test_backfill_when_symbols_short():
    out = _merge_quota(S[:1], D, n_sym=3, n_doc=3, k=6)
    assert len(out) == 6
    assert _kinds(out).count("symbol") == 1 and _kinds(out).count("doc") == 5


def test_caps_at_k_and_handles_small_pools():
    assert _merge_quota(S[:1], D[:1], n_sym=3, n_doc=3, k=6) == [S[0], D[0]]
```

- [ ] **Step 2: Run to verify it fails**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_ra_merge_quota.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `ImportError: cannot import name '_merge_quota'`.

- [ ] **Step 3: Implement the core changes in `repo_atlas/retrieve.py`**

Keep `rrf_fuse` and `_hit` as-is. **Replace the single `find_related_units` function** with the factored `_retrieve_mixed`, the new `_merge_quota`, and the dispatching `find_related_units`:

```python
async def _retrieve_mixed(store, embedder, query, repos, kinds, k) -> list:
    """Today's keyword+vector RRF over a (possibly kind-filtered) pool."""
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
        via = "+".join((["keyword"] if uid in kw_ids else [])
                       + (["semantic"] if uid in vec_ids else []))
        hits.append(_hit(u, score, via))
    return hits


def _merge_quota(sym_hits, doc_hits, n_sym, n_doc, k):
    """Take n_sym symbols + n_doc docs, backfilling unused slots from the other kind, then
    interleave symbol-first so both kinds appear at the top. Caps at k."""
    take_sym = sym_hits[:n_sym]
    take_doc = doc_hits[:n_doc]
    if len(take_doc) < n_doc:                      # docs short -> give slots to symbols
        take_sym = sym_hits[:n_sym + (n_doc - len(take_doc))]
    if len(take_sym) < n_sym:                      # symbols short -> give slots to docs
        take_doc = doc_hits[:n_doc + (n_sym - len(take_sym))]
    merged, i, j = [], 0, 0
    while len(merged) < k and (i < len(take_sym) or j < len(take_doc)):
        if i < len(take_sym):
            merged.append(take_sym[i]); i += 1
        if len(merged) < k and j < len(take_doc):
            merged.append(take_doc[j]); j += 1
    return merged[:k]


async def find_related_units(store, embedder, query, *, repos=None, kinds=None, k: int = 20,
                             symbol_ratio: float = 0.5) -> list:
    if kinds is not None:                          # explicit caller -> unchanged behavior
        return await _retrieve_mixed(store, embedder, query, repos, kinds, k)
    n_sym = k - int(k * (1.0 - symbol_ratio))      # symbols get the extra slot on odd k
    n_doc = k - n_sym
    sym = await _retrieve_mixed(store, embedder, query, repos, ["symbol"], k)
    doc = await _retrieve_mixed(store, embedder, query, repos, ["doc"], k)
    return _merge_quota(sym, doc, n_sym, n_doc, k)
```

- [ ] **Step 4: Run to verify the pure tests pass**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_ra_merge_quota.py -p no:cacheprovider --no-cov -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Add a balanced-behavior test to `tests/test_ra_retrieve.py`**

Append this test (it indexes 3 symbols + 3 docs and asserts the default mixed call is balanced & symbol-first):

```python
@pytest.mark.asyncio
async def test_find_related_units_balances_kinds(tmp_path):
    st = Store(str(tmp_path / "b.db"))
    emb = StubEmbedder(dim=16)
    units = ([Unit(repo="r1", kind="symbol", name=f"sym{i}", qualified_name=f"q.sym{i}",
                   file=f"s{i}.cpp", repo_head="H", text=f"image filter symbol {i}", meta={})
              for i in range(3)]
             + [Unit(repo="r1", kind="doc", name=f"doc{i}", qualified_name=None,
                     file=f"d{i}.md", repo_head="H", text=f"image filter doc {i}", meta={})
                for i in range(3)])
    vecs = emb.embed([u.text for u in units])
    st.reindex_repo("r1", list(zip(units, vecs)), repo_head="H")
    # default (kinds unset) -> balanced, symbol-first interleave
    hits = await find_related_units(st, emb, "image filter", k=4, symbol_ratio=0.5)
    assert [h["kind"] for h in hits] == ["symbol", "doc", "symbol", "doc"]
    # explicit kinds bypasses balancing
    only = await find_related_units(st, emb, "image filter", kinds=["symbol"], k=4)
    assert only and all(h["kind"] == "symbol" for h in only)
```

- [ ] **Step 6: Run the retrieve suite (new + existing must pass)**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_ra_retrieve.py -p no:cacheprovider --no-cov -q`
Expected: PASS (all, incl. the original `test_find_related_returns_hits` and `test_rrf_fuse_rewards_agreement`).
If `test_find_related_returns_hits` fails (it should not — `brightness` is the lone symbol and interleaves first), inspect the returned order; do **not** weaken the new behavior — fix the test only if it asserted incidental ordering.

- [ ] **Step 7: Lint + commit**

```bash
/home/vinc/code/knowledgeLoop/.venv/bin/ruff check repo_atlas/retrieve.py
git add repo_atlas/retrieve.py
git add -f tests/test_ra_merge_quota.py tests/test_ra_retrieve.py
git commit -m "feat(repo_atlas): kind-balanced find_related_units (quota+interleave, symbol_ratio, default-on when kinds unset)"
```

---

## Task 3: Group at the `find_related` tool + update breaking tests

**Files:**
- Modify: `repo_atlas/tools.py`
- Modify: `tests/test_ra_tools.py` (update `test_find_related_envelope` to the grouped contract; add a flat-on-explicit-kinds assertion)
- Modify: `tests/test_ra_integration.py` (update `test_index_and_find_related` to flatten the buckets)

- [ ] **Step 1: Update the unit test first (red)**

In `tests/test_ra_tools.py`, replace `test_find_related_envelope` with:

```python
@pytest.mark.asyncio
async def test_find_related_groups_buckets(tmp_path):
    st, emb = _seed(tmp_path)                      # existing helper in this file
    env = await tools.find_related(st, emb, "brightness")        # kinds unset -> grouped
    assert "result" in env and "freshness" in env
    res = env["result"]
    assert set(res) == {"docs", "symbols"}
    assert any(h["name"] == "cgeBrightnessAdjust" for h in res["symbols"])
    # explicit kinds -> flat list (no grouping)
    flat = await tools.find_related(st, emb, "brightness", kinds=["symbol"])
    assert isinstance(flat["result"], list)
```

- [ ] **Step 2: Run to verify it fails**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_ra_tools.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — the grouped assertions fail against the current flat-list `find_related`.

- [ ] **Step 3: Implement the tool change in `repo_atlas/tools.py`**

Add `import os` at the top (after `from __future__ import annotations`). Add the ratio resolver and rewrite `find_related`:

```python
def _symbol_ratio() -> float:
    from repo_atlas.config import load_config
    return load_config(os.environ).symbol_ratio


async def find_related(store, embedder, query: str, *, repos=None, kinds=None,
                       k: int = 20) -> dict:
    hits = await find_related_units(store, embedder, query, repos=repos, kinds=kinds, k=k,
                                    symbol_ratio=_symbol_ratio())
    if kinds is None:                              # grouped buckets for the default mixed call
        payload = {"docs": [h for h in hits if h["kind"] == "doc"],
                   "symbols": [h for h in hits if h["kind"] == "symbol"]}
    else:                                          # explicit kinds -> flat (back-compat)
        payload = hits
    return envelope(payload, freshness="fresh" if hits else "unverified",
                    warnings=[] if hits else ["no matches in index"])
```

- [ ] **Step 4: Run to verify it passes**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_ra_tools.py -p no:cacheprovider --no-cov -q`
Expected: PASS (the grouped + flat-explicit-kinds assertions, plus the unchanged `verify_grounding`/`list_repos` tests).

- [ ] **Step 5: Update the gated integration test**

In `tests/test_ra_integration.py::test_index_and_find_related`, replace the result assertions:

```python
    env = await find_related(store, emb, "adjust image brightness")
    assert env["result"], "expected related hits"
    flat = env["result"]["symbols"] + env["result"]["docs"]     # grouped buckets now
    assert any(h["repo"] == "gpuimage" for h in flat)
```

- [ ] **Step 6: Lint + commit**

```bash
/home/vinc/code/knowledgeLoop/.venv/bin/ruff check repo_atlas/tools.py
git add repo_atlas/tools.py
git add -f tests/test_ra_tools.py tests/test_ra_integration.py
git commit -m "feat(repo_atlas): group find_related into {docs,symbols} buckets; thread symbol_ratio from config"
```

---

## Task 4: Measure — re-run eval, sweep the ratio, regress, ready to merge

**Files:** none (operational). Requires local Ollama (`bge-m3`) up and the indexed store at `/home/vinc/repo-atlas-eval-full/atlas.db`.

- [ ] **Step 1: Re-run the offline eval (default ratio 0.5) and compare to baseline**

```bash
cd /mnt/x/code/knowledgeLoop/.claude/worktrees/cm
FULL=/home/vinc/repo-atlas-eval-full
CODEWIKI_NO_KEYRING=1 REPO_ATLAS_DB=$FULL/atlas.db REPO_ATLAS_REGISTRY=$FULL/atlas.toml \
  REPO_ATLAS_BASE_URL=http://127.0.0.1:11434/v1 REPO_ATLAS_API_KEY=local \
  REPO_ATLAS_EMBED_MODEL=bge-m3 \
  /home/vinc/code/knowledgeLoop/.venv/bin/python -m repo_atlas eval-offline \
  --cases repo_atlas/eval/offline/cases --layer retrieval --out $FULL/offline-scorecard-rebalanced.md
```
Expected: overall file-level **Recall@20 > 0.20** (the pre-rebalance baseline), and android-gpuimage-plus **> 0.00** (its source symbol units now surface). Record the new overall Recall@5/10/20.

- [ ] **Step 2: Sweep `symbol_ratio` ∈ {0.3, 0.5, 0.7} to pick the default**

```bash
cd /mnt/x/code/knowledgeLoop/.claude/worktrees/cm
FULL=/home/vinc/repo-atlas-eval-full
CODEWIKI_NO_KEYRING=1 REPO_ATLAS_DB=$FULL/atlas.db REPO_ATLAS_BASE_URL=http://127.0.0.1:11434/v1 \
  REPO_ATLAS_API_KEY=local REPO_ATLAS_EMBED_MODEL=bge-m3 \
  /home/vinc/code/knowledgeLoop/.venv/bin/python - <<'PY'
import asyncio, os
from repo_atlas.store import Store
from repo_atlas.embed import GatewayEmbedder
from repo_atlas.retrieve import find_related_units
from repo_atlas.eval.offline.cases import load_retrieval_cases
from repo_atlas.eval.offline import metrics
st = Store(os.environ["REPO_ATLAS_DB"])
emb = GatewayEmbedder(os.environ["REPO_ATLAS_BASE_URL"], os.environ["REPO_ATLAS_API_KEY"],
                      os.environ["REPO_ATLAS_EMBED_MODEL"])
cases = load_retrieval_cases("repo_atlas/eval/offline/cases/retrieval")
async def recall_for(ratio):
    rs = []
    for c in cases:
        hits = await find_related_units(st, emb, c.query, repos=[c.repo], k=20, symbol_ratio=ratio)
        rf = [h.get("file") for h in hits]
        rs.append(metrics.recall_at_k(rf, set(c.gold_files), 10))
    return sum(rs) / len(rs)
for r in (0.3, 0.5, 0.7):
    print(f"symbol_ratio={r}: file-level Recall@10 = {asyncio.run(recall_for(r)):.3f}")
PY
```
Record the best ratio. If it differs from 0.5, note it as the recommended `REPO_ATLAS_SYMBOL_RATIO` (do **not** hardcode — it stays a config knob; just document the recommended value in the run notes).

- [ ] **Step 3: Full unit-suite regression (capture-safe form)**

```bash
/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/ \
  --ignore=tests/test_eval_integration.py --ignore=tests/test_offline_integration.py \
  --ignore=tests/test_ra_integration.py \
  -p no:cacheprovider --no-cov -s -o addopts="" > /tmp/rebalance_suite.log 2>&1; echo "exit=$?"
grep -c "FAILED" /tmp/rebalance_suite.log
```
Expected: `exit=0` and `0` FAILED markers. (The `[offline-eval] case ... failed` / `[eval] task boom failed` lines are intentional resilience-test stdout, not failures.)

- [ ] **Step 4: Report results (no merge — leave for the human)**

Summarize: baseline vs rebalanced Recall@5/10/20 (overall + per-repo), the ratio-sweep table, and the chosen `symbol_ratio`. STOP before any `git merge`/`git push` to master — the human reviews the measured gain first.

---

## Self-review checklist (done while writing)

- **Spec coverage:** `symbol_ratio` knob (T1), `_retrieve_mixed`/`_merge_quota`/balanced `find_related_units` (T2), tool grouping + `_symbol_ratio` plumbing (T3), measurement + ratio sweep (T4). Non-goals (doc↔source relevance, grounding stratified sampling, intent-adaptive) correctly excluded.
- **Breakage handled:** `test_ra_tools.py` + `test_ra_integration.py` updated to the grouped contract (T3); `test_ra_retrieve.py`/`test_ra_server.py` confirmed to survive (T2 re-runs retrieve).
- **Type/contract consistency:** `find_related_units(..., symbol_ratio=0.5)` signature used identically in T2 (def), T3 (tool call), and T4 (sweep); `_merge_quota(sym, doc, n_sym, n_doc, k)` consistent between def and tests; grouped payload `{docs, symbols}` consistent across tool impl + both updated tests.
- **No placeholders:** every code step has complete code; the one `_store(tmp_path)` fixture reference in T3 carries an explicit instruction to match the existing file's actual setup.
