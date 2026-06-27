import pytest
from repo_atlas.eval.harness import run_eval
from repo_atlas.eval.tasks import Task
from repo_atlas.eval.runner import RunResult, StubRunner, SessionLimitReached
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


@pytest.mark.asyncio
async def test_score_credits_required_api_reference_as_reused():
    from repo_atlas.eval.harness import _score
    from repo_atlas.eval.tasks import Task
    from repo_atlas.eval.runner import RunResult
    from repo_atlas.eval.grounding_scorer import GroundingScorer
    task = Task(id="t", kind="dev", repo="r", prompt="p", rubric="x", required_apis=["cgeFoo"])
    run = RunResult("treatment", referenced_symbols=["cgeFoo"], touched_files=[])
    score = await _score(task, run, judge=GroundingScorer(), exists_fn=lambda s: True)
    assert score.success is True            # grounded
    assert score.reused_prior_art is True   # referencing the required api counts as reuse/grounded


@pytest.mark.asyncio
async def test_run_multi_eval_per_arm_with_stubs():
    from repo_atlas.eval.harness import run_multi_eval
    from repo_atlas.eval.grounding_scorer import GroundingScorer
    task = Task(id="t1", kind="dev", repo="r1", prompt="p", rubric="x", required_apis=["cgeFoo"])
    runner = StubRunner({
        ("t1", "control"): RunResult("control", [], [], 5, 50, {}, "", 0),
        ("t1", "optional"): RunResult("optional", ["cgeFoo"], [], 4, 60, {}, "", 1),
        ("t1", "forced-inject"): RunResult("forced-inject", ["cgeFoo"], [], 3, 70, {}, "", 0),
    })
    arms = ["control", "optional", "forced-inject"]
    sc = await run_multi_eval([task], runner, arms, GroundingScorer(), lambda s: True)
    assert sc.summary["n"] == 1
    assert sc.summary["success"]["control"] == 0.0           # no required api in diff
    assert sc.summary["success"]["optional"] == 1.0          # referenced cgeFoo
    assert sc.summary["success"]["forced-inject"] == 1.0
    assert sc.summary["contrasts"]["adoption_tax (forced−optional)"] == 0.0


class _LimitRunner:
    """Raises SessionLimitReached when it reaches (limit_task, limit_arm); else a valid empty run."""
    def __init__(self, limit_task, limit_arm):
        self._lt, self._la = limit_task, limit_arm

    async def run(self, task, *, condition):
        if task.id == self._lt and condition == self._la:
            raise SessionLimitReached("you've hit your session limit")
        return RunResult(condition, diff="")           # valid run, empty diff -> scorer fails


class _FalseJudge:
    async def score(self, task, run):
        return False


@pytest.mark.asyncio
async def test_run_multi_eval_stops_clean_on_session_limit():
    from repo_atlas.eval.harness import run_multi_eval
    tasks = [Task(id=f"t{i}", kind="dev", repo="r", prompt="p", rubric="x") for i in range(3)]
    runner = _LimitRunner(limit_task="t1", limit_arm="forced-inject")   # 2nd arm of the 2nd task
    sc = await run_multi_eval(tasks, runner, ["control", "forced-inject"], _FalseJudge(),
                              exists_fn=lambda s: False)
    # t0 fully completed; t1 hit the limit on its 2nd arm -> dropped; t2 never ran
    assert set(sc.per_task.keys()) == {"t0"}
    assert sc.summary["n"] == 1
