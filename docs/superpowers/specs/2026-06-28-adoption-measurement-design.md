# Adoption Measurement — Session-Limit-Safe Eval

**Status:** Approved (design)
**Date:** 2026-06-28
**Depends on:** lap-8 cross-repo ceiling (merged `6f21e03`) — the `assisted` arm, the
`local_context_insufficient` gate (`repo_atlas/eval/adoption.py`), and the N=15 cross-repo task set
(`tasks-xrepo` ×22 / `tasks-xrepo-gpuimage` ×9; the 15-task ceiling subset is in scratch dirs but is
re-derivable from the non-guessable tasks).

## Context — the problem this solves

Lap 8 proved the **ceiling**: shown the un-greppable cross-repo helper, the agent uses it (+60pp;
control 7% → forced-inject 67%, N=15, two codebases). What is **unmeasured** is **adoption** — will
the agent *fetch* that knowledge unprompted, or with a light-touch nudge? The built `assisted` arm (an
insufficiency-gated soft nudge) passed its over-steering check (silent on local tasks) but its
cross-repo capture was never measured.

The blocker is not the experiment design — it is **measurement reliability under the Claude session
limit**. The first full run (31 tasks × 5 arms, 3 concurrent drivers) exhausted the subscription quota
mid-run; **128/155 agents returned `"You've hit your session limit · resets …"` and no diff.** The
harness scored each of those as a grounded-success **failure (0)**, silently contaminating the
scorecard into a washed-out null. The contamination was only caught post-hoc by reading transcripts.

**A quota-limited run must never masquerade as a result.** This spec adds that correctness guarantee,
then defines the measurement protocol the guarantee unblocks.

We deliberately choose **measure-first**: do not design a stronger adoption mechanism (auto-retrieval
hook) until we know whether the *existing* gated nudge already captures the ceiling.

## Goals

1. **A session-limit hit can never be counted as a task failure.** Detect it, stop the run cleanly,
   and emit a scorecard over only the runs that did real work — plus an explicit resume point.
2. **Measure the adoption arms** (`control` / `optional` / `assisted`, against the banked
   `forced-inject` ceiling) on the N=15 cross-repo set, and produce the decision that selects the next
   step.

## Non-goals (YAGNI — explicitly out of scope)

- **No checkpoint/resume.** Resume is manual: re-run the remaining tasks in the next window. (Chosen
  explicitly: "detect-limit now, resume later.")
- **No per-run `invalid` flag threaded through `RunResult`/`TaskScore`/`aggregate`.** Once the limit is
  hit, every subsequent run also fails, so stop-clean is correct and simpler than mark-and-continue.
- **No pre-flight quota probe** (the probe itself burns quota).
- **No new adoption *mechanism*.** This spec measures the existing one; a stronger mechanism is a
  separate brainstorm, gated on the result here.

## Design

### Part 1 — Session-limit detection (the buildable artifact)

All changes are in the existing eval harness; the contract of `ClaudeRunner`/`run_multi_eval` is
otherwise unchanged.

**1a. `_is_session_limit(text: str) -> bool`** — new pure function in `repo_atlas/eval/runner.py`.
Returns `True` iff `text` contains a known Claude quota phrase, matched case-insensitively. Phrase set
(substring match, OR-combined):
- `"hit your session limit"`
- `"session limit"`
- `"usage limit"`
- `"limit · resets"` and the ASCII fallback `"limit reached"`

It must return `False` for normal agent output and for the JSON result envelope of a successful run.
Pure and directly unit-testable.

**1b. `SessionLimitReached(Exception)`** — new exception class in `runner.py`, distinct from ordinary
run failures and from `subprocess.TimeoutExpired`.

**1c. `ClaudeRunner._run_agent`** (`runner.py:266`) — after the subprocess returns, check the raw
output **before** JSON parsing: if `_is_session_limit(proc.stdout or "")` or
`_is_session_limit(proc.stderr or "")`, raise `SessionLimitReached`. The existing `TimeoutExpired →
return {}` path is unchanged (a timeout is a real per-arm failure; a quota hit is not). The normal
path (`json.loads` of a `{`-prefixed stdout) is unchanged.

  Rationale for detecting on the raw string, not the parsed JSON: on a quota hit the CLI may not emit a
  well-formed result envelope (observed: a `{"type":"last-prompt", …}` record with null fields), so the
  reliable signal is the limit phrase in stdout/stderr.

**1d. `harness.run_multi_eval`** (`repo_atlas/eval/harness.py:53`) — the per-task loop catches
`SessionLimitReached` **specially** and separately from the existing `except Exception` (which still
skips a single bad task and continues):
- on `SessionLimitReached`: `print("[eval] session limit reached — stopping after {N} clean tasks; "
  "resume the remaining {M} next window")`, **`break`** the loop, and fall through to
  `aggregate_arms(per_task, arms)` over the tasks completed *before* the limit. The task during which
  the limit fired is **not** added to `per_task` (it is dropped, not half-counted).
- ordinary `Exception` per task: unchanged (log + skip + continue).

  Note: because `run_arms` runs a task's arms sequentially and re-raises `SessionLimitReached`, a limit
  that fires on arm *k* of a task discards that whole task's partial arm set — correct, since the arms
  already run for it would be an incomplete row.

The legacy pair harness (`run_eval` / `run_pair`) is **not** modified — the adoption measurement uses
the multi-arm path only.

### Part 2 — The measurement protocol (runbook)

Run on the **N=15 cross-repo ceiling subset** (the non-guessable tasks: 10 libxcam + 5 gpuimage used
for the lap-8 ceiling), in quota-sized sequential batches (one window each), `SCORER=grounded-use
TIMEOUT=300 INJECT_K=20`, **one driver at a time** (never concurrent — concurrency splits the quota).

- **Arms, in priority order** (run as quota allows, batching across windows):
  1. `control`, `optional`, `assisted` — the core adoption question (does the gated nudge beat natural
     adoption?). ~45 runs ≈ ~1.5 windows.
  2. `mandatory-call` — the forced upper bound, if quota remains.
  - `forced-inject` (the ceiling, 67%) is **reused from the banked lap-8 ceiling run** — no need to
    re-run it.
- **After each batch**, validate it stayed clean: 0 `"session limit"` transcripts and all runs
  substantive (transcript assistant-turn counts), exactly as done for the lap-8 ceiling. With Part 1
  in place, a mid-batch limit now self-reports and stops cleanly instead of contaminating.
- **Read the contrasts** (`aggregate.py`):
  - `captured (optional − control)` — expected ≈ 0 (confirms the wall).
  - **`assisted_lift (assisted − control)`** — the headline.
  - `assist_gap (forced − assisted)` — ceiling left on the table.
  - `adoption_runs[assisted]` — did the gate fire **and** the agent then call `find_related`.
  - `exploration[assisted]` vs `control` — re-confirm no turn-ballooning on the (cross-repo) set.

**Decision tree (the deliverable the measurement feeds):**
- `assisted` ≈ ceiling (~67%) → **the gated nudge works** → adoption is cheaply solved → next step:
  productize the gate+nudge as a Claude Code hook/skill (separate brainstorm).
- `assisted` ≈ control (~7%) → nudge insufficient → next step: design the **gated auto-retrieve**
  hybrid (retrieve *for* the agent when the gate fires) — separate brainstorm.
- in between → tune the gate (`k`, an all-top-K-absent variant) and the `NUDGE` wording, then
  re-measure.

## Components & interfaces

| Unit | File | Responsibility | Depends on |
|---|---|---|---|
| `_is_session_limit(text)` | `repo_atlas/eval/runner.py` | classify CLI output as a quota hit | — (pure) |
| `SessionLimitReached` | `repo_atlas/eval/runner.py` | signal "abort the whole run" | — |
| `_run_agent` (modified) | `repo_atlas/eval/runner.py` | raise on quota hit; `{}` on timeout; JSON otherwise | `_is_session_limit` |
| `run_multi_eval` (modified) | `repo_atlas/eval/harness.py` | stop clean on `SessionLimitReached`, aggregate prior tasks | `SessionLimitReached` |

## Testing (TDD, judge-free, no `claude` needed)

1. `_is_session_limit`: `True` for `"You've hit your session limit · resets 8pm (Asia/Shanghai)"` and
   `"Claude usage limit reached"`; `False` for normal prose and for a successful result envelope
   string `'{"result":"done","is_error":false}'`.
2. `_run_agent` raises `SessionLimitReached` when the command echoes a limit message
   (`["printf", "You have hit your session limit; resets 8pm"]`); still returns `{}` on a `sleep`
   timeout; still parses JSON for a normal `printf '{"session_id":"x"}'`.
3. `run_multi_eval`: a `StubRunner` that raises `SessionLimitReached` on a chosen (task, arm) →
   the returned `MultiScorecard` contains only the tasks completed *before* it, excludes the partial
   task, and the others are unaffected (a separate stub task that raises a plain `Exception` is still
   skipped-and-continued).

Run new/changed unit tests **per-file** with the worktree venv (pytest 9.0.3); `git add -f` new test
files (the `tests/` dir is gitignored).

## Verification (end-to-end)

1. Unit tests green.
2. A 2-task smoke (`control,assisted`) on the cross-repo set confirms the harness runs and the gate
   fires (transcript shows `find_related` calls in `assisted`, none in `control`).
3. The measurement batches run clean (0 limit transcripts), or — if a limit is hit — the run **stops
   cleanly** with the "resume the remaining M" log and a scorecard over only the clean tasks (this is
   itself the acceptance test for Part 1).
4. Record the result + the decision (which branch of the tree) in `docs/repo-atlas-evaluation.md`
   (lap 9) and memory.

## Risks

- **Phrase drift:** Claude could reword the limit message. Mitigation: substring set is broad
  (`"session limit"`, `"usage limit"`, `"limit reached"`); add phrases if a new wording appears. The
  transcript-validation step (V-2/V-3) is the backstop.
- **False positive:** a *task* prompt or agent output legitimately containing "usage limit" → a run
  wrongly aborted. Low risk for these cross-repo coding tasks; the detector reads the CLI result
  output, and a wrongly-aborted run is a clean stop (no bad data), not a corrupted score.
- **Adoption arms still need ~1.5–3 quota windows** even when clean — inherent to the agentic eval;
  out of scope to remove here (that is the deferred checkpoint/resume).
