import pytest
from repo_atlas.eval.tasks import Task
from repo_atlas.eval.offline.retriever import StubRetriever
from repo_atlas.eval.aggregate import TaskScore, aggregate_arms
from repo_atlas.eval.correlation import compute_proxy, correlate


def _ts(arm, success):
    return TaskScore(task_id="x", condition=arm, success=success, hallucination_rate=0.0,
                     reuse_recall=0.0, exploration_cost=1)


@pytest.mark.asyncio
async def test_compute_proxy_surfaced_when_required_api_in_symbol_hits():
    t1 = Task(id="t1", kind="dev", repo="r", prompt="make a blend", rubric="x",
              required_apis=["cgeFoo"])
    t2 = Task(id="t2", kind="dev", repo="r", prompt="scale a buffer", rubric="x",
              required_apis=["cgeBar"])
    sr = StubRetriever(hits_by_query={
        "make a blend": [{"name": "cgeFoo", "file": "a.cpp", "text": ""}],
        "scale a buffer": [{"name": "cgeOther", "file": "b.cpp", "text": ""}]})
    proxy = await compute_proxy([t1, t2], sr, k=10)
    assert proxy == {"t1": True, "t2": False}


def test_correlate_conditional_success_rates():
    per_task = {
        "t1": {"optional": _ts("optional", True)},     # proxy surfaced, succeeded
        "t2": {"optional": _ts("optional", False)},    # proxy missed, failed
        "t3": {"optional": _ts("optional", False)},    # proxy surfaced, failed
    }
    sc = aggregate_arms(per_task, ["optional"])
    proxy = {"t1": True, "t2": False, "t3": True}
    cr = correlate(proxy, sc, "optional")
    assert cr["n_surfaced"] == 2 and cr["n_unsurfaced"] == 1
    assert cr["success_if_surfaced"] == 0.5            # t1 yes, t3 no
    assert cr["success_if_not"] == 0.0                 # t2 no
