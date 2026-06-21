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
