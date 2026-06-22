# repo_atlas — Design Principles, Evaluation Methodology, and Results

**Status:** living document · last updated 2026-06-21
**Scope:** the `repo_atlas` cross-repo knowledge layer of knowledgeLoop — what it is designed to do,
how we evaluate whether it works, and what the evaluation has shown so far.

This document consolidates the design thinking and the evaluation work that the per-feature specs
and plans under `docs/superpowers/{specs,plans}/` record in detail. It is the single place to
understand *why* repo_atlas is built the way it is and *how confident* we are that it helps.

---

## Part I — Design Principles

### 1. Exploit existing knowledge before acquiring new

knowledgeLoop already *produces* knowledge (CodeWiki generates architecture-aware wikis;
codebase-memory indexes a code graph). repo_atlas's thesis is that a coding agent should
**exploit what we already know before going to acquire new knowledge** — read the relevant prior
art first, then explore. The system's job is to surface the right existing pattern at the moment a
change is being made, so the agent reuses instead of re-deriving or inventing.

### 2. Produce → bridge → consume → (feed-back)

repo_atlas sits on the *consume* side of a four-stage loop:

- **Produce** — CodeWiki wikis + codebase-memory symbol graph, per repo.
- **Bridge** — index those into one cross-repo store (`atlas.db`: FTS5 keyword + brute-force
  vector cosine over `bge-m3` embeddings).
- **Consume** — MCP tools a coding agent calls (below).
- **Feed-back** — execution results flowing back to improve the knowledge. *Deferred* — not built.

### 3. Grounded, kind-aware retrieval

The consume surface is four MCP tools:

| tool | scope | purpose |
|---|---|---|
| `find_related` | all repos | discovery — surface prior-art docs **and** source symbols for a task |
| `prepare_change` | single repo | a context pack (conventions + related units) for a target |
| `verify_grounding` | single repo | confirm the symbols/APIs the agent used actually exist |
| `list_repos` | — | what's indexed + freshness |

Two design choices proved load-bearing under evaluation:

- **Kind-balanced retrieval.** `find_related` was originally doc-dominated — for "write a sepia
  filter" it returned 16 wiki-docs and 4 symbols, burying the canonical source file. Retrieval now
  balances the two kinds in the core (quota + interleave, default-on, `REPO_ATLAS_SYMBOL_RATIO`
  knob) and the tool groups them into `{docs, symbols}` buckets — the agent gets *the pattern* and
  *the code* to follow.
- **Grounding as a guardrail.** `verify_grounding` lets the agent check that referenced APIs are
  real before committing to them, directly targeting hallucination.

### 4. Relevance is "any-of," not "all-of"

Prior-art retrieval is inherently a *find me a relevant example* problem: several files may be
equally valid references, and surfacing **any** one is success. This shapes both the tool (return
a balanced set) and the metrics (Part II).

---

## Part II — Evaluation Methodology

The central methodological lesson: **measure the cheap, deterministic layers directly, and reserve
the expensive end-to-end agentic test for outcome validation.** We arrived at this after the
naive instrument — an end-to-end agentic A/B — proved too noisy to trust.

### 1. The evaluation pyramid

```
        ┌─ 4. Agentic A/B (outcome) ─┐   expensive, noisy   → validate, don't tune
        │  does the agent do better? │   (dozens of sessions)
        ├─ 3. Context-injection ─────┤
        │  does the context help     │
        │  the model's output?       │
        ├─ 2. Grounding ─────────────┤   cheap, deterministic
        │  verify_grounding          │   (ms/case, no agent)
        │  precision / recall        │   → tune here
        └─ 1. Retrieval ─────────────┘
           find_related Recall@k /
           MRR / nDCG
```

- **Layers 1–2 (offline)** are agent-free, deterministic, and run in seconds — so we can iterate on
  chunking / embeddings / fusion with instant feedback and real statistical power (N in the
  hundreds is feasible).
- **Layer 4 (agentic)** is the only thing that measures the actual goal (agent outcomes), but it is
  expensive and statistically weak at the N we can afford. We use it to *validate* that offline
  gains translate to outcomes — not as the day-to-day tuning instrument.

### 2. Retrieval metrics are any-of (Success@k + MRR), Recall is coverage

Because relevance is any-of (Part I.4):

- **Primary:** `Success@k` (any acceptable gold in the top-k) + `MRR` (rank of the first one).
- **Secondary:** `Recall@k` is demoted to a *coverage* stat (fraction of *all* acceptable golds
  found) — it understates by design when a case has several valid alternatives.
- Each case carries a **set** of acceptable gold files; curation discipline keeps that set to
  *canonical* targets (anti-gaming), and the scorecard reports **median golds/case** so the
  breadth is visible.

### 3. Grounding is measured against source reality, not the store

The grounding "real" symbol set is **grep-verified from the repo source**, not sampled from the
store — so a real symbol the store fails to confirm counts against it. This is what surfaced the
store's under-indexing of typedefs/externs as a *product* risk (the tool can tell an agent a real
API "doesn't exist"), not just a metric artifact.

### 4. Mechanism-resolved agentic evaluation

A binary success rate over a small N is uninterpretable. So the agentic layer traces the **causal
chain per task** instead of trusting an aggregate:

```
find_related surfaced the gold prior-art?  →  agent reused it?  →  outcome beat baseline?
   (scored on the agent's ACTUAL query)        (diff overlap)       (blinded judge)
```

Each task is classified — `causal-win` / `surfaced-ignored` / `retrieval-miss` /
`win-unattributed` / `regression` / `no-effect` — so any non-win is *attributed* to an adoption
gap vs a retrieval gap vs no headroom. At small N a per-task causal trace is far more informative
than a noisy rate.

### 5. Principles that emerged the hard way

- **Passive availability ≠ adoption.** Making MCP tools merely *available* did not make the agent
  use them (0 calls in the first run). A coding agent on a locally-solvable task won't reach for a
  knowledge tool unless *induced*. The treatment arm now prepends a mandatory directive, and the
  harness records **adoption telemetry** — a result is only interpretable if adoption > 0.
- **Avoid teaching-to-the-test.** Tuning ground truth toward what retrieval already returns is
  structurally circular. Mitigations: fresh tasks (not in the tuning set), scoring retrieval on the
  agent's *live* queries, and an explicit **difficulty self-check** (target baseline success ≈
  30–60% — if a baseline agent solves everything, there is no headroom for the tool to help).
- **Distinguish the proxy from the goal.** Retrieval/grounding quality is a *precondition*. "Better
  retrieval" is only worth claiming as "useful" once an outcome-level test confirms it.

### 6. The working loop, and the process discipline

Every improvement followed one loop:

> **eval → diagnose → spec → plan → build → measure**

- **eval** surfaces a number; **diagnose** localizes the cause (often via parallel forensic
  agents); **spec** (brainstorm → design doc) and **plan** (bite-sized TDD tasks) are written and
  reviewed; **build** runs subagent-driven (a fresh implementer per task + two-stage spec-then-
  quality review); **measure** re-runs the eval. Each artifact lives in
  `docs/superpowers/{specs,plans}/`.
- This discipline repeatedly caught real defects before they shipped — e.g. a `verify_grounding`
  envelope mismatch, banker's-rounding in a quota split, and a transcript-filter bug that would
  have silently zeroed the mechanism metric.

---

## Part III — Evaluation Results

### Timeline (one loop, seven laps)

| Lap | Instrument | Result | Lesson |
|---|---|---|---|
| 1 | Agentic A/B (N=6) | **null** — 0 tool calls; success 60%→60% | passive availability ≠ adoption |
| 2 | Agentic A/B + forced adoption | success 67%→83% (**one** task flip on N=6); adoption 6/6 | underpowered; tasks too local |
| 3 | **Offline retrieval+grounding** (pivot) | see below | tune the proxy deterministically |
| 4 | Close-the-loop agentic (mechanism-resolved) | **valid negative**: +0pp, 0 causal wins — but retrieval surfaced 90% | retrieval works end-to-end on *broad* prior-art; gap = task-*completion* + the judge can't verify |
| 5 | **Grounding-based finding-bottleneck** (judge-free) | **valid negative**: grounded-success 20%→20%, surfaced only 30% | the *reliable* test: for "use this specific buried API" tasks, retrieval doesn't surface the **symbol** — a precision gap |
| 6 | **Symbol-text enrichment** → leaner, deterministic rank-check | **6a (+body): net-neutral** (top-10 3→3); **6b (doc+sig, no body): WIN** — top-10 3→**6/11**, surfaced 6→**8/11**, mean rank 51.5→41.5 | the body dilutes a strong name-anchored match; **doc-comment + signature is pure signal → shipped as the default** |
| 7 | **Outcome-driven flywheel** — 3-arm agentic harness + proxy↔outcome correlation (instrument built) | infrastructure shipped + unit-tested (9 commits, 41 tests); **no outcome numbers yet** — first 3-arm reading pending a `claude`-CLI + built-index + live-embeddings env | built the *scale*, not the measurement: `forced-inject` arm isolates knowledge value, `optional` arm measures adoption, their gap = the adoption tax |

### Offline retrieval (file-level, 15 cases, `bge-m3`)

| metric | baseline | + rebalance | + multi-gold (any-of) |
|---|---|---|---|
| Recall@20 / Success@20 (overall) | 0.20 | 0.60 | **0.80** |
| — android-gpuimage-plus | 0.00 | 0.20 | **0.60** |
| — libxcam | — | 0.80 | **1.00** |
| — ndk-samples | — | 0.80 | 0.80 |
| MRR | 0.019 | 0.191 | 0.293 |

- **Rebalance** (doc/symbol balancing) tripled Recall@20 — the canonical source file now surfaces
  instead of being buried under wiki-docs.
- **Multi-gold** lifted Success@20 to 0.80 with `median golds/case = 1.0` (anti-gaming held — only
  6/15 cases needed alternatives). The gpuimage jump (0.20→0.60) came mostly from *correcting
  mis-specified ground truth* (the JNI gold pointed at the wrong file), confirmed by the
  investigation below.

### Grounding

`verify_grounding` sensitivity **0.99**, specificity **1.00** — it confirms ~99% of real symbols
and rejects 100% of fabricated ones. This *vindicated* a suspicion: the original agentic eval's
"hallucination ≈ 1.0" was a metric artifact, not a real grounding failure. Caveat: the current
generator under-samples the typedef/macro/extern surface that is most prone to under-indexing, so
0.99 likely overstates grounding health — a known follow-up.

### Key diagnostic findings

- **find_related was doc-dominated** — fixed by rebalance (Part I.3).
- **gpuimage's residual weakness is mostly mis-specified gold, not the engine.** For the JNI and
  sepia tasks, retrieval already returned the *right* files (`cgeNativeLibrary.h`, the concrete
  `cge*Adjust` filters); the hand-picked single gold was simply wrong/under-specified. Two of five
  gpuimage cases remain genuine retrieval difficulty (a correct base-class header ranked 19–27 in a
  31k-symbol pool) — isolated as the signal for deferred pool-aware re-ranking.

### Close-the-loop validation (2026-06-21, 10 tasks — 1 timed out)

11 fresh harder *intra-repo prior-art* tasks (e.g. "add a LUT color-grade following the existing
lookup filter," "fix the no-video-track null-deref following the existing error-bail pattern"),
baseline vs improved-treatment, mechanism-resolved (Part II.4). One task timed out (900s) and was
skipped → N=10.

**Headline:** task success **50% → 50% (+0pp)**, **0/10 causal wins**. Adoption **10/10** (forced
directive works). Difficulty self-check: baseline success **50%** — squarely in the 30–60% target,
so the tasks were well-calibrated (real headroom on the 5 failing tasks; this is *not* a
no-headroom artifact).

**Mechanism — where the chain breaks:**

| signal | value | reading |
|---|---|---|
| **surfaced** (find_related returned the gold prior-art) | **90%** | retrieval works end-to-end — the offline gains translate to a *live* agent |
| reused (edited the prior-art *file*) | 40% | **undercount** — see below |
| causal-wins | 0/10 | treatment never solved a task baseline failed |
| category histogram | `surfaced-ignored` ×6, `no-effect` ×3, `retrieval-miss` ×1 | — |

**The "reused" metric undercounts — corrected reading.** Inspecting the diffs, all 6
`surfaced-ignored` agents *did* use the surfaced prior art — by creating a **new file** that
follows it (`cgeLUTFilter` ← `cgeLookupFilter`; `cl_box_filter_handler` + a new `.cl` kernel ←
`cl_gauss_handler`; `cl_dehaze_handler` ← `cl_defog_dcp_handler`; etc.). Since "add a new X
following Y" is correctly solved by a *new* file, the file-level reuse metric scores these `False`
even though the pattern was followed (the blind spot the spec flagged). So the real chain is
**surfaced (90%) → followed-the-pattern (high) → but still failed the task**.

**Honest verdict.** This is a **valid negative on outcomes** (unlike lap 1's null-by-construction):
adoption was real, retrieval surfaced the right prior art 90% of the time, and the tasks had
headroom — yet treatment did not lift task success. The mechanism *attributes* it precisely: the
bottleneck is **not retrieval and not adoption** — it is **task completion**. On the 5 well-
calibrated hard tasks where baseline failed (a working OpenCL kernel + handler, a correct native
LUT filter with registration), the agent found and followed the right pattern and *still* produced
a solution the judge rejected — on both arms. Surfacing the pattern is necessary but, for these
hard implementation tasks, not sufficient. The already-passing tasks (jni-version, negation-blend,
audio-rate, codec-notrack) had no headroom for the tool to add value. The worse secondary metrics
(hallucination +0.14, exploration +7 turns) are the known-noisy ones — and partly real: after
find_related points the agent at a *complex* existing implementation, it explores that larger
surface (e.g. sketch 21→50 turns).

### Grounding-based finding-bottleneck eval (2026-06-22, 10 tasks — 1 timeout)

The close-the-loop run was blocked by an **unverifiable LLM judge** (it can't compile C/C++). So
this lap replaced the judge with a **mechanically-checkable `GroundingScorer`**: success = the
agent's diff references the **required real API** on tasks where finding that *non-obvious buried*
API is the bottleneck (11 fresh tasks, curated via a 3-agent fan-out, every `required_api`
grep-verified; e.g. `cgeGetDataAndChannelByFormat`, `convert_to_clbuffer`, `arraysize`). The claim
is narrow and honest: *does repo_atlas make the agent ground in the right real API instead of
reinventing/hallucinating* — not full task-correctness.

**Headline:** grounded-success **20% → 20% (+0pp)**, **0/10 causal wins**, adoption 10/10.
**Honesty check passes:** baseline grounded-success = **20%** (low) → the tasks really are
finding-bottleneck, so the result is informative — and, being judge-free, it is the first
**reliable** negative in the whole series.

**Mechanism attributes it to retrieval *precision*:**

| signal | value | reading |
|---|---|---|
| **surfaced** (find_related returned the API's defining file) | **30%** | the tool mostly did *not* surface the specific buried utility |
| categories | retrieval-miss ×5, surfaced-ignored ×2, win ×1, regression ×1, no-effect ×1 | dominated by retrieval-miss |

The offline work optimized *broad* prior-art retrieval (Recall@20 0.8 on "how do I do X"). But
"find the one specific function I should call" is a **different, harder, symbol-level** retrieval
problem the current `find_related` doesn't solve — it surfaces docs/files, not the precise symbol.
On the 2 surfaced cases the agent still reinvented. And the forced "find_related first" directive
sometimes *hurt*: `arraysize` went 2→24 turns (baseline wrote `sizeof/sizeof` immediately;
treatment burned 24 turns searching, never found the macro, and hallucinated). **The next lever is
symbol-precise retrieval for "use-the-existing-helper" intents** — the justified consume-side cycle.

### Symbol-text enrichment (2026-06-22, deterministic rank-check, real bge-m3)

The proposed fix for lap 5: index each symbol *with its source* (doc-comment + signature + first
~15 body lines, capped ~500 chars), so a goal-phrased query matches what the symbol *does*. Tested
the cleanest way — a **doc-free symbol-rank check**: build two indexes from the same CBM
enumeration on the same embedder (real bge-m3, served locally via a sentence-transformers GPU
endpoint when Ollama was unavailable), pre-enrich vs enriched, and compare the required-API's rank
in `kinds=['symbol']` retrieval. (Re-baselined, so the delta isolates the text change.)

**Result — net-neutral, a valid negative:** required-API in **top-10 3/11 → 3/11**, mixed-surfaced
**6/11 → 6/11**, mean rank 51.5 → 46.2 (~flat); **4 tasks improved, ~5 regressed, 2 flat**.

It is **double-edged**: enrichment *helped* where the body adds discriminating behavioral signal
(`format-decode` 14→2, `sensormanager` 17→4) but *hurt* where it diluted an already-strong
name-anchored match (`planar-info` 1→7, `convert-clbuffer` 10→21, `scale-buffer` 22→None). The
mechanism: appending the body **averages the symbol embedding** — adding signal *and* off-topic
tokens — so it rescues cryptic names and drags down good ones. The spec's "richer text → better
match" hypothesis is **partially refuted**: it's not free. So enrichment-with-body is **not** the
fix (the code is merged at `e2c899a` but shouldn't be claimed as a solution). The obvious next test
the mechanism points at: a **leaner enrichment — doc-comment + signature only, no body** — to keep
the behavioral signal without the body dilution (a one-line `body_lines=0` change on the now-ready
pipeline). Caveat: the local bge-m3 ran at `max_seq_length=1024` (docs truncate; symbols at ~150
tokens are unaffected, and the rank check is doc-free) — the pre→enr *delta* is controlled (same
embedder), so the net-neutral conclusion holds.

**6b — the leaner variant (the actual fix).** The mechanism pointed straight at the body as the
noise, so we re-tested with **doc-comment + signature only, no implementation body** (`body_lines=3`)
on the same pipeline. **Clear win:** required-API in **top-10 3/11 → 6/11** (doubled), mixed-surfaced
**6/11 → 8/11**, mean rank **51.5 → 41.5**, **6 improved / 1 regressed**. It both **kept the wins**
(cryptic names rescued by the doc-comment: `cgeGetBlendModeName` None→8, `sensormanager` 17→8,
`metadata-tag` 8→3) **and erased the regressions** the body had caused (`planar-info` held 1→1 vs
1→7; `convert-clbuffer` 10→6 vs 10→21; `metadata-tag` 8→3 vs 8→17). So the body genuinely diluted
the embedding; doc-comment + signature is the pure behavioral signal. **This is now the shipped
default** (`extract_symbol_source(body_lines=3)`). Bounds: N=11 (3→6 = 3 tasks flipping, directional
but real); 5/11 still miss top-10, 3 never improve (`gen-texture`/`readback`/`fps-macro` — likely no
doc-comment or a deeper query-mismatch). A real, measured improvement to symbol precision — not a
total fix, and the agentic grounded-success translation is still unrun.

---

## Part IV — Honest Assessment

**What is genuinely established:**
- A **deterministic measurement loop** that localizes problems and tunes the system with instant
  feedback — far more reliable than the noisy agentic A/B.
- **Two measured product improvements** (rebalance, multi-gold) with traceable causes, each built
  through spec → plan → reviewed implementation.
- **Grounding is good**; the earlier "hallucination" alarm was an artifact.
- **Retrieval works end-to-end.** The close-the-loop run showed `find_related` surfaces the right
  prior art for a *live* agent **90%** of the time, and the agent then follows that pattern (in a
  new file) — so the offline retrieval gains are real, not an artifact of curated queries.

**What is now known but unfavorable (be candid):**
- **Surfacing prior art did not lift task outcomes** on the hard close-the-loop set (+0pp, 0 causal
  wins, baseline well-calibrated at 50%). The mechanism attributes this precisely: the bottleneck
  is **task completion, not retrieval or adoption** — on the hard tasks the agent found and followed
  the right pattern and still produced a solution the judge rejected, on both arms. repo_atlas's
  payoff is therefore **most plausible where *finding* the pattern is the bottleneck** (large/
  unfamiliar codebases, "wire it up the standard way" tasks) and **least where *implementing* it
  correctly is the hard part** — which is what this task set happened to stress.
- **Retrieval surfaces the right *file*, not the right *symbol*.** The judge-free grounding eval
  (lap 5) is the reliable test: on "use this specific buried API" tasks, `find_related` surfaced the
  required API's file only **30%** of the time, and grounded-success was **20%→20%** — repo_atlas
  did not make the agent call the right real API more. So retrieval works for *broad* prior-art
  ("how do I do X" → 90%) but not for *symbol-level precision* ("which exact function do I call" →
  30%). Those are different retrieval problems; only the first is solved.
- **Ground-truth circularity** is mitigated, not eliminated; read offline Success as "retrieval
  surfaces plausible prior art," not proof of usefulness.
- **Measurement caveats:** the agentic "reused" metric is file-level and **undercounts** new-file-
  follows-pattern reuse (proven in lap 4); grounded-success (lap 5) fixed this for the find-intent
  case. hallucination/exploration deltas remain noisy. The forced "find_related first" directive can
  *hurt* (`arraysize` 2→24 turns) — adoption shouldn't be unconditionally forced.
- **Small, single corpus** (3 repos, 15 offline + 21 agentic tasks, one embedding model) —
  directional, not statistically strong.

**Net:** we have a **reliable, judge-free instrument**, three valid negatives — and now a **measured
positive**. The instrument's full arc: lap 5 *localized* the gap (symbol-precise retrieval, 30%
surfaced), lap 6a *refuted* a plausible fix (full-body enrichment, net-neutral) before we shipped it,
and lap 6b *found and validated* the real one (**leaner doc-comment+signature enrichment** — top-10
3/11→6/11, surfaced 6/11→8/11, now the default). The gap is **partially closed**: symbol precision
measurably improved, though 5/11 still miss top-10. That is the methodology paying off end-to-end —
diagnose → propose → refute → refine → ship, all on deterministic evidence.

**Deferred follow-ups (after lap 6b shipped):** (1) the **3 still-missing symbols** (`gen-texture`/
`readback`/`fps-macro`) — likely no doc-comment / deeper query-mismatch → a different lever
(name-weighting, body→FTS-only-not-vector, or a learned re-ranker); (2) confirm the rank gain
**translates to agentic grounded-success** — the *instrument* for this now exists (lap 7, below); the
real 3-arm reading is **pending** an environment with the `claude` CLI + a built index + live
embeddings; (3) don't *unconditionally* force find_related (it can waste turns when the answer is
trivial); pool-aware re-ranking; grounding stratified sampling; a doc↔source relevance model; and the
*feed-back* stage of the produce→consume loop.

### Lap 7 — Outcome-driven flywheel (instrument built, reading pending)

The original null result was null **by construction** — agents made *zero* MCP calls, so the A/B
had no signal — and the offline retrieval metric we have been optimizing (lap 6b) had never been
shown to move real agents. Lap 7 closes that gap by building the *instrument*, per
`docs/superpowers/specs/2026-06-22-outcome-driven-flywheel-design.md` (+ plan). Shipped, 9 commits,
41 unit tests, ruff clean:

- **3-arm agentic harness** (`ClaudeRunner` + `eval-arms` CLI): `control` (no KB) · `optional`
  (MCP available, *no* directive → natural adoption on finding-bottleneck tasks) · `forced-inject`
  (retrieval result pre-pasted into context, adoption-free) · `mandatory-call` (the legacy forced
  directive, retained). The `forced-inject` arm isolates *does the knowledge help*; `optional`
  measures *do agents adopt it*; their difference **is** the adoption tax.
- **Proxy↔outcome correlation** (`correlation.py`): joins the offline symbol-rank proxy (the lap-6b
  metric) with per-arm grounded-success, reporting "success if the proxy surfaced the API vs not"
  plus three arm contrasts — `forced−control` (knowledge ceiling), `optional−control` (captured
  today), `forced−optional` (adoption tax).
- **Trust fixes**: gold-anchored extraction (exact `required_api` tokens survive the `_is_symbol_ref`
  heuristic) + authoritative oracle (source-token fallback for under-indexed symbols) — the two bugs
  that biased the outcome signal.

**Status:** infrastructure + unit tests only. This lap built the *scale*, not the measurement — the
first real 3-arm reading needs the `claude` CLI, a built index, and a live embeddings endpoint (none
available at build time), so there are **no outcome numbers yet**. Built via a subagent workflow
(sequential implementers + per-task adversarial spec/quality review); the review pass caught one real
plan bug (a test-helper name collision) before merge.

---

## Appendix — Artifacts

- Specs/plans: `docs/superpowers/specs/2026-06-21-*` and `docs/superpowers/plans/2026-06-21-*`
  (retrieval eval, retrieval rebalance, multi-gold relevance, close-the-loop agentic eval,
  grounding-based finding-bottleneck eval).
- Run setup: `/home/vinc/repo-atlas-eval-full/` (`atlas.toml`, the `atlas-{preenrich,enriched,leaner}.db`
  indexes, `mcp{,-leaner}.json`, `bge_embed_server.py`).
- **Lap-7 runner:** `scripts/run_eval_arms.sh` (committed, parameterized, preflighted) +
  `/home/vinc/repo-atlas-eval-full/EVAL-ARMS-README.md` — one command for the first real 3-arm reading
  once the `claude` CLI + bge-m3 endpoint + `atlas-leaner.db` are present.
- Scorecards: `offline-scorecard{,-rebalanced,-multigold}.md`, `closeloop-scorecard.md`,
  `grounding-scorecard.md`; diagnosis: `diagnosis.md`.
- Code: `repo_atlas/` (engine + tools) · `repo_atlas/eval/` (agentic + mechanism) ·
  `repo_atlas/eval/offline/` (retrieval + grounding).
