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


# --- GroundedUseScorer: target-site + call-form (genuine-gap tasks) -----------------------------
from repo_atlas.eval.grounding_scorer import GroundedUseScorer   # noqa: E402


def _gap_task():
    return Task(id="t", kind="dev", repo="r", prompt="p", rubric="x",
                required_apis=["cgeGetBlendModeName"],
                expected_files=["cge/filters/cgeBlendFilter.cpp"])


def _diff(path, added):
    return f"--- a/{path}\n+++ b/{path}\n@@ -1 +1,2 @@\n+{added}\n"


@pytest.mark.asyncio
async def test_grounded_use_credits_call_in_target_file():
    run = RunResult("t", diff=_diff("cge/filters/cgeBlendFilter.cpp", "return cgeGetBlendModeName(mode);"))
    assert await GroundedUseScorer().score(_gap_task(), run) is True


@pytest.mark.asyncio
async def test_grounded_use_blocks_call_in_wrong_file():
    # the lap-7 gaming: the API is called, but in a demo/non-target file -> NOT credited
    run = RunResult("t", diff=_diff("demo/cgeDemo.cpp", "const char* n = cgeGetBlendModeName(mode);"))
    assert await GroundedUseScorer().score(_gap_task(), run) is False


@pytest.mark.asyncio
async def test_grounded_use_blocks_mention_without_call():
    # api named but not CALLED (e.g. a hand-rolled switch / a comment) -> NOT credited
    run = RunResult("t", diff=_diff("cge/filters/cgeBlendFilter.cpp", "// like cgeGetBlendModeName but inline"))
    assert await GroundedUseScorer().score(_gap_task(), run) is False


@pytest.mark.asyncio
async def test_grounded_use_falls_back_to_whole_diff_without_targets():
    task = Task(id="t", kind="dev", repo="r", prompt="p", rubric="x",
                required_apis=["cgeGetBlendModeName"])           # no expected_files
    run = RunResult("t", diff=_diff("anywhere.cpp", "x = cgeGetBlendModeName(m);"))
    assert await GroundedUseScorer().score(task, run) is True


@pytest.mark.asyncio
async def test_grounded_use_empty_required_is_false():
    run = RunResult("t", diff=_diff("cge/filters/cgeBlendFilter.cpp", "cgeGetBlendModeName(mode);"))
    assert await GroundedUseScorer().score(_task([]), run) is False
