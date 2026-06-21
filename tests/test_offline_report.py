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


def test_render_handles_skipped_layer():
    md = render_offline_scorecard(None, None)
    assert "no retrieval" in md.lower() or "skipped" in md.lower()
