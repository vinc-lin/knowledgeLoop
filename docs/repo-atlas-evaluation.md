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

### Timeline (one loop, eight laps)

| Lap | Instrument | Result | Lesson |
|---|---|---|---|
| 1 | Agentic A/B (N=6) | **null** — 0 tool calls; success 60%→60% | passive availability ≠ adoption |
| 2 | Agentic A/B + forced adoption | success 67%→83% (**one** task flip on N=6); adoption 6/6 | underpowered; tasks too local |
| 3 | **Offline retrieval+grounding** (pivot) | see below | tune the proxy deterministically |
| 4 | Close-the-loop agentic (mechanism-resolved) | **valid negative**: +0pp, 0 causal wins — but retrieval surfaced 90% | retrieval works end-to-end on *broad* prior-art; gap = task-*completion* + the judge can't verify |
| 5 | **Grounding-based finding-bottleneck** (judge-free) | **valid negative**: grounded-success 20%→20%, surfaced only 30% | the *reliable* test: for "use this specific buried API" tasks, retrieval doesn't surface the **symbol** — a precision gap |
| 6 | **Symbol-text enrichment** → leaner, deterministic rank-check | **6a (+body): net-neutral** (top-10 3→3); **6b (doc+sig, no body): WIN** — top-10 3→**6/11**, surfaced 6→**8/11**, mean rank 51.5→41.5 | the body dilutes a strong name-anchored match; **doc-comment + signature is pure signal → shipped as the default** |
| 7 | **Outcome-driven flywheel** — 4-arm agentic eval + proxy↔outcome correlation (FIRST READING, N=10) | **rich NULL on outcomes**: grounded-success control **40%** ≥ mandatory-call 30% ≥ optional 20% = forced-inject 20%; **natural adoption 0/10** (verified), forced 10/10; proxy does **not** predict outcome | the binding constraint is **adoption + task-completion**, not retrieval; KB arms don't beat control; **±20pp N=10 noise floor** (optional≡control behaviourally yet differ 20pp) |
| 7b | **Genuine-gap re-run** — 8 grep-verified gap tasks + `GroundedUseScorer` (target-site, anti-gaming), 4 arms × 8 | **inverts to ~100% on ALL arms** incl. no-KB control; ceiling forced−control **−12pp**, captured optional−control **0pp** | control finds the helper **itself via `grep`** (6 calls, transcript-verified) → find_related is **redundant with grep intra-repo**; repo_atlas is **untestable on single-repo tasks** — needs a cross-repo substrate |
| 7c | **Cross-repo MVP** — libxcam split into `core`(library)+`ocl`(consumer), helper un-greppable from the task's repo, 3 tasks (1 timed out) | **first positive**: mandatory-call **100%** vs control **50%** (+50pp); the win is **airtight** on the non-guessable helper — find_related surfaced `XCAM_STATIC_FPS_CALCULATION` from the *other* repo, agent used it; control couldn't | repo_atlas's value is **real but narrow + gated**: non-obvious cross-repo helpers only (proven), null intra-repo, unlocked only by **forced adoption** (optional still 0/2) |
| 8 | **Scaled cross-repo ceiling** — control vs forced-inject over **15 non-guessable tasks across two codebases** (libxcam 10 + gpuimage 5), quota-validated | **clean +60pp ceiling**: control **1/15 (7%)** → forced-inject **10/15 (67%)** (libxcam +50pp, gpuimage +80pp) | the cross-repo value is **real & powered** — shown the un-greppable helper the agent uses it ⅔ of the time; the no-KB baseline structurally can't reach it. Adoption arms deferred (Claude **session-limit** is the eval budget) |
| 9 | **Adoption measured** — control/optional/**assisted** (gated nudge) on the **N=15** cross-repo set (libxcam 10 + gpuimage 5), session-limit-safe harness | control **13%** → optional **40%** → **assisted 53%** (vs banked ceiling 67%); `assisted_lift` **+40pp**, `captured` **+27pp**; adoption 0 → 6/15 → **10/15** | **adoption is solvable** — the gated nudge captures ~80% of the ceiling, *and* the lap-8 legibility rewrite lifted *natural* adoption (optional) from the historical ~0 to **40%**. Next = productize the gate+nudge (+ kept descriptions) as a hook/skill. (Harness fix fired live: 429 → clean stop) |

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
doc-comment or a deeper query-mismatch). A real, measured improvement to symbol precision — but lap 7
then ran the agentic translation and found it does **not** move agents: the binding constraint is
adoption (0/10 unprompted) + task-completion, not symbol-retrieval rank.

---

## Part IV — Honest Assessment

**What is genuinely established:**
- **The cross-repo ceiling is real and powered (lap 8).** Across **15 non-guessable tasks in two
  codebases**, surfacing the un-greppable cross-repo helper lifts grounded success from **7% → 67%
  (+60pp)**; the no-KB baseline structurally cannot reach it (1/15, a guessed API). This is the clean,
  scaled, quota-validated confirmation of lap 7c — the core hypothesis (cross-repo knowledge helps
  *when surfaced*) holds.
- **Adoption is solvable (lap 9).** On the same N=15, an insufficiency-gated soft nudge (`assisted`)
  reaches **53%** — ~80% of the 67% ceiling, +40pp over control — by getting the agent to call
  `find_related` itself (10/15), with no mandatory directive and no over-steering on local tasks.
  Even pure legibility (`optional`, just the improved tool description) lifted *natural* adoption from
  the historical ~0 to **40%**. So both the "does it help" and the "will it fetch it" halves now have
  affirmative, measured answers; the remaining work is **productization** (ship the gate+nudge as a
  hook/skill) and breadth (more codebases/models).
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

**Net:** we have a **reliable, judge-free instrument** and a clear-eyed arc. On the *offline proxy*
the methodology paid off end-to-end — lap 5 localized the gap (symbol-precise retrieval, 30%
surfaced), lap 6a refuted a plausible fix (full-body enrichment) before shipping it, lap 6b found and
shipped the real one (leaner doc-comment+signature enrichment, top-10 3/11→6/11). **But lap 7 closed
the loop on outcomes and the news is sobering:** that offline win does **not** translate to agent
behaviour. The binding constraints are **adoption** (0/10 unprompted, replicating the lap-1 null) and
**task-completion** (even forced or pre-injected knowledge doesn't beat a no-KB control, within a
±20pp N=10 noise floor). The instrument's most valuable act was *deflationary* — it stopped us
optimising find_related precision (a non-binding constraint for the agentic outcome) and pointed at
the real walls.

**Deferred follow-ups (re-prioritised after lap 7b — the genuine-gap re-run resolved (1) and (2)):**
The task-recuration and scorer fixes were *built and run* (lap 7b): they worked, and the answer is
that **intra-repo tasks can't validate repo_atlas** because baseline `grep` already solves intra-repo
finding. So the live questions are now: (1) **Build a cross-repo substrate** — the only setting where
the tool's hypothesis is testable: a monorepo, or a library split into producer+consumer repos, or a
service family sharing conventions; generate+index their wikis, then write tasks whose answer lives in
*another* repo (un-greppable from the task's repo). (2) **Or test the un-greppable-intra-repo case** —
semantic discovery where the agent *doesn't know the lexical name* to grep (vague "how is X done here"
intents), the one intra-repo niche where retrieval could still beat grep. (3) **Adoption (0/10)**
remains real for locally-solvable tasks — but is moot until (1)/(2) give the tool something grep can't
do. (4) lower priority: the 3 still-missing symbols; pool-aware re-ranking; grounding stratified
sampling; a doc↔source relevance model; the still-unbuilt *feed-back* stage.

### Lap 7 — Outcome-driven flywheel (first real reading: a rich null)

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

**Built** via a subagent workflow (sequential implementers + per-task adversarial spec/quality
review; the review pass caught one real plan bug before merge). Infrastructure: 9 commits, 41 unit
tests; runner `scripts/run_eval_arms.sh`.

**First reading (N=10, the 11 finding-bottleneck tasks, 1 timed out; `atlas-leaner.db` / real bge-m3;
44 `claude -p` runs):**

| arm | grounded-success | natural adoption | find_related surfaced gold |
|---|---|---|---|
| control (no KB) | **40%** | — | — |
| optional (MCP available, no nudge) | 20% | **0/10** | — |
| forced-inject (prior-art pre-pasted) | 20% | — | — |
| mandatory-call (forced `find_related` first) | 30% | 10/10 | 60% |

Read it as a **rich null on outcomes**, with four robust findings:

1. **Adoption is the wall — 0/10, verified.** On tasks where the right API is non-obvious *and* the
   tools were wired, agents called repo-atlas **zero** times unprompted (transcript-parsed: the lone
   `mcp__repo-atlas` mention is the availability listing, not a call; mandatory-call made 2 calls
   each, so telemetry is sound). This **replicates the lap-1 null at the harder, retrieval-favourable
   task set**: passive availability ≠ adoption — agents rationally don't reach for a cross-repo tool
   on a *locally solvable* task.
2. **No arm beats control, and the deltas are noise.** `optional` is behaviourally **identical** to
   `control` (0 adoption → bare prompt) yet scored 20% vs 40% — a 2-task swing between identical
   conditions pins the **N=10 noise floor at ≈ ±20pp**. Every arm difference here is within it.
3. **Even forcing the knowledge in doesn't help.** `forced-inject` (answer pasted in) and
   `mandatory-call` (60% surfaced, forced to retrieve) both land ≤ control. So the bottleneck is
   **task-completion, not finding** — echoing lap 4. (And the grounding scorer under-credits
   "implement *using* X" tasks where the agent legitimately *edits* X instead of calling it — the
   format-decode case — so these numbers understate genuine API use.)
4. **The proxy does not predict the outcome.** Per-arm grounded-success was *lower* when the offline
   symbol-rank proxy surfaced the API (control 29% surfaced vs 67% not; n=7/3) — no positive signal
   that the lap-6b retrieval win moves agents (small unsurfaced bucket; likely a selection effect —
   retrieval-hard tasks are also implementation-hard).

**What validated:** the 4-arm harness ran end-to-end at scale, the MCP path works (10/10 forced
adoption, 60% surfaced), and the correlation/contrasts compute.

**Diagnosis (cheap, transcript-only, no new runs) — the null is largely a TASK + SCORER artifact.**
Reconstructing every task×arm from the persisted transcripts (edits made, API engaged-vs-called,
prior-art surfaced) exposed the mechanism, and it is decisive:

- The KB arms produced **zero edits far more often than control** (optional 6/10, forced-inject 5/10
  vs control 3/10). Reading those no-op runs, the agents all say the *same* thing: *"the helper
  already exists — here's how to use it."* (`convert_to_clbuffer` "already does this"; `sensormanager`
  "implementation is already complete"; `getOutputBufferData` "already exists at line 293".) They
  produced a **correct prose answer, not a diff.**
- `control` "won" by the opposite behaviour: lacking that grounding it wrote **redundant** code that
  happens to call the API — it *re-implemented* the already-existing `getOutputBufferData`, added an
  example `convert_to_clbuffer` call in a *demo* file, re-defined an already-defined macro. The
  grounding scorer (diff-must-call-the-API) **credits this redundant code and scores the correct
  "it already exists" answer as 0.**

So the finding-bottleneck tasks were curated around *an existing buried API* — but that very property
makes "it already exists" the correct response, which produces no creditable diff. **Better grounding
made the agent behave more correctly and score worse.** The control-beats-KB result measures
willingness-to-write-redundant-code, which grounding rightly suppresses — not repo_atlas's value. The
instrument did its job: the cheap diagnosis **invalidated the strong reading of its own null** and
pointed at the real fix — a task set with a *genuine code gap* (ideally cross-repo, where "it already
exists here" is not a valid answer) and a scorer that credits a correct grounded outcome, not just a
diff. (Adoption 0/10 stands as a separate, real finding for *locally-solvable* tasks.)

### Lap 7b — Genuine-gap re-run: baseline `grep` dominates intra-repo

The diagnosis prescribed two fixes, both shipped: **8 grep-verified genuine-gap tasks**
(`tasks-genuine-gap/`: an unused/under-used helper + a concrete *absent* target site, so the correct
answer is a new call there — "it already exists" is no longer valid) and **`GroundedUseScorer`**
(`--scorer grounded-use`: credits the API *called* on an added line *inside the task's target files*,
blocking the demo-file and mention-without-call gaming). Re-ran all 4 arms × 8 tasks:

| arm | grounded-success | natural adoption |
|---|---|---|
| control (no KB) | **100%** | 0/8 |
| optional | 100% | 0/8 |
| forced-inject | 88% (1 miss) | — |
| mandatory-call | 100% | 8/8 (100% surfaced) |

The fixes worked — agents now produce real diffs (no more "it already exists" prose), and the scorer
is honest. But the result **inverts** lap 7: *everyone* scores ~100%, including no-KB control. The
prompts do **not** name the helper, yet control found it anyway — transcript-verified, it ran **6
`grep` calls** to locate `cgeGetBlendModeName`, 2 for `slerp`, then wrote the call. **The agent's own
`grep`/`read` already solves intra-repo "find the existing helper" — so `find_related` is redundant
with `grep`, and adds no measurable value** (ceiling forced−control = **−12pp**, captured
optional−control = **0pp**). Forced-inject's lone miss again shows injection can mislead.

**The throughline of the whole arc (laps 5–7b):** repo_atlas cannot demonstrate value on *single-repo*
tasks, for two compounding reasons — (1) agents don't adopt it unprompted on locally-solvable tasks
(lap 7), and (2) even handed a genuine gap, the **baseline (the agent's own `grep`) already finds the
helper** (lap 7b). Its value proposition is specifically **knowledge the agent cannot `grep` for** —
genuinely cross-repo prior art, or semantic discovery where you don't know the lexical name. *Neither
is testable with the current unrelated corpora.* **Intra-repo grounding tasks structurally cannot
validate a cross-repo retrieval tool; a related-repo / monorepo substrate is required.** That is the
flywheel's most important deliverable: not a score, but the realisation that the eval substrate itself
must change before repo_atlas's core hypothesis can be tested at all.

### Lap 7c — Cross-repo MVP: the first genuine positive signal

Built the substrate lap 7b prescribed. Split libxcam into two standalone repos — **`libxcam-core`**
(the `xcore/` library, 2249 indexed units) and **`libxcam-ocl`** (the `modules/ocl/` consumer, 1663
units) — both in one cross-repo `atlas-xrepo.db`. The agent's task runs in `ocl`'s snapshot, which
**excludes** `xcore`; `find_related` spans both. So a helper in `xcore` is **un-greppable from the
agent's work tree** and reachable only through the KB — exactly the asymmetry intra-repo tasks lacked.
Three cross-repo tasks (a feature in `ocl` whose helper lives in `xcore`); MVP run control / optional
/ mandatory-call (the 360-stitch task timed out → N=2):

| arm | grounded-success | adoption |
|---|---|---|
| control (grep only) | 50% | 0/2 |
| optional | 50% | 0/2 |
| **mandatory-call** (forced cross-repo retrieval) | **100%** | 2/2 |

**`mandatory-call − control = +50pp` — the first positive KB contrast in the whole arc** — and it is
**mechanistically airtight** on the one discriminating task. On `xr-ocl-fps-logging` (helper
`XCAM_STATIC_FPS_CALCULATION`, a *non-guessable* macro): control made **0** `find_related` calls,
never found the macro, failed; the **mandatory-call** agent queried `find_related` with *"CL image
handler execute throughput FPS profiling logging frame rate"*, **the tool surfaced the macro from the
*other* repo (`libxcam-core`)**, and the agent wrote `XCAM_STATIC_FPS_CALCULATION(get_name(), …)` into
`cl_image_handler.cpp`. repo_atlas did something **grep and model-knowledge could not** — surface a
non-obvious helper from a sibling repo. That is the core hypothesis, finally demonstrated.

**Honest calibration — this is proof-of-mechanism, not a statistical result:**
- **N=2, one discriminating task.** The second task's helper (`xcam_set_log`) has a *guessable*
  conventional name, so *all* arms produced the call (control/optional by guessing, `find_related=0`)
  — it doesn't discriminate. The third (slerp in the 360-stitch handler) **timed out**.
- **Adoption is still the gate.** `optional` (KB available, no directive) had **0/2 adoption** — agents
  *still* don't reach for the KB unprompted, even when the answer is genuinely out of local reach. The
  win materialised only under **forced** retrieval (`mandatory-call`).
- **Task craft matters:** helpers must be non-guessable (not `xcam_set_log`), and tasks small enough
  not to time out (not the 360-stitch monster).

**The arc resolves.** repo_atlas's value is **real but narrow and gated**: it helps with *non-obvious,
cross-repo* helpers (proven here), is **null intra-repo** (grep dominates, lap 7b), and is **unlocked
only by adoption** (agents won't retrieve unprompted, laps 7/7c). The productive next steps are now
concrete: (1) **scale the cross-repo substrate** — more non-guessable helpers, smaller tasks, N ≥ 20,
ideally a second library/consumer pair — for a statistical result; (2) **solve adoption** — make the
agent retrieve when its local context is insufficient (close the `optional`→`mandatory` gap), since
that is the only thing standing between the proven mechanism and real deployment value.

### Lap 8 — Scaled cross-repo ceiling: the value is real and powered (2026-06-27)

Built what lap 7c prescribed, at scale, and fixed the instruments. **(c)** The ceiling arm now works
cross-repo: `forced-inject` and the offline proxy retrieve across **all** repos (`repos=None`) with a
focused, intent-only `retrieval_query` (authored per task; a guard test forbids it from naming the
answer API), and inject the top-20 (`--inject-k 20`) so the ceiling sees what `find_related` returns.
**(a)** Scaled to **31 cross-repo tasks** — 22 libxcam (`tasks-xrepo`) plus a **second** library/
consumer pair, **gpuimage** (`tasks-xrepo-gpuimage`: android-gpuimage-plus's `cge` library split from
its JNI/custom-filter consumer) — each a non-guessable helper verified 0-hit in the consumer snapshot
and pre-screened reachable via `find_related`. **(b)** Added an insufficiency-gated soft-nudge
`assisted` arm + `find_related` legibility, and a harness fix so a **timed-out arm scores as a failure**
instead of raising and dropping the whole task.

**Result — ceiling (control vs forced-inject), N=15 non-guessable tasks across two codebases, quota-clean:**

| codebase | N | control | forced-inject | ceiling |
|---|---|---|---|---|
| libxcam  | 10 | 0%  | 50%  | **+50pp** |
| gpuimage | 5  | 20% | 100% | **+80pp** |
| **pooled** | **15** | **7%** (1/15) | **67%** (10/15) | **+60pp** |

The no-KB baseline succeeds **once in fifteen** (and that one is a *guessed* cge API); the agent
**shown** the un-greppable cross-repo prior art uses the exact helper in the target file **two-thirds**
of the time. This promotes lap 7c from proof-of-mechanism to a **powered, two-codebase** result:
surfacing genuinely un-greppable cross-repo knowledge produces a large, real lift the agent cannot
otherwise reach.

**Operational finding — the Claude session limit is the real eval budget.** The first attempt ran all
31 tasks × 5 arms (155 runs) with three drivers concurrently; it exhausted the subscription quota
mid-run, so **128/155 agents returned *"you've hit your session limit"* and no diff** — a washed-out
null that is a *quota artifact*, not a verdict (the orchestration subagents draw on the same quota).
The fix: run **sequentially**, sized to ~35 substantive runs per window, and **verify every run did
real work** (transcript turn-counts) before trusting a scorecard. The numbers above are from clean,
quota-validated windows (0 limit-hits, all runs 15–81 assistant turns).

**Deferred (quota-bound):** the **adoption** arms — `optional` (natural), `assisted` (gated nudge),
`mandatory-call` — i.e. *will the agent fetch this ceiling unprompted, or with a light-touch nudge?*
The over-steering half is already checked: on local (in-tree) tasks the `assisted` gate stays silent —
turns **9.5 = control 9.5**, 0 nudges — so the nudge does not over-steer locally-solvable work. The
cross-repo adoption-capture measurement (does `assisted` approach the ceiling without the `mandatory`
tax) needs further quota windows.

### Lap 9 — Adoption measured: solvable (gated nudge + legibility), N=15 two codebases (2026-06-28)

The deferred adoption question, measured. First a harness fix (spec/plan `2026-06-28-adoption-measurement-*`)
so a Claude session-limit hit can never again masquerade as a failure: `_is_session_limit` +
`SessionLimitReached`, raised by `ClaudeRunner._run_agent`, caught by `run_multi_eval`, which stops
cleanly and aggregates only the tasks that completed before the limit. Built via subagent-driven TDD
(3 tasks, per-task spec+quality review + a final integration review; 70 eval tests pass), merged
`990508a`.

Then the measurement: `control` / `optional` / `assisted` (the insufficiency-gated soft nudge) on the
**N=15** non-guessable cross-repo tasks (libxcam 10 + gpuimage 5), `grounded-use`, `TIMEOUT=300
INJECT_K=20`, one driver — run across two quota windows (the harness fix made the resume clean).

| arm | grounded-success | adoption (runs) | vs banked ceiling |
|---|---|---|---|
| control  | **13%** (2/15) | 0/15 | — |
| optional | **40%** (6/15) | 6/15 | (legibility only) |
| **assisted** | **53%** (8/15) | **10/15** | ceiling = `forced-inject` **67%** |

Per codebase: libxcam (N=10) control 10% / optional 30% / assisted 40%; gpuimage (N=5) control 20% /
optional 60% / assisted 80%. `assisted_lift (assisted−control)` = **+40pp**; `captured (optional−control)`
= **+27pp**; `assist_gap (ceiling−assisted)` ≈ **14pp**.

**Adoption is solvable — two levers, both cheap.**
1. **The gated nudge works.** `assisted` at 53% captures ~80% of the ceiling (67%) and beats control by
   +40pp, with the agent actually *calling* `find_related` on **10/15** runs. It does this *without*
   the mandatory "FIRST action MUST be find_related" directive and *without* the adoption tax — lap 8
   showed the same gate stays silent on local tasks (turns 9.5 = control 9.5). The mechanism is
   selective: loud when the answer is out of local reach, silent when it isn't.
2. **Legibility alone helped more than priors predicted.** The `optional` arm — *no* nudge, only the
   lap-8 rewrite of `find_related`'s description/instructions ("call when local search doesn't surface
   the answer; essential for cross-repo") — lifted *natural* adoption from the historical **~0**
   (lap 7 optional 0/10, lap 7c 0/2, with the old terse description) to **6/15** runs / **40%** success.
   A cheap, passive change moved the needle that earlier soft nudges couldn't.

**The harness fix validated itself live.** The first window hit the quota on task 10
(`warp-create-quaternion`, HTTP 429, "resets 6am") and the new guard **stopped cleanly** —
`"session limit reached … stopping after 9 clean tasks; resume the remaining 1"` — yielding a clean
N=9 scorecard (resumed cleanly next window) instead of the lap-8-style contamination (where 128/155
limit-hits scored as false failures).

**Calibration:** N=15, two codebases, one model (Sonnet 4.6); pooled by hand across per-substrate
scorecards. The cross-run ceiling comparison is approximate (run-to-run variance on a stochastic
agent — e.g. control 13% here vs 7% in lap 8). Adoption ≠ guaranteed grounded-use: on the 1 libxcam
remainder task `assisted` retrieved + surfaced the helper yet didn't land the call (a residual
use-it-correctly gap). Scorecards: `/home/vinc/repo-atlas-xrepo/adopt-libxcam{,-rem}.md`,
`/home/vinc/repo-atlas-xrepo2/adopt-gpuimage.md`.

**Decision (the arc's payoff):** adoption is **cheaply solvable**, so the next step is to **productize**
— ship the insufficiency gate + soft nudge as a Claude Code hook/skill, and keep the improved tool
descriptions — rather than build a heavier always-on auto-retrieve. That is a fresh brainstorm.
**Decision (pending gpuimage confirmation):** the gated nudge works → next step is to **productize** it
as a Claude Code hook/skill (a real-deployment mechanism), not to design a heavier auto-retrieve.

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
