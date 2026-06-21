# tests/test_offline_report.py
import pytest
from repo_atlas.eval.offline.cases import RetrievalCase, GroundingCase
from repo_atlas.eval.offline.retriever import StubRetriever
from repo_atlas.eval.offline.harness import run_retrieval, run_grounding
from repo_atlas.eval.offline.report import render_offline_scorecard


@pytest.mark.asyncio
async def test_render_both_sections():
    rc = [RetrievalCase("c1", "r1", "q1", ("a.h",))]
    rret = await run_retrieval(rc, StubRetriever(
        hits_by_query={"q1": [{"file": "a.h", "name": "A", "qualified_name": None}]}), ks=(5,))
    gc = [GroundingCase("g1", "r1", ("Real",), ("Fake",))]
    gret = run_grounding(gc, StubRetriever(grounding_by_repo={"r1": {"Real": True}}))
    md = render_offline_scorecard(rret, gret, embed_model="bge-m3", db_path="/x/atlas.db", ks=(5,))
    assert "Retrieval" in md and "Grounding" in md
    assert "Success@5" in md                         # primary metric is now Success
    assert "coverage" in md.lower()                  # recall demoted to a coverage line
    assert "median golds" in md.lower()              # provenance line
    assert "sensitivity" in md.lower()
    assert "bge-m3" in md
    assert "r1" in md


@pytest.mark.asyncio
async def test_render_honours_custom_ks():
    rc = [RetrievalCase("c1", "r1", "q1", ("a.h",), ("A",))]
    rret = await run_retrieval(rc, StubRetriever(
        hits_by_query={"q1": [{"file": "a.h", "name": "A", "qualified_name": None}]}),
        ks=(3, 7))
    md = render_offline_scorecard(rret, None, embed_model="bge-m3", db_path="/x/atlas.db",
                                  ks=(3, 7))
    # actual cutoffs surface as Success columns
    assert "Success@3" in md and "Success@7" in md
    assert "nDCG@7" in md
    # the hardcoded defaults are gone
    assert "Success@5" not in md and "Success@10" not in md
    # Recall is NOT a primary column; it appears once as secondary coverage at kmax=7
    assert "coverage Recall@7" in md
    assert "Recall@3" not in md
    # perfect rank-1 retrieval reports 1.000, not 0.000
    assert "1.000" in md
    assert "symbol-level Success@7" in md


def test_render_handles_skipped_layer():
    md = render_offline_scorecard(None, None)
    assert "no retrieval" in md.lower() or "skipped" in md.lower()
