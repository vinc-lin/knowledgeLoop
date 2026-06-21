# tests/test_offline_harness.py
import pytest
from repo_atlas.eval.offline.cases import RetrievalCase, GroundingCase
from repo_atlas.eval.offline.retriever import StubRetriever
from repo_atlas.eval.offline.harness import run_retrieval, run_grounding


@pytest.mark.asyncio
async def test_run_retrieval_aggregates_and_perrepo():
    cases = [
        RetrievalCase("c1", "r1", "q1", ("a.h",), ("A",)),
        RetrievalCase("c2", "r2", "q2", ("b.h",)),
    ]
    stub = StubRetriever(hits_by_query={
        "q1": [{"file": "a.h", "name": "A", "qualified_name": None}],     # rank-1 hit
        "q2": [{"file": "x.h", "name": "X", "qualified_name": None}],     # miss
    })
    rep = await run_retrieval(cases, stub, ks=(5,))
    assert rep.overall["n"] == 2
    assert rep.overall["recall@5"] == 0.5            # c1 hit, c2 miss
    assert rep.per_repo["r1"]["recall@5"] == 1.0
    assert rep.per_repo["r2"]["recall@5"] == 0.0
    assert rep.overall["sym_recall@5"] == 1.0        # only c1 has gold_symbols, and it hit


@pytest.mark.asyncio
async def test_run_retrieval_skips_failing_case():
    class Boom(StubRetriever):
        async def retrieve(self, query, repo, k):
            raise RuntimeError("retrieval died")
    cases = [RetrievalCase("c1", "r1", "q1", ("a.h",))]
    rep = await run_retrieval(cases, Boom(), ks=(5,))
    assert rep.overall["n"] == 0                      # skipped, not crashed


def test_run_grounding():
    cases = [GroundingCase("g1", "r1", ("Real1", "Real2"), ("Fake1",))]
    stub = StubRetriever(grounding_by_repo={"r1": {"Real1": True}})  # Real2 missing -> FN
    rep = run_grounding(cases, stub)
    assert rep.overall["sensitivity"] == 0.5
    assert rep.overall["specificity"] == 1.0
    assert rep.false_negatives["r1"] == ["Real2"]
