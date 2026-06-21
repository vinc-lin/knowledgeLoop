# Close-the-Loop Mechanism-Resolved Agentic Eval — Design Spec

**Date:** 2026-06-21
**Status:** Approved design, pending implementation plan
**Related:** the agentic A/B eval (`repo_atlas/eval/`), the offline eval (`repo_atlas/eval/offline/`),
memory `repo-atlas-eval-null-result`, the retrieval-rebalance + multi-gold specs.

## Why

The offline eval proved retrieval/grounding *quality* improved (Success@20 0.20 → 0.60 → 0.80) —
but that is a **precondition/proxy**, not the goal. We have not shown that better retrieval, *when
used*, changes a real coding agent's outcomes. The original agentic A/B (N=6) couldn't: its tasks
were too **local** (solvable from in-repo context, so retrieval barely mattered), and a binary
success rate over N=6 is statistically powerless (consecutive runs gave opposite verdicts).

This eval **closes the loop**. Over a modest set of *harder intra-repo prior-art* tasks, it traces
the causal chain **per task** rather than trusting a noisy aggregate:

```
find_related surfaced the gold prior-art?  →  agent reused it?  →  outcome beat baseline?
   (scored on the agent's ACTUAL query)        (diff overlap)       (blinded judge)
```

At small N a per-task causal trace is far more informative than a binary rate — it shows *why*,
not just *whether*, and it resists the ground-truth circularity of the offline eval (retrieval is
scored on the agent's live queries, not curated ones).

## Decisions (locked during brainstorming)

- **Mechanism-resolved, modest N (~10-12 tasks, ~20-24 sessions).**
- **Harder intra-repo prior-art tasks**, fresh (not the existing 6 agentic tasks, not the offline
  curated cases) — so retrieval quality is the bottleneck and there's no teaching-to-the-test.
- **baseline vs improved-treatment** only (no third "old-retrieval" arm; the offline eval already
  proved retrieval improved — this tests whether that helps the *agent*).

## Non-goals

- No third (old-retrieval) arm; no re-running the offline eval.
- No new judge — reuse the existing blinded `GatewayJudge`.
- Cross-repo *transfer* tasks — deferred (the brainstorm chose intra-repo).
- Not a replacement for the offline eval — this is the outcome-level validation on top of it.

## Architecture

Reuse the existing agentic harness (`repo_atlas/eval/`): `ClaudeRunner` (baseline/treatment with
the forced directive + `--output-format json` session capture + adoption telemetry),
`GatewayJudge`, `run_eval`, `aggregate`, `report`. Three extensions:

1. **`Task` gains a `prior_art_files` field** — the canonical file(s) holding the pattern the
   agent *should* find and reuse, grep-verified. This is the mechanism-scoring gold, distinct from
   the (noisy) `expected_symbols`/`expected_files` reuse keys.
2. **`RunResult` gains `find_related_queries: list` + `retrieval_surfaced_gold: bool`** — extracted
   from the treatment session transcript.
3. **A causal classifier + a mechanism report** — per task, combine
   (baseline success, treatment success, surfaced, reused) into a category; aggregate the counts.

### Mechanism capture (`repo_atlas/eval/runner.py`)

Add, alongside the existing `_atlas_calls_for_session`:

```python
def _find_related_files_for_session(session_id: str) -> tuple[list, list]:
    """From a session transcript: (find_related query strings, files returned by find_related).
    Walks each mcp__repo-atlas__find_related tool_use (for the query) and its tool_result
    (collecting every 'file' value anywhere in the returned {docs,symbols} buckets)."""
```

Implementation notes:
- Reuse the transcript locator (`glob ~/.claude/projects/*/{session_id}.jsonl`).
- For `tool_use` blocks named `mcp__repo-atlas__find_related`, record `input.query`.
- For the matching `tool_result` (by `tool_use_id`), recursively collect all `"file"` string
  values (robust to the `{result:{docs:[...],symbols:[...]}}` envelope and to serialization as a
  JSON string vs structured content).

In `ClaudeRunner.run`, for the **treatment** condition only, after obtaining `session_id`:
```python
queries, fr_files = _find_related_files_for_session(session_id)
surfaced = any(pf in set(fr_files) for pf in task.prior_art_files)
```
Set `RunResult.find_related_queries = queries`, `RunResult.retrieval_surfaced_gold = surfaced`.
(Baseline runs leave both at their defaults — no tools.)

### Causal classifier (`repo_atlas/eval/causal.py` — new)

```python
def classify(task, base_run, treat_run, *, base_success, treat_success) -> str
```
Inputs per task: `b` (baseline success), `t` (treatment success), `s` (treat surfaced gold),
`r` (treat *reused* prior art = any `prior_art_files` ∈ `treat_run.touched_files`),
`a` (adoption = `treat_run.atlas_calls > 0`). Categories (first match wins):

| category | condition | meaning |
|---|---|---|
| `causal-win` | `t and not b and s and r` | solved where baseline failed; retrieval surfaced the prior art and the agent reused it — the gold-standard evidence |
| `win-unattributed` | `t and not b` | treatment won but not clearly via retrieval (possible variance) |
| `regression` | `b and not t` | treatment did worse |
| `surfaced-ignored` | `s and not r` | retrieval gave the prior art; agent didn't reuse it — an *adoption/integration* gap, not a retrieval gap |
| `retrieval-miss` | `a and not s` | agent called find_related but it didn't surface the gold — a *retrieval* gap |
| `no-effect` | otherwise | tool didn't change the outcome |

The **headline is the `causal-win` count** plus the category histogram — that's the close-the-loop
evidence. `surfaced-ignored` vs `retrieval-miss` cleanly attributes any non-win to adoption vs
retrieval.

### Report

Extend the agentic scorecard with a **Mechanism** section: the per-task category table
(`task | b→t | surfaced | reused | category`) and the aggregate category histogram, alongside the
existing success / adoption / exploration deltas.

## Task set (~10-12 harder intra-repo prior-art)

**Criteria for each task** (the design's hard part; full set enumerated in the plan):
- In a large / hard-to-navigate repo (especially **android-gpuimage-plus**, 31K symbols; also
  **libxcam**) where the right pattern is *buried* under many similar siblings.
- The solution requires following a **specific existing pattern** that naive grep/exploration
  would struggle to find (non-obvious name, deep path), so a baseline agent plausibly follows the
  wrong pattern, hallucinates, or burns many turns — while `find_related` points treatment at it.
- `prior_art_files` = the canonical file(s) holding that pattern, **grep-verified to exist**.
- **Fresh**: not the 6 existing agentic tasks, not the 15 offline curated cases.

**Difficulty self-check (built into the report):** baseline success rate is itself a task-quality
signal — if baseline solves most tasks easily, the set wasn't hard enough and there's no headroom
for retrieval to help. Target baseline success ≈ 30-60% (real headroom).

**Illustrative templates** (concrete, grep-verified tasks finalized in the plan):
- gpuimage: "Add a CGE native filter that applies *<effect>*, following the existing
  *<specific spatial/convolution filter>* implementation" — `prior_art_files` = that filter's file.
- gpuimage: "Expose a new native method *<name>* callable from Java, registered the same way as the
  existing native methods" — `prior_art_files` = `library/src/main/jni/interface/cgeNativeLibrary.cpp`.
- libxcam: "Add an OpenCL image handler that *<op>*, following the existing
  *<specific cl_*_handler>*" — `prior_art_files` = that handler's `.h/.cpp`.

## Conditions, metrics, cost

- **Conditions:** baseline (no tools) · treatment (improved retrieval + forced directive). Adoption
  should be ≈100% in treatment (directive forces it) — confirmed by telemetry.
- **Primary:** `causal-win` count; treatment-vs-baseline success delta.
- **Mechanism:** surfaced rate, reused rate, `surfaced-ignored` count, `retrieval-miss` count.
- **Secondary:** exploration (num_turns) delta; adoption rate.
- **Cost:** ~10-12 tasks × 2 conditions = ~20-24 `claude` sessions; gpuimage sessions slow (115MB
  archive). ~1.5-2.5h, run in background. The harness already skips a task whose run/judge raises
  (per-task resilience), which also absorbs the transient socket flakiness.

## Risks & open questions

- **Small N persists.** Mitigated, not eliminated, by the per-task causal trace — a single
  `causal-win` with surfaced+reused+outcome is real evidence; the aggregate is interpreted as a
  histogram of *mechanisms*, not a powered rate.
- **"Reused" detection is file-level** (`prior_art_files ∈ touched_files`) — robust, but misses an
  agent that *read* the prior art and internalized the pattern without editing that file. We
  therefore also report `surfaced` independently, and treat `surfaced-ignored` as "no file-level
  reuse," not "definitely ignored." (Symbol-level reuse via `extract_refs` is too noisy to gate on.)
- **Judge reliability** on harder tasks (unrunnable C/C++). The blinded `GatewayJudge` stays;
  treat single-judge verdicts as noisy and lean on the *mechanism* categories for interpretation.
- **Task-difficulty subjectivity.** The baseline-success self-check (target 30-60%) guards against
  tasks that are too easy (no headroom) or impossible (no signal); report it prominently.
- **Transcript-format drift.** `_find_related_files_for_session` must be defensive (tool_result
  serialized as JSON string vs structured content); unit-test both shapes with fixtures.
```
