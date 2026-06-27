import pytest
from repo_atlas.eval.tasks import Task
from repo_atlas.eval.offline.retriever import StubRetriever
from repo_atlas.eval.adoption import local_context_insufficient, _present_in_tree


def _task(q="q", **kw):
    return Task(id="t", kind="dev", repo="r", prompt=q, rubric="x", **kw)


def test_present_in_tree_matches_basename(tmp_path):
    (tmp_path / "cl_demo_handler.cpp").write_text("x")
    assert _present_in_tree("modules/ocl/cl_demo_handler.cpp", str(tmp_path)) is True
    assert _present_in_tree("xcore/vec_mat.h", str(tmp_path)) is False


def test_present_in_tree_skips_git_dir(tmp_path):
    gitdir = tmp_path / ".git"
    gitdir.mkdir()
    (gitdir / "vec_mat.h").write_text("x")          # only inside .git -> not counted
    assert _present_in_tree("vec_mat.h", str(tmp_path)) is False


@pytest.mark.asyncio
async def test_insufficient_when_top_hit_file_absent(tmp_path):
    # cross-repo case: the #1 hit lives in a sibling repo, absent from the work-tree -> nudge
    (tmp_path / "cl_demo_handler.cpp").write_text("x")
    sr = StubRetriever(hits_by_query={"q": [{"name": "slerp", "file": "xcore/vec_mat.h", "text": ""}]})
    assert await local_context_insufficient(_task("q"), str(tmp_path), sr) is True


@pytest.mark.asyncio
async def test_sufficient_when_top_hit_file_present(tmp_path):
    # local case: the #1 hit is in-tree prior art -> no nudge
    (tmp_path / "cl_demo_handler.cpp").write_text("x")
    sr = StubRetriever(hits_by_query={
        "q": [{"name": "foo", "file": "modules/ocl/cl_demo_handler.cpp", "text": ""}]})
    assert await local_context_insufficient(_task("q"), str(tmp_path), sr) is False


@pytest.mark.asyncio
async def test_no_hits_is_sufficient(tmp_path):
    assert await local_context_insufficient(_task("q"), str(tmp_path), StubRetriever()) is False


@pytest.mark.asyncio
async def test_no_retriever_is_sufficient(tmp_path):
    assert await local_context_insufficient(_task("q"), str(tmp_path), None) is False
