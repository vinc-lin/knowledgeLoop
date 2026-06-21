# Kind-Balanced Retrieval (find_related rebalance) — Design Spec

**Date:** 2026-06-21
**Status:** Approved design, pending implementation plan
**Related:** offline eval (`repo_atlas/eval/offline/`), the offline-eval first-run finding
(memory `repo-atlas-eval-null-result`), `docs/superpowers/specs/2026-06-21-retrieval-eval-design.md`.

## Why

The offline retrieval eval (built 2026-06-21) showed `find_related` is **doc-dominated**.
For the gpuimage "write a sepia filter" query the top-20 was **16 wiki-doc units / 4 symbols**
(top-9 all docs), and the canonical source `cgeImageFilter.h` — which has 26 symbol units
indexed — **never reached the top-20**. Result: file-level Recall@20 = 0.20 overall, 0.00 for
gpuimage. The cause is not missing data: the index holds 31,552 gpuimage symbol units. It is
that doc units (richer prose) systematically outrank symbol units in the flat RRF fusion, so an
agent that wants the actual class to subclass never gets it surfaced.

A coding agent asking "how do I write X" needs **both** the explanatory doc (the pattern) **and**
the canonical source (the code to follow). Today it gets only docs. This spec rebalances
retrieval so both kinds surface.

## Decisions (locked during brainstorming)

- **Balance lives in the core** (`find_related_units`) and returns a **flat, balanced** list, so
  `prepare_change.related` and the offline eval (which call the core directly) benefit
  automatically and unchanged.
- **Grouping lives at the tool** (`find_related`): it partitions the balanced core result into
  `{docs: [...], symbols: [...]}` — the new agent-facing bucket contract.
- **Fixed quota / interleave** balance policy with a configurable `symbol_ratio` (default 0.5).
- **Default-on when `kinds` is unset**; explicit `kinds=[...]` callers bypass balancing
  (today's behavior, untouched).

## Non-goals (separate follow-ups)

- Doc↔source **relevance model** in the eval (crediting a doc that describes the gold source
  file). This spec improves retrieval; the eval keeps its current file-level metric, which will
  now register the gain because real source units surface.
- Grounding **stratified sampling** (a `gen_grounding` refinement).
- **Intent-adaptive** ratio (code-intent vs concept-intent classifier) — explicitly deferred;
  the fixed ratio is the deterministic baseline the eval tunes.
- Changing the **store** schema or search SQL (the existing `kinds` filter is sufficient).

## Architecture

Two layers, matching the two decisions:

```
find_related TOOL (tools.find_related)
  └─ groups the balanced flat list -> envelope({docs:[...], symbols:[...]})   ← NEW contract
       │
find_related_units (retrieve.py, CORE)
  ├─ kinds given  -> _retrieve_mixed(query, kinds, k)         ← today's behavior, untouched
  └─ kinds = None -> balance:                                  ← NEW default
        sym = _retrieve_mixed(query, ["symbol"], k)   # own kw+vec RRF
        doc = _retrieve_mixed(query, ["doc"],    k)   # own kw+vec RRF
        return _merge_quota(sym, doc, n_sym=round(k*ratio), n_doc=k-n_sym)   # flat, balanced
```

`prepare_change.related` and the offline `OfflineRetriever` call the **core** → they get the
flat balanced list with no code change. Only the **tool** output shape changes (to buckets).

## Detailed changes

### 1. `repo_atlas/retrieve.py`

**Factor today's body into `_retrieve_mixed`** (verbatim logic, just parameterized):

```python
async def _retrieve_mixed(store, embedder, query, repos, kinds, k) -> list[dict]:
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
```

**Add `_merge_quota`** (pure, no I/O — the testable heart):

```python
def _merge_quota(sym_hits, doc_hits, n_sym, n_doc, k):
    """Take n_sym symbols + n_doc docs (backfill from the other kind if one is short to fill
    k), then interleave (symbol, doc, symbol, doc, ...) so both kinds appear at the top."""
    take_sym = sym_hits[:n_sym]
    take_doc = doc_hits[:n_doc]
    # backfill: if one kind is short, give its unused slots to the other
    deficit = (n_sym - len(take_sym)) + (n_doc - len(take_doc))
    if deficit:
        if len(take_sym) < n_sym:
            take_doc = doc_hits[:n_doc + (n_sym - len(take_sym))]
        if len(take_doc) < n_doc:
            take_sym = sym_hits[:n_sym + (n_doc - len(take_doc))]
    merged, i, j = [], 0, 0
    while len(merged) < k and (i < len(take_sym) or j < len(take_doc)):
        if i < len(take_sym):
            merged.append(take_sym[i]); i += 1
        if len(merged) < k and j < len(take_doc):
            merged.append(take_doc[j]); j += 1
    return merged[:k]
```

**Rewrite `find_related_units`** to dispatch:

```python
async def find_related_units(store, embedder, query, *, repos=None, kinds=None, k=20,
                             symbol_ratio=0.5):
    if kinds is not None:
        return await _retrieve_mixed(store, embedder, query, repos, kinds, k)
    n_sym = round(k * symbol_ratio)
    n_doc = k - n_sym
    sym = await _retrieve_mixed(store, embedder, query, repos, ["symbol"], k)
    doc = await _retrieve_mixed(store, embedder, query, repos, ["doc"], k)
    return _merge_quota(sym, doc, n_sym, n_doc, k)
```

Behavior notes: explicit `kinds` (incl. `["doc"]` from `prepare_change.conventions`) is
unaffected. Odd `k` with ratio 0.5 → `round` gives symbols the extra slot (favor code). A repo
with no docs → `doc` empty → backfill fills with symbols (and vice-versa).

### 2. `repo_atlas/tools.py` — group at the tool

```python
async def find_related(store, embedder, query, *, repos=None, kinds=None, k=20):
    hits = await find_related_units(store, embedder, query, repos=repos, kinds=kinds, k=k,
                                    symbol_ratio=_symbol_ratio())
    if kinds is None:                       # grouped buckets only for the default mixed call
        grouped = {"docs": [h for h in hits if h["kind"] == "doc"],
                   "symbols": [h for h in hits if h["kind"] == "symbol"]}
        payload = grouped
    else:
        payload = hits                      # explicit-kinds callers keep the flat list
    return envelope(payload, freshness="fresh" if hits else "unverified",
                    warnings=[] if hits else ["no matches in index"])
```

`_symbol_ratio()` reads the config knob (below). When the caller restricts `kinds`, grouping is
moot, so the flat list is returned (back-compat for any explicit-kinds tool use).

### 3. `repo_atlas/config.py` — the ratio knob

Add `symbol_ratio: float` to `AtlasConfig`; in `load_config`, read
`REPO_ATLAS_SYMBOL_RATIO` (default `"0.5"`, `float()`-parsed, clamped to `[0.0, 1.0]`).
`tools._symbol_ratio()` resolves it via `load_config(os.environ).symbol_ratio` (or a module-level
cached config). The offline eval calls `find_related_units(..., symbol_ratio=r)` **directly** to
sweep `r` without env changes.

### 4. `repo_atlas/server.py`

No signature change — `find_related` already forwards `query/repos/kinds/k`. The grouped output
flows through unchanged. (Confirm the MCP tool's declared result description, if any, still fits.)

## Measurement plan

1. Re-run the offline eval (`repo-atlas eval-offline`) → expect file-level **Recall@k up**
   (gpuimage `cgeImageFilter.h` symbol units now surface in top-k); grounding unchanged.
2. **Ratio sweep:** a small loop calling `find_related_units(..., symbol_ratio=r)` for
   `r ∈ {0.3, 0.5, 0.7}` over the retrieval cases, reporting Recall@10 per ratio — pick the best
   default and update `REPO_ATLAS_SYMBOL_RATIO`. (A `--symbol-ratio` pass-through on
   `eval-offline` is a convenient, optional add.)
3. Record before/after Recall@k in the run notes.

## Testing (TDD)

- `_merge_quota` (pure): exact quota (3 sym + 3 doc from longer pools); backfill when docs short
  (e.g. 1 doc available, ratio 0.5, k=6 → 5 symbols + 1 doc); backfill when symbols short;
  interleave order (symbol-first); odd-k extra slot to symbols; `k` larger than both pools.
- `find_related_units`: with a stub store/embedder returning known symbol/doc pools, assert
  `kinds=None` returns a balanced interleaved list and `kinds=["symbol"]` bypasses to mixed.
- `tools.find_related`: grouped `{docs, symbols}` payload for `kinds=None`; flat for explicit
  kinds; envelope intact.
- `config`: `REPO_ATLAS_SYMBOL_RATIO` parsed + clamped; default 0.5.
- Integration: the offline-eval integration test still passes and Recall@20 is finite in [0,1].

## Risks & open questions

- **Doc usefulness regression:** capping docs at ~half could drop a genuinely best doc below the
  fold. Mitigated by the ratio knob + eval sweep; 0.5 is a starting point, not a fixed truth.
- **Two extra searches** per balanced call (4 store queries vs 2). Negligible vs embedding cost;
  retrieval stays sub-second.
- **Eval still file-level:** until the doc↔source relevance refinement lands, the eval credits
  only source-file hits — so it will *under*-credit the (still-valuable) docs. That's acceptable
  here: the metric will move in the right direction precisely because source symbols now surface,
  which is the change we're making.
- **Tool contract change** (`find_related` now returns buckets for the default call). Any existing
  consumer expecting a flat `result` list must adapt; within this repo the only caller is the MCP
  surface (agent-consumed) — document the change in the tool's description.
```
