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
    md = render_offline_scorecard(rret, gret, embed_model="bge-m3", db_path="/x/atlas.db")
    assert "Retrieval" in md and "Grounding" in md
    assert "Recall@5" in md
    assert "sensitivity" in md.lower()
    assert "bge-m3" in md                       # provenance recorded
    assert "r1" in md                           # per-repo row


@pytest.mark.asyncio
async def test_render_honours_custom_ks():
    # Regression: with non-default ks the scorecard must render the ACTUAL k columns and
    # the real numbers — not the hardcoded Recall@5/10/20 / Hit@10 / nDCG@10 showing 0.0.
    rc = [RetrievalCase("c1", "r1", "q1", ("a.h",), ("A",))]
    rret = await run_retrieval(rc, StubRetriever(
        hits_by_query={"q1": [{"file": "a.h", "name": "A", "qualified_name": None}]}),
        ks=(3, 7))
    md = render_offline_scorecard(rret, None, embed_model="bge-m3", db_path="/x/atlas.db",
                                  ks=(3, 7))
    # actual cutoffs surface in the header...
    assert "Recall@3" in md and "Recall@7" in md
    assert "Hit@7" in md and "nDCG@7" in md
    # ...and the hardcoded defaults are gone.
    assert "Recall@5" not in md and "Recall@10" not in md and "Recall@20" not in md
    assert "Hit@10" not in md and "nDCG@10" not in md
    # perfect rank-1 retrieval must report 1.000, not 0.000.
    assert "0.000" not in md
    assert "1.000" in md
    # secondary symbol-recall line uses max(ks)=7, where the data actually lives.
    assert "symbol-level Recall@7" in md


def test_render_handles_skipped_layer():
    md = render_offline_scorecard(None, None)
    assert "no retrieval" in md.lower() or "skipped" in md.lower()
