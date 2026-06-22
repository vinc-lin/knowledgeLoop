# Outcome-Driven Flywheel — Design Spec

**Date:** 2026-06-22
**Status:** Approved (brainstorm) → ready for implementation plan
**Component:** `repo_atlas/eval/`

## Goal

Close the two-tier evaluation flywheel so that optimizations to `repo_atlas` retrieval are
driven by — and validated against — **real agent outcomes**, not a proxy alone. Concretely:
add the missing agentic-eval arms, compute an explicit **proxy↔outcome correlation**, and
harden the two metric bugs that would otherwise make the outcome signal untrustworthy.

This directly answers the still-open question from lap 6b: *does the symbol-precise retrieval
win actually change what agents do?*

## Background & motivation

The eval pyramid has two tiers, both already physically built:

- **Inner loop (cheap, deterministic):** the offline proxy in `repo_atlas/eval/offline/`.
  `run_retrieval` scores `success@k` / `recall@k` / `ndcg@k` / `mrr` / **`sym_success@k`**
  against the production retrieval path (`find_related_units`). `sym_success@k` is the lap-6b
  instrument (is the required API in the symbol-retrieval top-K). Sub-second, judge-free.
- **Outer loop (expensive, real):** the agentic harness in `repo_atlas/eval/`. `ClaudeRunner`
  drives `claude -p` headless in an isolated git snapshot; `GroundingScorer` is judge-free
  (the diff must reference every `required_api`); `causal.classify` assigns a per-task category;
  adoption telemetry (`atlas_calls`, `find_related_queries`, `retrieval_surfaced_gold`) is wired.

**What is missing is the wiring that makes them a flywheel:**

1. The agentic harness has only **two** conditions — `baseline` and `treatment`. `treatment`
   prepends a **mandatory** STEER directive ("your FIRST action MUST be `find_related`… then
   `verify_grounding`"). It already *gave up* on measuring adoption: the harness comment records
   that agents never called the tools when merely available, and ignored a soft system-prompt
   nudge, so the directive was made mandatory. Today's A/B therefore answers only "does the
   knowledge help **when forced to be used**."
2. **Nobody has measured proxy↔outcome correlation.** The offline proxy and the agentic eval
   have never been run on the same task set and joined per-task. So "optimize the proxy" (what
   lap 6b did) is currently an act of faith.
3. **Two metric bugs bias the outcome signal** (flagged in the null-result post-mortem):
   extractor noise can register false grounded-misses; the existence oracle under-indexes and
   can inflate the hallucination rate.

### Key reframing (why the arms matter on *these* tasks)

The mandatory directive exists because agents don't retrieve unprompted on *locally-solvable*
tasks. But the grounding task set is deliberately **finding-bottleneck**: the `required_api` is
non-obvious and hand-rolling is the easy wrong path. On those tasks an **optional** arm (tools
available, no directive) is a genuine natural-adoption measurement, not a foregone null.

## Architecture

A two-tier loop:

```
inner loop (every candidate change, sub-second):
    offline proxy  ──►  sym_success@k / required-API rank      [optimize here]

outer loop (milestones, expensive):
    3-arm agentic eval  ──►  per-arm grounded-success
                        ──►  proxy↔outcome correlation          [validate the proxy]
                        ──►  arm contrasts (ceiling / capture / adoption tax)
```

The inner loop is what you iterate on; the outer loop periodically confirms the inner-loop
metric still predicts real agent behavior and tells you *which* lever the next lap should pull.

## The arms

Generalize `RunResult.condition` and `ClaudeRunner` from the `baseline|treatment` pair to an
arm set. Each arm is a `(prompt-prefix, mcp-wiring)` pairing; the snapshot/run/diff machinery
in `ClaudeRunner.run` is unchanged.

| Arm | Prompt | MCP wired? | Answers |
|---|---|---|---|
| `control` | bare task | no | local-only baseline (= existing `baseline`) |
| `optional` | bare task | yes, **no directive** | natural adoption rate on finding-bottleneck tasks |
| `forced-inject` | task + **pre-pasted retrieval result** | no | does the knowledge help, adoption aside |
| `mandatory-call` | task + STEER directive | yes | helps when forced to *call* (= existing `treatment`) |

`control` and `mandatory-call` are the existing two conditions, renamed/retained. `optional`
and `forced-inject` are new. `mandatory-call` is retained as an optional 4th arm (it is free —
it already exists); a run may select any subset of arms.

### Forced-injection mechanism

Before the agent runs, the harness calls the **production** retrieval path
(`repo_atlas.retrieve.find_related_units`, the same function the MCP `find_related` tool wraps)
for the task prompt, formats the top-K units, and prepends them to the prompt under a
`Relevant prior art in this codebase:` header. Each formatted unit shows file, symbol, and the
enriched doc-comment+signature snippet (the lap-6b symbol text). No tool call, no adoption
variable — the prior art is simply present in the context.

Because injection reuses `find_related_units`, the *injected* knowledge is byte-identical to
what the `optional`/`mandatory-call` arms would retrieve. That equality is what makes the
cross-arm comparison clean: the arms differ only in *how the knowledge reaches the agent*, not
in *what* knowledge it is.

## The correlation — headline deliverable

Run the offline proxy and the agentic eval on the **same** task set and join per task:

- **proxy signal:** is the task's `required_api` in the retrieval top-K (`sym_success@k`).
- **outcome signal:** per-arm grounded-success (`GroundingScorer`), plus `retrieval_surfaced_gold`
  and the `causal.classify` category.

Compute, per arm, **does proxy-success predict outcome-success** — i.e. among tasks where the
proxy surfaces the API, the grounded-success rate vs. tasks where it does not. With N≈10 this is
**directional, not significant**; the report states that plainly and the per-task causal
categories carry the explanatory weight.

### Arm contrasts (decompose the loop's failure modes)

- `forced-inject − control` = the **ceiling** value of the knowledge (best case: it's in front
  of the agent).
- `optional − control` = what the loop **actually captures** today (agent must choose to retrieve).
- `forced-inject − optional` = the **adoption tax** (value lost because agents don't retrieve).

The size of the adoption tax tells the next lap where to invest: close `forced−control` by
improving retrieval quality, or close `optional−forced` by improving adoption.

## Metric trustworthiness fixes

Only the two fixes that bias the **headline** are in scope.

1. **Gold-anchored extraction** (`repo_atlas/eval/extract.py`). `extract_refs`'s `_is_symbol_ref`
   heuristic drops a lowercase API token not followed by `(`, so `GroundingScorer` can register a
   false miss. Fix: in addition to the heuristic sweep, scan added diff lines for the task's exact
   `required_apis` / `expected_symbols` tokens and include any found. Grounded-success stays
   **diff-anchored** (the diff is the outcome); it just stops losing real hits to extractor noise.
2. **Authoritative oracle** (`repo_atlas/eval/oracle.py`). `store_exists_fn` is backed only by the
   atlas index, so an under-indexed-but-real symbol inflates `hallucination_rate`. Fix: before
   declaring a symbol non-existent, fall back to the CBM graph / source grep (the same machinery
   the gold-API verifier already uses at curation time).

## Reporting

Extend the agentic scorecard/report to show, per arm: grounded-success rate, adoption rate
(`atlas_calls > 0`, meaningful for `optional`), `surfaced-but-ignored` count, and the
`causal.classify` histogram. Add a top-line block with the three arm contrasts and the
proxy↔outcome correlation, with an explicit `N=<n>, directional only` caveat.

## Scope

**In (one coherent spec):**
- Generalize `condition` to the arm set; add `forced-inject` + `optional`; retain `control`
  (`baseline`) and `mandatory-call` (`treatment`).
- Forced-injection via `find_related_units`.
- Proxy↔outcome correlation join + arm-contrast report.
- Gold-anchored extraction + authoritative oracle.

**Deferred (each its own spec):**
- Adoption-**driving** levers (tool descriptions, skill nudges, naming) — **measure the optional
  arm first**, build only if adoption is the proven bottleneck.
- Transcript-aware reuse refinement (telemetry: distinguish "surfaced-but-ignored" from
  "extractor missed it") — grounded-success is diff-anchored and sufficient for the headline.
- Expanding N beyond ~10 / new tasks — the report states the power caveat; growing the set is
  separate work.

**Out:**
- Functional / test-based scoring (compile-or-pass-tests). Too expensive and flaky on the C/C++
  NDK corpora; grounding-based judge-free scoring is the deliberate choice.

## Testing

TDD throughout (`superpowers:test-driven-development`).

- **Unit:** extend the existing `StubRunner` / `StubRetriever` with canned per-arm `RunResult`s;
  assert per-arm grounded-success, the correlation join, and the three arm contrasts. Test
  forced-injection formatting against a `StubRetriever`. Test gold-anchored extraction on fixture
  diffs (a lowercase non-call API token that the old heuristic dropped). Test the oracle fallback
  (a real-but-unindexed symbol resolves to exists=true).
- **Integration:** the real `claude -p` 3-arm run is integration-only (needs the `claude` CLI and
  a built index); run at milestones, not in CI — consistent with the existing `ClaudeRunner` being
  integration-only.

## Risks & open questions

- **N≈10 is small.** The correlation and arm contrasts are directional. Mitigation: lead with
  per-task causal categories; state the caveat in the report; growing N is a deferred follow-up.
- **The optional arm may still read ~0 adoption** even on finding-bottleneck tasks. That is itself
  a real, publishable finding (the adoption tax is ~100%) and motivates the deferred
  adoption-levers spec — not a failure of this spec.
- **Forced-inject prompt budget.** Injecting top-K enriched units enlarges the prompt; cap K and
  the per-unit snippet length (reuse the lap-6b `max_chars` discipline) so the injected context
  stays bounded.
