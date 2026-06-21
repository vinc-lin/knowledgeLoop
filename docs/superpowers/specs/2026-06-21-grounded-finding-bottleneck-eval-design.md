# Grounding-Based Finding-Bottleneck Eval — Design Spec

**Date:** 2026-06-21
**Status:** Approved design, pending implementation plan
**Related:** `docs/repo-atlas-evaluation.md` (the consolidated methodology + results), the
close-the-loop spec/plan (`2026-06-21-close-the-loop-agentic-eval-*`), memory
`repo-atlas-eval-null-result`.

## Why

The close-the-loop run answered "does retrieval surface the right prior art?" — **yes, 90%**, and
the agent then reads it and follows the pattern. But it could **not** answer "does that improve
outcomes," for one decisive reason: the LLM judge (`deepseek-chat`) **cannot compile or run**
C/C++/OpenCL, so it guesses whether a complete-looking solution is correct and likely over-rejects.
Inspection confirmed the failing agents were *not* context-starved — they found the API, read the
full prior-art, and produced complete, wired solutions, yet were scored `False`. **The judge is the
binding constraint, and the consume side already works.**

So the highest-leverage optimization is **a reliable, judge-free way to measure the thing
repo_atlas is actually responsible for**: making the agent *ground its solution in the correct
existing API* instead of reinventing or hallucinating one. This eval does that. Improving the
consume side (the user's "2") is the **next cycle, gated on this eval** — we won't build a consume
change the data doesn't yet justify (YAGNI), and we can't measure one until success is reliable.

## The claim, reframed (important)

This eval measures a **narrower, defensible** claim than "repo_atlas makes the agent solve more
tasks" (which needs executable verification we don't have):

> **repo_atlas makes the agent ground its solution in the correct *real* existing API — instead of
> reinventing it or calling a fabricated one — on tasks where finding that API is the bottleneck.**

That is exactly the tool's job (find the right prior art + ground), and it is mechanically
checkable without a compiler. We will state results in those terms, not as full task-correctness.

## Decisions (locked during brainstorming)

- **Grounding-based success**, not an LLM judge.
- **Finding-bottleneck tasks**: the correct solution must call a specific *non-obvious existing*
  API; the prompt states the goal without naming it, so a baseline agent tends to miss/hallucinate.
- **All-required semantics** (every `required_api` must be referenced), with usually **1 API/task**
  to keep it clean.
- **Decompose**: spec the eval now; consume-side improvements are the gated next cycle.

## Non-goals

- No executable verification, no reference-diff mining, no stronger LLM judge (the three rejected
  alternatives).
- No consume-side product change in this spec.
- No claim of full task-correctness — only "grounded in the right real API / didn't fabricate."

## Architecture (reuse, don't rebuild)

Reuse the agentic harness (`repo_atlas/eval/`): `ClaudeRunner` already captures the diff,
transcript, adoption (`atlas_calls`), and `retrieval_surfaced_gold`; `run_eval`/`aggregate`/`report`
already pair baseline vs treatment. Changes:

1. **`Task.required_apis: list`** — the real symbol(s) a correct solution must call (grep + store
   verified to exist; non-obvious). The mechanism-scoring gold for this eval.
2. **`GroundingScorer`** — a drop-in replacement for `GatewayJudge` (same `async def score(task,
   run) -> bool` interface, so `harness._score` is unchanged). Returns **grounded-success**.
3. **Trustworthy hallucination metric** — a `grounded_hallucination(...)` that fixes the known
   defects (exclude diff-*defined* symbols, stoplist SDK/language builtins, source-grep fallback
   for real-but-unindexed symbols) so the secondary signal is interpretable.
4. **Report** — grounded-success (baseline→treatment) + hallucination delta + the existing
   mechanism trace (surfaced/adoption); the causal classifier's "reused" becomes **"grounded"**
   (referenced the required API).

### `GroundingScorer` (replaces the judge)

```python
class GroundingScorer:
    def __init__(self, store): self._store = store
    async def score(self, task, run) -> bool:
        # grounded-success = every required_api is referenced in the diff AND exists in the store
        if not task.required_apis:
            return False
        referenced = set(run.referenced_symbols)          # from extract_refs(diff), already tightened
        exists = self._store.symbols_exist(task.repo, list(task.required_apis))
        return all(api in referenced and exists.get(api, False) for api in task.required_apis)
```

- `run.referenced_symbols` is already produced by `ClaudeRunner` via `extract_refs(diff)`.
- The `symbols_exist` check is a guard — `required_apis` are curated to exist, so a `False` there
  signals a bad task (caught by the verifier, below), not an agent miss.
- Matching is on the bare callable name (what the agent writes, e.g. `cgeColorOp` from
  `cgeColorOp(...)`); `required_apis` are curated as bare names.

### Metrics

- **Primary — grounded-success** (per condition): did the agent reference the required real
  API(s)? The A/B headline is `grounded_success_treatment − grounded_success_baseline`.
- **Secondary — hallucination** (per condition): fraction of the diff's *external* referenced
  symbols (excluding diff-defined names and a builtin stoplist) that exist in neither the store nor
  the repo source. Lower is better; the treatment should reduce it if grounding helps.
- **Mechanism (carried over)** — `surfaced` (find_related returned the required API's file/symbol),
  adoption; the causal category uses `grounded` in place of file-level `reused`.

## Task design — finding-bottleneck

**Criteria for each task (the hard curation; concrete set in the plan):**
- The natural correct solution must call a **specific existing API** (`required_apis`) — a real
  symbol, grep+store verified.
- That API is **non-obvious**: a deep/oddly-named util a baseline agent is unlikely to discover by
  shallow exploration, so it tends to **reinvent the logic inline or call a fabricated name**.
- The **prompt states the goal, not the API** ("do X"), so *finding* it is the challenge.
- **Baseline-miss check** (difficulty guard, reported): the eval is only meaningful if the baseline
  agent frequently *fails to ground* (reinvents/hallucinates). If baseline grounded-success is
  already high, the task wasn't finding-bottleneck — flag it.

**Illustrative templates** (finalized + grep-verified in the plan):
- "Convert the decoded frame to grayscale using the library's existing color utility" →
  `required_apis = [<the real obscure cge*/cl* color op>]` (baseline tends to write `toGray()`).
- "Clamp the filter parameter to the engine's supported range using the existing validation helper"
  → `required_apis = [<the real clamp/validate symbol>]`.
- "Release the OpenCL buffer using the project's existing wrapper, not raw clRelease*" →
  `required_apis = [<the real SmartPtr/release wrapper>]`.

A **gold-API verifier** (extending the existing `verify_offline_gold.py` pattern) asserts every
`required_api` exists in its repo's store before a run.

## Conditions, cost

- baseline vs treatment (improved retrieval + forced directive) — identical harness to close-the-
  loop; only the scorer changes. ~10–12 tasks × 2 ≈ 20–24 sessions, background, per-task resilience.
- No judge model call (grounding is local) — cheaper and fully deterministic given a fixed diff.

## What it proves / how we'll read it

- **treatment grounded-success > baseline** (and/or lower hallucination): a reliable, judge-free
  demonstration that repo_atlas makes the agent use the right real API more / fabricate less — the
  tool's actual value, on its actual job.
- **no difference**: an honest, *reliable* negative (not judge noise) — meaning even when finding is
  the bottleneck, surfacing the API didn't change whether the agent grounded in it (→ the lever is
  then consume-side integration, which becomes the justified next cycle).
- The **baseline-miss check** keeps us honest: a +0 with low baseline-miss means the tasks weren't
  actually finding-bottleneck.

## Risks & open questions

- **grounded-success ≠ correctness.** Using the right API is necessary, not sufficient, for a
  correct solution. We state the claim narrowly (Part "claim, reframed") and never inflate it.
- **Curation is the crux.** "Non-obvious real API a baseline will miss" is a judgment call; the
  baseline-miss check is the empirical guard. Some candidate tasks will turn out not to be
  finding-bottleneck — expect to discard/replace.
- **extract_refs matching** — the required API must surface as a symbol-ref token in the diff's
  added lines. Call sites and identifiers are caught; if a task's API is only used in an unusual
  syntax, the reference may be missed. Keep `required_apis` to plainly-called functions/classes.
- **Hallucination metric** remains the harder secondary; grounded-success is the trustworthy
  primary. Don't gate conclusions on hallucination alone.
```
