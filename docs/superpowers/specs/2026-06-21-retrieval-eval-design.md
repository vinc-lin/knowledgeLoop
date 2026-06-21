# repo_atlas Offline Eval (Retrieval + Grounding) — Design Spec

**Date:** 2026-06-21
**Status:** Approved design, pending implementation plan
**Related:** the agentic A/B eval (`repo_atlas/eval/`), the null-result diagnosis
(`/home/vinc/repo-atlas-eval-full/diagnosis.md`), memory `repo-atlas-eval-null-result`.

## Why

The end-to-end agentic A/B eval is the wrong *primary* instrument for "is repo_atlas
useful." Two real runs over the same 6 tasks gave opposite verdicts ("NOT useful" then
"useful"), both inside the noise band of an N=6 binary outcome with large run-to-run
variance (e.g. `ndk-fix-codec-crash` baseline went 900s-timeout → 10-turn success across
runs). It is expensive (12 `claude` sessions, ~30–60 min), low-power, and confounds five
variables (did the agent call the tool · did retrieval surface the right prior art · did the
agent use it · did the task need cross-repo knowledge · did the judge score correctly).

repo_atlas is fundamentally a **retrieval + grounding** system. Both are directly,
deterministically, cheaply measurable *without an agent* — which is more accurate (isolated,
high-N, repeatable) and ~1000× cheaper. The run that produced a real win was driven by
`find_related` surfacing the CGE filter-family doc; the run also exposed `verify_grounding`
telling the agent that real symbols (`CGEConstString`, `g_vshDefaultWithoutTexCoord`) don't
exist. Both effects are exactly what this eval measures head-on.

This eval is the foundation layer of an "evaluation pyramid": **(1) retrieval → (2) grounding →
(3) context-injection → (4) a small agentic integration check**. This spec covers layers 1–2.

## Decisions (locked during brainstorming)

- **Ground truth: hybrid** — stand up the harness + metrics on a ~30-case curated/auto seed
  now; add commit-mined cases later *iff* the corpora are re-cloned with full history (current
  checkouts are depth-1 exports, `rev-list --count HEAD == 1`, so commit mining is impossible
  today). The case format carries a `source` field so commit-mined cases drop in with **no
  harness change**.
- **Scope: retrieval + grounding** (pyramid layers 1 and 2). They share infrastructure and
  grounding is cheap; grounding already demonstrably misfires.
- **Relevance grain: file-level primary, symbol-level secondary.** A retrieval hit is primarily
  "a returned unit whose `file` ∈ the case's gold files"; symbol-level recall is reported as a
  stricter secondary number.

## Non-goals

- No "useful / not useful" verdict. This is a **tuning instrument** that reports measured
  quality (Recall@k, MRR, nDCG, grounding sensitivity/specificity). The agentic A/B remains the
  separate, final integration check.
- No LLM judge, no `claude` sessions, no MCP server process. Pure library calls.
- No re-indexing. The eval reads an existing `atlas.db`. (Re-cloning + commit mining is a
  documented future extension, not in this scope.)

## Architecture & data flow

```
cases/retrieval/*.toml ─┐
cases/grounding/*.toml ─┤
auto-generated grounding┘
                         │
                         ▼
        harness.run_retrieval / run_grounding
                         │
                         ▼
        retriever adapter  (SAME code path as the MCP tools)
          retrieve.find_related_units(store, embedder, query, k=…)
          tools.verify_grounding(store, repo, symbols)   (→ store.symbols_exist)
                         │
                         ▼
        metrics (recall@k · mrr · ndcg · sensitivity · specificity)
                         │
                         ▼
        report → markdown scorecard (overall + per-repo + worst false-negatives)
```

The adapter calls the **real retrieval functions** the MCP tools use — not a reimplementation —
so the eval measures production behavior. `Store` + an `Embedder` are constructed exactly as the
`index` CLI does, from `load_config(os.environ)` (`REPO_ATLAS_DB`, `REPO_ATLAS_BASE_URL`,
`REPO_ATLAS_API_KEY`, `REPO_ATLAS_EMBED_MODEL`).

**Determinism invariant:** the `atlas.db` must have been indexed with the *same* embedding model
the eval queries with (`bge-m3` locally). `bge-m3` + FTS5 + RRF are deterministic, so the whole
pipeline is reproducible → tuning changes (chunking, embeddings, RRF `k0`) produce comparable
deltas across runs.

## Module layout

```
repo_atlas/eval/offline/
  __init__.py
  cases.py        # RetrievalCase, GroundingCase dataclasses + TOML loaders
  retriever.py    # OfflineRetriever adapter (wraps find_related_units / verify_grounding);
                  #   StubRetriever for unit tests
  metrics.py      # recall_at_k, hit_rate_at_k, mrr, ndcg_at_k, grounding_scores (pure fns)
  harness.py      # run_retrieval(cases, retriever, ks) -> RetrievalReport
                  # run_grounding(cases, retriever) -> GroundingReport
  report.py       # render_offline_scorecard(retrieval_report, grounding_report) -> md
  gen_grounding.py# auto-generate grounding cases from corpora source + perturbation
  cases/
    retrieval/*.toml
    grounding/*.toml
CLI: repo-atlas eval-offline [--cases DIR] [--layer retrieval|grounding|all] [--out FILE]
                              [--k 5,10,20]
```

(Working name during brainstorming was `eval-retrieval`; renamed to `eval-offline` because it
covers both retrieval and grounding.)

## Data model: cases

### RetrievalCase (`cases.py`)

```python
@dataclass(frozen=True)
class RetrievalCase:
    id: str
    repo: str                      # must match a registry repo / store `repo` value
    query: str                     # the search string handed to find_related
    gold_files: list[str]          # repo-relative paths; PRIMARY relevance set (>=1 required)
    gold_symbols: list[str] = ()   # optional; SECONDARY (symbol-level) relevance set
    source: str = "curated"        # "curated" | "task:<id>" | "commit:<sha>" (future)
```

TOML form:
```toml
id = "gpuimage-sepia-filter"
repo = "android-gpuimage-plus"
query = "add a sepia tone color adjustment filter to the CGE native filter library"
gold_files = ["library/src/main/jni/cge/common/cgeImageFilter.h"]
gold_symbols = ["CGEImageFilterInterface"]
source = "curated"
```

### GroundingCase (`cases.py`)

```python
@dataclass(frozen=True)
class GroundingCase:
    id: str
    repo: str
    real_symbols: list[str]        # source-grep-verified to EXIST in the repo
    fake_symbols: list[str]        # constructed to NOT exist (perturbations / invented)
```

> Design choice: `real_symbols` are verified against the **repo source** (grep), *not* the
> store. The metric therefore measures the store against reality — a real symbol that
> `verify_grounding` reports as missing is a true defect (under-indexing), not a mislabeled case.

### Loaders

```python
def load_retrieval_cases(path: str) -> list[RetrievalCase]   # dir of .toml or a single file
def load_grounding_cases(path: str) -> list[GroundingCase]
```

Validation: non-empty `id`/`repo`/`query`; `gold_files` non-empty for retrieval; `real_symbols`
and `fake_symbols` non-empty for grounding; duplicate `id` → error.

## The retriever adapter (`retriever.py`)

```python
class OfflineRetriever:
    """Adapter over the production retrieval code paths. One per (store, embedder)."""
    def __init__(self, store, embedder): ...
    async def retrieve(self, query: str, repo: str | None, k: int) -> list[dict]:
        # delegates to repo_atlas.retrieve.find_related_units(self._store, self._embedder,
        #   query, repos=[repo] if repo else None, k=k); returns the hit dicts
    def ground(self, repo: str, symbols: list[str]) -> dict:
        # delegates to repo_atlas.tools.verify_grounding(self._store, repo, symbols)

class StubRetriever:
    """Canned hits/grounding keyed by query/symbols, for unit tests (no store/embedder)."""
```

Scoping retrieval to the case's `repo` (`repos=[repo]`) matches how a grounded single-repo tool
call works and keeps relevance judgement unambiguous. (A future variant can evaluate all-repo
`find_related` for cross-repo discovery; out of scope here.)

## Metrics (`metrics.py`) — all pure functions

Let a case return a ranked list of hits `H = [h_1 … h_n]` (best-first), and `G_f` = gold files,
`G_s` = gold symbols. A hit `h_i` is **file-relevant** iff `h_i.file ∈ G_f`.

- **Recall@k (file, primary)** = `|{ f ∈ G_f : f appears in {h_1.file … h_k.file} }| / |G_f|`.
- **Hit-rate@k** = `1` if any of `h_1…h_k` is file-relevant else `0` (mean over cases = fraction
  of cases with ≥1 gold file in top-k).
- **MRR** = `1 / rank` where `rank` = position (1-indexed) of the first file-relevant hit in `H`
  (whole list, not truncated); `0` if none. Mean over cases.
- **nDCG@k (file, binary, dedup)** = `DCG@k / IDCG@k` where
  `DCG@k = Σ_{i=1..k} rel_i / log2(i+1)`, `rel_i = 1` iff `h_i.file ∈ G_f` **and** that file has
  not appeared at an earlier position (each gold file counted once), and
  `IDCG@k = Σ_{i=1..min(k,|G_f|)} 1 / log2(i+1)`.
- **Recall@k (symbol, secondary)** — same as file recall but relevance = `h_i.name ∈ G_s` or
  `h_i.qualified_name ∈ G_s`; only computed for cases that declare `gold_symbols`.

Aggregation: report mean of each metric **overall** and **per-repo**. `k ∈ {5,10,20}` default
(configurable via `--k`); `find_related_units` is called once at `k = max(ks)` and metrics are
computed at each cutoff from that single ranked list.

**Grounding** — over a case's `real_symbols` (positives) and `fake_symbols` (negatives), with
`v = verify_grounding(repo, real ∪ fake)`:

- **Sensitivity (recall)** = `|{ s ∈ real : v[s].exists }| / |real|`. *Low ⇒ under-indexing.*
- **Specificity** = `|{ s ∈ fake : not v[s].exists }| / |fake|`. *Low ⇒ false "exists".*
- **False-negative list** = `{ s ∈ real : not v[s].exists }`, surfaced per repo (the actionable
  output — exactly the symbols the index is missing).

## Harness (`harness.py`)

```python
@dataclass
class RetrievalReport: per_case: list; overall: dict; per_repo: dict
@dataclass
class GroundingReport: per_case: list; overall: dict; per_repo: dict; false_negatives: dict

async def run_retrieval(cases, retriever, ks=(5,10,20)) -> RetrievalReport
def       run_grounding(cases, retriever) -> GroundingReport
```

`run_retrieval` is resilient per the agentic harness pattern: a case whose retrieval raises is
logged (`[offline-eval] case <id> failed: …`) and skipped; `overall`/`per_repo` are computed
over completed cases. No barrier needed — cases are independent.

## Report (`report.py`)

`render_offline_scorecard(retrieval_report, grounding_report) -> str` emits markdown:

```
# repo_atlas offline eval — retrieval + grounding

## Retrieval (find_related)   cases: N
| scope | Recall@5 | Recall@10 | Recall@20 | Hit@10 | MRR | nDCG@10 |
| overall | … | … | … | … | … | … |
| android-gpuimage-plus | … |
| libxcam | … |
| ndk-samples | … |
(secondary) symbol-level Recall@10: overall …

## Grounding (verify_grounding)   real: R  fake: F
| scope | sensitivity | specificity |
| overall | … | … |
| <repo> | … | … |
Worst false-negatives (real symbols reported missing): repo → [sym, …]
```

No verdict line — numbers only.

## CLI (`cli.py`)

Add subcommand `eval-offline`:
```
repo-atlas eval-offline --cases repo_atlas/eval/offline/cases \
  --layer all --k 5,10,20 --out offline-scorecard.md
```
Builds `Store(cfg.db_path)` + `GatewayEmbedder(cfg.base_url, cfg.api_key, cfg.embed_model)` from
`load_config(os.environ)`; constructs `OfflineRetriever`; loads cases; runs requested layer(s);
writes + prints the scorecard. `--layer grounding` skips the embedder (grounding needs only the
store).

## Seed corpus plan

**Retrieval seed (~30 cases):**
- **6 free** — convert the agentic tasks: `query = task.prompt`, `gold_files`/`gold_symbols`
  = the curated `expected_files`/`expected_symbols`, `source = "task:<id>"`.
- **~24 curated** — hand-written concept→files cases spread across the 3 repos (e.g. "OpenCL
  3A image processor pipeline" → `modules/ocl/cl_3a_image_processor.{h,cpp}`; "JNI bridge that
  registers native methods" → `hello-jni/.../hello-jni.cpp`). Gold files grep-verified to exist.

**Grounding (~150 symbols, auto via `gen_grounding.py`):**
- `real_symbols`: sample declarations from each repo's source (e.g. `grep -oE` over
  class/struct/function/typedef patterns in `.h/.cpp/.java`), keep ~40–50/repo, verified present.
- `fake_symbols`: perturb reals (char swaps, plausible suffixes like `…FooBar`, `…2`), assert
  absent from source. ~40–50/repo.
- Emitted as `cases/grounding/<repo>.toml`. Re-runnable to regenerate.

## Determinism & cost

- Retrieval case = 1 embed + 2 store queries (~50–200 ms). Grounding case = 1 `symbols_exist`
  batch. Full seed run = seconds to ~1 min — vs ~30–60 min for one agentic A/B.
- Fully re-runnable; safe to run in a tight tune→measure loop.

## Testing (TDD)

- `metrics.py`: worked-example unit tests for `recall_at_k`, `hit_rate_at_k`, `mrr`, `ndcg_at_k`
  (incl. the dedup rule and the empty/no-hit cases), and `grounding_scores`
  (sensitivity/specificity/false-negatives).
- `cases.py`: loader tests (valid dir, missing required field → error, duplicate id → error).
- `retriever.py`: `StubRetriever` behavior; `OfflineRetriever` delegation asserted via a fake
  store/embedder (no network).
- `harness.py`: `run_retrieval`/`run_grounding` end-to-end with `StubRetriever`; resilience test
  (a raising case is skipped, report computed over the rest).
- One `@pytest.mark.integration` test: run the seed against the real `atlas.db` + local Ollama,
  assert the scorecard renders and overall Recall@20 is a finite number in `[0,1]`.
- Tests are git-`add -f` (tests/ is gitignored); run with
  `pytest … -m "not integration" -p no:cacheprovider --no-cov`.

## Extensibility: commit mining (future, out of scope)

When/if the corpora are re-cloned with full history, a `gen_commits.py` selects source-touching
non-merge commits and emits `RetrievalCase(source="commit:<sha>", query=<message/issue>,
gold_files=<diff files>, gold_symbols=<diff-added decls>)` into `cases/retrieval/`. The harness,
metrics, and report are unchanged. This unlocks N=100s and objective, SWE-bench-style ground
truth (and, for commits with tests, executable verification at higher pyramid layers).

## Risks & open questions

- **Curator bias** in the seed retrieval cases (small-N, hand-picked queries). Mitigated by the
  6 task-derived cases and the commit-mining extension; flagged in the scorecard as `source`
  breakdown so curated vs task vs commit cases can be read separately.
- **Symbol-name matching** in `symbols_exist` is exact (`name` OR `qualified_name`, `kind=
  'symbol'`). The grounding eval will expose how much real surface that misses; the *fix* (suffix
  / member-access / external-symbol indexing) is downstream product work informed by this eval —
  not changed here.
- **Embedding/model drift:** if `atlas.db` is re-indexed with a different embed model, retrieval
  numbers shift; the report should record the embed model + db path for provenance.
```
