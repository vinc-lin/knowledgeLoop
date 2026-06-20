import pytest
from repo_atlas import tools
from repo_atlas.store import Store, Unit
from repo_atlas.embed import StubEmbedder
from repo_atlas.registry import RepoEntry


def _seed(tmp_path):
    st = Store(str(tmp_path / "a.db"))
    emb = StubEmbedder(dim=16)
    units = [Unit(repo="r1", kind="symbol", name="cgeBrightnessAdjust",
                  qualified_name="cge.cgeBrightnessAdjust", file="f.cpp", repo_head="H",
                  text="adjust brightness", meta={}),
             Unit(repo="r1", kind="doc", name="Filters", qualified_name=None, file="d.md",
                  repo_head="H", text="how filters work", meta={"module": "Image Filters"})]
    st.reindex_repo("r1", list(zip(units, emb.embed([u.text for u in units]))), repo_head="H")
    return st, emb


@pytest.mark.asyncio
async def test_find_related_envelope(tmp_path):
    st, emb = _seed(tmp_path)
    env = await tools.find_related(st, emb, "brightness")
    assert "result" in env and "freshness" in env
    assert any(h["name"] == "cgeBrightnessAdjust" for h in env["result"])


def test_verify_grounding_flags_hallucinations(tmp_path):
    st, _ = _seed(tmp_path)
    env = tools.verify_grounding(st, "r1", ["cgeBrightnessAdjust", "cgeApplyBrightness"])
    res = env["result"]
    assert res["cgeBrightnessAdjust"]["exists"] is True
    assert res["cgeApplyBrightness"]["exists"] is False
    assert "cgeBrightnessAdjust" in res["cgeApplyBrightness"]["nearest"]


def test_list_repos(tmp_path):
    st, _ = _seed(tmp_path)
    entries = [RepoEntry("r1", "/p/r1", "/w/r1", "/w/r1/em.json")]
    env = tools.list_repos(entries, st, head_fn=lambda p: "H")
    assert env["result"][0]["repo"] == "r1"
    assert env["result"][0]["freshness"] == "fresh"
