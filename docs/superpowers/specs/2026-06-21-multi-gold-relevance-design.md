# Multi-Gold (Any-Of) Relevance — Design Spec

**Date:** 2026-06-21
**Status:** Approved design, pending implementation plan
**Related:** offline eval (`repo_atlas/eval/offline/`), the gpuimage retrieval investigation
(memory `repo-atlas-eval-null-result`), `docs/superpowers/specs/2026-06-21-retrieval-eval-design.md`.

## Why

The gpuimage retrieval investigation (2026-06-21) found that the low Recall@20 (0.20) for
android-gpuimage-plus is **mostly mis-specified ground truth, not a retrieval-engine failure**:
- The two JNI cases' gold is `cgeGlobal.h`, but the real native-method registration lives in
  `cgeNativeLibrary.cpp` (6 JNI signals in `cgeNativeLibrary.h` vs 1 in `cgeGlobal.h`); retrieval
  **correctly** returns `cgeNativeLibrary.h`, so it's scored a miss against the wrong gold.
- The sepia case lists only `cgeImageFilter.h`, but the query says "follow the cge*Adjust pattern,"
  so the concrete `cgeContrastAdjust.h` / `cgeHueAdjust.cpp` are *equally valid* prior art that a
  single gold file can't capture.

Prior-art retrieval is inherently an **any-of** problem: "did the agent get *a* relevant example?"
The current `Recall@k` measures fraction-of-*all*-golds-found, which is the wrong frame for
alternatives. This change adopts any-of relevance and re-curates the ground truth.

## Decisions (locked during brainstorming)

- **Any-of semantics.** Gold = a set of *acceptable alternatives*. The primary metric is whether
  any acceptable gold is in the top-k.
- **Promote Success@k + MRR to primary; demote Recall@k to a secondary "coverage" stat.**
- **Re-curate all 15 retrieval cases** for acceptable alternatives, including the gpuimage JNI fix.
- No per-case `match` mode (every case in this eval is prior-art = any-of).

## Non-goals (separate / deferred)

- Pool-aware re-ranking for the 2 genuinely-crowded gpuimage base-class cases — harder, separate.
- Grounding stratified sampling — its own follow-up.
- `cases.py` schema changes — `gold_files`/`gold_symbols` are **already tuples**; multi-gold is
  populated data, not a schema change.
- Commit-mined cases — still future.

## Changes

### 1. `repo_atlas/eval/offline/metrics.py` — rename + reframe (minimal new math)

- **Rename `hit_rate_at_k` → `success_at_k`** (identical body: `1.0` if any gold file ∈ top-k).
  It is now the primary metric; the name should say so.
- **Rename `symbol_recall_at_k` → `symbol_success_at_k`** *and* change its semantics from
  fraction-of-all to **any-of**: return `1.0` if any gold symbol's `name`/`qualified_name`
  appears in the top-k hits, else `0.0`.
- **Keep `recall_at_k`** unchanged — it becomes the secondary "coverage" stat (fraction of all
  acceptable golds found).
- `mrr`, `ndcg_at_k`, `grounding_scores` — unchanged.

```python
def success_at_k(ranked_files: list, gold: set, k: int) -> float:
    """1.0 if any acceptable gold file is in the top-k, else 0.0 (any-of relevance)."""
    return 1.0 if (gold & set(ranked_files[:k])) else 0.0


def symbol_success_at_k(hits: list, gold_symbols, k: int) -> float:
    """1.0 if any gold symbol (by name or qualified_name) appears in the top-k hits."""
    gold = set(gold_symbols)
    if not gold:
        return 0.0
    for h in hits[:k]:
        if h.get("name") in gold or h.get("qualified_name") in gold:
            return 1.0
    return 0.0
```

### 2. `repo_atlas/eval/offline/harness.py` — row keys + provenance

In `run_retrieval`'s per-case row:
- `row[f"success@{k}"] = metrics.success_at_k(ranked_files, gold_f, k)`  (was `hit@{k}`)
- **keep** `row[f"recall@{k}"] = metrics.recall_at_k(...)`  (secondary coverage)
- `row[f"ndcg@{k}"]`, `row["mrr"]` — unchanged.
- `row["n_golds"] = len(gold_f)`  (for the median-#golds provenance / anti-gaming).
- symbol: `row[f"sym_success@{kmax}"] = metrics.symbol_success_at_k(hits, c.gold_symbols, kmax)`.

`_agg_retrieval`: aggregate `success@{k}` (mean) as primary; `recall@{k}` (mean) as secondary;
`mrr`, `ndcg@{k}`; `sym_success@{kmax}`; and `median(n_golds)` over the rows.

### 3. `repo_atlas/eval/offline/report.py` — primary/secondary split

```
## Retrieval (find_related) — cases: N  (median golds/case: M)
| scope | Success@5 | Success@10 | Success@20 | MRR | nDCG@10 |
| overall | … |
| <repo>  | … |
(secondary) coverage Recall@20 (fraction of all acceptable golds found): … overall
(secondary) symbol-level Success@20: … overall
```

The headline columns are Success@{ks}; Recall is gone from the main table and reported once as a
secondary "coverage" line. The grounding section is unchanged.

### 4. Cases — multi-gold curation (`repo_atlas/eval/offline/cases/retrieval/*.toml`)

Re-curate all 15 cases. For each, set `gold_files` (and `gold_symbols` where apt) to the set of
**genuinely acceptable** targets — the canonical file plus legitimate alternatives a competent
agent would accept as prior art. Grep-verify every path exists under the repo.

Concrete required corrections (from the investigation):
- **gpuimage JNI cases** (`task-gpuimage-fix-jni`, `cur-gpuimage-jni-bridge`):
  `gold_files = ["library/src/main/jni/interface/cgeNativeLibrary.h",
                 "library/src/main/jni/interface/cgeNativeLibrary.cpp",
                 "library/src/main/jni/cge/common/cgeGlobal.h"]`  (cgeNativeLibrary first — that's
  where `RegisterNatives`/`JNINativeMethod` live; keep cgeGlobal.h as an acceptable alternative).
- **gpuimage add-sepia** (`task-gpuimage-add-sepia`): keep `cgeImageFilter.h` and add the concrete
  adjust-filter exemplars (e.g. `library/src/main/jni/cge/filters/cgeContrastAdjust.h`,
  `.../cgeHueAdjust.h`) — any is valid "follow this pattern" prior art.
- The remaining gpuimage + all libxcam/ndk cases: add legitimate alternative files where they
  exist (e.g. a base header *and* its `.cpp`), keeping the set tight (canonical targets only).

**Anti-gaming rule (curation discipline):** golds must be *canonical/acceptable targets*, not "any
file in the module." The report's median-#golds line makes the curation breadth visible; MRR + nDCG
still discriminate ranking quality even when Success saturates.

The existing `scripts/verify_offline_gold.py` re-runs to assert every (now multiple) gold file
exists; it already iterates `gold_files` per case, so no change is needed there.

### 5. Tests

- `metrics`: rename the `hit_rate_at_k` test to `success_at_k`; update `symbol_recall_at_k` test →
  `symbol_success_at_k` with any-of assertions (1.0 if any gold symbol found, regardless of how
  many gold symbols total). Keep the `recall_at_k` test as-is.
- `harness`: the existing balanced/aggregation tests assert `recall@k`; add assertions for
  `success@k`, `n_golds`, and `sym_success@{kmax}`; confirm `recall@k` still present (secondary).
- `report`: assert the primary table shows `Success@` columns and the secondary `coverage Recall`
  + `symbol-level Success` lines; assert median-golds appears.
- `cases`: the loader is unchanged; add/keep a test that a multi-`gold_files` case round-trips.

## Validation & measurement

1. Re-run `repo-atlas eval-offline --layer retrieval` against the real store → expect **gpuimage
   Success@k to jump** (JNI gold now points where retrieval already looks; sepia accepts the
   concrete filters), and overall MRR up. The secondary **coverage Recall will drop** (more golds
   to cover) — expected and acceptable.
2. Record before/after Success@5/10/20 + MRR (overall + per-repo) and the median-#golds.

## Risks & open questions

- **Curation subjectivity / gaming.** Mitigated by the anti-gaming rule, the visible median-#golds
  provenance, and MRR/nDCG retaining discrimination. If Success saturates near 1.0 across the
  board, MRR becomes the de-facto primary (rank quality), which is fine.
- **Reduced comparability with the pre-change scorecards.** The headline metric changes
  (Recall→Success), so old vs new scorecards aren't directly comparable on the headline; record
  both Success *and* coverage-Recall so the transition is legible.
- **The 2 genuinely-crowded gpuimage base-class cases** (`cur-gpuimage-filter-base`,
  `cur-gpuimage-image-handler`) won't be fixed by curation — their correct gold ranks 19–27 in a
  31k-symbol pool. They remain the signal for the deferred pool-aware re-ranking work; multi-gold
  may still help if a sibling base header is an acceptable alternative, but don't force it.
```
