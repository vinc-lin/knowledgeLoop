from __future__ import annotations

from typing import Callable

from repo_atlas.eval.aggregate import TaskScore, make_pair, aggregate
from repo_atlas.eval import metrics


async def _score(task, run, *, judge, exists_fn) -> TaskScore:
    success = await judge.score(task, run)
    return TaskScore(
        task_id=task.id, condition=run.condition, success=success,
        hallucination_rate=metrics.hallucination_rate(run.referenced_symbols, exists_fn),
        reuse_recall=metrics.reuse_recall(
            run.referenced_symbols, run.touched_files,
            expected_symbols=task.expected_symbols, expected_files=task.expected_files),
        exploration_cost=metrics.exploration_cost(run.tool_calls),
        atlas_calls=run.atlas_calls,
        retrieval_surfaced_gold=run.retrieval_surfaced_gold,
        reused_prior_art=(any(pf in run.touched_files for pf in task.prior_art_files)
                          or any(api in run.referenced_symbols for api in task.required_apis)))


async def run_pair(task, runner, judge, exists_fn: Callable[[str], bool]):
    base_run = await runner.run(task, condition="baseline")
    treat_run = await runner.run(task, condition="treatment")
    base = await _score(task, base_run, judge=judge, exists_fn=exists_fn)
    treat = await _score(task, treat_run, judge=judge, exists_fn=exists_fn)
    return make_pair(task.id, base, treat)


async def run_eval(tasks, runner, judge, exists_fn: Callable[[str], bool]):
    """Run every task; a task whose agent run/judge raises is skipped (logged), so one
    bad run doesn't waste a long multi-task eval. Scorecard `n` = completed tasks."""
    pairs = []
    for t in tasks:
        try:
            pairs.append(await run_pair(t, runner, judge, exists_fn))
        except Exception as exc:                       # noqa: BLE001 - resilience boundary
            print(f"[eval] task {t.id} failed, skipping: {type(exc).__name__}: {exc}")
    return aggregate(pairs)


async def run_arms(task, runner, arms, judge, exists_fn: Callable[[str], bool]) -> dict:
    """Run one task across every arm; return {arm -> TaskScore}."""
    out = {}
    for arm in arms:
        run = await runner.run(task, condition=arm)
        out[arm] = await _score(task, run, judge=judge, exists_fn=exists_fn)
    return out


async def run_multi_eval(tasks, runner, arms, judge, exists_fn: Callable[[str], bool]):
    """Multi-arm agentic eval. An ordinary task failure is skipped (logged) so one bad run doesn't
    waste a long eval. A SessionLimitReached STOPS the eval cleanly — the quota is exhausted, so
    every later run would also fail; we aggregate only the tasks that completed before it and report
    where to resume. Returns a MultiScorecard."""
    from repo_atlas.eval.aggregate import aggregate_arms
    from repo_atlas.eval.runner import SessionLimitReached
    per_task = {}
    for t in tasks:
        try:
            per_task[t.id] = await run_arms(t, runner, arms, judge, exists_fn)
        except SessionLimitReached as exc:
            done = len(per_task)
            print(f"[eval] session limit reached on task {t.id} — stopping after {done} clean "
                  f"tasks; resume the remaining {len(tasks) - done} next window: {exc}")
            break
        except Exception as exc:                       # noqa: BLE001 - resilience boundary
            print(f"[eval] task {t.id} failed, skipping: {type(exc).__name__}: {exc}")
    return aggregate_arms(per_task, arms)
