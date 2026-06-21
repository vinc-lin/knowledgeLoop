import pytest
from repo_atlas.eval.harness import run_eval
from repo_atlas.eval.tasks import Task
from repo_atlas.eval.runner import RunResult, StubRunner
from repo_atlas.eval.judge import StubJudge


@pytest.mark.asyncio
async def test_run_eval_end_to_end_with_stubs():
    task = Task(id="t1", kind="dev", repo="r1", prompt="p", rubric="x",
                expected_symbols=["cgeImageFilter"], expected_files=["a.h"])
    runner = StubRunner({
        ("t1", "baseline"): RunResult("baseline", ["madeUp"], ["z.cpp"], 11, 200, {}, "", 0),
        ("t1", "treatment"): RunResult("treatment", ["cgeImageFilter"], ["a.h"], 4, 90, {}, "", 2),
    })
    judge = StubJudge({"t1": True})
    real = {"cgeImageFilter"}
    sc = await run_eval([task], runner, judge, lambda s: s in real)
    assert sc.summary["n"] == 1
    p = sc.pairs[0]
    assert p.treatment.hallucination_rate == 0.0
    assert p.baseline.hallucination_rate == 1.0
    assert p.treatment.reuse_recall == 1.0
    assert p.treatment.exploration_cost == 4
    # adoption telemetry must thread through from RunResult -> TaskScore -> scorecard
    assert p.treatment.atlas_calls == 2
    assert sc.summary["adoption_mean"] == 2.0
    assert sc.summary["adoption_runs"] == 1


@pytest.mark.asyncio
async def test_run_eval_skips_a_failing_task():
    class BoomRunner:
        async def run(self, task, *, condition):
            if task.id == "boom":
                raise RuntimeError("agent died")
            return RunResult(condition, [], [], 1, 1, {}, "")

    tasks = [Task(id="ok", kind="dev", repo="r", prompt="p", rubric="x"),
             Task(id="boom", kind="dev", repo="r", prompt="p", rubric="x")]
    sc = await run_eval(tasks, BoomRunner(), StubJudge({"ok": True}), lambda s: True)
    assert sc.summary["n"] == 1                         # "boom" skipped, "ok" kept
    assert sc.pairs[0].task_id == "ok"
