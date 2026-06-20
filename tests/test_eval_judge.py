import pytest
from repo_atlas.eval.judge import StubJudge
from repo_atlas.eval.runner import RunResult
from repo_atlas.eval.tasks import Task


@pytest.mark.asyncio
async def test_stub_judge():
    j = StubJudge({"t1": True})
    ok = await j.score(Task(id="t1", kind="dev", repo="r", prompt="p", rubric="x"),
                       RunResult("treatment"))
    assert ok is True
