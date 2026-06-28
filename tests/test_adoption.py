import pytest
from repo_atlas.adoption import (NUDGE, _present_in_tree, gate_query_out_of_tree, nudge_for)
from repo_atlas.eval.offline.retriever import StubRetriever


def test_present_in_tree_basename_and_skips_git(tmp_path):
    (tmp_path / "cl_demo_handler.cpp").write_text("x")
    assert _present_in_tree("modules/ocl/cl_demo_handler.cpp", str(tmp_path)) is True
    assert _present_in_tree("xcore/vec_mat.h", str(tmp_path)) is False
    gd = tmp_path / ".git"; gd.mkdir(); (gd / "vec_mat.h").write_text("x")
    assert _present_in_tree("vec_mat.h", str(tmp_path)) is False        # .git is skipped


@pytest.mark.asyncio
async def test_gate_true_when_top_hit_out_of_tree(tmp_path):
    (tmp_path / "cl_demo_handler.cpp").write_text("x")
    sr = StubRetriever(hits_by_query={"q": [{"name": "slerp", "file": "xcore/vec_mat.h", "text": ""}]})
    assert await gate_query_out_of_tree("q", str(tmp_path), sr) is True


@pytest.mark.asyncio
async def test_gate_false_when_in_tree_or_empty_or_no_retriever(tmp_path):
    (tmp_path / "cl_demo_handler.cpp").write_text("x")
    in_tree = StubRetriever(hits_by_query={"q": [{"name": "f", "file": "ocl/cl_demo_handler.cpp", "text": ""}]})
    assert await gate_query_out_of_tree("q", str(tmp_path), in_tree) is False
    assert await gate_query_out_of_tree("q", str(tmp_path), StubRetriever()) is False    # no hits
    assert await gate_query_out_of_tree("q", str(tmp_path), None) is False               # no retriever


@pytest.mark.asyncio
async def test_nudge_for_returns_text_iff_out_of_tree(tmp_path):
    (tmp_path / "local.cpp").write_text("x")
    out = StubRetriever(hits_by_query={"q": [{"name": "h", "file": "other/x.h", "text": ""}]})
    assert await nudge_for("q", str(tmp_path), out) == NUDGE
    inn = StubRetriever(hits_by_query={"q": [{"name": "h", "file": "local.cpp", "text": ""}]})
    assert await nudge_for("q", str(tmp_path), inn) is None


from repo_atlas.adoption import is_coding_intent


def test_is_coding_intent_true_for_implementation_requests():
    for p in ["Implement a sepia filter", "add per-handler FPS logging",
              "fix the codec crash", "use the existing profiling helper", "refactor the blender"]:
        assert is_coding_intent(p) is True


def test_is_coding_intent_false_for_questions_and_blank():
    for p in ["What does this function do?", "explain the architecture", "", "summarize the module"]:
        assert is_coding_intent(p) is False
