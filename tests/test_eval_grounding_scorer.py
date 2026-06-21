# tests/test_eval_grounding_scorer.py
import pytest
from repo_atlas.eval.grounding_scorer import GroundingScorer
from repo_atlas.eval.runner import RunResult
from repo_atlas.eval.tasks import Task


def _task(apis):
    return Task(id="t", kind="dev", repo="r", prompt="p", rubric="x", required_apis=apis)


@pytest.mark.asyncio
async def test_grounded_success_when_all_apis_referenced():
    run = RunResult("treatment", referenced_symbols=["cgeFoo", "x", "y"])
    assert await GroundingScorer().score(_task(["cgeFoo"]), run) is True


@pytest.mark.asyncio
async def test_not_grounded_when_api_missing():
    run = RunResult("treatment", referenced_symbols=["x", "y"])
    assert await GroundingScorer().score(_task(["cgeFoo"]), run) is False


@pytest.mark.asyncio
async def test_all_required_semantics():
    run = RunResult("treatment", referenced_symbols=["a"])
    assert await GroundingScorer().score(_task(["a", "b"]), run) is False   # needs both


@pytest.mark.asyncio
async def test_empty_required_is_false():
    run = RunResult("treatment", referenced_symbols=["a"])
    assert await GroundingScorer().score(_task([]), run) is False
