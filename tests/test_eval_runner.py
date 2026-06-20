import pytest
from repo_atlas.eval.runner import RunResult, StubRunner
from repo_atlas.eval.tasks import Task


def _task():
    return Task(id="t1", kind="dev", repo="gpuimage", prompt="p", rubric="r")


@pytest.mark.asyncio
async def test_stub_runner_returns_canned():
    canned = {("t1", "baseline"): RunResult("baseline", ["X"], ["a.cpp"], 9, 100, {}, ""),
              ("t1", "treatment"): RunResult("treatment", ["cgeImageFilter"], ["a.cpp"], 4, 80, {}, "")}
    r = StubRunner(canned)
    base = await r.run(_task(), condition="baseline")
    treat = await r.run(_task(), condition="treatment")
    assert base.tool_calls == 9 and treat.referenced_symbols == ["cgeImageFilter"]
