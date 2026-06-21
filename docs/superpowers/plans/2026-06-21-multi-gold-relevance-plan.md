# Multi-Gold (Any-Of) Relevance — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adopt any-of relevance in the offline eval — rename `hit_rate_at_k → success_at_k` (primary) and `symbol_recall_at_k → symbol_success_at_k` (any-of), demote `recall_at_k` to a secondary coverage stat, re-curate all 15 retrieval cases with acceptable alternatives (incl. the gpuimage JNI fix), and re-measure.

**Architecture:** Per `docs/superpowers/specs/2026-06-21-multi-gold-relevance-design.md`. No schema change (`gold_files`/`gold_symbols` are already tuples). Blast radius of the rename is confined to `repo_atlas/eval/offline/{metrics,harness,report}.py` + their tests.

**Tech Stack:** Python 3.12 (`statistics.median`), pytest. The eval runs against `/home/vinc/repo-atlas-eval-full/atlas.db` (bge-m3) with local Ollama up.

**Conventions:**
- Run tests: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest <file> -m "not integration" -p no:cacheprovider --no-cov -q`
- `tests/` is gitignored → use `git add -f`. `from __future__ import annotations`; line length 100.

---

## Task 1: Metrics — rename + any-of symbol metric

**Files:**
- Modify: `repo_atlas/eval/offline/metrics.py`
- Modify: `tests/test_offline_metrics.py`

- [ ] **Step 1: Update the tests first (red)**

In `tests/test_offline_metrics.py`, replace `test_hit_rate_at_k` and `test_symbol_recall_at_k`:

```python
def test_success_at_k():
    assert m.success_at_k(["x", "a.h"], {"a.h"}, k=2) == 1.0
    assert m.success_at_k(["x", "a.h"], {"a.h"}, k=1) == 0.0
    assert m.success_at_k(["x"], {"a.h", "b.h"}, k=1) == 0.0       # none of the alternatives
    assert m.success_at_k(["b.h"], {"a.h", "b.h"}, k=1) == 1.0     # any acceptable gold -> hit
```

```python
def test_symbol_success_at_k():
    hits = [{"name": "Foo", "qualified_name": "ns.Foo"},
            {"name": "Bar", "qualified_name": None}]
    assert m.symbol_success_at_k(hits, ["Foo", "Baz"], k=2) == 1.0     # any-of: Foo found
    assert m.symbol_success_at_k(hits, ["ns.Foo"], k=2) == 1.0         # qualified_name match
    assert m.symbol_success_at_k(hits, ["Nope", "Nada"], k=2) == 0.0   # none found
    assert m.symbol_success_at_k(hits, [], k=2) == 0.0
    assert m.symbol_success_at_k(hits, ["Bar"], k=1) == 0.0            # Bar not in top-1
```

(Leave `test_recall_at_k`, `test_mrr_uses_full_list`, `test_ndcg_dedup_and_ideal`,
`test_grounding_scores` unchanged — `recall_at_k` stays.)

- [ ] **Step 2: Run to verify it fails**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_offline_metrics.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'success_at_k'`.

- [ ] **Step 3: Implement the rename in `repo_atlas/eval/offline/metrics.py`**

Replace `hit_rate_at_k` with `success_at_k` (identical body, new name + docstring):

```python
def success_at_k(ranked_files: list, gold: set, k: int) -> float:
    """1.0 if any acceptable gold file is in the top-k, else 0.0 (any-of relevance)."""
    return 1.0 if (gold & set(ranked_files[:k])) else 0.0
```

Replace `symbol_recall_at_k` with `symbol_success_at_k` (any-of semantics):

```python
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

Keep `recall_at_k`, `mrr`, `ndcg_at_k`, `grounding_scores` exactly as they are.

- [ ] **Step 4: Run to verify it passes**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_offline_metrics.py -p no:cacheprovider --no-cov -q`
Expected: PASS (6 passed). (`harness.py` still references the old names — it is fixed in Task 2; do not run the harness tests yet.)

- [ ] **Step 5: Commit**

```bash
cd /mnt/x/code/knowledgeLoop/.claude/worktrees/cm
git add repo_atlas/eval/offline/metrics.py
git add -f tests/test_offline_metrics.py
git commit -m "feat(repo_atlas/offline): success_at_k + any-of symbol_success_at_k (rename from hit_rate/symbol_recall)"
```

---

## Task 2: Harness — success primary, recall secondary, n_golds provenance

**Files:**
- Modify: `repo_atlas/eval/offline/harness.py`
- Modify: `tests/test_offline_harness.py`

- [ ] **Step 1: Update the harness test first (red)**

In `tests/test_offline_harness.py`, replace `test_run_retrieval_aggregates_and_perrepo`:

```python
@pytest.mark.asyncio
async def test_run_retrieval_aggregates_and_perrepo():
    cases = [
        RetrievalCase("c1", "r1", "q1", ("a.h", "alt.h"), ("A",)),   # 2 acceptable golds
        RetrievalCase("c2", "r2", "q2", ("b.h",)),
    ]
    stub = StubRetriever(hits_by_query={
        "q1": [{"file": "a.h", "name": "A", "qualified_name": None}],     # hits an alternative
        "q2": [{"file": "x.h", "name": "X", "qualified_name": None}],     # miss
    })
    rep = await run_retrieval(cases, stub, ks=(5,))
    assert rep.overall["n"] == 2
    assert rep.overall["success@5"] == 0.5           # c1 hit (any-of), c2 miss
    assert rep.per_repo["r1"]["success@5"] == 1.0
    assert rep.per_repo["r2"]["success@5"] == 0.0
    assert rep.overall["recall@5"] == 0.25           # secondary: c1 found 1 of 2 golds, c2 0
    assert rep.overall["sym_success@5"] == 1.0       # c1 symbol hit
    assert rep.overall["median_golds"] == 1.5        # golds: [2, 1] -> median 1.5
```

(Leave `test_run_retrieval_skips_failing_case` and `test_run_grounding` unchanged.)

- [ ] **Step 2: Run to verify it fails**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_offline_harness.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — `KeyError: 'success@5'` (harness still emits `hit@5`/`sym_recall@5`, no `median_golds`).

- [ ] **Step 3: Implement in `repo_atlas/eval/offline/harness.py`**

Add `import statistics` after `from dataclasses import dataclass`.

Replace `_agg_retrieval` with:

```python
def _agg_retrieval(rows: list, ks) -> dict:
    out = {"n": len(rows)}
    keys = ([f"success@{k}" for k in ks] + [f"recall@{k}" for k in ks]
            + [f"ndcg@{k}" for k in ks] + ["mrr"])
    for key in keys:
        vals = [r[key] for r in rows if key in r]
        out[key] = sum(vals) / len(vals) if vals else 0.0
    sym_key = f"sym_success@{max(ks)}"
    sym_vals = [r[sym_key] for r in rows if sym_key in r]
    if sym_vals:
        out[sym_key] = sum(sym_vals) / len(sym_vals)
    golds = [r["n_golds"] for r in rows if "n_golds" in r]
    if golds:
        out["median_golds"] = statistics.median(golds)
    return out
```

In `run_retrieval`, replace the per-case row construction (the `row = {...}` block through the
`if c.gold_symbols:` line) with:

```python
        row = {"id": c.id, "repo": c.repo, "source": c.source, "n_golds": len(gold_f)}
        for k in ks:
            row[f"success@{k}"] = metrics.success_at_k(ranked_files, gold_f, k)
            row[f"recall@{k}"] = metrics.recall_at_k(ranked_files, gold_f, k)   # secondary coverage
            row[f"ndcg@{k}"] = metrics.ndcg_at_k(ranked_files, gold_f, k)
        row["mrr"] = metrics.mrr(ranked_files, gold_f)
        if c.gold_symbols:
            row[f"sym_success@{kmax}"] = metrics.symbol_success_at_k(hits, c.gold_symbols, kmax)
```

- [ ] **Step 4: Run to verify it passes**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_offline_harness.py -p no:cacheprovider --no-cov -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Lint + commit**

```bash
/home/vinc/code/knowledgeLoop/.venv/bin/ruff check repo_atlas/eval/offline/harness.py
git add repo_atlas/eval/offline/harness.py
git add -f tests/test_offline_harness.py
git commit -m "feat(repo_atlas/offline): harness emits success@k (primary) + recall@k (secondary) + median_golds + sym_success"
```

---

## Task 3: Report — Success primary, Recall demoted to coverage

**Files:**
- Modify: `repo_atlas/eval/offline/report.py`
- Modify: `tests/test_offline_report.py`

- [ ] **Step 1: Update the report tests first (red)**

In `tests/test_offline_report.py`, replace `test_render_both_sections` and
`test_render_honours_custom_ks`:

```python
@pytest.mark.asyncio
async def test_render_both_sections():
    rc = [RetrievalCase("c1", "r1", "q1", ("a.h",))]
    rret = await run_retrieval(rc, StubRetriever(
        hits_by_query={"q1": [{"file": "a.h", "name": "A", "qualified_name": None}]}), ks=(5,))
    gc = [GroundingCase("g1", "r1", ("Real",), ("Fake",))]
    gret = run_grounding(gc, StubRetriever(grounding_by_repo={"r1": {"Real": True}}))
    md = render_offline_scorecard(rret, gret, embed_model="bge-m3", db_path="/x/atlas.db", ks=(5,))
    assert "Retrieval" in md and "Grounding" in md
    assert "Success@5" in md                         # primary metric is now Success
    assert "coverage" in md.lower()                  # recall demoted to a coverage line
    assert "median golds" in md.lower()              # provenance line
    assert "sensitivity" in md.lower()
    assert "bge-m3" in md
    assert "r1" in md


@pytest.mark.asyncio
async def test_render_honours_custom_ks():
    rc = [RetrievalCase("c1", "r1", "q1", ("a.h",), ("A",))]
    rret = await run_retrieval(rc, StubRetriever(
        hits_by_query={"q1": [{"file": "a.h", "name": "A", "qualified_name": None}]}),
        ks=(3, 7))
    md = render_offline_scorecard(rret, None, embed_model="bge-m3", db_path="/x/atlas.db",
                                  ks=(3, 7))
    # actual cutoffs surface as Success columns
    assert "Success@3" in md and "Success@7" in md
    assert "nDCG@7" in md
    # the hardcoded defaults are gone
    assert "Success@5" not in md and "Success@10" not in md
    # Recall is NOT a primary column; it appears once as secondary coverage at kmax=7
    assert "coverage Recall@7" in md
    assert "Recall@3" not in md
    # perfect rank-1 retrieval reports 1.000, not 0.000
    assert "1.000" in md
    assert "symbol-level Success@7" in md
```

(Leave `test_render_handles_skipped_layer` unchanged.)

- [ ] **Step 2: Run to verify it fails**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_offline_report.py -p no:cacheprovider --no-cov -q`
Expected: FAIL — current report renders `Recall@`/`Hit@` columns, no `Success@`/`coverage`/`median golds`.

- [ ] **Step 3: Implement in `repo_atlas/eval/offline/report.py`**

Replace `_retrieval_section` with:

```python
def _retrieval_section(rep, ks=(5, 10, 20)) -> list:
    if rep is None:
        return ["## Retrieval (find_related)\n_no retrieval layer run._\n"]
    ks = tuple(ks)
    kmax = max(ks)
    succ_cols = [f"Success@{k}" for k in ks]
    header = "| scope | " + " | ".join(succ_cols + ["MRR", f"nDCG@{kmax}"]) + " |"
    sep = "|---" * (len(succ_cols) + 3) + "|"
    mg = rep.overall.get("median_golds")
    title = (f"## Retrieval (find_related) — cases: {rep.overall['n']}"
             + (f"  (median golds/case: {_f(mg)})" if mg is not None else "") + "\n")
    lines = [title, header, sep]

    def row(name, agg):
        cells = [name] + [_f(agg.get(f"success@{k}", 0)) for k in ks]
        cells += [_f(agg.get("mrr", 0)), _f(agg.get(f"ndcg@{kmax}", 0))]
        return "| " + " | ".join(cells) + " |"

    lines.append(row("overall", rep.overall))
    for repo in sorted(rep.per_repo):
        lines.append(row(repo, rep.per_repo[repo]))
    lines.append(f"\n(secondary) coverage Recall@{kmax} (fraction of all acceptable golds): "
                 f"{_f(rep.overall.get(f'recall@{kmax}', 0))} overall")
    sym = rep.overall.get(f"sym_success@{kmax}")
    if sym is not None:
        lines.append(f"(secondary) symbol-level Success@{kmax}: {_f(sym)} overall")
    return lines
```

(`_grounding_section` and `render_offline_scorecard` are unchanged.)

- [ ] **Step 4: Run to verify it passes**

Run: `/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/test_offline_report.py -p no:cacheprovider --no-cov -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Lint + commit**

```bash
/home/vinc/code/knowledgeLoop/.venv/bin/ruff check repo_atlas/eval/offline/report.py
git add repo_atlas/eval/offline/report.py
git add -f tests/test_offline_report.py
git commit -m "feat(repo_atlas/offline): scorecard shows Success@k primary + coverage-Recall/median-golds secondary"
```

---

## Task 4: Re-curate the 15 retrieval cases (multi-gold + gpuimage JNI fix)

**Files:**
- Modify: `repo_atlas/eval/offline/cases/retrieval/tasks.toml`
- Modify: `repo_atlas/eval/offline/cases/retrieval/curated.toml`

All paths below are grep-verified to exist in the corpora.

- [ ] **Step 1: Rewrite `tasks.toml` with acceptable-alternative gold sets**

```toml
[[case]]
id = "task-gpuimage-add-sepia"
repo = "android-gpuimage-plus"
query = "Add a sepia-tone image filter to the CGE native filter library, following the existing filter pattern used by the other cge*Adjust filters."
gold_files = [
  "library/src/main/jni/cge/common/cgeImageFilter.h",
  "library/src/main/jni/cge/filters/cgeContrastAdjust.h",
  "library/src/main/jni/cge/filters/cgeBrightnessAdjust.h",
  "library/src/main/jni/cge/filters/cgeColorBalanceAdjust.h",
]
gold_symbols = ["CGEImageFilterInterface"]
source = "task:gpuimage-add-sepia"

[[case]]
id = "task-gpuimage-fix-jni"
repo = "android-gpuimage-plus"
query = "A native method is failing to bind from Java to C++. Fix the JNI registration in the CGE native bridge so the Java layer can call into the native filter code."
gold_files = [
  "library/src/main/jni/interface/cgeNativeLibrary.h",
  "library/src/main/jni/interface/cgeNativeLibrary.cpp",
  "library/src/main/jni/cge/common/cgeGlobal.h",
]
source = "task:gpuimage-fix-jni-registration"

[[case]]
id = "task-libxcam-add-handler"
repo = "libxcam"
query = "Add a new OpenCL image handler to libxcam that applies a simple gamma adjustment, following the existing CLImageHandler pattern in the ocl module."
gold_files = [
  "modules/ocl/cl_image_handler.h",
  "modules/ocl/cl_csc_handler.h",
  "modules/ocl/cl_3d_denoise_handler.h",
]
gold_symbols = ["CLImageHandler"]
source = "task:libxcam-add-handler"

[[case]]
id = "task-libxcam-fix-csc"
repo = "libxcam"
query = "The color-space-conversion handler in libxcam produces incorrect output for a specific input format. Fix the CSC image handler."
gold_files = [
  "modules/ocl/cl_csc_handler.h",
  "modules/ocl/cl_csc_handler.cpp",
  "modules/ocl/cl_csc_image_processor.h",
  "modules/ocl/cl_3a_image_processor.h",
]
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

- [ ] **Step 2: Rewrite `curated.toml` with acceptable-alternative gold sets**

```toml
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
gold_files = [
  "library/src/main/jni/interface/cgeNativeLibrary.h",
  "library/src/main/jni/interface/cgeNativeLibrary.cpp",
  "library/src/main/jni/cge/common/cgeGlobal.h",
]

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
gold_files = [
  "modules/ocl/cl_3a_image_processor.h",
  "modules/ocl/cl_csc_image_processor.h",
]

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

- [ ] **Step 3: Verify every gold file exists**

Run:
```bash
cd /mnt/x/code/knowledgeLoop/.claude/worktrees/cm
CODEWIKI_NO_KEYRING=1 REPO_ATLAS_REGISTRY=/home/vinc/repo-atlas-eval-full/atlas.toml \
  /home/vinc/code/knowledgeLoop/.venv/bin/python scripts/verify_offline_gold.py
```
Expected: `OK: all gold files exist across the cases ...`. If any path is missing, correct it (grep the corpus under `/mnt/x/code/corpora/<repo>`) and re-run until OK.

- [ ] **Step 4: Confirm the cases still load**

Run:
```bash
/home/vinc/code/knowledgeLoop/.venv/bin/python -c "from repo_atlas.eval.offline.cases import load_retrieval_cases as L; cs=L('repo_atlas/eval/offline/cases/retrieval'); print('cases:', len(cs)); print('multi-gold:', sum(1 for c in cs if len(c.gold_files)>1), 'of', len(cs))"
```
Expected: `cases: 15` and several multi-gold cases (≈6).

- [ ] **Step 5: Commit**

```bash
git add repo_atlas/eval/offline/cases/retrieval/tasks.toml repo_atlas/eval/offline/cases/retrieval/curated.toml
git commit -m "feat(repo_atlas/offline): multi-gold (any-of) case curation + gpuimage JNI gold fix (cgeGlobal.h -> cgeNativeLibrary.{h,cpp})"
```

---

## Task 5: Re-measure + regress (no merge)

**Files:** none (operational). Requires local Ollama (`bge-m3`) + `/home/vinc/repo-atlas-eval-full/atlas.db`.

- [ ] **Step 1: Re-run the offline eval and capture the new scorecard**

```bash
cd /mnt/x/code/knowledgeLoop/.claude/worktrees/cm
FULL=/home/vinc/repo-atlas-eval-full
CODEWIKI_NO_KEYRING=1 REPO_ATLAS_DB=$FULL/atlas.db REPO_ATLAS_REGISTRY=$FULL/atlas.toml \
  REPO_ATLAS_BASE_URL=http://127.0.0.1:11434/v1 REPO_ATLAS_API_KEY=local \
  REPO_ATLAS_EMBED_MODEL=bge-m3 \
  /home/vinc/code/knowledgeLoop/.venv/bin/python -m repo_atlas eval-offline \
  --cases repo_atlas/eval/offline/cases --layer retrieval --out $FULL/offline-scorecard-multigold.md
```
Expected: a scorecard with `Success@5/10/20` + MRR + nDCG primary columns, a `coverage Recall@20`
secondary line, and `median golds/case`. Record overall + per-repo `Success@k` and MRR.

- [ ] **Step 2: Compare to the rebalanced baseline**

Compare `$FULL/offline-scorecard-multigold.md` against `$FULL/offline-scorecard-rebalanced.md`.
Expected: **gpuimage Success@20 jumps** (JNI gold now points where retrieval already returns
`cgeNativeLibrary.h`; sepia accepts the concrete `cge*Adjust` filters), overall MRR up. Note the
2 base-class cases (`cur-gpuimage-filter-base`, `cur-gpuimage-image-handler`) may still miss —
that is the documented pool-crowding signal, not a regression.

- [ ] **Step 3: Full unit-suite regression (capture-safe form)**

```bash
/home/vinc/code/knowledgeLoop/.venv/bin/python -m pytest tests/ \
  --ignore=tests/test_eval_integration.py --ignore=tests/test_offline_integration.py \
  --ignore=tests/test_ra_integration.py \
  -p no:cacheprovider --no-cov -s -o addopts="" > /tmp/multigold_suite.log 2>&1; echo "exit=$?"
grep -c "FAILED" /tmp/multigold_suite.log
```
Expected: `exit=0` and `0` FAILED. (The `[offline-eval] case ... failed` / `[eval] task boom failed`
lines are intentional resilience-test stdout.)

- [ ] **Step 4: Report (no merge — leave for the human)**

Summarize baseline-vs-multigold Success@5/10/20 + MRR (overall + per-repo, esp. gpuimage), the
median-#golds, and the coverage-Recall. STOP before any `git merge`/`git push` to master.

---

## Self-review checklist (done while writing)

- **Spec coverage:** metric rename + any-of symbol (T1), harness success-primary/recall-secondary/median-golds (T2), report restructure (T3), all-15 multi-gold curation + gpuimage JNI fix (T4), re-measure (T5). Non-goals (per-case match mode, pool-aware re-ranking, grounding sampling, schema change) correctly excluded.
- **Blast radius:** only `harness.py` + `test_offline_metrics.py` referenced the renamed fns; both updated (T1/T2). No other consumers (grep-verified).
- **Type/key consistency:** `success@{k}` / `recall@{k}` / `ndcg@{k}` / `mrr` / `sym_success@{kmax}` / `median_golds` / `n_golds` keys are used identically across harness emit (T2), agg (T2), and report read (T3); metric signatures match between metrics.py and the tests.
- **No placeholders:** every gold path is concrete and grep-verified; every code + command step is complete with expected output.
