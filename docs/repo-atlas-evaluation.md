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

### Timeline (one loop, four laps)

| Lap | Instrument | Result | Lesson |
|---|---|---|---|
| 1 | Agentic A/B (N=6) | **null** — 0 tool calls; success 60%→60% | passive availability ≠ adoption |
| 2 | Agentic A/B + forced adoption | success 67%→83% (**one** task flip on N=6); adoption 6/6 | underpowered; tasks too local |
| 3 | **Offline retrieval+grounding** (pivot) | see below | tune the proxy deterministically |
| 4 | Close-the-loop agentic (mechanism-resolved) | *in progress* | does the proxy predict the outcome? |

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

### Close-the-loop validation (in progress)

11 fresh harder *intra-repo prior-art* tasks (e.g. "add a LUT color-grade following the existing
lookup filter," "fix the no-video-track null-deref following the existing error-bail pattern"),
baseline vs improved-treatment, mechanism-resolved (Part II.4). Adoption confirmed (every treatment
session calls the tools). **Results pending — this section will be filled with the causal-win
count, the difficulty self-check, and the category histogram when the run completes.**

---

## Part IV — Honest Assessment

**What is genuinely established:**
- A **deterministic measurement loop** that localizes problems and tunes the system with instant
  feedback — far more reliable than the noisy agentic A/B.
- **Two measured product improvements** (rebalance, multi-gold) with traceable causes, each built
  through spec → plan → reviewed implementation.
- **Grounding is good**; the earlier "hallucination" alarm was an artifact.

**What is not yet proven (be candid):**
- That improved retrieval **changes a real coding agent's outcomes** — the close-the-loop run is
  exactly this test, and it is still in flight. Until it lands, repo_atlas is a well-engineered,
  well-measured *foundation* whose end-user payoff is *inferred, not demonstrated*.
- **Ground-truth circularity** is mitigated, not eliminated; read offline Success as "retrieval
  surfaces plausible prior art," not proof of usefulness.
- **Small, single corpus** (3 repos, 15 offline cases, one embedding model) — directional, not
  statistically strong.

**Deferred follow-ups:** pool-aware re-ranking (the crowded base-class cases), grounding stratified
sampling, a doc↔source relevance model, and the *feed-back* stage of the produce→consume loop.

---

## Appendix — Artifacts

- Specs/plans: `docs/superpowers/specs/2026-06-21-*` and `docs/superpowers/plans/2026-06-21-*`
  (retrieval eval, retrieval rebalance, multi-gold relevance, close-the-loop agentic eval).
- Run setup: `/home/vinc/repo-atlas-eval-full/` (`atlas.db`, `atlas.toml`, `mcp.json`).
- Scorecards: `offline-scorecard{,-rebalanced,-multigold}.md`, `closeloop-scorecard.md`;
  diagnosis: `diagnosis.md`.
- Code: `repo_atlas/` (engine + tools) · `repo_atlas/eval/` (agentic + mechanism) ·
  `repo_atlas/eval/offline/` (retrieval + grounding).
