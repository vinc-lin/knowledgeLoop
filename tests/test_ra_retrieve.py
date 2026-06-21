import pytest
from repo_atlas.retrieve import rrf_fuse, find_related_units
from repo_atlas.store import Store, Unit
from repo_atlas.embed import StubEmbedder


def test_rrf_fuse_rewards_agreement():
    fused = rrf_fuse([["a", "b", "c"], ["b", "a", "d"]], k0=60)
    ids = [i for i, _ in fused]
    assert ids[0] in ("a", "b")          # both ranked high in both lists
    assert set(ids) == {"a", "b", "c", "d"}


@pytest.mark.asyncio
async def test_find_related_returns_hits(tmp_path):
    st = Store(str(tmp_path / "a.db"))
    emb = StubEmbedder(dim=16)
    units = [Unit(repo="r1", kind="symbol", name="brightness",
                  qualified_name="cge.brightness", file="f.cpp", repo_head="H",
                  text="adjust image brightness", meta={}),
             Unit(repo="r1", kind="doc", name="Filters", qualified_name=None, file="d.md",
                  repo_head="H", text="how filters work", meta={})]
    vecs = emb.embed([u.text for u in units])
    st.reindex_repo("r1", list(zip(units, vecs)), repo_head="H")
    hits = await find_related_units(st, emb, "brightness adjust", k=5)
    assert hits and hits[0]["repo"] == "r1"
    assert any(h["name"] == "brightness" for h in hits)
    assert "freshness" not in hits[0] or hits[0].get("repo")   # hit shape sane


@pytest.mark.asyncio
async def test_find_related_units_balances_kinds(tmp_path):
    st = Store(str(tmp_path / "b.db"))
    emb = StubEmbedder(dim=16)
    units = ([Unit(repo="r1", kind="symbol", name=f"sym{i}", qualified_name=f"q.sym{i}",
                   file=f"s{i}.cpp", repo_head="H", text=f"image filter symbol {i}", meta={})
              for i in range(3)]
             + [Unit(repo="r1", kind="doc", name=f"doc{i}", qualified_name=None,
                     file=f"d{i}.md", repo_head="H", text=f"image filter doc {i}", meta={})
                for i in range(3)])
    vecs = emb.embed([u.text for u in units])
    st.reindex_repo("r1", list(zip(units, vecs)), repo_head="H")
    # default (kinds unset) -> balanced, symbol-first interleave
    hits = await find_related_units(st, emb, "image filter", k=4, symbol_ratio=0.5)
    assert [h["kind"] for h in hits] == ["symbol", "doc", "symbol", "doc"]
    # explicit kinds bypasses balancing
    only = await find_related_units(st, emb, "image filter", kinds=["symbol"], k=4)
    assert only and all(h["kind"] == "symbol" for h in only)
